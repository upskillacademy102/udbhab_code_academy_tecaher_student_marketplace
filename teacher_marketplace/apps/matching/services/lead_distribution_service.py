"""
Lead distribution service for the Teacher Marketplace Platform.

Implements Sections 19-24 exactly:
    1. Determine eligible teachers via EligibilityService (SAME hard
       gate as search - Section 19: "Do NOT distribute the lead to
       ineligible teachers").
    2. Group eligible teachers by subscription tier (Section 20),
       using the same SubscriptionPriorityService ordinal ranking
       used for search ranking - NOT duplicated logic.
    3. Offer the highest tier's teachers SIMULTANEOUSLY (Section 21)
       - all get a LeadAssignment row with the same assigned_at/
       expires_at in one transaction.
    4. On accept: stop the cascade (Section 22/23).
    5. On reject/expiry of an ENTIRE tier: activate the next tier.
    6. Free teachers (Section 24): ranked by rating+experience,
       same-ranked free teachers grouped and offered simultaneously
       too - implemented by treating "Free" as just another tier in
       the SAME grouping mechanism, with an additional within-tier
       rating/experience sub-grouping for simultaneity ties.

CONCURRENCY (Section 27): every state-mutating operation
(accept_assignment, reject_assignment, expire) runs inside
transaction.atomic() with select_for_update() on the relevant
LeadAssignment row(s), preventing double-acceptance and race
conditions when a lead expires at nearly the same moment a teacher
responds. Uses the SAME select_for_update pattern already
established by WalletService/LeadQuotaService in this codebase.
"""

import logging
from collections import defaultdict

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.matching.models import AssignmentResponse, AssignmentStatus, LeadAssignment
from apps.matching.services.config_service import get_config
from apps.matching.services.eligibility_service import EligibilityService
from apps.matching.services.location_matching_service import LocationMatchingService
from apps.matching.services.subscription_priority_service import (
    SubscriptionPriorityService,
)
from apps.subscriptions.services import SubscriptionService
from apps.teacher_profile.models import TeacherProfile, TeachingMode

logger = logging.getLogger("apps.matching.lead_distribution")


class LeadDistributionService:

    @staticmethod
    def _get_eligible_teachers_with_scores(requirement) -> list:
        """
        Runs the SAME EligibilityService gate as search - no
        separate/looser criteria for leads (Section 19's explicit
        requirement). Returns a list of dicts:
            {"teacher_profile": ..., "eligibility": EligibilityResult}
        for eligible teachers only.
        """
        from apps.lead_engine.services.time_compatibility_service import TimeSlot
        from apps.trust.matching_support import (
            apply_teacher_gate,
            exclude_blocked_teachers,
        )

        config = get_config()

        candidates = (
            exclude_blocked_teachers(
                apply_teacher_gate(
                    TeacherProfile.objects.filter(
                        subjects=requirement.subject,
                        teacher__user__is_active=True,
                    )
                ),
                requirement.student,
            )
            .select_related("teacher", "teacher__user", "teacher__pincode_location")
            .prefetch_related("weekly_availability", "languages", "subjects")
            .distinct()
        )
        if requirement.preferred_language_id:
            candidates = candidates.filter(languages=requirement.preferred_language)

        student_slots = [
            TimeSlot(
                day_of_week=p.day_of_week,
                start_time=p.start_time,
                end_time=p.end_time,
                timezone=p.timezone,
                is_flexible=(p.flexibility == "flexible"),
            )
            for p in requirement.schedule_preferences.all()
        ]

        location_results = {}
        if requirement.teaching_mode in (TeachingMode.OFFLINE, TeachingMode.BOTH):
            candidate_pincode_ids = {
                c.id: c.teacher.pincode_location_id
                for c in candidates
                if c.teacher.pincode_location_id is not None
            }
            if requirement.pincode_location is not None and candidate_pincode_ids:
                location_results = LocationMatchingService.find_eligible_teacher_ids(
                    requirement.pincode_location, candidate_pincode_ids
                )

        eligible = []
        for profile in candidates:
            teacher_slots = [
                TimeSlot(
                    day_of_week=w.day_of_week,
                    start_time=w.start_time,
                    end_time=w.end_time,
                    timezone=w.timezone,
                )
                for w in profile.weekly_availability.all()
                if w.is_active
            ]
            result = EligibilityService.check_teacher_eligibility(
                teacher_profile=profile,
                requirement=requirement,
                teacher_slots=teacher_slots,
                student_slots=student_slots,
                location_precomputed=location_results.get(profile.id),
                config=config,
            )
            if result.is_eligible:
                eligible.append({"teacher_profile": profile, "eligibility": result})

        return eligible

    @staticmethod
    def _plans_for(eligible_teachers: list) -> dict:
        """{teacher_id: SubscriptionPlan} for every eligible teacher, in a
        fixed number of queries (avoids get_effective_plan per teacher)."""
        teachers = [e["teacher_profile"].teacher for e in eligible_teachers]
        return SubscriptionService.get_effective_plans(teachers)

    @staticmethod
    def _group_by_tier(eligible_teachers: list, plan_by_teacher_id: dict) -> dict:
        """
        Groups eligible teachers by subscription_rank (0=highest
        tier). Within each tier, sorted by rating desc then
        experience desc (Section 24 - applies uniformly, since Free
        is just the last tier in this same grouping).

        ``plan_by_teacher_id`` is precomputed once by the caller
        (LeadDistributionService._plans_for) so tier grouping does not
        issue one subscription query per teacher.
        """
        from apps.trust.matching_support import ranking_enabled, verification_score_map

        order = get_config().subscription_priority_order or ["Free"]
        groups = defaultdict(list)
        for entry in eligible_teachers:
            teacher_id = entry["teacher_profile"].teacher_id
            plan = plan_by_teacher_id[teacher_id]
            rank = SubscriptionPriorityService.rank_for_plan_name(plan.name, order)
            groups[rank].append(entry)

        # Within a tier, a more-verified teacher is offered first (flag-gated).
        # Subscription tier still gates the stage cascade above this.
        vscore = (
            verification_score_map(
                e["teacher_profile"].teacher_id for e in eligible_teachers
            )
            if ranking_enabled()
            else {}
        )
        for rank in groups:
            groups[rank].sort(
                key=lambda e: (
                    -float(vscore.get(e["teacher_profile"].teacher_id, 0)),
                    -float(e["teacher_profile"].rating),
                    -(e["teacher_profile"].years_of_experience or 0),
                )
            )

        return dict(sorted(groups.items()))

    @staticmethod
    def _create_assignments(
        lead, group, plan_by_teacher_id, *, stage, now, expires_at
    ) -> list:
        """
        Create one LeadAssignment per teacher in ``group``. Each insert
        is guarded against the unique (lead, teacher) constraint so a
        concurrent writer that beat us to a row is a skip, not a crash
        (defence-in-depth behind the requirement row lock).
        """
        created = []
        for entry in group:
            profile = entry["teacher_profile"]
            eligibility = entry["eligibility"]
            plan = plan_by_teacher_id[profile.teacher_id]
            try:
                with transaction.atomic():
                    assignment = LeadAssignment.objects.create(
                        lead=lead,
                        teacher=profile.teacher,
                        subscription_tier=plan.name,
                        assignment_stage=stage,
                        assigned_at=now,
                        expires_at=expires_at,
                        status=AssignmentStatus.ASSIGNED,
                        time_match_score=eligibility.time_result.get("time_score"),
                        location_score=(
                            eligibility.location_result.score
                            if eligibility.location_result
                            else None
                        ),
                        subject_match_score=eligibility.subject_result.score,
                        language_match_score=eligibility.language_result.score,
                    )
                created.append(assignment)
            except IntegrityError:
                logger.info(
                    "Lead %s: assignment for teacher %s already exists - skipping (race).",
                    lead.id,
                    profile.teacher_id,
                )
        return created

    @staticmethod
    @transaction.atomic
    def distribute_lead(lead) -> list:
        """
        Entry point, called once when a Lead is created (from
        apps.lead_engine's requirement-submission flow). Determines
        eligible teachers, groups by tier, and activates STAGE 1
        (the highest tier group) by creating LeadAssignment rows for
        all of them simultaneously - same assigned_at/expires_at.

        Returns the list of newly created LeadAssignment rows for
        stage 1. If NO teachers are eligible at all, returns an
        empty list (this is a valid, expected outcome - not an
        error - per Section 19, an ineligible pool means no
        distribution happens).
        """
        from apps.student_requirement.models import StudentRequirement

        config = get_config()
        requirement = lead.student_requirement

        # Concurrency gate: lock the requirement row so two workers
        # processing the same requirement id serialize here. Combined
        # with the existence check below, the second worker sees the
        # first's assignments and no-ops instead of racing to insert
        # duplicates.
        StudentRequirement.objects.select_for_update().filter(pk=requirement.pk).first()

        # Per-requirement idempotency: the caller may hold several Lead rows
        # for this requirement (one per candidate teacher). Only the first
        # call distributes; later calls - a retry, a redelivery, a
        # re-submit - are no-ops.
        if LeadAssignment.objects.filter(
            lead__student_requirement_id=requirement.pk
        ).exists():
            logger.info("Lead %s: requirement already distributed - skipping.", lead.id)
            return []

        eligible = LeadDistributionService._get_eligible_teachers_with_scores(
            requirement
        )
        if not eligible:
            logger.info(
                "No eligible teachers for lead %s - distribution skipped.", lead.id
            )
            return []

        plan_by_teacher_id = LeadDistributionService._plans_for(eligible)
        tiers = LeadDistributionService._group_by_tier(eligible, plan_by_teacher_id)
        first_stage_rank = next(iter(tiers))
        first_group = tiers[first_stage_rank]

        now = timezone.now()
        expires_at = now + timezone.timedelta(hours=config.lead_response_window_hours)

        assignments = LeadDistributionService._create_assignments(
            lead,
            first_group,
            plan_by_teacher_id,
            stage=1,
            now=now,
            expires_at=expires_at,
        )

        logger.info(
            "Lead %s distributed: stage 1 (%d teacher(s), tier rank %d) assigned, expires %s",
            lead.id,
            len(assignments),
            first_stage_rank,
            expires_at,
        )

        # Store the full tier plan on the Lead's requirement context
        # via a fresh per-call computation next time advance_stage is
        # called, rather than persisting the whole tier structure -
        # see advance_stage()'s docstring for why re-computing
        # eligibility at cascade time (not caching the original
        # groups) is the correct, safer approach.
        return assignments

    @staticmethod
    @transaction.atomic
    def accept_assignment(assignment: LeadAssignment) -> LeadAssignment:
        """
        Teacher accepts. Locks the row, validates the transition,
        marks ACCEPTED, and - per Section 23's "Stop distributing
        this lead" - cancels every OTHER still-open assignment for
        the same lead (any stage) so no other teacher can also
        accept the same lead afterward.
        """
        locked = LeadAssignment.objects.select_for_update().get(id=assignment.id)

        if not locked.can_transition_to(AssignmentStatus.ACCEPTED):
            raise ValidationException(
                detail=f"Cannot accept an assignment in '{locked.status}' status."
            )

        now = timezone.now()
        locked.status = AssignmentStatus.ACCEPTED
        locked.response = AssignmentResponse.ACCEPT
        locked.responded_at = now
        locked.save(update_fields=["status", "response", "responded_at"])

        other_open = (
            LeadAssignment.objects.select_for_update()
            .filter(
                lead=locked.lead,
                status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.VIEWED],
            )
            .exclude(id=locked.id)
        )
        cancelled_count = other_open.update(status=AssignmentStatus.CANCELLED)

        logger.info(
            "Lead %s ACCEPTED by teacher %s - %d other open assignment(s) cancelled.",
            locked.lead_id,
            locked.teacher.user.email,
            cancelled_count,
        )
        return locked

    @staticmethod
    @transaction.atomic
    def reject_assignment(assignment: LeadAssignment) -> LeadAssignment:
        """
        Teacher rejects. Locks the row, validates transition, marks
        REJECTED, then checks whether this was the LAST open
        assignment in its stage - if so, cascades to the next tier.
        """
        locked = LeadAssignment.objects.select_for_update().get(id=assignment.id)

        if not locked.can_transition_to(AssignmentStatus.REJECTED):
            raise ValidationException(
                detail=f"Cannot reject an assignment in '{locked.status}' status."
            )

        now = timezone.now()
        locked.status = AssignmentStatus.REJECTED
        locked.response = AssignmentResponse.REJECT
        locked.responded_at = now
        locked.save(update_fields=["status", "response", "responded_at"])

        logger.info(
            "Lead %s REJECTED by teacher %s.", locked.lead_id, locked.teacher.user.email
        )

        LeadDistributionService._maybe_advance_stage(
            locked.lead, locked.assignment_stage
        )
        return locked

    @staticmethod
    @transaction.atomic
    def expire_assignment(assignment: LeadAssignment) -> LeadAssignment:
        """
        Called by the Celery task (expire_lead_assignments) for any
        assignment whose expires_at has passed while still
        ASSIGNED/VIEWED. Marks EXPIRED, then checks for stage
        cascade - identical follow-up logic to reject_assignment.
        """
        locked = LeadAssignment.objects.select_for_update().get(id=assignment.id)

        if not locked.can_transition_to(AssignmentStatus.EXPIRED):
            # Already resolved (accepted/rejected/etc.) by the time
            # the task got to it - not an error, just a no-op.
            return locked

        locked.status = AssignmentStatus.EXPIRED
        locked.save(update_fields=["status"])

        logger.info(
            "Lead %s assignment for teacher %s EXPIRED.",
            locked.lead_id,
            locked.teacher.user.email,
        )

        LeadDistributionService._maybe_advance_stage(
            locked.lead, locked.assignment_stage
        )
        return locked

    @staticmethod
    def _maybe_advance_stage(lead, current_stage: int) -> None:
        """
        Checks whether every assignment in `current_stage` is now
        resolved (not ASSIGNED/VIEWED). If so, re-runs eligibility
        fresh (rather than reusing a cached tier list from
        distribute_lead time) and activates the next tier rank up.

        RE-COMPUTING ELIGIBILITY AT CASCADE TIME, NOT CACHING: a
        teacher's availability, verification status, or subject list
        could genuinely change in the time between initial
        distribution and a later stage's cascade (hours later, per
        the 24-hour window) - re-running EligibilityService here
        ensures stage 2/3 offers reflect CURRENT reality, not a
        stale snapshot from when the lead was first created. This is
        a deliberate correctness choice over a (cheaper but
        potentially wrong) cached-plan approach.
        """
        still_open = LeadAssignment.objects.filter(
            lead=lead,
            assignment_stage=current_stage,
            status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.VIEWED],
        ).exists()
        if still_open:
            return  # this stage isn't fully resolved yet

        already_accepted = LeadAssignment.objects.filter(
            lead=lead, status=AssignmentStatus.ACCEPTED
        ).exists()
        if already_accepted:
            return  # cascade already stopped by an acceptance

        config = get_config()
        eligible = LeadDistributionService._get_eligible_teachers_with_scores(
            lead.student_requirement
        )
        if not eligible:
            logger.info(
                "Lead %s: no eligible teachers remain for further stages.", lead.id
            )
            return

        plan_by_teacher_id = LeadDistributionService._plans_for(eligible)
        tiers = LeadDistributionService._group_by_tier(eligible, plan_by_teacher_id)
        already_offered_teacher_ids = set(
            LeadAssignment.objects.filter(
                lead__student_requirement_id=lead.student_requirement_id
            ).values_list("teacher_id", flat=True)
        )

        next_stage = current_stage + 1
        for rank in tiers:
            candidates = [
                e
                for e in tiers[rank]
                if e["teacher_profile"].teacher_id not in already_offered_teacher_ids
            ]
            if not candidates:
                continue

            now = timezone.now()
            expires_at = now + timezone.timedelta(
                hours=config.lead_response_window_hours
            )
            created = LeadDistributionService._create_assignments(
                lead,
                candidates,
                plan_by_teacher_id,
                stage=next_stage,
                now=now,
                expires_at=expires_at,
            )

            logger.info(
                "Lead %s advanced to stage %d (%d teacher(s), tier rank %d).",
                lead.id,
                next_stage,
                len(created),
                rank,
            )
            return

        logger.info(
            "Lead %s: all tiers exhausted, no further teachers to offer.", lead.id
        )

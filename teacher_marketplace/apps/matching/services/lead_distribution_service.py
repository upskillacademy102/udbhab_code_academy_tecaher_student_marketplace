"""
Lead distribution service for the Teacher Marketplace Platform.

Two entirely separate distribution modes, dispatched on
requirement.teaching_mode:

ONLINE (_distribute_online / _maybe_advance_online_stage):
    1. Determine eligible teachers via EligibilityService (SAME hard
       gate as search - subject/language/time; location is skipped
       for online).
    2. Group eligible teachers by subscription tier, using
       SubscriptionPriorityService's ordinal ranking (Elite before
       Professional before Free).
    3. Offer the highest tier's teachers SIMULTANEOUSLY: all get a
       LeadAssignment row, expires_at set to their own personal
       lead_visibility_window_hours (default 24h) from when THEY were
       shown it.
    4. Unlocking a lead now doubles as "accept" (see on_unlocked,
       called from apps.lead_engine.unlock_service). For ONLINE this
       is shared/pooled: accepting/unlocking does NOT stop the
       cascade or cancel other teachers' assignments.
    5. Lower tiers are revealed on a FIXED time-based clock
       (online_tier_window_hours, default 8h per tier), via
       reveal_next_online_stage - run periodically by the
       reveal_online_lead_tiers Celery beat task. This is completely
       independent of whether an earlier tier's assignment was
       unlocked, rejected, or expired: reject_assignment/
       expire_assignment do NOT cascade for online at all (see
       _maybe_advance_stage).

OFFLINE/BOTH (_distribute_offline / _maybe_advance_offline_stage):
    Subscription tier plays NO role at all - pure distance ordering.
    1. Same EligibilityService gate, but location is a hard
       requirement here (must resolve to a real distance within
       max_location_radius_km).
    2. Group eligible teachers by exact distance_km, ascending -
       teachers tied at the same distance are offered simultaneously
       regardless of plan.
    3. Offer only the nearest distance band.
    4. On accept: stop the cascade, same as online.
    5. On reject/expiry of the WHOLE nearest band: activate the
       next-nearest not-yet-offered band, expanding outward up to
       max_location_radius_km (LocationMatchingService's existing
       expanding-radius search already bounds candidates to this).

CONCURRENCY: every state-mutating operation (accept_assignment,
reject_assignment, expire) runs inside transaction.atomic() with
select_for_update() on the relevant LeadAssignment row(s), preventing
double-acceptance and race conditions when a lead expires at nearly
the same moment a teacher responds. Uses the SAME select_for_update
pattern already established by WalletService/LeadQuotaService in
this codebase.
"""

import logging
from collections import defaultdict

from django.db import IntegrityError, transaction
from django.db.models import Max
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

        from django.db.models import prefetch_related_objects

        config = get_config()

        # EligibilityService reads requirement.preferred_language_ids once
        # per candidate below - without this, that's one query per
        # candidate teacher (the same N+1 shape lead_generation_service
        # prefetches schedule_preferences/preferred_languages against).
        prefetch_related_objects([requirement], "preferred_languages")

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
        if not requirement.no_language_preference:
            language_ids = requirement.preferred_language_ids
            if language_ids:
                candidates = candidates.filter(languages__id__in=language_ids)

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
        ONLINE ONLY (see _distribute_offline for OFFLINE/BOTH, which
        does not use subscription tier at all). Groups eligible
        teachers by subscription_rank (0=highest tier) - Elite before
        Professional before Free - each whole tier offered
        simultaneously (Section 21/24). Within a tier: a more-
        verified teacher is offered first (flag-gated), then rating
        desc, then experience desc.

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
    def _group_offline_by_distance(eligible_teachers: list) -> dict:
        """
        OFFLINE/BOTH ONLY. Buckets eligible candidates by their exact
        distance_km (every eligible offline/both entry has a real
        one - EligibilityService only marks such a teacher eligible
        once location_precomputed.is_eligible is True), ascending -
        subscription tier plays NO role in offline/both ordering at
        all, unlike online. Two candidates at the same distance are
        grouped together so they get offered simultaneously,
        regardless of subscription plan.
        """
        groups = defaultdict(list)
        for entry in eligible_teachers:
            distance = entry["eligibility"].location_result.distance_km
            groups[distance].append(entry)
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

        Deliberately does NOT fire a per-teacher LEAD_OFFERED
        notification here even though NotificationService.lead_offered
        exists for that purpose - NotificationService.notify() is 2
        synchronous queries (create + email-status save), and this
        method's caller can offer an entire subscription tier at once,
        so a per-teacher call here would turn the whole cascade linear
        in candidate count - exactly the N+1 shape
        test_distribution_query_count_is_sublinear_in_teacher_count
        exists to catch. Sending it would need a genuinely batched
        (bulk_create) or async (Celery) path, not a loop.
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
    def _distribute_online(lead, eligible: list) -> list:
        """
        ONLINE: activates STAGE 1 (the highest subscription tier)
        immediately. expires_at is this stage's PERSONAL visibility
        window (lead_visibility_window_hours) - each teacher who gets
        shown the lead keeps seeing it for this long from when they
        were first shown it, independent of the separate tier-reveal
        clock (online_tier_window_hours) that brings in lower tiers -
        see reveal_next_online_stage, which runs on that clock alone
        and does not wait for this stage to resolve or expire.
        """
        config = get_config()
        plan_by_teacher_id = LeadDistributionService._plans_for(eligible)
        tiers = LeadDistributionService._group_by_tier(eligible, plan_by_teacher_id)
        first_stage_rank = next(iter(tiers))
        first_group = tiers[first_stage_rank]

        now = timezone.now()
        expires_at = now + timezone.timedelta(
            hours=config.lead_visibility_window_hours
        )
        assignments = LeadDistributionService._create_assignments(
            lead,
            first_group,
            plan_by_teacher_id,
            stage=1,
            now=now,
            expires_at=expires_at,
        )
        logger.info(
            "Lead %s distributed online: stage 1 (%d teacher(s), tier rank %d) assigned, visible until %s",
            lead.id,
            len(assignments),
            first_stage_rank,
            expires_at,
        )
        return assignments

    @staticmethod
    def _distribute_offline(lead, eligible: list) -> list:
        """
        OFFLINE/BOTH: activates only the single nearest distance band
        (which may hold more than one teacher, if tied) - subscription
        tier plays no role in this ordering at all. Farther bands are
        not offered yet; see _maybe_advance_offline_stage for how they
        eventually get their turn, on reject/expiry rather than tier
        resolution.
        """
        config = get_config()
        plan_by_teacher_id = LeadDistributionService._plans_for(eligible)
        bands = LeadDistributionService._group_offline_by_distance(eligible)
        nearest_distance = next(iter(bands))
        nearest_group = bands[nearest_distance]

        now = timezone.now()
        expires_at = now + timezone.timedelta(
            hours=config.offline_response_window_hours
        )
        assignments = LeadDistributionService._create_assignments(
            lead,
            nearest_group,
            plan_by_teacher_id,
            stage=1,
            now=now,
            expires_at=expires_at,
        )
        logger.info(
            "Lead %s distributed offline: stage 1 (%d teacher(s) at %.2fkm) assigned, expires %s",
            lead.id,
            len(assignments),
            nearest_distance,
            expires_at,
        )
        return assignments

    @staticmethod
    @transaction.atomic
    def distribute_lead(lead) -> list:
        """
        Entry point, called once when a Lead is created (from
        apps.lead_engine's requirement-submission flow). Determines
        eligible teachers, then dispatches to _distribute_online
        (subscription-tier ordering) or _distribute_offline
        (pure-distance ordering, no tier) depending on the
        requirement's teaching_mode.

        Returns the list of newly created LeadAssignment rows for
        stage 1. If NO teachers are eligible at all, returns an
        empty list (this is a valid, expected outcome - not an
        error - per Section 19, an ineligible pool means no
        distribution happens).
        """
        from apps.student_requirement.models import StudentRequirement

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

        if requirement.teaching_mode == TeachingMode.ONLINE:
            return LeadDistributionService._distribute_online(lead, eligible)
        return LeadDistributionService._distribute_offline(lead, eligible)

    @staticmethod
    @transaction.atomic
    def on_unlocked(lead, teacher) -> None:
        """
        Called once, right after a teacher unlocks a lead's contact
        details (apps.lead_engine.unlock_service._mark_unlocked).
        Unlocking now doubles as "accept" on the underlying
        LeadAssignment - there is no separate accept step for the
        general cascade any more, and a direct offer (is_direct)
        works the same way here since it only ever has one assignment.

        OFFLINE/BOTH: exclusive - marks this assignment ACCEPTED and
        cancels every other open assignment for the lead (including
        any tied-distance siblings), since a student only wants one
        offline tutor.

        ONLINE (and any is_direct assignment): shared/pooled - marks
        this assignment ACCEPTED for audit only; other tiers keep
        their scheduled reveal and can still unlock the same lead
        later (see reveal_next_online_stage).

        Looked up via lead__student_requirement, not lead= directly:
        every LeadAssignment for this requirement shares one
        canonical `lead` FK (see distribute_lead's docstring), which
        for a non-canonical teacher is a DIFFERENT Lead row than the
        one passed in here (their own).
        """
        assignment = (
            LeadAssignment.objects.select_for_update()
            .filter(lead__student_requirement=lead.student_requirement, teacher=teacher)
            .first()
        )
        if assignment is None or not assignment.can_transition_to(
            AssignmentStatus.ACCEPTED
        ):
            return  # nothing to reconcile - e.g. a stale/expired assignment

        now = timezone.now()
        assignment.status = AssignmentStatus.ACCEPTED
        assignment.response = AssignmentResponse.ACCEPT
        assignment.responded_at = now
        assignment.save(update_fields=["status", "response", "responded_at"])

        if (
            assignment.is_direct
            or lead.student_requirement.teaching_mode == TeachingMode.ONLINE
        ):
            return  # shared/pooled - no cascade stop

        other_open = (
            LeadAssignment.objects.select_for_update()
            .filter(
                lead=assignment.lead,  # the shared canonical lead, not the
                # (possibly non-canonical) `lead` param - see above.
                status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.VIEWED],
            )
            .exclude(id=assignment.id)
        )
        cancelled_count = other_open.update(status=AssignmentStatus.CANCELLED)
        if cancelled_count:
            logger.info(
                "Lead %s ACCEPTED (via unlock) by teacher %s - %d other open "
                "assignment(s) cancelled.",
                lead.id,
                teacher.user.email,
                cancelled_count,
            )

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
        OFFLINE/BOTH only: cascades to the next-nearest distance band
        once the current one is fully resolved (reject/expire).
        ONLINE no longer cascades on reject/expiry at all - a
        rejection or personal-visibility expiry just stops for that
        one teacher; reveal_next_online_stage runs on its own fixed
        time-based schedule instead, independent of resolution
        (see the module docstring).
        """
        requirement = lead.student_requirement
        if requirement.teaching_mode == TeachingMode.ONLINE:
            return
        LeadDistributionService._maybe_advance_offline_stage(lead, current_stage)

    @staticmethod
    @transaction.atomic
    def reveal_next_online_stage(lead, *, force: bool = False) -> list:
        """
        Time-based subscription-tier reveal for ONLINE leads only.
        Runs independently of whether the current stage has been
        unlocked, accepted, or rejected - a lower tier gets its
        scheduled turn regardless, since online leads are shared/
        pooled rather than exclusive (that's the whole point of this
        function existing separately from the offline cascade, which
        IS resolution-gated).

        Called by the reveal_online_lead_tiers beat task every few
        minutes; `force=True` skips the time check for exactly ONE
        reveal (the next due tier), then reverts to normal time
        gating for the rest of this call - used only by the
        `force_reveal_online_tier` management command, so a human can
        step through tiers one at a time for manual QA rather than
        jumping straight to the end in one call.

        Re-runs eligibility fresh every call (never caches the
        original tier plan, same reasoning as the offline cascade).
        Otherwise loops so a single (non-forced) call catches up more
        than one tier if several are simultaneously overdue (e.g. the
        beat task missed a cycle), stopping once the next tier isn't
        due yet or every eligible tier has already been offered.
        """
        requirement = lead.student_requirement
        if requirement.teaching_mode != TeachingMode.ONLINE:
            return []

        # lead__student_requirement, not lead= - any lead for this
        # requirement (canonical or not, e.g. one a management command
        # was pointed at) resolves the same underlying cascade.
        stage_one = (
            LeadAssignment.objects.filter(
                lead__student_requirement=requirement,
                assignment_stage=1,
                is_direct=False,
            )
            .order_by("assigned_at")
            .first()
        )
        if stage_one is None:
            return []  # never distributed - e.g. no eligible teachers at all

        # The true canonical lead every assignment for this requirement is
        # actually anchored to - not necessarily the `lead` passed in
        # (e.g. force_reveal_online_tier may be pointed at any teacher's
        # own Lead row for this requirement).
        canonical_lead = stage_one.lead

        config = get_config()
        revealed = []
        force_remaining = force
        while True:
            latest_stage = (
                LeadAssignment.objects.filter(
                    lead__student_requirement=requirement, is_direct=False
                ).aggregate(Max("assignment_stage"))["assignment_stage__max"]
                or 1
            )
            due_at = stage_one.assigned_at + timezone.timedelta(
                hours=config.online_tier_window_hours * latest_stage
            )
            if not force_remaining and timezone.now() < due_at:
                break
            force_remaining = False  # force only ever skips ONE reveal per call

            eligible = LeadDistributionService._get_eligible_teachers_with_scores(
                requirement
            )
            if not eligible:
                break

            plan_by_teacher_id = LeadDistributionService._plans_for(eligible)
            tiers = LeadDistributionService._group_by_tier(eligible, plan_by_teacher_id)
            already_offered_teacher_ids = set(
                LeadAssignment.objects.filter(
                    lead__student_requirement_id=requirement.id
                ).values_list("teacher_id", flat=True)
            )

            created_this_round = []
            for rank in tiers:
                candidates = [
                    e
                    for e in tiers[rank]
                    if e["teacher_profile"].teacher_id
                    not in already_offered_teacher_ids
                ]
                if not candidates:
                    continue
                now = timezone.now()
                expires_at = now + timezone.timedelta(
                    hours=config.lead_visibility_window_hours
                )
                created_this_round = LeadDistributionService._create_assignments(
                    canonical_lead,
                    candidates,
                    plan_by_teacher_id,
                    stage=latest_stage + 1,
                    now=now,
                    expires_at=expires_at,
                )
                logger.info(
                    "Lead %s revealed online stage %d (%d teacher(s), tier rank %d).",
                    canonical_lead.id,
                    latest_stage + 1,
                    len(created_this_round),
                    rank,
                )
                break

            if not created_this_round:
                break  # nothing left to reveal at any tier
            revealed.extend(created_this_round)

        return revealed

    @staticmethod
    def _maybe_advance_offline_stage(lead, current_stage: int) -> None:
        """
        Checks whether every assignment in `current_stage` (one
        distance band) is now resolved. If so, re-runs eligibility
        fresh and activates the next-nearest not-yet-offered distance
        band - subscription tier is never consulted for offline/both.
        """
        requirement = lead.student_requirement
        still_open = LeadAssignment.objects.filter(
            lead=lead,
            assignment_stage=current_stage,
            status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.VIEWED],
        ).exists()
        if still_open:
            return  # this band isn't fully resolved yet

        already_accepted = LeadAssignment.objects.filter(
            lead=lead, status=AssignmentStatus.ACCEPTED
        ).exists()
        if already_accepted:
            return  # cascade already stopped by an acceptance

        config = get_config()
        eligible = LeadDistributionService._get_eligible_teachers_with_scores(
            requirement
        )
        if not eligible:
            logger.info(
                "Lead %s: no eligible teachers remain for further stages.", lead.id
            )
            return

        plan_by_teacher_id = LeadDistributionService._plans_for(eligible)
        bands = LeadDistributionService._group_offline_by_distance(eligible)
        already_offered_teacher_ids = set(
            LeadAssignment.objects.filter(
                lead__student_requirement_id=lead.student_requirement_id
            ).values_list("teacher_id", flat=True)
        )

        next_stage = current_stage + 1
        for distance in bands:
            candidates = [
                e
                for e in bands[distance]
                if e["teacher_profile"].teacher_id not in already_offered_teacher_ids
            ]
            if not candidates:
                continue

            now = timezone.now()
            expires_at = now + timezone.timedelta(
                hours=config.offline_response_window_hours
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
                "Lead %s advanced to offline stage %d (%d teacher(s) at %.2fkm).",
                lead.id,
                next_stage,
                len(created),
                distance,
            )
            return

        logger.info(
            "Lead %s: all distance bands exhausted, no further teachers to offer.",
            lead.id,
        )

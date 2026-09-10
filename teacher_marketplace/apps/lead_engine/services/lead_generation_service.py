"""
Lead matching service for the Teacher Marketplace Platform.

This module contains the core matching algorithm described in the
spec: "When a student submits a requirement, automatically find
matching teachers." Implemented as a plain, synchronous service
function - called directly from
StudentRequirementListCreateView.create() (patched in the next
relevant file) immediately after a requirement is saved.

Kept as a service function rather than inline view logic or a
model method, following the Service Layer pattern mandated by the
project's architecture rules - this is genuine business logic
(a matching algorithm), which belongs in a service, not a view or
a model.

MATCHING CRITERIA (per spec):
    1. Subject      - teacher must teach the requirement's subject
    2. Language      - if the student specified a preferred language,
                       the teacher must teach in that language
                       (if the student left it blank, this
                       criterion is skipped entirely - no
                       requirement to match against)
    3. Location      - if the requirement's teaching_mode requires
                       Offline (OFFLINE or BOTH), the teacher must
                       serve the requirement's city
    4. Teaching Mode  - the teacher's teaching_mode must be
                       compatible with the requirement's (see
                       _teaching_modes_compatible for the exact
                       compatibility rules)
    5. Availability   - Phase 2 note: the requirement model does not
                       capture availability in the same structured
                       (day_type, time_slot) shape TeacherProfile
                       uses - preferred_timing is free text. So
                       "availability" matching in this phase means:
                       the teacher must have AT LEAST ONE
                       availability slot defined at all (i.e. they
                       have specified some availability), rather
                       than a precise slot-to-slot comparison. This
                       is a deliberate, documented simplification -
                       precise timing matching would require either
                       parsing free text or adding structured
                       availability fields to StudentRequirement,
                       neither of which is in scope here.
    6. Experience    - Phase 2 note: StudentRequirement has no
                       "minimum experience required" field in the
                       spec's own field list for this model, so
                       there is nothing to match Experience AGAINST.
                       This criterion is satisfied by simply
                       including years_of_experience in the Lead's
                       eventual display data (via TeacherProfile's
                       existing property) rather than as a filter -
                       there's no numeric threshold in the input
                       data to filter by.
    7. Verified       - only TeacherProfile records with
                       verification_status=VERIFIED are matched.
                       This is a firm filter, not a soft-preference,
                       since the spec explicitly lists "Verified
                       Teacher" as a Lead Dashboard/matching
                       criterion.

PHASE 4 UPDATE: this module's matching logic has been replaced.
find_matching_teacher_profiles() (Phase 2/3's simple filter-based
matching) is superseded by the two-phase pipeline below:

    PHASE 1 (this file): find_candidate_teacher_profiles() - a
        cheap, indexed SQL filter (subject, language, verification)
        narrowing the full teacher table down to a small candidate
        set. This is the ONLY step that touches the database at
        scale - it uses indexed columns (verification_status,
        subjects M2M, languages M2M) exclusively.

    PHASE 2 (this file, calling out to services/): generate_leads_
        for_requirement() runs apps.lead_engine.services.
        matching_service.MatchingService.score_teacher() - the full,
        expensive, Python-side scoring computation (including time-
        overlap math) - ONLY against the already-narrowed PHASE 1
        candidate set. This guarantees the expensive scoring never
        runs against the full teacher table, regardless of how many
        teachers exist platform-wide - it only scales with the
        (typically much smaller) number of verified teachers
        teaching the requested subject.

Results are ranked via apps.lead_engine.services.ranking_service.
RankingService (match_score desc, with explicit tie-breaking), and
filtered by settings.MINIMUM_LEAD_MATCH_SCORE before any Lead rows
are created - per the explicit business rule against generating
"obviously incompatible" leads.

_teaching_modes_compatible() (below) is retained from Phase 2/3 -
it's now reused by MatchingService._location_score() as well, so
this small function has two callers across two files.
"""

import logging

from django.conf import settings

from apps.lead_engine.models import Lead, LeadMatchScore
from apps.teacher_profile.models import TeacherProfile, TeachingMode

logger = logging.getLogger("apps.lead_engine")


def _teaching_modes_compatible(requirement_mode: str, teacher_mode: str) -> bool:
    """
    Determines whether a teacher's teaching_mode can satisfy a
    requirement's teaching_mode.

    Compatibility rules:
        - Teacher offering BOTH satisfies any requirement mode.
        - Requirement asking for BOTH is satisfied by a teacher
          offering ONLINE, OFFLINE, or BOTH (the teacher covers at
          least one of the modes the student is open to).
        - Otherwise, the modes must match exactly (ONLINE-ONLINE,
          OFFLINE-OFFLINE).
    """
    if teacher_mode == TeachingMode.BOTH:
        return True
    if requirement_mode == TeachingMode.BOTH:
        return True
    return requirement_mode == teacher_mode


def find_candidate_teacher_profiles(requirement):
    """
    PHASE 1 of the two-phase performance strategy (see module
    docstring below): a cheap, indexed SQL filter narrowing to
    verified teachers who teach the right subject - and, if the
    requirement is offline-capable, who serve the right city. This
    is intentionally the SAME cheap narrowing Phase 2 used, now
    explicitly separated from scoring (which is expensive and must
    only run against this already-narrowed set, never the full
    teacher table).
    """
    from apps.trust.matching_support import apply_teacher_gate, exclude_blocked_teachers

    queryset = (
        exclude_blocked_teachers(
            apply_teacher_gate(
                TeacherProfile.objects.filter(
                    subjects=requirement.subject,
                    teacher__user__is_active=True,
                )
            ),
            requirement.student,
        )
        .select_related("teacher", "teacher__user")
        .prefetch_related(
            "weekly_availability",
            "schedule_exceptions",
            "languages",
            "cities",
            "subjects",
        )
        .distinct()
    )

    if requirement.preferred_language_id:
        queryset = queryset.filter(languages=requirement.preferred_language)

    return queryset


def generate_leads_for_requirement(requirement):
    """
    PHASE 2 of the two-phase performance strategy: runs the full
    MatchingService scoring pass ONLY against the already-narrowed
    candidate set from find_candidate_teacher_profiles(), never the
    full teacher table - this is the query-optimization strategy
    the spec explicitly asks to be documented.

    For each candidate scoring at or above
    settings.MINIMUM_LEAD_MATCH_SCORE, creates a Lead + its
    corresponding LeadMatchScore row (skipping any teacher who
    already has a Lead for this requirement, same idempotency
    guarantee as Phase 2). Returns the list of newly created Lead
    instances, ranked by RankingService (best match first).
    """
    from django.db import transaction
    from django.db.models import prefetch_related_objects
    from django.utils import timezone as _timezone

    from apps.lead_engine.services.matching_service import MatchingService
    from apps.lead_engine.services.ranking_service import RankingService
    from apps.subscriptions.services import SubscriptionService

    # MatchingService.score_teacher() reads requirement.schedule_preferences
    # twice, and it runs once per candidate - without this prefetch that was
    # 2 identical queries for the *student's* windows per matching teacher
    # (the linear cost that made a popular-subject POST slow). Prefetch once.
    prefetch_related_objects([requirement], "schedule_preferences")

    candidates = list(find_candidate_teacher_profiles(requirement))

    existing_teacher_profile_ids = set(
        Lead.objects.filter(student_requirement=requirement).values_list(
            "teacher_profile_id", flat=True
        )
    )

    # One subscription query for the whole candidate set instead of two
    # per candidate inside MatchingService._premium_score.
    plan_by_teacher_id = SubscriptionService.get_effective_plans(
        {c.teacher_id for c in candidates}
    )

    scored_candidates = []
    for profile in candidates:
        if profile.id in existing_teacher_profile_ids:
            continue
        score = MatchingService.score_teacher(
            profile,
            requirement,
            effective_plan=plan_by_teacher_id.get(profile.teacher_id),
        )
        scored_candidates.append({"teacher_profile": profile, "score": score})

    minimum_score = getattr(settings, "MINIMUM_LEAD_MATCH_SCORE", 0)
    scored_candidates = RankingService.filter_minimum_relevance(
        scored_candidates, minimum_score
    )
    ranked_candidates = RankingService.rank_candidates(scored_candidates)

    # Bulk insert instead of get_or_create-per-candidate: the old loop did
    # ~5-7 queries PER matching teacher (BEGIN/SELECT/SAVEPOINT/INSERT x2/
    # RELEASE/COMMIT), so a popular subject with 100+ verified teachers ran
    # hundreds of queries synchronously. This is now a fixed handful
    # regardless of candidate count. ignore_conflicts keeps the same
    # idempotency guarantee as the old per-row savepoint: the
    # (student_requirement, teacher_profile) unique constraint and
    # LeadMatchScore.lead OneToOne are the real guards, so a concurrent
    # worker inserting the same rows is a silent skip, not a crash.
    to_create = [
        c
        for c in ranked_candidates
        if c["teacher_profile"].id not in existing_teacher_profile_ids
    ]
    new_leads = []
    if to_create:
        now = _timezone.now()
        candidate_tp_ids = [c["teacher_profile"].id for c in to_create]
        with transaction.atomic():
            Lead.objects.bulk_create(
                [
                    Lead(
                        student_requirement=requirement,
                        teacher_profile=c["teacher_profile"],
                        updated_at=now,  # auto_now is skipped by bulk_create
                    )
                    for c in to_create
                ],
                ignore_conflicts=True,
            )
            # Re-read for authoritative PKs (ignore_conflicts leaves the PK
            # unset on any row a concurrent worker had already inserted).
            lead_by_tp_id = {
                lead.teacher_profile_id: lead
                for lead in Lead.objects.filter(
                    student_requirement=requirement,
                    teacher_profile_id__in=candidate_tp_ids,
                )
            }
            already_scored = set(
                LeadMatchScore.objects.filter(
                    lead_id__in=[lead.id for lead in lead_by_tp_id.values()]
                ).values_list("lead_id", flat=True)
            )
            score_objs = []
            for candidate in to_create:  # preserves RankingService order
                lead = lead_by_tp_id.get(candidate["teacher_profile"].id)
                if lead is None or lead.id in already_scored:
                    continue
                score_objs.append(
                    LeadMatchScore(lead=lead, updated_at=now, **candidate["score"])
                )
                new_leads.append(lead)
            LeadMatchScore.objects.bulk_create(score_objs, ignore_conflicts=True)

    # Advance the requirement's lifecycle status once it has at least one
    # generated Lead - the RequirementStatus.MATCHED docstring states this
    # is "set by lead_engine", but nothing actually did it before, so a
    # matched requirement showed as "Open" forever in the student's UI.
    if new_leads:
        from apps.student_requirement.models import RequirementStatus

        if requirement.status == RequirementStatus.OPEN:
            requirement.status = RequirementStatus.MATCHED
            requirement.save(update_fields=["status", "updated_at"])

    if new_leads:
        logger.info(
            "Generated %d lead(s) for requirement %s (subject=%s, min_score=%d)",
            len(new_leads),
            requirement.id,
            requirement.subject.name,
            minimum_score,
        )
    else:
        logger.info(
            "No teachers met the minimum match score (%d) for requirement %s (subject=%s)",
            minimum_score,
            requirement.id,
            requirement.subject.name,
        )

    return new_leads

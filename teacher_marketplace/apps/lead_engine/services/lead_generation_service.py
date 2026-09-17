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
    2. Language      - if the student ranked one or more preferred
                       languages, the teacher must teach in at
                       least one of them (rank affects relative
                       score, not this pass/fail gate - see
                       MatchingService._language_score); if the
                       student chose "any language", this
                       criterion is skipped entirely
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


def _allowed_teacher_modes(requirement_mode) -> list:
    """
    The set of TeacherProfile.teaching_mode values that
    _teaching_modes_compatible(requirement_mode, teacher_mode) would
    accept, expressed as a plain list so it can be used in a
    `teaching_mode__in=...` DB filter - collapsing the pairwise
    function into a single-sided lookup since `requirement_mode` is
    fixed for the whole queryset.
    """
    if requirement_mode == TeachingMode.BOTH:
        return [TeachingMode.ONLINE, TeachingMode.OFFLINE, TeachingMode.BOTH]
    return [requirement_mode, TeachingMode.BOTH]


def _offline_location_eligible_ids(candidates, requirement) -> set:
    """
    Returns the subset (by TeacherProfile.id) of `candidates` who
    could actually be offered this OFFLINE/BOTH requirement in real
    life - i.e. applies the SAME location gate
    LeadDistributionService/EligibilityService already use for the
    real LeadAssignment offer, so a teacher who is genuinely too far
    away (or in an unconfirmed city) never even generates a soft Lead
    a student's "matched" count relies on and a teacher can pay to
    unlock. Before this, location only fed a soft score
    (MatchingService._location_score, 10% weight) that was never
    enough to actually exclude anyone - a teacher tens of kilometres
    away for an in-person lesson still generated a Lead.

    `candidates` must already be the subject/language/mode-narrowed
    list (small, per the two-phase strategy) - this never runs
    against the full teacher table.

    Falls back to the older "teacher lists this city as served" check
    only when real pincode-distance data isn't available for the
    requirement or a given teacher (e.g. pre-dates the address
    feature, or geocoding hasn't resolved yet) - real distance is
    authoritative whenever both sides have it.
    """
    from apps.matching.services.location_matching_service import (
        LocationMatchingService,
    )

    candidate_pincode_ids = {
        c.id: c.teacher.pincode_location_id
        for c in candidates
        if c.teacher.pincode_location_id is not None
    }
    location_results = {}
    if requirement.pincode_location_id is not None and candidate_pincode_ids:
        location_results = LocationMatchingService.find_eligible_teacher_ids(
            requirement.pincode_location, candidate_pincode_ids
        )

    kept_ids = set()
    for c in candidates:
        result = location_results.get(c.id)
        if result is not None:
            # Real distance was computed for this teacher - authoritative,
            # whichever way it goes.
            if result.is_eligible:
                kept_ids.add(c.id)
            continue
        # No pincode-distance comparison available for this teacher
        # specifically (their own pincode_location is missing/unresolved).
        # Fall back to the coarser "does this teacher serve that city"
        # signal wherever the requirement actually has one to check.
        if requirement.city_id is not None:
            teacher_city_ids = {city.id for city in c.cities.all()}
            if requirement.city_id in teacher_city_ids:
                kept_ids.add(c.id)
            continue
        if requirement.pincode_location_id is None:
            # The requirement itself has NO location signal at all (no
            # city, no pincode) - nothing to disqualify this teacher
            # against, so don't over-exclude on missing data.
            kept_ids.add(c.id)
            continue
        # The requirement DOES have a real, precise pincode-based location
        # (just no separate City row - e.g. it was created from a raw
        # pincode rather than a city name), but this teacher has neither a
        # comparable pincode_location nor a served-city entry. There is no
        # way to confirm they are anywhere near this student, so - unlike
        # the "no signal at all" case above - do not assume they are.
    return kept_ids


def find_candidate_teacher_profiles(requirement):
    """
    PHASE 1 of the two-phase performance strategy (see module
    docstring below): a cheap, indexed SQL filter narrowing to
    verified teachers who teach the right subject and whose teaching
    mode is compatible with the requirement's - plus, if the
    requirement is offline-capable, a hard location-eligibility gate
    (see _filter_by_offline_location_eligibility). This is
    intentionally the SAME narrowing Phase 2 used, now explicitly
    separated from scoring (which is expensive and must only run
    against this already-narrowed set, never the full teacher table).

    Still returns a lazy queryset (existing callers outside this
    module chain further queryset methods - e.g. .values_list() - off
    the result), even though the location gate below needs the rows
    materialised first to compute distances in Python: that
    materialisation happens internally, and the ineligible rows are
    then excluded via one final `.filter(id__in=...)` so the return
    value stays a genuine, further-chainable QuerySet.
    """
    from apps.trust.matching_support import apply_teacher_gate, exclude_blocked_teachers

    queryset = (
        exclude_blocked_teachers(
            apply_teacher_gate(
                TeacherProfile.objects.filter(
                    subjects=requirement.subject,
                    teacher__user__is_active=True,
                    teaching_mode__in=_allowed_teacher_modes(requirement.teaching_mode),
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

    if not requirement.no_language_preference:
        language_ids = requirement.preferred_language_ids
        if language_ids:
            queryset = queryset.filter(languages__id__in=language_ids)

    if requirement.teaching_mode not in (TeachingMode.OFFLINE, TeachingMode.BOTH):
        return queryset

    eligible_ids = _offline_location_eligible_ids(list(queryset), requirement)
    return queryset.filter(id__in=eligible_ids)


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
    # and (via _language_score) requirement.preferred_languages, each once
    # per candidate - without this prefetch that was N identical queries
    # per matching teacher (the linear cost that made a popular-subject
    # POST slow). Prefetch both once.
    prefetch_related_objects(
        [requirement], "schedule_preferences", "preferred_languages"
    )

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

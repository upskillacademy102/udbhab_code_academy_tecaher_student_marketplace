"""
Matching service for the Teacher Marketplace Platform.

MatchingService.score_teacher() is the single entry point that
computes a full LeadMatchScore-shaped result for one
(teacher, requirement) pair. It composes 10 independent score components,
each 0-100, weighted per settings.MATCHING_WEIGHTS, into one
composite match_score.

CRITICAL BUSINESS RULE - ENFORCED STRUCTURALLY, NOT VIA SPECIAL-CASE
CODE: "Premium Membership must NOT override a severe schedule
mismatch." This is guaranteed purely by weighting arithmetic:
premium_score contributes at most 2% of the total (per
MATCHING_WEIGHTS["premium"]), while time_score contributes up to
30%. A Premium teacher with 0% time compatibility can gain at most
2 points from their premium status - nowhere near enough to
out-rank a Free teacher scoring even moderately on time
compatibility. There is no `if is_premium: boost_score()` branch
anywhere in this file - the rule holds simply because the weights
are what they are. See
apps/lead_engine/tests/test_matching_service.py for the explicit
"High time match vs Premium status" test proving this.

This service is called from lead_generation_service.py (rewired in
the next file) at requirement-submission time - never on-demand per
search request (that's handled by a lighter-weight path in
apps.search for the general browse/search case, which does not
require a specific StudentRequirement to score against).
"""

import logging

from django.conf import settings

from apps.lead_engine.services.time_compatibility_service import (
    TimeCompatibilityService,
    TimeSlot,
)
from apps.subscriptions.services import SubscriptionService

logger = logging.getLogger("apps.lead_engine.matching")


class MatchingService:

    @staticmethod
    def _get_weights() -> dict:
        """
        Reads weights from settings on every call (not cached at
        import time) - a future admin-configurable override that
        writes to a database-backed config and monkeypatches or
        overrides settings.MATCHING_WEIGHTS at runtime would be
        picked up immediately, without requiring this service to
        change.
        """
        weights = settings.MATCHING_WEIGHTS
        total = sum(weights.values())
        if total != 100:
            logger.warning(
                "MATCHING_WEIGHTS do not sum to 100 (sum=%s) - scores will "
                "be scaled proportionally, but this should be corrected in "
                "settings.",
                total,
            )
        return weights

    # ------------------------------------------------------------
    # INDIVIDUAL SCORE COMPONENTS (each returns 0-100)
    # ------------------------------------------------------------
    @staticmethod
    def _subject_score(teacher_profile, requirement) -> int:
        # Uses the prefetched `subjects` cache (see
        # find_candidate_teacher_profiles) - `.filter().exists()` would
        # bypass it and issue one query per candidate.
        teacher_subject_ids = {s.id for s in teacher_profile.subjects.all()}
        return 100 if requirement.subject_id in teacher_subject_ids else 0

    @staticmethod
    def _language_score(teacher_profile, requirement) -> int:
        if requirement.preferred_language_id is None:
            # Student expressed no preference - not a mismatch,
            # full score (nothing to fail to match against).
            return 100
        teacher_language_ids = {lang.id for lang in teacher_profile.languages.all()}
        return 100 if requirement.preferred_language_id in teacher_language_ids else 0

    @staticmethod
    def _location_score(teacher_profile, requirement) -> int:
        """
        100 if teaching modes are compatible AND (for offline-
        capable requirements) the teacher serves the requirement's
        city. Purely online requirements score on mode compatibility
        alone since location doesn't apply.
        """
        from apps.lead_engine.services import _teaching_modes_compatible
        from apps.teacher_profile.models import TeachingMode

        if not _teaching_modes_compatible(
            requirement.teaching_mode, teacher_profile.teaching_mode
        ):
            return 0

        if requirement.teaching_mode in (TeachingMode.OFFLINE, TeachingMode.BOTH):
            teacher_city_ids = {c.id for c in teacher_profile.cities.all()}
            if requirement.city_id and requirement.city_id not in teacher_city_ids:
                return 40  # mode compatible but no confirmed location coverage - partial credit
        return 100

    @staticmethod
    def _budget_score(teacher_profile, requirement) -> int:
        """
        100 if the teacher's hourly_rate falls within
        [budget_min, budget_max] (inclusive). Degrades linearly for
        rates above budget_max (a teacher who costs 20% more than
        the top of budget is a much softer mismatch than one who
        costs 200% more). No penalty for being below budget_min
        (cheaper than requested is never a problem for the student).
        Returns 100 if the requirement has no budget specified at
        all (nothing to compare against) or the teacher has no rate
        set yet.
        """
        rate = teacher_profile.hourly_rate
        if rate is None or (
            requirement.budget_min is None and requirement.budget_max is None
        ):
            return 100

        if requirement.budget_min is not None and rate < requirement.budget_min:
            return 100  # cheaper than the student's minimum - not a problem

        if requirement.budget_max is not None and rate > requirement.budget_max:
            overage_ratio = float(
                (rate - requirement.budget_max) / requirement.budget_max
            )
            # Linear decay: at 100% over budget, score hits 0.
            score = max(0, 100 - round(overage_ratio * 100))
            return score

        return 100

    @staticmethod
    def _rating_score(teacher_profile) -> int:
        # rating is stored 0.00-5.00 - scale directly to 0-100.
        return min(round(float(teacher_profile.rating) / 5 * 100), 100)

    @staticmethod
    def _experience_score(teacher_profile) -> int:
        """
        Log-scaled and capped, per the file plan's summary: raw
        years of experience diminish in marginal value (the
        difference between 1 and 3 years matters more than between
        15 and 17). Capped at 100 for 10+ years.
        """
        years = teacher_profile.years_of_experience or 0
        if years <= 0:
            return 20  # some baseline credit even for a brand-new teacher, not zero
        if years >= 10:
            return 100
        # Simple piecewise scale: 20 (0yr baseline) up to 100 (10yr).
        return min(round(20 + (years / 10) * 80), 100)

    @staticmethod
    def _verification_score(teacher_profile) -> int:
        from apps.teacher_profile.models import VerificationStatus

        return (
            100
            if teacher_profile.verification_status == VerificationStatus.VERIFIED
            else 0
        )

    @staticmethod
    def _response_rate_score() -> int:
        # See LeadMatchScore.response_rate_score's docstring - no
        # real tracking exists yet; always full score until it does.
        return 100

    @staticmethod
    def _premium_score(teacher, plan=None) -> int:
        """
        Small boost for teachers on a paid (non-Free) plan. Capped
        low deliberately - this component's WEIGHT (2%, per
        MATCHING_WEIGHTS) is what actually enforces the "premium
        cannot override mismatch" rule.

        ``plan`` may be passed in by a caller that already resolved
        effective plans in bulk (see generate_leads_for_requirement),
        avoiding one subscription query per candidate teacher.
        """
        if plan is None:
            plan = SubscriptionService.get_effective_plan(teacher)
        if plan.name.lower() == "free":
            return 0
        return 100

    # ------------------------------------------------------------
    # ORCHESTRATION
    # ------------------------------------------------------------
    @staticmethod
    def _get_teacher_time_slots(teacher_profile, on_date=None) -> list:
        """
        Builds TimeSlot objects from this teacher's active
        TeacherWeeklyAvailability rows, EXCLUDING any day currently
        covered by a full-day TeacherScheduleException (partial-time
        exceptions are not yet subtracted from the slot itself in
        this implementation - see note in the docstring below).

        NOTE ON EXCEPTION SCOPE: a full-day exception for "today" is
        checked against `on_date` if provided; recurring weekly
        matching (the primary use case at lead-generation time, which
        has no single specific target date) does not filter by
        exceptions at all, since a recurring pattern match is
        answering "are these schedules generally compatible," not
        "is the teacher free on this exact date." Exception-aware
        matching for a SPECIFIC session date is a booking-flow
        concern for a later phase - flagged here rather than silently
        conflating the two.
        """
        if on_date is not None:
            exception_days = set(
                teacher_profile.schedule_exceptions.filter(
                    date=on_date, start_time__isnull=True
                ).values_list("date", flat=True)
            )
            if on_date in exception_days:
                return []

        # Iterate the prefetched cache and filter in Python -
        # `.filter(is_active=True)` would bypass the prefetch and hit the
        # DB once per candidate teacher.
        return [
            TimeSlot(
                day_of_week=row.day_of_week,
                start_time=row.start_time,
                end_time=row.end_time,
                timezone=row.timezone,
            )
            for row in teacher_profile.weekly_availability.all()
            if row.is_active
        ]

    @staticmethod
    def _get_student_time_slots(requirement) -> list:
        return [
            TimeSlot(
                day_of_week=row.day_of_week,
                start_time=row.start_time,
                end_time=row.end_time,
                timezone=row.timezone,
                is_flexible=(row.flexibility == "flexible"),
            )
            for row in requirement.schedule_preferences.all()
        ]

    @staticmethod
    def score_teacher(teacher_profile, requirement, *, effective_plan=None) -> dict:
        """
        Computes the full score breakdown for one (teacher_profile,
        requirement) pair. Returns a dict with keys matching
        LeadMatchScore's fields exactly, ready for
        LeadMatchScore.objects.create(**result) by the caller (minus
        the `lead` FK, which the caller attaches).

        ``effective_plan`` may be supplied by a caller that resolved
        every candidate's plan in one query (generate_leads_for_
        requirement) - otherwise it is looked up here.
        """
        weights = MatchingService._get_weights()
        teacher = teacher_profile.teacher

        subject_score = MatchingService._subject_score(teacher_profile, requirement)
        language_score = MatchingService._language_score(teacher_profile, requirement)
        location_score = MatchingService._location_score(teacher_profile, requirement)
        budget_score = MatchingService._budget_score(teacher_profile, requirement)
        rating_score = MatchingService._rating_score(teacher_profile)
        experience_score = MatchingService._experience_score(teacher_profile)
        verification_score = MatchingService._verification_score(teacher_profile)
        response_rate_score = MatchingService._response_rate_score()
        premium_score = MatchingService._premium_score(teacher, plan=effective_plan)

        student_slots = MatchingService._get_student_time_slots(requirement)
        teacher_slots = MatchingService._get_teacher_time_slots(teacher_profile)

        time_result = TimeCompatibilityService.find_best_overlap(
            student_slots=student_slots,
            teacher_slots=teacher_slots,
            required_duration_minutes=requirement.class_duration_minutes,
        )
        time_score = time_result["time_score"]

        if not time_result["has_any_overlap"]:
            availability_status = "incompatible"
        elif time_result["is_duration_compatible"]:
            availability_status = "compatible"
        else:
            availability_status = "partially_compatible"

        component_scores = {
            "subject": subject_score,
            "time": time_score,
            "language": language_score,
            "location": location_score,
            "budget": budget_score,
            "rating": rating_score,
            "experience": experience_score,
            "verification": verification_score,
            "response_rate": response_rate_score,
            "premium": premium_score,
        }

        weighted_sum = sum(
            component_scores[key] * weights.get(key, 0) for key in component_scores
        )
        total_weight = sum(weights.values()) or 100
        match_score = round(weighted_sum / total_weight)

        best_start_local = None
        best_end_local = None
        best_tz = None
        if time_result["best_start_utc"] is not None:
            student_pref = next(
                (
                    p
                    for p in requirement.schedule_preferences.all()
                    if p.day_of_week == time_result["best_day"]
                ),
                None,
            )
            best_tz = student_pref.timezone if student_pref else "UTC"
            best_start_local = TimeCompatibilityService.convert_utc_to_timezone(
                time_result["best_start_utc"], best_tz
            )
            best_end_local = TimeCompatibilityService.convert_utc_to_timezone(
                time_result["best_end_utc"], best_tz
            )

        return {
            "match_score": max(min(match_score, 100), 0),
            "subject_score": subject_score,
            "time_score": time_score,
            "language_score": language_score,
            "location_score": location_score,
            "budget_score": budget_score,
            "rating_score": rating_score,
            "experience_score": experience_score,
            "verification_score": verification_score,
            "response_rate_score": response_rate_score,
            "premium_score": premium_score,
            "best_matching_day": time_result["best_day"],
            "best_matching_start_time": (
                best_start_local.time() if best_start_local else None
            ),
            "best_matching_end_time": best_end_local.time() if best_end_local else None,
            "best_matching_timezone": best_tz,
            "availability_status": availability_status,
        }

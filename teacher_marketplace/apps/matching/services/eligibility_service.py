"""
Eligibility service for the Teacher Marketplace Platform.

THE MOST IMPORTANT STRUCTURAL GUARANTEE IN THIS APP: this service's
signature takes ONLY relevance inputs (teacher's subjects/languages/
availability/pincode, requirement's subject/language/schedule/mode/
pincode). It has NO parameter for subscription_tier, token_balance,
rating, or experience - those literally cannot influence
is_eligible() because they are not in scope inside this function.
This is the concrete mechanism implementing Section 3's rule:
"Do NOT allow ranking factors such as subscription or token balance
to make an otherwise ineligible teacher eligible."

ONLINE eligibility (Section 14): subject AND language AND time.
    Location is NEVER checked - not skipped due to missing data,
    genuinely not part of the online eligibility function at all.

OFFLINE eligibility (Section 15): subject AND language AND time AND
    location (within the current search radius).

All four/three checks are ANDed - a single failing criterion makes
the teacher ineligible, full stop, regardless of how strongly they
pass the others.
"""

from dataclasses import dataclass
from typing import Optional

from apps.lead_engine.services.time_compatibility_service import (
    TimeCompatibilityService,
)
from apps.matching.services.config_service import get_config
from apps.matching.services.language_matching_service import LanguageMatchingService
from apps.matching.services.subject_matching_service import SubjectMatchingService
from apps.teacher_profile.models import TeachingMode


@dataclass(frozen=True)
class EligibilityResult:
    """
    Full breakdown, not just a boolean - the caller
    (MatchScoreService / TeacherRankingService) needs the individual
    component results both to compute the relevance score AND to
    build the search-result explanation (Section 39).
    """

    is_eligible: bool
    subject_result: object
    language_result: object
    time_result: dict
    location_result: Optional[object]  # None for ONLINE mode - genuinely not applicable
    rejection_reason: Optional[str] = None


class EligibilityService:

    @staticmethod
    def check_teacher_eligibility(
        *,
        teacher_profile,
        requirement,
        teacher_slots: list,
        student_slots: list,
        location_precomputed=None,
        config=None,
    ) -> EligibilityResult:
        """
        Args:
            teacher_profile: a TeacherProfile instance.
            requirement: a StudentRequirement instance.
            teacher_slots / student_slots: pre-built TimeSlot lists
                (caller's responsibility to fetch these - keeps this
                service free of its own duplicate availability
                queries, since callers already have this data from
                the two-phase candidate-narrowing step).
            location_precomputed: an already-computed
                LocationMatchResult for this teacher, if the caller
                ran LocationMatchingService.find_eligible_teacher_ids()
                in bulk beforehand (the efficient path for scoring
                many candidates at once - see MatchScoreService).
                If None and mode is OFFLINE, this method returns
                ineligible with a clear rejection_reason rather than
                silently skipping the location check.

        Returns EligibilityResult. NOTHING about subscription/tokens
        is read or referenced anywhere in this method.

        ``config`` may be passed by a caller scoring many candidates so
        the MatchingConfig row is fetched once, not once per teacher.
        """
        config = config or get_config()

        subject_result = SubjectMatchingService.match_by_id(
            teacher_subject_ids={s.id for s in teacher_profile.subjects.all()},
            required_subject_id=requirement.subject_id,
        )
        if not subject_result.is_eligible:
            return EligibilityResult(
                is_eligible=False,
                subject_result=subject_result,
                language_result=None,
                time_result={},
                location_result=None,
                rejection_reason="subject_mismatch",
            )

        # Teaching-mode compatibility: a teacher who only teaches online
        # must never be eligible for an OFFLINE requirement, and vice
        # versa - a BOTH on either side satisfies anything (see
        # _teaching_modes_compatible's own docstring for the exact rule).
        # Previously this was checked nowhere in this service - the
        # OFFLINE/BOTH direction happened to be caught downstream only as
        # a side effect of an online-only teacher usually lacking
        # pincode_location (so location_precomputed came back None), and
        # the ONLINE direction wasn't caught at all: a strictly-offline
        # teacher (who has explicitly said they never teach online) could
        # be marked eligible for - and offered - a purely online lead.
        from apps.lead_engine.services import _teaching_modes_compatible

        if not _teaching_modes_compatible(
            requirement.teaching_mode, teacher_profile.teaching_mode
        ):
            return EligibilityResult(
                is_eligible=False,
                subject_result=subject_result,
                language_result=None,
                time_result={},
                location_result=None,
                rejection_reason="teaching_mode_mismatch",
            )

        language_result = LanguageMatchingService.match_by_ids(
            teacher_language_ids={lang.id for lang in teacher_profile.languages.all()},
            required_language_ids=requirement.preferred_language_ids,
            no_preference=getattr(requirement, "no_language_preference", False),
        )
        if not language_result.is_eligible:
            return EligibilityResult(
                is_eligible=False,
                subject_result=subject_result,
                language_result=language_result,
                time_result={},
                location_result=None,
                rejection_reason="language_mismatch",
            )

        time_result = TimeCompatibilityService.find_best_overlap(
            student_slots=student_slots,
            teacher_slots=teacher_slots,
            required_duration_minutes=requirement.class_duration_minutes,
        )
        time_eligible = (
            time_result["has_any_overlap"]
            and time_result["overlap_minutes"] >= config.time_match_threshold_minutes
        )
        if not time_eligible:
            return EligibilityResult(
                is_eligible=False,
                subject_result=subject_result,
                language_result=language_result,
                time_result=time_result,
                location_result=None,
                rejection_reason="no_time_overlap",
            )

        # ONLINE: location is genuinely not part of eligibility.
        if requirement.teaching_mode == TeachingMode.ONLINE:
            return EligibilityResult(
                is_eligible=True,
                subject_result=subject_result,
                language_result=language_result,
                time_result=time_result,
                location_result=None,
            )

        # OFFLINE (or BOTH, treated as offline-capable for location
        # purposes - a teacher offering BOTH must still be within
        # radius to be eligible for an offline-mode requirement).
        if location_precomputed is None:
            return EligibilityResult(
                is_eligible=False,
                subject_result=subject_result,
                language_result=language_result,
                time_result=time_result,
                location_result=None,
                rejection_reason="location_not_evaluated",
            )

        if not location_precomputed.is_eligible:
            return EligibilityResult(
                is_eligible=False,
                subject_result=subject_result,
                language_result=language_result,
                time_result=time_result,
                location_result=location_precomputed,
                rejection_reason="outside_search_radius",
            )

        return EligibilityResult(
            is_eligible=True,
            subject_result=subject_result,
            language_result=language_result,
            time_result=time_result,
            location_result=location_precomputed,
        )

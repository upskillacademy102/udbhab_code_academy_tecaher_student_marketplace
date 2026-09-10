"""
Match score service for the Teacher Marketplace Platform.

Computes RELEVANCE SCORE ONLY - subject, language, time, location.
Per Section 32's explicit instruction: "Do not mix subscription and
token balance into the core eligibility score." This service's
output has no knowledge of subscription tier or token balance -
those are computed entirely separately by
SubscriptionPriorityService / TokenPriorityService and combined
only at the final ranking step, never blended into this score.

This intentionally reuses (does not duplicate) the weighting
concept already established in apps.lead_engine.services.
matching_service.MatchingService - but scoped to ONLY the four
relevance components, using a dedicated RELEVANCE_WEIGHTS dict
rather than the full 10-component MATCHING_WEIGHTS (which already
blends in rating/experience/premium - exactly what Section 32 says
to keep separate at this layer).
"""

from dataclasses import dataclass

from django.conf import settings

RELEVANCE_WEIGHTS = getattr(
    settings,
    "RELEVANCE_WEIGHTS",
    {"subject": 35, "language": 20, "time": 35, "location": 10},
)


@dataclass(frozen=True)
class RelevanceScore:
    overall: int
    subject_score: int
    language_score: int
    time_score: int
    location_score: int


class MatchScoreService:

    @staticmethod
    def compute(eligibility_result) -> RelevanceScore:
        """
        Takes the EligibilityResult already produced by
        EligibilityService (avoids recomputing subject/language/
        time/location - this service is purely arithmetic over
        results the gate already calculated) and produces the
        weighted relevance score.

        For ONLINE requirements, location_result is None
        (Section 14: location genuinely doesn't apply) - its weight
        is proportionally redistributed across the remaining three
        components rather than silently treated as a 0, since
        scoring a non-applicable dimension as zero would incorrectly
        drag down an online teacher's relevance for a criterion that
        was never relevant to them in the first place.
        """
        subject_score = (
            eligibility_result.subject_result.score
            if eligibility_result.subject_result
            else 0
        )
        language_score = (
            eligibility_result.language_result.score
            if eligibility_result.language_result
            else 0
        )
        time_score = eligibility_result.time_result.get("time_score", 0)

        if eligibility_result.location_result is None:
            # ONLINE - redistribute location's weight across the other three.
            total_weight = (
                RELEVANCE_WEIGHTS["subject"]
                + RELEVANCE_WEIGHTS["language"]
                + RELEVANCE_WEIGHTS["time"]
            )
            weighted = (
                subject_score * RELEVANCE_WEIGHTS["subject"]
                + language_score * RELEVANCE_WEIGHTS["language"]
                + time_score * RELEVANCE_WEIGHTS["time"]
            )
            location_score = 0
        else:
            location_score = eligibility_result.location_result.score
            total_weight = sum(RELEVANCE_WEIGHTS.values())
            weighted = (
                subject_score * RELEVANCE_WEIGHTS["subject"]
                + language_score * RELEVANCE_WEIGHTS["language"]
                + time_score * RELEVANCE_WEIGHTS["time"]
                + location_score * RELEVANCE_WEIGHTS["location"]
            )

        overall = round(weighted / total_weight) if total_weight else 0

        return RelevanceScore(
            overall=max(min(overall, 100), 0),
            subject_score=subject_score,
            language_score=language_score,
            time_score=time_score,
            location_score=location_score,
        )

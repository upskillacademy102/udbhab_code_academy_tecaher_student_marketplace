"""
Teacher ranking service for the Teacher Marketplace Platform.

Implements Section 32's exact architecture:

    RELEVANCE SCORE (primary sort key, descending)
    +
    BUSINESS PRIORITY (subscription tier, then token balance, then
        rating, then experience - tiebreak ONLY, in that priority
        order, per Section 16's requested ranking priority list)
    =
    FINAL RANK

Relevance is checked FIRST and is the dominant sort key - two
teachers with different relevance scores are never reordered by
business priority. Business priority only decides ordering AMONG
teachers who are already eligible and have already been scored on
relevance - it can influence WHERE within a relevance tier a teacher
lands, never WHETHER they appear at all (that was already decided,
irrevocably, by EligibilityService).
"""

from dataclasses import dataclass

from apps.matching.services.subscription_priority_service import (
    SubscriptionPriorityService,
)
from apps.matching.services.token_priority_service import TokenPriorityService


@dataclass(frozen=True)
class RankedCandidate:
    teacher_profile: object
    relevance: object  # RelevanceScore
    subscription_rank: int
    token_balance: int
    rating: float
    experience_years: int
    verification_score: float = 0.0


class TeacherRankingService:

    @staticmethod
    def rank(candidates: list, *, plan_by_teacher_id: dict = None) -> list:
        """
        Args:
            candidates: list of dicts, each with "teacher_profile"
                and "relevance" (a RelevanceScore from
                MatchScoreService) - already filtered to eligible-
                only teachers by the caller (EligibilityService's
                verdict is final and is NOT re-checked here).

        Sort key (all business-priority fields are TIEBREAKS after
        relevance, per Section 32):
            1. relevance.overall (desc)      - PRIMARY
            2. subscription_rank (asc, lower=better)
            3. token_balance (desc)
            4. rating (desc)
            5. experience_years (desc)
            6. teacher_profile.created_at (asc) - final deterministic
               tiebreak, same reasoning as lead_engine.RankingService
        """
        # Resolve every candidate's effective plan in one query (falls back
        # to per-teacher only if the caller didn't precompute the map).
        if plan_by_teacher_id is None:
            from apps.subscriptions.services import SubscriptionService

            plan_by_teacher_id = SubscriptionService.get_effective_plans(
                {c["teacher_profile"].teacher_id for c in candidates}
            )

        from apps.trust.matching_support import (
            ranking_enabled,
            risk_penalty_map,
            verification_score_map,
        )

        vscore = (
            verification_score_map(c["teacher_profile"].teacher_id for c in candidates)
            if ranking_enabled()
            else {}
        )
        rpenalty = risk_penalty_map(c["teacher_profile"].teacher_id for c in candidates)

        enriched = []
        for candidate in candidates:
            profile = candidate["teacher_profile"]
            teacher = profile.teacher
            plan = plan_by_teacher_id.get(profile.teacher_id)
            sub_rank = (
                SubscriptionPriorityService.rank_for_plan_name(plan.name)
                if plan is not None
                else SubscriptionPriorityService.get_priority_rank(teacher)
            )
            enriched.append(
                RankedCandidate(
                    teacher_profile=profile,
                    relevance=candidate["relevance"],
                    subscription_rank=sub_rank,
                    token_balance=TokenPriorityService.get_token_balance(teacher),
                    rating=float(profile.rating),
                    experience_years=profile.years_of_experience or 0,
                    verification_score=float(vscore.get(profile.teacher_id, 0)),
                )
            )

        def sort_key(c: RankedCandidate):
            return (
                -c.relevance.overall,
                # risk penalty: 0 for everyone unless TRUST_ENABLE_RISK_AUTO_ACTIONS
                rpenalty.get(c.teacher_profile.teacher_id, 0),
                -c.verification_score,  # 0 for everyone when the flag is off -> no-op
                c.subscription_rank,
                -c.token_balance,
                -c.rating,
                -c.experience_years,
                c.teacher_profile.created_at,
            )

        return sorted(enriched, key=sort_key)

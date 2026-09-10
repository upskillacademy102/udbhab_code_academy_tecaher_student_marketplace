"""
Subscription priority service - business ranking factor, computed
entirely separately from relevance (see match_score_service.py's
module docstring for why these must stay separate).

subscription_priority_score is an ORDINAL rank derived from
settings.SUBSCRIPTION_PRIORITY_ORDER / MatchingConfig.
subscription_priority_order (an ordered list of plan names), NOT a
raw comparison of monthly_price - directly satisfies Section 16's
explicit warning: "Do NOT compare subscription price as a raw
monetary value if different plans have different billing periods."
"""

from apps.matching.services.config_service import get_config
from apps.subscriptions.services import SubscriptionService


class SubscriptionPriorityService:

    @staticmethod
    def rank_for_plan_name(plan_name: str, order: list = None) -> int:
        """
        Pure ordinal lookup: position of ``plan_name`` in the configured
        priority order (0 = highest tier). Unknown/misconfigured plans
        rank last rather than crashing or ranking first. Pass ``order``
        to avoid re-reading config in a loop.
        """
        if order is None:
            order = get_config().subscription_priority_order or ["Free"]
        try:
            return order.index(plan_name)
        except ValueError:
            return len(order)

    @staticmethod
    def get_priority_rank(teacher) -> int:
        """
        Returns an integer rank where LOWER is better (0 = highest
        priority tier), based on position in the configured
        subscription_priority_order list.
        """
        plan = SubscriptionService.get_effective_plan(teacher)
        return SubscriptionPriorityService.rank_for_plan_name(plan.name)

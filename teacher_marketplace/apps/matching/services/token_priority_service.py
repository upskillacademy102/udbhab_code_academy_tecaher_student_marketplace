"""
Token priority service - business ranking factor, computed
separately from relevance.

IMPORTANT (Section 16): "Do not let token balance completely
dominate relevance... Ranking happens ONLY after eligibility." This
service returns only a raw balance/derived rank for TIEBREAK
purposes within TeacherRankingService - it is never consulted by
EligibilityService and never blended into MatchScoreService's
relevance score.

DISABLED (2026-09-09): while settings.TOKEN_SYSTEM_ENABLED is False this
returns 0 for every teacher, collapsing the tiebreak to a no-op so that
TeacherRankingService falls through to rating and experience.

That is deliberate and load-bearing, not an optimisation. Under the
allowance model a teacher's purchased balance is bought unlocks, so
leaving this live would mean buying a top-up pack silently bought search
position too - pay-to-rank through the back door. Top-ups grant volume
only; priority comes from the subscription tier and nothing else.
"""

from django.conf import settings

from apps.wallet.services import WalletService


class TokenPriorityService:

    @staticmethod
    def get_token_balance(teacher) -> int:
        if not settings.TOKEN_SYSTEM_ENABLED:
            return 0
        return WalletService.get_balance(teacher)

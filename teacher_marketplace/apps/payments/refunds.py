"""
RefundEligibilityService (Phase 7e).

Token balances are fungible - we can't prove which wallet tokens came from
which payment - so eligibility is computed conservatively: a payment's
tokens are refundable only up to the wallet's currently-spendable balance.
If a refund / chargeback lands for tokens the teacher has already spent,
that gap is flagged as possible refund abuse.
"""

from __future__ import annotations

import logging

from apps.wallet.services import WalletService

logger = logging.getLogger("apps.payments.refunds")


class RefundEligibilityService:
    @staticmethod
    def assess(payment, requested_tokens: int) -> dict:
        """
        How many of `requested_tokens` (from this payment) the wallet can
        still cover, and how many look already-spent.
        """
        spendable = WalletService.available_balance(payment.teacher)
        refundable = max(0, min(int(requested_tokens), spendable))
        consumed = max(0, int(requested_tokens) - spendable)
        return {
            "requested_tokens": int(requested_tokens),
            "spendable_now": spendable,
            "refundable_tokens": refundable,
            "consumed_tokens": consumed,
            "fully_refundable": consumed == 0,
        }

    @staticmethod
    def flag_if_abusive(payment, requested_tokens: int) -> dict:
        """
        Record a payment-risk signal + review item when a refund / dispute
        covers tokens the teacher already consumed. Never raises.
        """
        assessment = RefundEligibilityService.assess(payment, requested_tokens)
        if assessment["consumed_tokens"] <= 0:
            return assessment
        try:
            from apps.trust.models import ManualReviewKind, RiskSignalKind
            from apps.trust.services.risk_service import RiskService
            from apps.trust.services.trust_service import TrustService

            RiskService.add_signal(
                payment.teacher.user,
                kind=RiskSignalKind.PAYMENT_RISK,
                weight=40,
                detail=(
                    f"Refund/dispute for {requested_tokens} tokens but "
                    f"{assessment['consumed_tokens']} were already spent"
                ),
                payload={"payment_id": str(payment.id), **assessment},
            )
            TrustService.open_review_item(
                kind=ManualReviewKind.PAYMENT_RISK,
                summary=(
                    f"Possible refund abuse: {payment.teacher.user.email} "
                    f"refunded {requested_tokens} tokens, {assessment['consumed_tokens']} already spent"
                ),
                subject_user=payment.teacher.user,
                payload={"payment_id": str(payment.id), **assessment},
                dedupe_key=f"refundabuse:{payment.id}",
                priority=1,
            )
            logger.warning(
                "refund abuse flag: payment=%s consumed=%d",
                payment.id,
                assessment["consumed_tokens"],
            )
        except Exception:  # noqa: BLE001
            logger.exception("flag_if_abusive failed for payment %s", payment.id)
        return assessment

"""
DisputeService (Phase 7d) - records chargebacks / disputes / refunds from
Razorpay webhooks and, when payment-risk checks are enabled, freezes the
tokens the disputed payment credited via a wallet.WalletHold.

Recording the dispute + opening a review item + notifying ops always
happens (never lose the event). Only the automatic wallet freeze is gated
behind ``TRUST_ENABLE_PAYMENT_RISK_CHECKS``.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.payments.models import DisputeKind, DisputeStatus, Payment, PaymentDispute
from apps.wallet.services import WalletService

logger = logging.getLogger("apps.payments.disputes")


def _freeze_enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_PAYMENT_RISK_CHECKS", False))


def _tokens_for_amount(payment: Payment, disputed_amount: Decimal) -> int:
    """How many of the payment's tokens the disputed amount corresponds to."""
    if payment.payment_type != "token_purchase" or not payment.token_count:
        return 0
    if not payment.amount or payment.amount <= 0:
        return 0
    if disputed_amount >= payment.amount:
        return payment.token_count
    ratio = disputed_amount / payment.amount
    return max(1, int((Decimal(payment.token_count) * ratio).to_integral_value()))


class DisputeService:
    @staticmethod
    @transaction.atomic
    def open(
        *,
        payment: Payment,
        kind: str,
        external_ref: str,
        amount: Decimal,
        reason_code: str = "",
        raw_event: dict | None = None,
    ) -> PaymentDispute:
        existing = PaymentDispute.objects.filter(external_ref=external_ref).first()
        if existing is not None:
            return existing

        dispute = PaymentDispute.objects.create(
            payment=payment,
            kind=kind,
            external_ref=external_ref,
            amount=amount,
            reason_code=reason_code[:120],
            raw_event=raw_event or {},
        )

        tokens = _tokens_for_amount(payment, amount)

        # Refund-abuse check (Phase 7e): flag when the disputed tokens were
        # already spent. Runs BEFORE the hold so the assessment sees the
        # pre-freeze spendable balance.
        if tokens:
            from apps.payments.refunds import RefundEligibilityService

            RefundEligibilityService.flag_if_abusive(payment, tokens)

        # Refund/dispute velocity (Phase 9b) - no-op unless anomaly alerts on.
        from apps.trust.services.anomaly_service import AnomalyService

        AnomalyService.note_refund(payment.teacher.user)

        # Learning Partner commission clawback (apps.commissions). A REFUND
        # never gets a separate "resolve" step in this codebase - the
        # refund.created/processed webhook calls open() directly and
        # nothing else ever touches it - so this is the one point in time
        # a refund's commission can be reversed. A CHARGEBACK is NOT
        # reversed here: it's still an open dispute, not yet a loss - see
        # resolve() below for that case.
        if kind == DisputeKind.REFUND:
            from apps.commissions.services import CommissionService

            CommissionService.reverse_for_payment(
                payment, reason=f"Refund {external_ref}"
            )

        if tokens and _freeze_enabled():
            try:
                hold = WalletService.place_hold(
                    payment.teacher,
                    amount=tokens,
                    reason=f"{kind} on payment {payment.razorpay_order_id}",
                    payment=payment,
                )
                dispute.wallet_hold = hold
                dispute.tokens_frozen = hold.amount
            except Exception:  # noqa: BLE001 - a hold failure must not lose the dispute
                logger.exception(
                    "Could not place wallet hold for dispute %s", external_ref
                )

        # Risk signal + review item + ops notification (always).
        try:
            from apps.trust.models import ManualReviewKind, RiskSignalKind
            from apps.trust.services.risk_service import RiskService
            from apps.trust.services.trust_service import TrustService

            RiskService.add_signal(
                payment.teacher.user,
                kind=RiskSignalKind.PAYMENT_RISK,
                weight=50 if kind == DisputeKind.CHARGEBACK else 25,
                detail=f"{kind} raised on a payment ({amount})",
                payload={"payment_id": str(payment.id), "external_ref": external_ref},
            )
            item = TrustService.open_review_item(
                kind=ManualReviewKind.PAYMENT_DISPUTE,
                summary=f"{kind} on {payment.teacher.user.email}'s payment {payment.razorpay_order_id}",
                subject_user=payment.teacher.user,
                payload={
                    "payment_id": str(payment.id),
                    "external_ref": external_ref,
                    "amount": str(amount),
                    "tokens_frozen": dispute.tokens_frozen,
                },
                dedupe_key=f"dispute:{external_ref}",
                priority=1,
            )
            dispute.review_item = item
        except Exception:  # noqa: BLE001
            logger.exception("dispute signalling failed for %s", external_ref)

        dispute.save(
            update_fields=["wallet_hold", "tokens_frozen", "review_item", "updated_at"]
        )
        DisputeService._notify_ops(dispute)
        logger.warning(
            "Payment %s: %s recorded (ref=%s, tokens_frozen=%d)",
            payment.razorpay_order_id,
            kind,
            external_ref,
            dispute.tokens_frozen,
        )
        return dispute

    @staticmethod
    @transaction.atomic
    def resolve(
        dispute: PaymentDispute, *, won: bool, note: str = ""
    ) -> PaymentDispute:
        dispute = PaymentDispute.objects.select_for_update().get(pk=dispute.pk)
        if dispute.status in (
            DisputeStatus.WON,
            DisputeStatus.LOST,
            DisputeStatus.CANCELLED,
        ):
            return dispute

        dispute.status = DisputeStatus.WON if won else DisputeStatus.LOST
        dispute.resolved_at = timezone.now()
        dispute.save(update_fields=["status", "resolved_at", "updated_at"])

        if dispute.wallet_hold_id:
            if won:
                WalletService.release_hold(
                    dispute.wallet_hold,
                    resolution=note or "Dispute resolved in our favour.",
                )
            else:
                WalletService.settle_hold_as_debit(
                    dispute.wallet_hold,
                    description=f"Chargeback upheld - {dispute.external_ref}",
                    reference_id=str(dispute.payment_id),
                )

        if not won:
            # Chargeback lost - the money is now actually gone, so (unlike
            # open()'s CHARGEBACK branch, which deliberately does nothing)
            # this is where a Learning Partner's commission on it gets
            # clawed back.
            from apps.commissions.services import CommissionService

            CommissionService.reverse_for_payment(
                dispute.payment, reason=f"Chargeback lost {dispute.external_ref}"
            )

        if dispute.review_item_id:
            try:
                from apps.trust.services.trust_service import TrustService

                TrustService.resolve_review_item(
                    dispute.review_item,
                    resolution=f"Dispute {dispute.status}. {note}".strip(),
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "could not resolve review item for dispute %s", dispute.id
                )

        return dispute

    # ---- webhook entry points ---------------------------------------

    @staticmethod
    def handle_webhook(event_type: str, payload: dict):
        body = payload.get("payload", {})

        if event_type.startswith("payment.dispute."):
            entity = body.get("dispute", {}).get("entity", {})
            payment = DisputeService._payment_for(entity.get("payment_id"))
            if payment is None:
                logger.warning("dispute webhook for unknown payment: %s", entity)
                return None
            amount = _paise_to_rupees(entity.get("amount"))
            if event_type == "payment.dispute.created":
                return DisputeService.open(
                    payment=payment,
                    kind=DisputeKind.CHARGEBACK,
                    external_ref=entity.get("id") or f"dispute:{payment.id}",
                    amount=amount or payment.amount,
                    reason_code=entity.get("reason_code", "")
                    or entity.get("reason", ""),
                    raw_event=payload,
                )
            if event_type in ("payment.dispute.won", "payment.dispute.closed"):
                d = PaymentDispute.objects.filter(external_ref=entity.get("id")).first()
                return DisputeService.resolve(d, won=True) if d else None
            if event_type == "payment.dispute.lost":
                d = PaymentDispute.objects.filter(external_ref=entity.get("id")).first()
                return DisputeService.resolve(d, won=False) if d else None
            return None

        if event_type in ("refund.created", "refund.processed"):
            entity = body.get("refund", {}).get("entity", {})
            payment = DisputeService._payment_for(entity.get("payment_id"))
            if payment is None:
                logger.warning("refund webhook for unknown payment: %s", entity)
                return None
            return DisputeService.open(
                payment=payment,
                kind=DisputeKind.REFUND,
                external_ref=entity.get("id") or f"refund:{payment.id}",
                amount=_paise_to_rupees(entity.get("amount")) or payment.amount,
                reason_code=(
                    entity.get("notes", {}).get("reason", "")
                    if isinstance(entity.get("notes"), dict)
                    else ""
                ),
                raw_event=payload,
            )
        return None

    @staticmethod
    def _payment_for(payment_id_or_order):
        if not payment_id_or_order:
            return None
        return (
            Payment.objects.select_related("teacher", "teacher__user")
            .filter(razorpay_payment_id=payment_id_or_order)
            .first()
            or Payment.objects.select_related("teacher", "teacher__user")
            .filter(razorpay_order_id=payment_id_or_order)
            .first()
        )

    @staticmethod
    def _notify_ops(dispute: PaymentDispute) -> None:
        """
        Ops visibility = a priority-1 ManualReviewItem (opened above) plus a
        SECURITY audit row. There is no separate ops mailing list in this
        codebase; the review queue is where disputes are worked.
        """
        try:
            from apps.ops.models import AuditCategory, AuditStatus
            from apps.ops.services import AuditService

            AuditService.record(
                action=f"payment_{dispute.kind}",
                category=AuditCategory.SECURITY,
                status=AuditStatus.PENDING,
                actor=dispute.payment.teacher.user,
                target=dispute.payment,
                message=f"{dispute.kind} recorded; {dispute.tokens_frozen} tokens frozen.",
                external_ref=dispute.external_ref,
                amount=str(dispute.amount),
            )
        except Exception:  # noqa: BLE001
            logger.exception("ops audit failed for dispute %s", dispute.id)


def _paise_to_rupees(paise):
    try:
        return (Decimal(int(paise)) / Decimal("100")).quantize(Decimal("0.01"))
    except (TypeError, ValueError):
        return None

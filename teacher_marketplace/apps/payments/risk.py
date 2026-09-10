"""
PaymentRiskService (Phase 7c) - lightweight, flag-gated payment-fraud
signals derived from Razorpay webhook data.

Every method is a no-op unless ``TRUST_ENABLE_PAYMENT_RISK_CHECKS`` is on.
Nothing here blocks a payment; it only records ``RiskSignal`` rows (and, for
the strongest signal, a ``ManualReviewItem``). Auto-enforcement of the
resulting ``risk_state`` is Phase 9 (``TRUST_ENABLE_RISK_AUTO_ACTIONS``).
"""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db.models import Max

from apps.payments.models import (
    Payment,
    PaymentInstrumentKind,
    PaymentInstrumentSignature,
    PaymentStatus,
)

logger = logging.getLogger("apps.payments.risk")

_FAILED_BURST_TTL = 3600  # rolling one-hour window for failed-attempt counting


def _enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_PAYMENT_RISK_CHECKS", False))


def _hash(value: str) -> str:
    return hashlib.sha256(f"{value}:{settings.SECRET_KEY}".encode()).hexdigest()


def _instrument_fingerprint(entity: dict):
    """
    (kind, raw_fingerprint) for a Razorpay payment entity, or None when the
    payload doesn't carry anything stable enough to fingerprint.
    """
    if not isinstance(entity, dict):
        return None

    method = (entity.get("method") or "").lower()

    vpa = entity.get("vpa") or (entity.get("upi") or {}).get("vpa")
    if vpa:
        return PaymentInstrumentKind.UPI, str(vpa).strip().lower()

    card = entity.get("card") or {}
    # Razorpay's `card.id`/`token_id` is the stable per-card token; fall back
    # to a coarse last4+network+issuer fingerprint.
    card_token = entity.get("token_id") or card.get("id")
    if method == "card" or card:
        if card_token:
            return PaymentInstrumentKind.CARD, f"tok:{card_token}"
        last4 = card.get("last4")
        if last4:
            coarse = f"{last4}|{card.get('network', '')}|{card.get('issuer', '')}"
            return PaymentInstrumentKind.CARD, coarse

    wallet = entity.get("wallet")
    if wallet:
        return PaymentInstrumentKind.WALLET, str(wallet).strip().lower()

    bank = entity.get("bank")
    if method == "netbanking" and bank:
        return PaymentInstrumentKind.NETBANKING, str(bank).strip().lower()

    return None


class PaymentRiskService:
    @staticmethod
    def evaluate_captured(payment: Payment, entity: dict) -> None:
        """Run every capture-time check. Never raises."""
        if not _enabled():
            return
        try:
            PaymentRiskService._check_instrument_reuse(payment, entity)
            PaymentRiskService._check_amount_spike(payment)
        except Exception:  # noqa: BLE001 - risk scoring must not break the webhook
            logger.exception(
                "payment risk evaluation failed for payment %s", payment.id
            )

    @staticmethod
    def note_failed_payment(teacher, entity: dict | None = None) -> None:
        if not _enabled():
            return
        try:
            key = f"payrisk:failburst:{teacher.id}"
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, _FAILED_BURST_TTL)
                count = 1
            if count == settings.TRUST_PAYMENT_FAILED_BURST:
                from apps.trust.models import RiskSignalKind
                from apps.trust.services.risk_service import RiskService

                RiskService.add_signal(
                    teacher.user,
                    kind=RiskSignalKind.PAYMENT_RISK,
                    weight=20,
                    detail=f"{count} failed payment attempts within an hour",
                    payload={"failed_attempts": count},
                )
        except Exception:  # noqa: BLE001
            logger.exception("note_failed_payment failed for teacher %s", teacher.id)

    # ---- individual checks --------------------------------------------

    @staticmethod
    def _check_instrument_reuse(payment: Payment, entity: dict) -> None:
        fp = _instrument_fingerprint(entity)
        if fp is None:
            return
        kind, raw = fp
        value_hash = _hash(raw)

        PaymentInstrumentSignature.objects.get_or_create(
            teacher=payment.teacher, kind=kind, value_hash=value_hash
        )

        teacher_ids = (
            PaymentInstrumentSignature.objects.filter(kind=kind, value_hash=value_hash)
            .values_list("teacher_id", flat=True)
            .distinct()
        )
        n = len(set(teacher_ids))
        if n < settings.TRUST_PAYMENT_INSTRUMENT_MAX_ACCOUNTS:
            return

        from apps.trust.models import ManualReviewKind, RiskSignalKind
        from apps.trust.services.risk_service import RiskService
        from apps.trust.services.trust_service import TrustService

        RiskService.add_signal(
            payment.teacher.user,
            kind=RiskSignalKind.PAYMENT_RISK,
            weight=35,
            detail=f"Payment instrument shared across {n} accounts",
            payload={"kind": kind, "account_count": n},
        )
        TrustService.open_review_item(
            kind=ManualReviewKind.PAYMENT_RISK,
            summary=f"{payment.teacher.user.email}: {kind} instrument used by {n} accounts",
            subject_user=payment.teacher.user,
            payload={"kind": kind, "account_count": n, "value_hash": value_hash},
            dedupe_key=f"payinstr:{kind}:{value_hash}",
            priority=2,
        )
        logger.warning(
            "payment instrument reuse: %s hash=%s across %d accounts",
            kind,
            value_hash[:12],
            n,
        )

    @staticmethod
    def _check_amount_spike(payment: Payment) -> None:
        prior_max = (
            Payment.objects.filter(
                teacher=payment.teacher, status=PaymentStatus.SUCCESS
            )
            .exclude(pk=payment.pk)
            .aggregate(m=Max("amount"))["m"]
        )
        if not prior_max or prior_max <= 0:
            return
        multiplier = Decimal(settings.TRUST_PAYMENT_SPIKE_MULTIPLIER)
        if payment.amount <= prior_max * multiplier:
            return

        from apps.trust.models import RiskSignalKind
        from apps.trust.services.risk_service import RiskService

        RiskService.add_signal(
            payment.teacher.user,
            kind=RiskSignalKind.PAYMENT_RISK,
            weight=15,
            detail=(
                f"Purchase {payment.amount} is >{multiplier}x the prior max {prior_max}"
            ),
            payload={"amount": str(payment.amount), "prior_max": str(prior_max)},
        )

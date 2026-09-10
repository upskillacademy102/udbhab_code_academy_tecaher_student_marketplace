"""
NewAccountCooldownService (Phase 7g).

For the first ``TRUST_NEW_ACCOUNT_COOLDOWN_HOURS`` after signup a teacher is
treated as higher-risk:
  * a single purchase is capped at ``TRUST_NEW_ACCOUNT_MAX_PURCHASE`` rupees, and
  * tokens bought in that window are frozen (WalletHold) and released
    automatically once the cooldown elapses (``release_due_cooldown_holds``).

All of this is a no-op unless ``TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN`` is on.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Q as models_Q
from django.utils import timezone

from apps.payments.exceptions import PaymentHeldForReview

logger = logging.getLogger("apps.payments.cooldown")

_HOLD_REASON = "new-account cooldown"


def _enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN", False))


def _cooldown_delta() -> timedelta:
    return timedelta(
        hours=int(getattr(settings, "TRUST_NEW_ACCOUNT_COOLDOWN_HOURS", 24))
    )


class NewAccountCooldownService:
    @staticmethod
    def account_age_start(teacher):
        user = teacher.user
        return getattr(user, "created_at", None) or getattr(teacher, "created_at", None)

    @staticmethod
    def in_cooldown(teacher) -> bool:
        if not _enabled():
            return False
        started = NewAccountCooldownService.account_age_start(teacher)
        if started is None:
            return False
        return timezone.now() - started < _cooldown_delta()

    @staticmethod
    def guard_order_amount(teacher, amount) -> None:
        """Raise if a brand-new account is trying to buy more than the cap."""
        if not NewAccountCooldownService.in_cooldown(teacher):
            return
        cap = int(getattr(settings, "TRUST_NEW_ACCOUNT_MAX_PURCHASE", 2000))
        if amount is not None and amount > cap:
            logger.info(
                "new-account cooldown: capped purchase %s > %s for teacher %s",
                amount,
                cap,
                teacher.id,
            )
            raise PaymentHeldForReview(
                detail=(
                    f"New accounts can spend up to {cap} per purchase for the "
                    f"first {int(getattr(settings, 'TRUST_NEW_ACCOUNT_COOLDOWN_HOURS', 24))} "
                    f"hours. Please try a smaller amount or wait."
                )
            )

    @staticmethod
    def maybe_hold_new_tokens(payment) -> None:
        """Freeze tokens bought during the cooldown window. Never raises."""
        try:
            if not NewAccountCooldownService.in_cooldown(payment.teacher):
                return
            if not payment.token_count:
                return
            from apps.wallet.services import WalletService

            WalletService.place_hold(
                payment.teacher,
                amount=payment.token_count,
                reason=f"{_HOLD_REASON} ({payment.razorpay_order_id})",
                payment=payment,
            )
            logger.info(
                "new-account cooldown: held %d tokens for teacher %s",
                payment.token_count,
                payment.teacher.id,
            )
        except Exception:  # noqa: BLE001 - a hold failure must not fail the payment
            logger.exception("maybe_hold_new_tokens failed for payment %s", payment.id)

    @staticmethod
    def release_due_holds() -> int:
        """
        Release cooldown holds once the *account* is older than the cooldown
        window - not once the hold itself is that old, so a purchase made
        late in the window isn't frozen for a full extra window. Idempotent.
        """
        from apps.wallet.models import WalletHold
        from apps.wallet.services import WalletService

        cutoff = timezone.now() - _cooldown_delta()
        due = WalletHold.objects.filter(
            active=True, reason__startswith=_HOLD_REASON
        ).filter(
            models_Q(wallet__teacher__user__created_at__lte=cutoff)
            | models_Q(created_at__lte=cutoff)  # fallback for missing account age
        )
        released = 0
        for hold in due.select_related("wallet"):
            WalletService.release_hold(hold, resolution="New-account cooldown elapsed.")
            released += 1
        if released:
            logger.info("released %d cooldown hold(s)", released)
        return released

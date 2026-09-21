"""
SanctionService - apply and lift account bans / suspensions.

A sanction (ban or suspend) deactivates the account: ``User.is_active`` is
set False and every active ``UserSession`` is killed, so the user is
signed out everywhere and cannot sign back in. Neither kind lifts on its
own - a Super Admin reactivating the account is the only way out
(``lift``). ``source`` records whether a human applied it or the
fake-lead auto-ban did.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import UserRole, UserSession
from apps.core.exceptions.custom_exceptions import ValidationException
from apps.trust.models import (
    AccountSanction,
    AccountSanctionKind,
    AccountSanctionSource,
)

logger = logging.getLogger("apps.trust.sanction")

# Roles a sanction may never touch, however it is triggered. Super Admin is
# the only permanently protected role - there is always at least one, and
# it must never be able to lock itself/each other out. Admin is deliberately
# NOT protected: a Super Admin must be able to ban/unban an Admin account
# (manually, or via the staff-login brute-force auto-ban), same as any
# Student or Teacher account.
_PROTECTED_ROLES = (UserRole.SUPERADMIN,)


class SanctionService:
    @staticmethod
    def active_for(user) -> AccountSanction | None:
        return AccountSanction.objects.filter(user=user, active=True).first()

    @staticmethod
    @transaction.atomic
    def apply(
        user,
        *,
        kind: str = AccountSanctionKind.BAN,
        reason: str = "",
        source: str = AccountSanctionSource.MANUAL,
        by=None,
        review_item=None,
        payload: dict | None = None,
        audit_request=None,
    ) -> AccountSanction:
        """
        Ban or suspend ``user``. Idempotent: if an active sanction already
        exists it is returned unchanged (the account is already
        deactivated), so a second automatic trigger or a double click does
        nothing.
        """
        if user.role in _PROTECTED_ROLES:
            raise ValidationException(
                detail="Super Admin accounts cannot be sanctioned here."
            )

        existing = SanctionService.active_for(user)
        if existing is not None:
            return existing

        try:
            with transaction.atomic():
                sanction = AccountSanction.objects.create(
                    user=user,
                    kind=kind,
                    source=source,
                    reason=reason[:4000],
                    created_by=by,
                    review_item=review_item,
                    payload=payload or {},
                )
        except IntegrityError:
            # A concurrent trigger created the active sanction between the
            # check above and here (partial unique constraint). The account
            # is already deactivated - return that row, do nothing else.
            return SanctionService.active_for(user)

        if user.is_active:
            user.is_active = False
            user.save(update_fields=["is_active", "updated_at"])
        UserSession.objects.filter(user=user, is_active=True).update(is_active=False)

        SanctionService._audit(
            request=audit_request,
            actor=by,
            action="account.sanctioned",
            target=user,
            message=(
                f"{kind} applied to {user.email}"
                + (" (automatic)" if source != AccountSanctionSource.MANUAL else "")
            ),
            sanction_id=str(sanction.id),
            source=source,
        )
        logger.info(
            "account sanction: %s %s (source=%s, by=%s)",
            kind,
            user.email,
            source,
            getattr(by, "email", "system"),
        )
        return sanction

    @staticmethod
    @transaction.atomic
    def lift(sanction: AccountSanction, *, by=None, reason: str = "", audit_request=None):
        """Reactivate the account and mark the sanction lifted."""
        sanction = AccountSanction.objects.select_for_update().get(pk=sanction.pk)
        if not sanction.active:
            return sanction

        sanction.active = False
        sanction.lifted_at = timezone.now()
        sanction.lifted_by = by
        sanction.lift_reason = reason[:4000]
        sanction.save(
            update_fields=[
                "active",
                "lifted_at",
                "lifted_by",
                "lift_reason",
                "updated_at",
            ]
        )

        user = sanction.user
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active", "updated_at"])

        SanctionService._audit(
            request=audit_request,
            actor=by,
            action="account.sanction_lifted",
            target=user,
            message=f"{sanction.kind} on {user.email} lifted",
            sanction_id=str(sanction.id),
        )
        logger.info(
            "account sanction lifted: %s (by=%s)",
            user.email,
            getattr(by, "email", "system"),
        )
        return sanction

    @staticmethod
    def _audit(*, request, actor, action, target, message, **metadata):
        try:
            from apps.ops.models import AuditCategory
            from apps.ops.services import AuditService

            AuditService.record(
                request=request,
                actor=actor,
                category=AuditCategory.USER,
                action=action,
                target=target,
                message=message,
                **metadata,
            )
        except Exception:  # noqa: BLE001 - auditing must never break a sanction
            logger.exception("sanction audit failed for %s", action)

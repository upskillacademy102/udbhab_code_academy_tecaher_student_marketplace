"""
AppealService - the in-app suspension-appeal flow (plan Section 5
residual risk: "suspended users have no in-app appeal flow").

A user whose ``TrustProfile.risk_state`` is ``suspended`` (which only
happens when ``TRUST_ENABLE_RISK_AUTO_ACTIONS`` is on) may file one appeal
explaining their side. Filing it opens a ``SUSPENSION_APPEAL`` review
item; when ops **resolves** that item the appeal is GRANTED - the user's
active ``RiskSignal`` rows are deactivated and the risk score recomputed,
which lifts the suspension - and when ops **dismisses** it the appeal is
DENIED.

The in-app form is gated by ``TRUST_ENABLE_SUSPENSION_APPEALS`` (default
off). With that flag off the ``/suspended/`` page still renders but offers
only a support email address; nothing here does anything.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.core.exceptions.custom_exceptions import (
    ConflictException,
    ValidationException,
)
from apps.trust.models import (
    ManualReviewKind,
    RiskSignal,
    SuspensionAppeal,
    SuspensionAppealStatus,
)

logger = logging.getLogger("apps.trust")

_MIN_MESSAGE = 20
_MAX_MESSAGE = 4000

_STATUS_LABEL = {
    SuspensionAppealStatus.PENDING: "received - pending review",
    SuspensionAppealStatus.IN_REVIEW: "under review",
    SuspensionAppealStatus.GRANTED: "approved",
    SuspensionAppealStatus.DENIED: "declined",
    SuspensionAppealStatus.WITHDRAWN: "withdrawn",
}


def enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_SUSPENSION_APPEALS", False))


def _support_email() -> str:
    return getattr(settings, "SUPPORT_EMAIL", "") or getattr(
        settings, "DEFAULT_FROM_EMAIL", ""
    )


def _client_ip(request):
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AppealService:
    # ---- state -----------------------------------------------------

    @staticmethod
    def is_suspended(user) -> bool:
        from apps.trust.services.risk_service import RiskService

        return bool(RiskService.is_suspended(user))

    @staticmethod
    def current_appeal(user):
        """The user's open (pending / in-review) appeal, or None."""
        return (
            SuspensionAppeal.objects.filter(
                user=user, status__in=SuspensionAppeal.OPEN_STATES
            )
            .order_by("-created_at")
            .first()
        )

    @staticmethod
    def latest_appeal(user):
        return (
            SuspensionAppeal.objects.filter(user=user).order_by("-created_at").first()
        )

    @staticmethod
    def status_for(user) -> dict:
        suspended = AppealService.is_suspended(user)
        appeal = AppealService.latest_appeal(user)
        return {
            "suspended": suspended,
            "appeals_enabled": enabled(),
            "can_appeal": bool(
                suspended and enabled() and AppealService.current_appeal(user) is None
            ),
            "support_email": _support_email(),
            "appeal": AppealService._serialize(appeal) if appeal else None,
        }

    @staticmethod
    def _serialize(appeal: SuspensionAppeal) -> dict:
        return {
            "id": str(appeal.id),
            "status": appeal.status,
            "status_label": _STATUS_LABEL.get(appeal.status, appeal.status),
            "message": appeal.message,
            "contact_email": appeal.contact_email,
            "decision_note": appeal.decision_note,
            "is_open": appeal.is_open,
            "submitted_at": appeal.created_at,
            "decided_at": appeal.decided_at,
        }

    # ---- actions ---------------------------------------------------

    @staticmethod
    def submit(user, *, message: str, contact_email: str = "", request=None):
        if not enabled():
            raise ValidationException(
                detail=(
                    "Online appeals aren't available right now - "
                    f"please email {_support_email()}."
                )
            )
        if not AppealService.is_suspended(user):
            raise ValidationException(detail="Your account isn't suspended.")
        if AppealService.current_appeal(user) is not None:
            raise ConflictException(
                detail="You already have an appeal awaiting review."
            )

        message = (message or "").strip()
        if len(message) < _MIN_MESSAGE:
            raise ValidationException(
                detail=(
                    "Please add a few sentences explaining your situation "
                    f"(at least {_MIN_MESSAGE} characters)."
                )
            )

        from apps.trust.services.trust_service import TrustService

        profile = TrustService.get_or_create_profile(user)
        appeal = SuspensionAppeal.objects.create(
            user=user,
            message=message[:_MAX_MESSAGE],
            contact_email=(contact_email or getattr(user, "email", "") or "").strip()[
                :254
            ],
            risk_score_at_submit=profile.risk_score,
            risk_state_at_submit=profile.risk_state,
            requested_ip=_client_ip(request),
        )

        item = TrustService.open_review_item(
            kind=ManualReviewKind.SUSPENSION_APPEAL,
            summary=f"Suspension appeal from {user.email}",
            subject_user=user,
            payload={
                "appeal_id": str(appeal.id),
                "risk_score": profile.risk_score,
                "risk_state": profile.risk_state,
            },
            dedupe_key=f"appeal:{user.id}",
            priority=2,
        )
        appeal.review_item = item
        appeal.save(update_fields=["review_item", "updated_at"])

        AppealService._audit(user, "suspension_appeal_submitted", request, appeal)
        AppealService._notify_ops(appeal)
        AppealService._email_user(
            user,
            "We've received your appeal",
            "Our team will review your account and email you when there's an "
            "update. You don't need to do anything else for now.",
        )
        logger.info("suspension appeal filed by %s", user.email)
        return appeal

    @staticmethod
    def withdraw(user, *, request=None):
        appeal = AppealService.current_appeal(user)
        if appeal is None:
            return None
        appeal.status = SuspensionAppealStatus.WITHDRAWN
        appeal.decided_at = timezone.now()
        appeal.save(update_fields=["status", "decided_at", "updated_at"])
        # Close the queue item. on_review_resolved() no-ops because the
        # appeal is no longer open.
        if appeal.review_item_id and appeal.review_item.is_open:
            from apps.trust.services.trust_service import TrustService

            TrustService.resolve_review_item(
                appeal.review_item,
                by=user,
                resolution="Withdrawn by the account holder.",
                dismiss=True,
            )
        AppealService._audit(user, "suspension_appeal_withdrawn", request, appeal)
        return appeal

    @staticmethod
    def on_review_resolved(
        item, *, by=None, resolution: str = "", dismissed: bool = False
    ) -> None:
        """
        Hook called from ``TrustService.resolve_review_item`` for
        ``SUSPENSION_APPEAL`` items. Resolve -> grant (lift the
        suspension); dismiss -> deny.
        """
        try:
            appeal = (
                SuspensionAppeal.objects.filter(review_item=item)
                .order_by("-created_at")
                .first()
            )
            if appeal is None or not appeal.is_open:
                return

            appeal.decided_by = by if getattr(by, "pk", None) else None
            appeal.decided_at = timezone.now()
            appeal.decision_note = (resolution or "").strip()[:_MAX_MESSAGE]

            if dismissed:
                appeal.status = SuspensionAppealStatus.DENIED
                appeal.save(
                    update_fields=[
                        "status",
                        "decided_by",
                        "decided_at",
                        "decision_note",
                        "updated_at",
                    ]
                )
                note = (
                    f" Note from our team: {appeal.decision_note}"
                    if appeal.decision_note
                    else ""
                )
                AppealService._email_user(
                    appeal.user,
                    "We've reviewed your appeal",
                    "After reviewing your account, the restriction stays in "
                    "place for now." + note,
                )
                return

            appeal.status = SuspensionAppealStatus.GRANTED
            appeal.save(
                update_fields=[
                    "status",
                    "decided_by",
                    "decided_at",
                    "decision_note",
                    "updated_at",
                ]
            )
            AppealService._lift_suspension(appeal.user)
            AppealService._email_user(
                appeal.user,
                "Your account access has been restored",
                "Good news - we've reviewed your appeal and lifted the "
                "restriction on your account. You can sign in and continue as "
                "normal.",
            )
            logger.info("suspension appeal granted for %s", appeal.user.email)
        except Exception:  # noqa: BLE001 - appeal bookkeeping must not break resolve
            logger.exception(
                "suspension appeal on_review_resolved failed for item %s",
                getattr(item, "id", "?"),
            )

    # ---- helpers --------------------------------------------------

    @staticmethod
    def _lift_suspension(user) -> None:
        from apps.trust.services.risk_service import RiskService

        RiskSignal.objects.filter(user=user, active=True).update(active=False)
        RiskService.recompute(user)

    @staticmethod
    def _email_user(user, subject: str, body: str) -> None:
        to = getattr(user, "email", "") or ""
        if not to:
            return
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to],
                fail_silently=True,
            )
        except Exception:  # noqa: BLE001 - notification must not break the flow
            logger.exception(
                "appeal user email failed for %s", getattr(user, "id", "?")
            )

    @staticmethod
    def _notify_ops(appeal: SuspensionAppeal) -> None:
        to = getattr(settings, "TRUST_APPEALS_NOTIFY_EMAIL", "") or ""
        if not to:
            return
        try:
            send_mail(
                subject=f"[Appeals] Suspension appeal from {appeal.user.email}",
                message=(
                    f"User:    {appeal.user.email}\n"
                    f"Risk:    {appeal.risk_state_at_submit} "
                    f"({appeal.risk_score_at_submit})\n"
                    f"Contact: {appeal.contact_email}\n\n"
                    f"{appeal.message}\n\n"
                    "Work it in the review queue (kind: suspension_appeal)."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to],
                fail_silently=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("appeal ops email failed")

    @staticmethod
    def _audit(user, action: str, request, appeal: SuspensionAppeal) -> None:
        try:
            from apps.ops.models import AuditCategory
            from apps.ops.services import AuditService

            AuditService.record(
                action=action,
                category=AuditCategory.SECURITY,
                request=request,
                actor=user,
                target=appeal,
                message=f"Suspension appeal ({appeal.status})",
            )
        except Exception:  # noqa: BLE001
            logger.exception("appeal audit failed")

"""
SensitiveChangeService - the step-up flow for changing email / mobile /
password.

Every change is a two-step: initiate (validates + sends a one-time code)
then confirm (checks the code). What confirm does next depends on the
field and the ``TRUST_ENABLE_STEP_UP_REVERIFICATION`` flag:

    password                    -> applied immediately on confirm
                                   (the owner needs their new password now)
    email / mobile, flag OFF    -> applied immediately on confirm
    email / mobile, flag ON     -> SCHEDULED: a cooldown runs during which
                                   the owner can cancel; a Celery-beat task
                                   applies it once the cooldown elapses.

The code for an email/mobile change goes to the NEW contact (proving the
owner controls it). The code for a password change goes to a CURRENT
verified contact. Either way the CURRENT contact is notified that a
change was requested.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.exceptions.custom_exceptions import (
    ConflictException,
    ValidationException,
)
from apps.trust.models import (
    OTPChannel,
    OTPPurpose,
    SensitiveChangeField,
    SensitiveChangeRequest,
    SensitiveChangeState,
)
from apps.trust.services.otp_service import OTPService
from apps.trust.services.trust_service import TrustService

logger = logging.getLogger("apps.trust.sensitive_change")


def _site() -> str:
    return getattr(settings, "SITE_NAME", "the platform")


def _mask(value: str) -> str:
    if "@" in value:
        name, _, domain = value.partition("@")
        return f"{name[:1]}{'*' * max(len(name) - 1, 1)}@{domain}"
    return (
        f"{value[:2]}{'*' * max(len(value) - 4, 1)}{value[-2:]}"
        if len(value) > 4
        else "***"
    )


def _security_email(to: str, subject: str, body: str) -> None:
    if not to:
        return
    try:
        send_mail(
            subject=f"{_site()}: {subject}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 - never let a security email break the flow
        logger.error("Security email to %s failed: %s", to, exc, exc_info=True)


def _client_ip(request):
    return (
        getattr(request, "META", {}).get("REMOTE_ADDR") if request is not None else None
    )


def _audit(action, *, user, request, message, status=None):
    from apps.ops.models import AuditCategory, AuditStatus
    from apps.ops.services import AuditService

    AuditService.record(
        action=action,
        category=AuditCategory.SECURITY,
        request=request,
        actor=user,
        target=user,
        status=status or AuditStatus.SUCCESS,
        message=message,
    )


class SensitiveChangeService:
    @staticmethod
    def step_up_enabled() -> bool:
        return bool(getattr(settings, "TRUST_ENABLE_STEP_UP_REVERIFICATION", False))

    @staticmethod
    def _current_channel(user) -> str:
        if user.is_email_verified:
            return OTPChannel.EMAIL
        if user.is_mobile_verified:
            return OTPChannel.SMS
        return OTPChannel.EMAIL if user.email else OTPChannel.SMS

    @staticmethod
    def _cancel_active(user, field) -> None:
        SensitiveChangeRequest.objects.filter(
            user=user, field=field, state__in=SensitiveChangeRequest.ACTIVE_STATES
        ).update(state=SensitiveChangeState.CANCELLED, cancelled_at=timezone.now())

    # ----- initiate -------------------------------------------------------
    @staticmethod
    @transaction.atomic
    def initiate_email_change(
        user, *, new_email: str, request=None
    ) -> SensitiveChangeRequest:
        new_email = User.objects.normalize_email(new_email)
        if new_email.lower() == (user.email or "").lower():
            raise ValidationException(detail="That is already your email address.")
        if User.all_objects.filter(email__iexact=new_email).exists():
            raise ConflictException(detail="A user with this email already exists.")

        SensitiveChangeService._cancel_active(user, SensitiveChangeField.EMAIL)
        challenge = OTPService.issue(
            user,
            channel=OTPChannel.EMAIL,
            purpose=OTPPurpose.SENSITIVE_CHANGE,
            destination=new_email,
        )
        scr = SensitiveChangeRequest.objects.create(
            user=user,
            field=SensitiveChangeField.EMAIL,
            new_value=new_email,
            challenge=challenge,
            requested_ip=_client_ip(request),
        )
        _security_email(
            user.email,
            "email-change requested",
            f"A request to change your {_site()} email to {_mask(new_email)} was just made. "
            f"If this wasn't you, sign in and change your password immediately.",
        )
        _audit(
            "sensitive_change.email.initiated",
            user=user,
            request=request,
            message=f"Email change to {_mask(new_email)} requested",
        )
        return scr

    @staticmethod
    @transaction.atomic
    def initiate_mobile_change(
        user, *, new_mobile: str, request=None
    ) -> SensitiveChangeRequest:
        new_mobile = str(new_mobile).strip()
        if new_mobile == (user.mobile or ""):
            raise ValidationException(detail="That is already your mobile number.")
        if User.all_objects.filter(mobile=new_mobile).exists():
            raise ConflictException(
                detail="A user with this mobile number already exists."
            )

        SensitiveChangeService._cancel_active(user, SensitiveChangeField.MOBILE)
        challenge = OTPService.issue(
            user,
            channel=OTPChannel.SMS,
            purpose=OTPPurpose.SENSITIVE_CHANGE,
            destination=new_mobile,
        )
        scr = SensitiveChangeRequest.objects.create(
            user=user,
            field=SensitiveChangeField.MOBILE,
            new_value=new_mobile,
            challenge=challenge,
            requested_ip=_client_ip(request),
        )
        _security_email(
            user.email,
            "mobile-number change requested",
            f"A request to change your {_site()} mobile number to {_mask(new_mobile)} was just made. "
            f"If this wasn't you, sign in and change your password immediately.",
        )
        _audit(
            "sensitive_change.mobile.initiated",
            user=user,
            request=request,
            message=f"Mobile change to {_mask(new_mobile)} requested",
        )
        return scr

    @staticmethod
    @transaction.atomic
    def initiate_password_change(
        user, *, new_password_hash: str, request=None
    ) -> SensitiveChangeRequest:
        SensitiveChangeService._cancel_active(user, SensitiveChangeField.PASSWORD)
        channel = SensitiveChangeService._current_channel(user)
        challenge = OTPService.issue(
            user, channel=channel, purpose=OTPPurpose.SENSITIVE_CHANGE
        )
        scr = SensitiveChangeRequest.objects.create(
            user=user,
            field=SensitiveChangeField.PASSWORD,
            new_secret_hash=new_password_hash,
            challenge=challenge,
            requested_ip=_client_ip(request),
        )
        _audit(
            "sensitive_change.password.initiated",
            user=user,
            request=request,
            message="Password change requested (awaiting code)",
        )
        return scr

    # ----- confirm / cancel / apply -------------------------------------
    @staticmethod
    def active_request(user, field) -> SensitiveChangeRequest | None:
        return (
            SensitiveChangeRequest.objects.filter(
                user=user, field=field, state=SensitiveChangeState.AWAITING_OTP
            )
            .order_by("-created_at")
            .first()
        )

    @staticmethod
    @transaction.atomic
    def confirm(
        scr: SensitiveChangeRequest, *, code: str, request=None
    ) -> SensitiveChangeRequest:
        if scr.state != SensitiveChangeState.AWAITING_OTP:
            raise ValidationException(
                detail="This change is no longer awaiting confirmation."
            )
        if scr.challenge is None:
            raise ValidationException(
                detail="This request has expired. Please start again."
            )

        OTPService.verify_challenge(scr.challenge, code)

        immediate = (
            scr.field == SensitiveChangeField.PASSWORD
            or not SensitiveChangeService.step_up_enabled()
        )
        if immediate:
            SensitiveChangeService._apply(scr, request=request)
            return scr

        cooldown = settings.TRUST_SENSITIVE_CHANGE_COOLDOWN_MINUTES
        scr.state = SensitiveChangeState.SCHEDULED
        scr.apply_after = timezone.now() + timezone.timedelta(minutes=cooldown)
        scr.save(update_fields=["state", "apply_after", "updated_at"])

        _security_email(
            scr.user.email,
            f"{scr.get_field_display().lower()} change scheduled",
            f"Your {_site()} {scr.get_field_display().lower()} will change to "
            f"{_mask(scr.new_value)} in about {cooldown} minutes. "
            f"If you didn't request this, cancel it now from Settings, or sign in and change your password.",
        )
        _audit(
            f"sensitive_change.{scr.field}.scheduled",
            user=scr.user,
            request=request,
            message=f"{scr.get_field_display()} change scheduled for {scr.apply_after:%Y-%m-%d %H:%M} UTC",
        )
        return scr

    @staticmethod
    @transaction.atomic
    def _apply(scr: SensitiveChangeRequest, *, request=None) -> None:
        user = scr.user
        if scr.field == SensitiveChangeField.EMAIL:
            if (
                User.all_objects.filter(email__iexact=scr.new_value)
                .exclude(pk=user.pk)
                .exists()
            ):
                raise ConflictException(
                    detail="That email address is now in use by another account."
                )
            old = user.email
            user.email = scr.new_value
            user.is_email_verified = True  # proven via the OTP sent to the new address
            user.save(update_fields=["email", "is_email_verified"])
            _security_email(
                old,
                "your email was changed",
                f"Your {_site()} sign-in email is now {_mask(scr.new_value)}.",
            )
        elif scr.field == SensitiveChangeField.MOBILE:
            if (
                User.all_objects.filter(mobile=scr.new_value)
                .exclude(pk=user.pk)
                .exists()
            ):
                raise ConflictException(
                    detail="That mobile number is now in use by another account."
                )
            user.mobile = scr.new_value
            user.is_mobile_verified = True
            user.save(update_fields=["mobile", "is_mobile_verified"])
            _security_email(
                user.email,
                "your mobile number was changed",
                f"Your {_site()} mobile number is now {_mask(scr.new_value)}.",
            )
        elif scr.field == SensitiveChangeField.PASSWORD:
            user.password = scr.new_secret_hash
            user.save(update_fields=["password"])
            _security_email(
                user.email,
                "your password was changed",
                f"Your {_site()} password was just changed. If this wasn't you, contact support immediately.",
            )

        scr.state = SensitiveChangeState.APPLIED
        scr.applied_at = timezone.now()
        scr.save(update_fields=["state", "applied_at", "updated_at"])
        TrustService.recompute_verification_score(user)
        _audit(
            f"sensitive_change.{scr.field}.applied",
            user=user,
            request=request,
            message=f"{scr.get_field_display()} change applied",
        )

    @staticmethod
    def cancel(scr: SensitiveChangeRequest, *, request=None) -> SensitiveChangeRequest:
        if not scr.is_active:
            raise ValidationException(
                detail="There is nothing to cancel for this request."
            )
        scr.state = SensitiveChangeState.CANCELLED
        scr.cancelled_at = timezone.now()
        scr.save(update_fields=["state", "cancelled_at", "updated_at"])
        _audit(
            f"sensitive_change.{scr.field}.cancelled",
            user=scr.user,
            request=request,
            message=f"{scr.get_field_display()} change cancelled by the owner",
        )
        return scr

    # ----- background sweeps -------------------------------------------
    @staticmethod
    def apply_due() -> int:
        due = SensitiveChangeRequest.objects.filter(
            state=SensitiveChangeState.SCHEDULED, apply_after__lte=timezone.now()
        ).select_related("user")
        applied = 0
        for scr in due:
            try:
                SensitiveChangeService._apply(scr)
                applied += 1
            except Exception:  # noqa: BLE001 - one bad row must not stop the sweep
                logger.exception(
                    "apply_due: failed to apply sensitive change %s - marking expired",
                    scr.id,
                )
                # _apply is atomic, so nothing partial persisted. Retrying it
                # every 60s forever is worse than giving up: the usual cause
                # is the target email/mobile getting taken during the
                # cooldown. Fail the request and tell the owner.
                SensitiveChangeRequest.objects.filter(pk=scr.pk).update(
                    state=SensitiveChangeState.EXPIRED, updated_at=timezone.now()
                )
                _security_email(
                    scr.user.email,
                    f"{scr.get_field_display().lower()} change could not be applied",
                    f"Your scheduled {_site()} {scr.get_field_display().lower()} change to "
                    f"{_mask(scr.new_value or '')} could not be completed (the new "
                    f"contact may already be in use). Nothing was changed. Please try again.",
                )
        return applied

    @staticmethod
    def expire_stale() -> int:
        cutoff = timezone.now() - timezone.timedelta(
            minutes=settings.TRUST_OTP_TTL_MINUTES + 60
        )
        return SensitiveChangeRequest.objects.filter(
            state=SensitiveChangeState.AWAITING_OTP, created_at__lt=cutoff
        ).update(state=SensitiveChangeState.EXPIRED)

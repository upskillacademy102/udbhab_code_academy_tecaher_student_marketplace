"""
OTPService - issue and verify one-time codes.

Two use cases share the primitives here:
  * contact verification (``verify_email`` / ``verify_mobile``) - a
    successful verify flips ``User.is_email_verified`` /
    ``is_mobile_verified`` (Phase 1).
  * sensitive-change confirmation (``sensitive_change``) - no side effect
    on the user; the caller (SensitiveChangeService) links the challenge
    and acts on the confirmed change itself (Phase 2).

Email codes go out via Django's ``send_mail`` (console backend in dev,
like password reset). SMS codes go through the configured ``SMSProvider``
(console adapter logs the code in dev).
"""

from __future__ import annotations

import hashlib
import logging
import secrets

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.trust.models import OTPChallenge, OTPChannel, OTPPurpose
from apps.trust.providers import get_provider
from apps.trust.services.trust_service import TrustService

logger = logging.getLogger("apps.trust.otp")

_PURPOSE_FOR_CHANNEL = {
    OTPChannel.EMAIL: OTPPurpose.VERIFY_EMAIL,
    OTPChannel.SMS: OTPPurpose.VERIFY_MOBILE,
}


def _hash(code: str) -> str:
    return hashlib.sha256(f"{code}:{settings.SECRET_KEY}".encode()).hexdigest()


class OTPService:
    @staticmethod
    def issue(
        user,
        *,
        channel: str,
        purpose: str | None = None,
        destination: str | None = None,
    ) -> OTPChallenge:
        """
        Create + send a fresh 6-digit code. Supersedes any earlier
        unconsumed challenge for the same (user, purpose).
        """
        purpose = purpose or _PURPOSE_FOR_CHANNEL[channel]
        destination = destination or (
            user.email if channel == OTPChannel.EMAIL else user.mobile
        )
        if not destination:
            raise ValidationException(detail="No contact on file for this channel.")

        OTPChallenge.objects.filter(
            user=user, purpose=purpose, consumed_at__isnull=True
        ).update(consumed_at=timezone.now())

        code = f"{secrets.randbelow(1_000_000):06d}"
        ttl = settings.TRUST_OTP_TTL_MINUTES
        challenge = OTPChallenge.objects.create(
            user=user,
            channel=channel,
            purpose=purpose,
            destination=destination,
            code_hash=_hash(code),
            expires_at=timezone.now() + timezone.timedelta(minutes=ttl),
            max_attempts=settings.TRUST_OTP_MAX_ATTEMPTS,
        )

        site = getattr(settings, "SITE_NAME", "the platform")
        body = (
            f"Your {site} verification code is {code}. "
            f"It expires in {ttl} minutes. If you didn't request this, ignore this message."
        )
        if channel == OTPChannel.SMS:
            result = get_provider("sms").send(to=destination, body=body)
            if not result.ok:
                logger.error(
                    "OTP SMS send failed for user %s: %s", user.id, result.detail
                )
        else:
            try:
                send_mail(
                    subject=f"{site}: your verification code",
                    message=body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[destination],
                    fail_silently=False,
                )
            # noqa: BLE001 - an email-delivery failure must not 500 the request
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "OTP email send failed for user %s: %s", user.id, exc, exc_info=True
                )

        logger.info(
            "OTP issued: user=%s channel=%s purpose=%s", user.id, channel, purpose
        )
        return challenge

    @staticmethod
    def verify_challenge(challenge: OTPChallenge, code: str) -> None:
        """Validate ``code`` against one specific challenge. Marks it consumed on success."""
        now = timezone.now()
        if challenge.consumed_at is not None:
            raise ValidationException(
                detail="This code has already been used. Request a new one."
            )
        if challenge.expires_at <= now:
            raise ValidationException(
                detail="This code has expired. Request a new one."
            )
        if challenge.attempts >= challenge.max_attempts:
            raise ValidationException(
                detail="Too many incorrect attempts. Request a new code."
            )

        challenge.attempts += 1
        if not code or _hash(str(code).strip()) != challenge.code_hash:
            challenge.save(update_fields=["attempts", "updated_at"])
            remaining = max(challenge.max_attempts - challenge.attempts, 0)
            raise ValidationException(
                detail=f"Incorrect code. {remaining} attempt(s) left."
            )

        challenge.consumed_at = now
        challenge.save(update_fields=["attempts", "consumed_at", "updated_at"])

    @staticmethod
    def verify(
        user, *, channel: str, code: str, purpose: str | None = None
    ) -> OTPChallenge:
        """
        Verify against the latest pending challenge for (user, channel,
        purpose). For contact-verification purposes this also flips the
        matching ``User.is_*_verified`` flag.
        """
        purpose = purpose or _PURPOSE_FOR_CHANNEL[channel]
        challenge = (
            OTPChallenge.objects.filter(
                user=user, channel=channel, purpose=purpose, consumed_at__isnull=True
            )
            .order_by("-created_at")
            .first()
        )
        if challenge is None:
            raise ValidationException(
                detail="No verification code is pending. Request a new one."
            )

        OTPService.verify_challenge(challenge, code)

        if purpose == OTPPurpose.VERIFY_EMAIL and not user.is_email_verified:
            user.is_email_verified = True
            user.save(update_fields=["is_email_verified"])
            TrustService.recompute_verification_score(user)
        elif purpose == OTPPurpose.VERIFY_MOBILE and not user.is_mobile_verified:
            user.is_mobile_verified = True
            user.save(update_fields=["is_mobile_verified"])
            TrustService.recompute_verification_score(user)

        logger.info(
            "OTP verified: user=%s channel=%s purpose=%s", user.id, channel, purpose
        )
        return challenge

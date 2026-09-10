"""
AnomalyService (Phase 9b).

Cheap login-time anomaly checks:
  * login from a country the account has never used before (GeoIP stub),
  * login from a device the account has never used before,
  * one device fingerprint signing into many distinct accounts.

Each hit records an ``ANOMALY`` RiskSignal + one ``ANOMALY`` review item +
a SECURITY audit row. Enforcement (whether ``review`` / ``suspended`` does
anything) is the risk engine's job (``TRUST_ENABLE_RISK_AUTO_ACTIONS``).

Everything here is a no-op unless ``TRUST_ENABLE_ANOMALY_ALERTS`` is on.
Also exposes ``note_refund`` for payment-refund velocity.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger("apps.trust.anomaly")

_REFUND_WINDOW = 24 * 3600
_REFUND_SPIKE = 3  # refunds/disputes for one user within 24h


def enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_ANOMALY_ALERTS", False))


def _raise(user, *, detail: str, kind_hint: str, request=None) -> None:
    from apps.ops.models import AuditCategory, AuditStatus
    from apps.ops.services import AuditService
    from apps.trust.models import ManualReviewKind, RiskSignalKind
    from apps.trust.services.risk_service import RiskService
    from apps.trust.services.trust_service import TrustService

    RiskService.add_signal(
        user,
        kind=RiskSignalKind.ANOMALY,
        weight=15,
        detail=detail,
        payload={"anomaly": kind_hint},
    )
    TrustService.open_review_item(
        kind=ManualReviewKind.ANOMALY,
        summary=f"Anomaly for {user.email}: {detail}",
        subject_user=user,
        payload={"anomaly": kind_hint, "detail": detail},
        dedupe_key=f"anomaly:{user.id}",
        priority=2,
    )
    AuditService.record(
        action="anomaly_detected",
        category=AuditCategory.SECURITY,
        status=AuditStatus.PENDING,
        request=request,
        actor=user,
        target=user,
        message=detail,
        anomaly=kind_hint,
    )
    logger.warning("anomaly: %s - %s", user.email, detail)


class AnomalyService:
    @staticmethod
    def on_login(user, request) -> None:
        """Runs BEFORE the dedupe device-signature write in LoginView."""
        if not enabled():
            return
        try:
            AnomalyService._check_country(user, request)
            AnomalyService._check_device(user, request)
        except Exception:  # noqa: BLE001 - anomaly checks must not break login
            logger.exception("anomaly on_login failed for %s", getattr(user, "id", "?"))

    @staticmethod
    def _check_country(user, request) -> None:
        from apps.trust.fingerprint import client_ip
        from apps.trust.providers import get_provider
        from apps.trust.services.trust_service import TrustService

        ip = client_ip(request)
        try:
            result = get_provider("geoip").lookup(ip=ip)
        except Exception:  # noqa: BLE001
            return
        country = (result.metadata or {}).get("country")
        if not country:
            return

        profile = TrustService.get_or_create_profile(user)
        known = list(profile.known_countries or [])
        if known and country not in known:
            _raise(
                user,
                detail=f"Login from a new country ({country}); previously {', '.join(known)}",
                kind_hint="new_country",
                request=request,
            )
        if country not in known:
            known.append(country)
            profile.known_countries = known[-10:]
            profile.save(update_fields=["known_countries", "updated_at"])

    @staticmethod
    def _check_device(user, request) -> None:
        from apps.trust.fingerprint import client_fingerprint
        from apps.trust.models import IdentitySignature, IdentitySignatureKind
        from apps.trust.services.dedupe_service import DedupeService

        fp = client_fingerprint(request)
        h = DedupeService._hash(IdentitySignatureKind.DEVICE, fp)

        user_devices = IdentitySignature.objects.filter(
            user=user, kind=IdentitySignatureKind.DEVICE
        )
        this_device_known = user_devices.filter(value_hash=h).exists()
        if user_devices.exists() and not this_device_known:
            _raise(
                user,
                detail="Login from a device this account has not used before",
                kind_hint="new_device",
                request=request,
            )

        # many accounts on one device
        since = timezone.now() - timedelta(days=1)
        account_count = (
            IdentitySignature.objects.filter(
                kind=IdentitySignatureKind.DEVICE, value_hash=h, created_at__gte=since
            )
            .values("user_id")
            .distinct()
            .count()
        )
        # +1 for this login if the device sig doesn't exist for this user yet
        effective = account_count + (0 if this_device_known else 1)
        if effective >= int(getattr(settings, "TRUST_ANOMALY_ACCOUNTS_PER_DEVICE", 4)):
            _raise(
                user,
                detail=f"{effective} accounts used this device in 24h",
                kind_hint="many_accounts_per_device",
                request=request,
            )

    @staticmethod
    def note_refund(user) -> None:
        """Payment-refund / dispute velocity for one user."""
        if not enabled():
            return
        try:
            key = f"anomaly:refunds:{user.id}"
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, _REFUND_WINDOW)
                count = 1
            if count == _REFUND_SPIKE:
                _raise(
                    user,
                    detail=f"{count} refunds/disputes within 24h",
                    kind_hint="refund_spike",
                )
        except Exception:  # noqa: BLE001
            logger.exception("note_refund failed for %s", getattr(user, "id", "?"))

"""
StaffLoginGuardService - brute-force protection for the admin/super-admin
login endpoints (``/api/v1/auth/staff/login-admin/`` and
``/staff/login-superadmin/``).

Two independent mechanisms, both keyed per (page, ...) so an admin-page
attack never affects the superadmin-page counters or vice versa:

  * Per-identifier failure counter (cache, 24h rolling window). When a
    *real* account's login identifier (email for superadmin, account_name
    for admin) racks up >= ``STAFF_LOGIN_BRUTEFORCE_THRESHOLD`` failures in
    the window, that account is auto-banned via
    ``SanctionService.apply(source=AUTO_STAFF_LOGIN_BRUTEFORCE)`` - a real,
    auditable, superadmin-reversible sanction.
  * Per-IP cooldown block (cache). When failures accumulate against
    identifiers that do NOT resolve to any real account (pure guessing -
    there is no account to ban), the source IP is blocked from POSTing to
    either staff-login endpoint for ``STAFF_LOGIN_IP_BLOCK_MINUTES``.

Every failure is also written to the durable ``AuditLog`` regardless of
outcome - that is the superadmin-visible trail; the cache counters are
purely the fast threshold check and can be safely lost on a cache flush
(worst case: the threshold resets early - fails open, the safe direction).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

from apps.core.exceptions.custom_exceptions import ThrottledException
from apps.trust.fingerprint import client_ip

logger = logging.getLogger("apps.trust.staff_login_guard")

_FAIL_PREFIX = "staff_login:fail:"
_IP_FAIL_PREFIX = "staff_login:ipfail:"
_IP_BLOCK_PREFIX = "staff_login:ipblock:"
_WINDOW_SECONDS = 24 * 60 * 60


class StaffLoginGuardService:
    @staticmethod
    def check_ip_block(request, *, page: str) -> None:
        """Raise ThrottledException if this IP is currently cooled down for `page`."""
        try:
            blocked = cache.get(f"{_IP_BLOCK_PREFIX}{page}:{client_ip(request)}")
        except Exception:  # noqa: BLE001 - never let the cache break a login
            blocked = None
        if blocked:
            raise ThrottledException(
                detail="Too many failed attempts from this network. Try again later."
            )

    @staticmethod
    def record_failure(request, *, page: str, identifier: str, resolved_user) -> None:
        """
        Log the failure and bump the relevant counter. `resolved_user` is
        the User the caller already looked up for authentication (or
        None) - reused here so "does this identifier belong to a real
        account" is never re-derived.
        """
        StaffLoginGuardService._audit_failure(request, page=page, identifier=identifier)

        try:
            if resolved_user is not None:
                StaffLoginGuardService._bump_account_counter(
                    request, resolved_user, page=page
                )
            else:
                StaffLoginGuardService._bump_ip_counter(request, page=page)
        except Exception:  # noqa: BLE001 - guard logic must never break a login
            logger.exception("staff login guard bookkeeping failed for page=%s", page)

    @staticmethod
    def record_success(*, page: str, identifier: str) -> None:
        try:
            cache.delete(f"{_FAIL_PREFIX}{page}:{identifier.lower()}")
        except Exception:  # noqa: BLE001
            logger.debug("staff login guard cache clear failed", exc_info=True)

    # ------------------------------------------------------------------
    @staticmethod
    def _bump_account_counter(request, user, *, page: str) -> None:
        from apps.core.exceptions.custom_exceptions import ValidationException
        from apps.trust.models import AccountSanctionKind, AccountSanctionSource
        from apps.trust.services.sanction_service import SanctionService

        key = f"{_FAIL_PREFIX}{page}:{StaffLoginGuardService._identifier_for(user, page).lower()}"
        count = (cache.get(key) or 0) + 1
        cache.set(key, count, _WINDOW_SECONDS)

        threshold = getattr(settings, "STAFF_LOGIN_BRUTEFORCE_THRESHOLD", 10)
        if count < threshold:
            return
        try:
            SanctionService.apply(
                user,
                kind=AccountSanctionKind.BAN,
                source=AccountSanctionSource.AUTO_STAFF_LOGIN_BRUTEFORCE,
                reason=f"{count} failed {page}-login attempts against this account within 24h.",
            )
        except ValidationException:
            # Super Admin can never be auto-banned (SanctionService's
            # permanent protection on that role) - fall back to an IP
            # cooldown so repeated attacks against a known Super Admin
            # email are still slowed down somehow.
            StaffLoginGuardService._bump_ip_counter(request, page=page)

    @staticmethod
    def _bump_ip_counter(request, *, page: str) -> None:
        ip = client_ip(request)
        key = f"{_IP_FAIL_PREFIX}{page}:{ip}"
        count = (cache.get(key) or 0) + 1
        cache.set(key, count, _WINDOW_SECONDS)

        threshold = getattr(settings, "STAFF_LOGIN_BRUTEFORCE_THRESHOLD", 10)
        if count >= threshold:
            minutes = getattr(settings, "STAFF_LOGIN_IP_BLOCK_MINUTES", 60)
            cache.set(f"{_IP_BLOCK_PREFIX}{page}:{ip}", True, minutes * 60)

    @staticmethod
    def _identifier_for(user, page: str) -> str:
        return user.admin_account_name if page == "admin" else user.email

    @staticmethod
    def _audit_failure(request, *, page: str, identifier: str) -> None:
        try:
            from apps.ops.models import AuditCategory, AuditStatus
            from apps.ops.services import AuditService

            AuditService.record(
                request=request,
                category=AuditCategory.SECURITY,
                action="staff_login.failed",
                status=AuditStatus.FAILURE,
                message=f"Failed {page}-login attempt for '{identifier}'",
                page=page,
            )
        except Exception:  # noqa: BLE001 - auditing must never break a login
            logger.exception("staff login failure audit-write failed")

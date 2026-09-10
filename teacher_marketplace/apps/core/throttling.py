"""
Rate-limit classes for the Teacher Marketplace Platform.

Two jobs:

1. **Resilience.** Every throttle here is wrapped so a cache-backend failure
   (e.g. a Redis blip when throttle counters live in Redis for multi-worker
   accuracy - see ``config/settings/production.py``) **fails open**: the
   request is allowed rather than 500-ing. Availability of login / the whole
   API must not hinge on the rate-limiter's datastore. Every downstream auth
   and permission check still runs.

   ``ResilientAnonRateThrottle`` / ``ResilientUserRateThrottle`` are the
   project-wide defaults (settings ``DEFAULT_THROTTLE_CLASSES``) - drop-in
   replacements for DRF's stock classes with only the fail-open behaviour
   added.

2. **A tighter, named ceiling on abuse-prone endpoints** an attacker actually
   hammers:

       * credential stuffing / password brute-force  -> LoginRateThrottle
       * account / email enumeration + spam signups  -> RegisterRateThrottle
       * password-reset token flooding               -> PasswordResetRateThrottle
       * privileged-login guessing                    -> AdminLoginRateThrottle

   ``LoginRateThrottle`` keys on *(client IP, sha256(email))* so a shared IP
   (school lab, office NAT, carrier CGNAT) throttles per account, never
   collectively. The others key on client IP - the actions they guard are
   genuinely rare per IP. Rates are in ``config/settings/base.py`` so they
   tune per environment without a code change.
"""

from __future__ import annotations

import hashlib

from rest_framework.throttling import (
    AnonRateThrottle,
    SimpleRateThrottle,
    UserRateThrottle,
)


class _FailOpenMixin:
    """Never let a cache-backend error turn into a failed request."""

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:  # noqa: BLE001 - availability > strictness here
            return True


class ResilientAnonRateThrottle(_FailOpenMixin, AnonRateThrottle):
    pass


class ResilientUserRateThrottle(_FailOpenMixin, UserRateThrottle):
    pass


class LoginRateThrottle(_FailOpenMixin, SimpleRateThrottle):
    """Per-(IP, email) cap on ``POST /api/v1/auth/login/``."""

    scope = "login"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = ""
        if isinstance(getattr(request, "data", None), dict):
            email = str(request.data.get("email") or "").strip().lower()
        who = hashlib.sha256(f"{ident}|{email}".encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": who}


class _ScopedIPThrottle(_FailOpenMixin, SimpleRateThrottle):
    """Per-IP cap; ``scope`` set by the subclass."""

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class RegisterRateThrottle(_ScopedIPThrottle):
    scope = "register"


class PasswordResetRateThrottle(_ScopedIPThrottle):
    scope = "password_reset"


class AdminLoginRateThrottle(_ScopedIPThrottle):
    scope = "admin_login"


class OTPRequestThrottle(_FailOpenMixin, SimpleRateThrottle):
    """
    Per-(user, verification-channel) cap on requesting a fresh OTP, so a
    logged-in account cannot flood itself (or, via a spoofed destination
    in future, someone else) with codes. The view sets ``otp_channel``.
    """

    scope = "otp_request"

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        ident = (
            str(user.pk) if user and user.is_authenticated else self.get_ident(request)
        )
        channel = getattr(view, "otp_channel", getattr(view, "channel", "")) or ""
        return self.cache_format % {"scope": self.scope, "ident": f"{ident}:{channel}"}

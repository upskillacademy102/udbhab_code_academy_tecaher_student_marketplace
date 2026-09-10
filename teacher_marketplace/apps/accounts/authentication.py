"""
Authentication classes for the Teacher Marketplace Platform.

Two things layered on top of SimpleJWT's stock ``JWTAuthentication``:

1. **Single-active-session enforcement** (``SessionAwareJWTAuthentication``).
   Every access/refresh token carries a ``sid`` claim = the id of the
   user's :class:`apps.accounts.models.UserSession` row at the moment it
   was minted. On every request we re-check that claim against the DB:

       * session row missing            -> 401
       * session ``is_active`` is False  (logout happened)   -> 401
       * ``sid`` != current session_id  (a newer login rotated it) -> 401

   This is what makes logout invalidate the *access* token immediately
   (SimpleJWT's blacklist only covers refresh tokens) and what makes a
   new login anywhere silently end the previous session.

2. **Cookie transport** (``CookieJWTAuthentication``).
   Falls back to reading the access token from an httpOnly cookie when
   there is no ``Authorization`` header, so browser / Swagger sessions
   authenticate automatically without pasting a token. The classic
   ``Authorization: Bearer <token>`` header continues to work unchanged
   and takes precedence when both are present.

Tokens minted before this module existed have no ``sid`` claim and are
rejected with 401 - clients simply log in again.
"""

from __future__ import annotations

import logging

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed

from apps.accounts.models import ImpersonationSession, UserSession

logger = logging.getLogger("apps.accounts")

SESSION_CLAIM = "sid"
IMPERSONATOR_CLAIM = "act"


class SessionAwareJWTAuthentication(JWTAuthentication):
    """Stock header-based JWT auth + single-active-session check."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        self._enforce_session(user, validated_token)
        return user

    @staticmethod
    def _enforce_session(user, validated_token):
        token_sid = validated_token.get(SESSION_CLAIM)
        if not token_sid:
            raise AuthenticationFailed(
                "Token is not bound to a login session. Please log in again.",
                code="session_not_bound",
            )

        # Impersonation token: validate against ImpersonationSession, not
        # the target user's real UserSession (which is left untouched).
        if validated_token.get(IMPERSONATOR_CLAIM):
            imp = ImpersonationSession.active_for(user.id, token_sid)
            if imp is None:
                raise AuthenticationFailed(
                    "This impersonation session has ended. Return to your account and try again.",
                    code="impersonation_ended",
                )
            return

        active_sid = UserSession.active_sid_for(user.id)
        if active_sid is None or str(active_sid) != str(token_sid):
            raise AuthenticationFailed(
                "This session is no longer active. Please log in again.",
                code="session_invalidated",
            )


class CookieJWTAuthentication(SessionAwareJWTAuthentication):
    """
    ``SessionAwareJWTAuthentication`` plus an httpOnly-cookie fallback.

    Resolution order:
        1. ``Authorization`` header, if present (delegates to super).
        2. the access-token cookie (``settings.JWT_AUTH_COOKIE``).
        3. otherwise -> unauthenticated (returns ``None``).
    """

    def authenticate(self, request):
        if self.get_header(request) is not None:
            return super().authenticate(request)

        raw_token = request.COOKIES.get(settings.JWT_AUTH_COOKIE)
        if not raw_token:
            return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token


# ----------------------------------------------------------------------
# drf-spectacular: describe both transports in the OpenAPI security scheme
# (auto-discovered because this module is imported at startup).
# ----------------------------------------------------------------------
class _SessionAwareJWTScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.SessionAwareJWTAuthentication"
    name = "jwtHeaderAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}


class _CookieJWTScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.CookieJWTAuthentication"
    name = "jwtCookieAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.JWT_AUTH_COOKIE,
        }

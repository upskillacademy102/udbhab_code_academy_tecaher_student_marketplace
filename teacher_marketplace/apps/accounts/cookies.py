"""
Helpers for putting / clearing the JWT httpOnly cookies on a response.

Used by the login, refresh and logout views so a browser or Swagger
session carries authentication automatically, without the user ever
handling a token by hand. Programmatic clients can keep ignoring the
cookies and send ``Authorization: Bearer <token>`` instead.

Cookie attributes are driven by settings (see config/settings/base.py):
    JWT_AUTH_COOKIE           name of the access-token cookie   ("access")
    JWT_REFRESH_COOKIE        name of the refresh-token cookie  ("refresh")
    JWT_AUTH_COOKIE_SECURE    Secure flag  (False in dev, True in prod)
    JWT_AUTH_COOKIE_SAMESITE  SameSite policy ("Lax" by default)
    JWT_AUTH_COOKIE_HTTPONLY  HttpOnly flag (True)

The refresh cookie is scoped to the auth path so it is only ever sent to
``/api/v1/auth/*`` (login / refresh / logout), never to ordinary API
endpoints.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework_simplejwt.settings import api_settings as jwt_settings

REFRESH_COOKIE_PATH = "/api/v1/auth/"


def _common_kwargs() -> dict:
    return {
        "httponly": getattr(settings, "JWT_AUTH_COOKIE_HTTPONLY", True),
        "secure": getattr(settings, "JWT_AUTH_COOKIE_SECURE", False),
        "samesite": getattr(settings, "JWT_AUTH_COOKIE_SAMESITE", "Lax"),
    }


def set_auth_cookies(response, access_token: str, refresh_token: str | None = None):
    """Attach the access (and optionally refresh) token as httpOnly cookies."""
    response.set_cookie(
        settings.JWT_AUTH_COOKIE,
        access_token,
        max_age=int(jwt_settings.ACCESS_TOKEN_LIFETIME.total_seconds()),
        path="/",
        **_common_kwargs(),
    )
    if refresh_token is not None:
        response.set_cookie(
            settings.JWT_REFRESH_COOKIE,
            refresh_token,
            max_age=int(jwt_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
            path=REFRESH_COOKIE_PATH,
            **_common_kwargs(),
        )
    return response


def clear_auth_cookies(response):
    """Remove both auth cookies (logout, or a failed refresh)."""
    samesite = getattr(settings, "JWT_AUTH_COOKIE_SAMESITE", "Lax")
    response.delete_cookie(settings.JWT_AUTH_COOKIE, path="/", samesite=samesite)
    response.delete_cookie(
        settings.JWT_REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, samesite=samesite
    )
    return response

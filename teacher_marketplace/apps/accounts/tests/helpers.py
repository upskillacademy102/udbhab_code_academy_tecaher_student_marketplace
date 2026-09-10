"""
Shared helpers for the accounts test-suite.

Nothing here prints or asserts on token *values* - tests only ever
check status codes, envelope error codes, and cookie presence/absence.
"""

from __future__ import annotations

import itertools

from apps.accounts.models import User, UserRole

# Passes every AUTH_PASSWORD_VALIDATOR incl. the custom
# PasswordStrengthValidator (upper + lower + digit + special, >= 8).
TEST_PASSWORD = "Str0ng!Pass1"

_mobile_counter = itertools.count(919800000000)


def make_user(
    role: str = UserRole.STUDENT, *, password: str = TEST_PASSWORD, **extra
) -> User:
    """Create an active user with a unique email + mobile for the given role."""
    n = next(_mobile_counter)
    defaults = {
        "email": extra.pop("email", f"user{n}@example.com"),
        "mobile": extra.pop("mobile", str(n)),
        "first_name": extra.pop("first_name", "Test"),
        "last_name": extra.pop("last_name", "User"),
        "role": role,
    }
    defaults.update(extra)
    return User.objects.create_user(password=password, **defaults)


def login(api_client, user, password: str = TEST_PASSWORD):
    """
    Log `user` in and return the DRF response. On success the APIClient keeps
    the auth cookies for subsequent requests.

    student / teacher / superadmin -> POST /api/v1/auth/login/
    admin                          -> the Super-Admin approval flow, auto-approved
                                      here so tests don't need a second account.
    """
    if getattr(user, "role", None) == UserRole.ADMIN:
        return _admin_login(api_client, user, password)
    return api_client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": password},
        format="json",
    )


def _admin_login(api_client, user, password):
    from apps.accounts.models import AdminLoginRequest

    resp = api_client.post(
        "/api/v1/auth/admin/login/",
        {"email": user.email, "password": password},
        format="json",
    )
    if resp.status_code != 202:
        return resp  # bad credentials etc.
    req = resp.data["data"]
    AdminLoginRequest.objects.filter(id=req["request_id"]).update(status="approved")
    return api_client.get(
        f"/api/v1/auth/admin/login/{req['request_id']}/status/?token={req['poll_token']}"
    )


def bearer(api_client, access_token: str):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    return api_client

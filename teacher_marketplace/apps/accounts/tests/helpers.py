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


def make_learning_partner_admin(name: str = "TestPartner", *, mobile: str | None = None, **extra) -> User:
    """
    Create a Learning Partner admin: role=admin, department=the seeded
    Learning Partner one, with a generated-shape admin_account_name (the `n`
    suffix keeps it unique across tests that don't bother passing a distinct
    `name`). Mirrors what admin_account_naming.build_admin_account_name's
    organization_name branch would produce, without importing it - tests
    want a predictable, caller-chosen name, not the real collision-suffixing
    algorithm.
    """
    from apps.accounts.models import AdminDepartment

    dept, _ = AdminDepartment.objects.get_or_create(
        name="Learning Partner", defaults={"is_learning_partner": True}
    )
    if not dept.is_learning_partner:
        dept.is_learning_partner = True
        dept.save(update_fields=["is_learning_partner"])
    n = next(_mobile_counter)
    defaults = {
        "email": extra.pop("email", f"lp{n}@example.com"),
        "mobile": mobile or str(n),
        "first_name": name,
        "last_name": "",
        "role": UserRole.ADMIN,
        "admin_department": dept,
        "admin_account_name": f"{name}@LearningPartner{n}",
    }
    defaults.update(extra)
    return User.objects.create_user(password=TEST_PASSWORD, **defaults)


def login_lp(api_client, lp_admin, password: str = TEST_PASSWORD):
    """
    A Learning Partner is a new-flow admin (admin_account_name set) - it
    signs in via /staff/login-admin/ (account name + password), not login()'s
    /auth/admin/login/ path, which explicitly rejects any account with
    admin_account_name set (see AdminLoginView.post).
    """
    return api_client.post(
        "/api/v1/auth/staff/login-admin/",
        {"account_name": lp_admin.admin_account_name, "password": password},
        format="json",
    )

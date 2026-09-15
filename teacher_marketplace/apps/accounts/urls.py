"""
URL configuration for the accounts app.

Included from config/urls.py at the `api/v1/auth/` prefix.

    POST /api/v1/auth/register/                         self-registration
    POST /api/v1/auth/login/                            student/teacher/superadmin login
    POST /api/v1/auth/refresh/                          token refresh
    POST /api/v1/auth/logout/                           logout
    GET  /api/v1/auth/me/                               current user + impersonation state
    POST /api/v1/auth/stop-impersonation/               end "act as user"
    POST /api/v1/auth/change-password/
    POST /api/v1/auth/forgot-password/
    POST /api/v1/auth/reset-password/

    POST /api/v1/auth/admin/login/                      admin submits creds -> pending request
    GET  /api/v1/auth/admin/login/{id}/status/          admin polls; tokens once approved
    GET  /api/v1/auth/admin/login-requests/             pending + recent   (Super Admin)
    POST /api/v1/auth/admin/login-requests/{id}/approve/
    POST /api/v1/auth/admin/login-requests/{id}/deny/
"""

from django.urls import path

from apps.accounts.admin_api import (
    AdminLoginRequestDecisionView,
    AdminLoginRequestListView,
    AdminLoginStatusView,
    AdminLoginView,
)
from apps.accounts.views import (
    ChangeEmailConfirmView,
    ChangeEmailRequestView,
    ChangeMobileConfirmView,
    ChangeMobileRequestView,
    ChangePasswordConfirmView,
    ChangePasswordView,
    CookieTokenRefreshView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
    ResetPasswordView,
    SensitiveChangeCancelView,
    SensitiveChangeListView,
    StopImpersonationView,
    SwitchRoleView,
)

app_name = "accounts"

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", CookieTokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path(
        "stop-impersonation/",
        StopImpersonationView.as_view(),
        name="stop-impersonation",
    ),
    path("switch-role/", SwitchRoleView.as_view(), name="switch-role"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path(
        "change-password/confirm/",
        ChangePasswordConfirmView.as_view(),
        name="change-password-confirm",
    ),
    path("change-email/", ChangeEmailRequestView.as_view(), name="change-email"),
    path(
        "change-email/confirm/",
        ChangeEmailConfirmView.as_view(),
        name="change-email-confirm",
    ),
    path("change-mobile/", ChangeMobileRequestView.as_view(), name="change-mobile"),
    path(
        "change-mobile/confirm/",
        ChangeMobileConfirmView.as_view(),
        name="change-mobile-confirm",
    ),
    path(
        "sensitive-changes/",
        SensitiveChangeListView.as_view(),
        name="sensitive-change-list",
    ),
    path(
        "sensitive-changes/<uuid:id>/cancel/",
        SensitiveChangeCancelView.as_view(),
        name="sensitive-change-cancel",
    ),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    # ---- admin-login approval flow ----
    path("admin/login/", AdminLoginView.as_view(), name="admin-login"),
    path(
        "admin/login/<uuid:request_id>/status/",
        AdminLoginStatusView.as_view(),
        name="admin-login-status",
    ),
    path(
        "admin/login-requests/",
        AdminLoginRequestListView.as_view(),
        name="admin-login-requests",
    ),
    path(
        "admin/login-requests/<uuid:id>/approve/",
        AdminLoginRequestDecisionView.as_view(approve=True),
        name="admin-login-approve",
    ),
    path(
        "admin/login-requests/<uuid:id>/deny/",
        AdminLoginRequestDecisionView.as_view(approve=False),
        name="admin-login-deny",
    ),
]

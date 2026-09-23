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

    POST /api/v1/auth/become-learning-partner/          submit request (public)
    GET  /api/v1/auth/learning-partners/                active partners, for signup dropdowns (public)

    POST /api/v1/auth/admin/login/                      admin submits creds -> pending request
    GET  /api/v1/auth/admin/login/{id}/status/          admin polls; tokens once approved
    GET  /api/v1/auth/admin/login-requests/             pending + recent   (Super Admin)
    POST /api/v1/auth/admin/login-requests/{id}/approve/
    POST /api/v1/auth/admin/login-requests/{id}/deny/

    POST /api/v1/auth/staff/login-superadmin/           Super Admin direct sign-in
    POST /api/v1/auth/staff/login-admin/                Admin sign-in (account name + password)
    POST /api/v1/auth/staff/login-learning-partner/     Learning Partner sign-in (account name + password)

    POST /api/v1/auth/staff/create-admin-account/               submit request (public)
    GET  /api/v1/auth/staff/admin-account-requests/              pending + recent   (Super Admin)
    POST /api/v1/auth/staff/admin-account-requests/{id}/approve/ (Super Admin, requires department_id)
    POST /api/v1/auth/staff/admin-account-requests/{id}/deny/    (Super Admin)
    GET/POST             /api/v1/auth/staff/departments/          (Super Admin)
    GET/PUT/PATCH/DELETE /api/v1/auth/staff/departments/{id}/     (Super Admin)

    GET  /api/v1/auth/staff/taxonomy-requests/               pending + recent, every partner (Super Admin)
    POST /api/v1/auth/staff/taxonomy-requests/{id}/approve/  (Super Admin)
    POST /api/v1/auth/staff/taxonomy-requests/{id}/deny/     (Super Admin)

The above are reached only via the hidden triple-click gateway on the
landing-page logo (see apps.web for the logged-out gateway/login pages) -
never linked from any nav.
"""

from django.urls import path

from apps.accounts.admin_api import (
    AdminAccountRequestCreateView,
    AdminAccountRequestDecisionView,
    AdminAccountRequestListView,
    AdminDepartmentDetailView,
    AdminDepartmentListCreateView,
    AdminDepartmentPublicListView,
    AdminLoginRequestDecisionView,
    AdminLoginRequestListView,
    AdminLoginStatusView,
    AdminLoginView,
    BecomeLearningPartnerView,
    LearningPartnerAdminListView,
    LearningPartnerListView,
    StaffAdminLoginView,
    StaffLearningPartnerLoginView,
    StaffSuperAdminLoginView,
    TaxonomyRequestDecisionView,
    TaxonomyRequestListView,
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
    # ---- Learning Partner onboarding (public - not under staff/) ----
    path(
        "become-learning-partner/",
        BecomeLearningPartnerView.as_view(),
        name="become-learning-partner",
    ),
    path(
        "learning-partners/",
        LearningPartnerListView.as_view(),
        name="learning-partners",
    ),
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
    # ---- staff gateway direct login (hidden triple-click entry point) ----
    path(
        "staff/login-superadmin/",
        StaffSuperAdminLoginView.as_view(),
        name="staff-login-superadmin",
    ),
    path(
        "staff/login-admin/",
        StaffAdminLoginView.as_view(),
        name="staff-login-admin",
    ),
    # ---- Learning Partner sign-in (separate from the admin gateway above -
    # reached from the normal "I am a Learning Partner" landing-page link) ----
    path(
        "staff/login-learning-partner/",
        StaffLearningPartnerLoginView.as_view(),
        name="staff-login-learning-partner",
    ),
    # ---- admin-account requests (self-service "become an Admin") ----
    path(
        "staff/create-admin-account/",
        AdminAccountRequestCreateView.as_view(),
        name="staff-create-admin-account",
    ),
    path(
        "staff/admin-account-requests/",
        AdminAccountRequestListView.as_view(),
        name="staff-admin-account-requests",
    ),
    path(
        "staff/admin-account-requests/<uuid:id>/approve/",
        AdminAccountRequestDecisionView.as_view(approve=True),
        name="staff-admin-account-request-approve",
    ),
    path(
        "staff/admin-account-requests/<uuid:id>/deny/",
        AdminAccountRequestDecisionView.as_view(approve=False),
        name="staff-admin-account-request-deny",
    ),
    # ---- admin departments (super admin, fixed-but-editable list) ----
    path(
        "staff/departments/public/",
        AdminDepartmentPublicListView.as_view(),
        name="staff-departments-public",
    ),
    path(
        "staff/departments/",
        AdminDepartmentListCreateView.as_view(),
        name="staff-departments",
    ),
    path(
        "staff/departments/<uuid:id>/",
        AdminDepartmentDetailView.as_view(),
        name="staff-department-detail",
    ),
    # ---- Learning Partner accounts (super admin, "Active" tab) ----
    path(
        "staff/learning-partners/",
        LearningPartnerAdminListView.as_view(),
        name="staff-learning-partners",
    ),
    # ---- Learning Partner taxonomy requests (super admin review) ----
    path(
        "staff/taxonomy-requests/",
        TaxonomyRequestListView.as_view(),
        name="staff-taxonomy-requests",
    ),
    path(
        "staff/taxonomy-requests/<uuid:id>/approve/",
        TaxonomyRequestDecisionView.as_view(approve=True),
        name="staff-taxonomy-request-approve",
    ),
    path(
        "staff/taxonomy-requests/<uuid:id>/deny/",
        TaxonomyRequestDecisionView.as_view(approve=False),
        name="staff-taxonomy-request-deny",
    ),
]

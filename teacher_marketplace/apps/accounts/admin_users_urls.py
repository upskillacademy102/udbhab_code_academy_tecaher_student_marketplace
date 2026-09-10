"""
User-management routes. Included from config/urls.py at
`api/v1/admin/users/`.

    GET    /api/v1/admin/users/                  list + filter        (admin, superadmin)
    POST   /api/v1/admin/users/                  create               (superadmin; admin -> student/teacher)
    GET    /api/v1/admin/users/{id}/             detail               (admin, superadmin)
    PATCH  /api/v1/admin/users/{id}/             update               (superadmin)
    POST   /api/v1/admin/users/{id}/activate/    reactivate           (superadmin)
    POST   /api/v1/admin/users/{id}/deactivate/  deactivate + logout  (superadmin)
    POST   /api/v1/admin/users/{id}/impersonate/ act as user          (superadmin)
"""

from django.urls import path

from apps.accounts.admin_api import (
    AdminUserDetailView,
    AdminUserImpersonateView,
    AdminUserListCreateView,
    AdminUserSetActiveView,
)

app_name = "admin_users"

urlpatterns = [
    path("", AdminUserListCreateView.as_view(), name="list"),
    path("<uuid:id>/", AdminUserDetailView.as_view(), name="detail"),
    path(
        "<uuid:id>/activate/",
        AdminUserSetActiveView.as_view(active=True),
        name="activate",
    ),
    path(
        "<uuid:id>/deactivate/",
        AdminUserSetActiveView.as_view(active=False),
        name="deactivate",
    ),
    path(
        "<uuid:id>/impersonate/", AdminUserImpersonateView.as_view(), name="impersonate"
    ),
]

"""
Admin teacher-verification routes. Included from config/urls.py at
``api/v1/admin/teacher-profiles/``.

    GET  /api/v1/admin/teacher-profiles/                     list + filter   (admin, superadmin)
    GET  /api/v1/admin/teacher-profiles/{id}/                detail          (admin, superadmin)
    POST /api/v1/admin/teacher-profiles/{id}/verification/   set status      (admin, superadmin)

``{id}`` is the Teacher id (matches /admin-portal/teachers/{id}/).
"""

from django.urls import path

from apps.teacher_profile.admin_views import (
    AdminTeacherProfileDetailView,
    AdminTeacherProfileListView,
    AdminTeacherVerificationItemView,
    AdminTeacherVerificationView,
)

app_name = "admin_teacher_profiles"

urlpatterns = [
    path("", AdminTeacherProfileListView.as_view(), name="list"),
    path("<uuid:id>/", AdminTeacherProfileDetailView.as_view(), name="detail"),
    path(
        "<uuid:id>/verification/",
        AdminTeacherVerificationView.as_view(),
        name="verification",
    ),
    path(
        "<uuid:id>/verification-items/<str:key>/",
        AdminTeacherVerificationItemView.as_view(),
        name="verification-item",
    ),
]

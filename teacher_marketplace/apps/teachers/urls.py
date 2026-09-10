"""
URL configuration for the teachers app.

Included from config/urls.py at the `api/v1/teachers/` prefix, so
the full paths resolve to:

    GET/POST/PUT/PATCH /api/v1/teachers/me/
    GET                /api/v1/teachers/
    GET                /api/v1/teachers/{id}/
"""

from django.urls import path

from apps.teachers.views import (
    MyPincodeView,
    TeacherDetailView,
    TeacherListView,
    TeacherProfileView,
)

app_name = "teachers"

urlpatterns = [
    path("me/", TeacherProfileView.as_view(), name="my-profile"),
    path("", TeacherListView.as_view(), name="teacher-list"),
    path("<uuid:id>/", TeacherDetailView.as_view(), name="teacher-detail"),
    path("me/pincode/", MyPincodeView.as_view(), name="my-pincode"),
]

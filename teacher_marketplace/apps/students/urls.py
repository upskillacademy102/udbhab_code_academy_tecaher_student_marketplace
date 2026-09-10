"""
URL configuration for the students app.

Included from config/urls.py at the `api/v1/students/` prefix, so
the full paths resolve to:

    GET/POST/PUT/PATCH /api/v1/students/me/
    GET                /api/v1/students/
    GET                /api/v1/students/{id}/
"""

from django.urls import path

from apps.students.views import StudentDetailView, StudentListView, StudentProfileView

app_name = "students"

urlpatterns = [
    path("me/", StudentProfileView.as_view(), name="my-profile"),
    path("", StudentListView.as_view(), name="student-list"),
    path("<uuid:id>/", StudentDetailView.as_view(), name="student-detail"),
]

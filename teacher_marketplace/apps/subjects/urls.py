"""
URL configuration for the subjects app.

Included from config/urls.py at the `api/v1/subjects/` prefix, so
the full paths resolve to:

    GET/POST                /api/v1/subjects/
    GET/PUT/PATCH/DELETE     /api/v1/subjects/{id}/
"""

from django.urls import path

from apps.subjects.views import SubjectDetailView, SubjectListCreateView

app_name = "subjects"

urlpatterns = [
    path("", SubjectListCreateView.as_view(), name="subject-list-create"),
    path("<uuid:id>/", SubjectDetailView.as_view(), name="subject-detail"),
]

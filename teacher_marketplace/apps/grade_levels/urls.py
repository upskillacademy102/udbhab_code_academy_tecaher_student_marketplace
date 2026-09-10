"""
URL configuration for the grade_levels app.

Included from config/urls.py at the `api/v1/grade-levels/` prefix, so the
full paths resolve to:

    GET/POST                /api/v1/grade-levels/
    GET/PUT/PATCH/DELETE     /api/v1/grade-levels/{id}/
"""

from django.urls import path

from apps.grade_levels.views import GradeLevelDetailView, GradeLevelListCreateView

app_name = "grade_levels"

urlpatterns = [
    path("", GradeLevelListCreateView.as_view(), name="grade-level-list-create"),
    path("<uuid:id>/", GradeLevelDetailView.as_view(), name="grade-level-detail"),
]

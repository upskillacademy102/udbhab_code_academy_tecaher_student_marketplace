"""
URL configuration for the search app.

Included from config/urls.py at the `api/v1/search/` prefix, so
the full path resolves to:

    GET /api/v1/search/teachers/
    GET /api/v1/search/teachers/{teacher_id}/
"""

from django.urls import path

from apps.search.views import PublicTeacherMarketplaceProfileView, TeacherSearchView

app_name = "search"

urlpatterns = [
    path("teachers/", TeacherSearchView.as_view(), name="teacher-search"),
    path(
        "teachers/<uuid:teacher_id>/",
        PublicTeacherMarketplaceProfileView.as_view(),
        name="teacher-marketplace-profile",
    ),
]

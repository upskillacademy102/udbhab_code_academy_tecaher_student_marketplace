"""
URL configuration for the languages app.

Included from config/urls.py at the `api/v1/languages/` prefix, so
the full paths resolve to:

    GET/POST                /api/v1/languages/
    GET/PUT/PATCH/DELETE     /api/v1/languages/{id}/
"""

from django.urls import path

from apps.languages.views import LanguageDetailView, LanguageListCreateView

app_name = "languages"

urlpatterns = [
    path("", LanguageListCreateView.as_view(), name="language-list-create"),
    path("<uuid:id>/", LanguageDetailView.as_view(), name="language-detail"),
]

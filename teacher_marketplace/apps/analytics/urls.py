"""
URL configuration for the analytics app.

Included from config/urls.py at the `api/v1/dashboard/` prefix, so
the full path resolves to:

    GET /api/v1/dashboard/
"""

from django.urls import path

from apps.analytics.views import DashboardView

app_name = "analytics"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
]

from django.urls import path

from apps.web.api_views import PublicStatsView

app_name = "public"

urlpatterns = [
    path("stats/", PublicStatsView.as_view(), name="stats"),
]

"""
URL configuration for the lead_engine app.

Included from config/urls.py at the `api/v1/leads/` prefix, so the
full paths resolve to:

    GET  /api/v1/leads/
    GET  /api/v1/leads/{id}/
    GET  /api/v1/leads/{id}/matches/
    POST /api/v1/leads/unlock/
    GET  /api/v1/leads/unlock-history/

LeadUnlockPricing gets its own separate top-level prefix
(/api/v1/lead-unlock-pricing/) since it's admin-configured
reference data conceptually distinct from a teacher's own leads -
not included under this file's urlpatterns, but exported here as a
second list for config/urls.py to include separately (same pattern
as apps.payments's dual-prefix split).

teacher_best_slots_urlpatterns is a THIRD exported list, mounted at
/api/v1/teachers/{id}/best-slots/ from config/urls.py - this lives
in this app (not apps.teachers) since it depends on
TimeCompatibilityService, owned by lead_engine.
"""

from django.urls import path

from apps.lead_engine.views import (
    LeadDetailView,
    LeadListView,
    LeadMatchDetailView,
    LeadRateView,
    LeadUnlockPricingDetailView,
    LeadUnlockPricingListCreateView,
    MyUnlockHistoryView,
    PendingRatingsView,
    TeacherBestSlotsView,
    UnlockLeadView,
)

app_name = "lead_engine"

urlpatterns = [
    path("", LeadListView.as_view(), name="lead-list"),
    path("unlock/", UnlockLeadView.as_view(), name="unlock-lead"),
    path("unlock-history/", MyUnlockHistoryView.as_view(), name="my-unlock-history"),
    path(
        "pending-ratings/",
        PendingRatingsView.as_view(),
        name="pending-ratings",
    ),
    path("<uuid:id>/matches/", LeadMatchDetailView.as_view(), name="lead-matches"),
    path("<uuid:id>/rate/", LeadRateView.as_view(), name="lead-rate"),
    path("<uuid:id>/", LeadDetailView.as_view(), name="lead-detail"),
]

lead_unlock_pricing_urlpatterns = [
    path("", LeadUnlockPricingListCreateView.as_view(), name="pricing-list-create"),
    path("<uuid:id>/", LeadUnlockPricingDetailView.as_view(), name="pricing-detail"),
]

teacher_best_slots_urlpatterns = [
    path(
        "<uuid:id>/best-slots/",
        TeacherBestSlotsView.as_view(),
        name="teacher-best-slots",
    ),
]

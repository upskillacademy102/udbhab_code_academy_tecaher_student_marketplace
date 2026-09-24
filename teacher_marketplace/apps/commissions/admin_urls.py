"""
Admin-facing URL configuration for the commissions app.

Included from config/urls.py at the `api/v1/admin/payouts/` prefix.
"""

from django.urls import path

from apps.commissions.admin_views import (
    AdminPayoutDecideView,
    AdminPayoutDetailView,
    AdminPayoutListView,
    AdminPayoutMarkPaidView,
)

app_name = "admin_payouts"

urlpatterns = [
    path("", AdminPayoutListView.as_view(), name="list"),
    path("<uuid:id>/", AdminPayoutDetailView.as_view(), name="detail"),
    path("<uuid:id>/decide/", AdminPayoutDecideView.as_view(), name="decide"),
    path("<uuid:id>/mark-paid/", AdminPayoutMarkPaidView.as_view(), name="mark-paid"),
]

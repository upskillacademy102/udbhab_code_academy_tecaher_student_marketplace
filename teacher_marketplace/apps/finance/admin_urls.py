"""
Admin-facing URL configuration for the finance app.

Included from config/urls.py at the `api/v1/admin/finance/` prefix.
"""

from django.urls import path

from apps.finance.admin_views import (
    FinanceDashboardView,
    FinancePricingRequestListCreateView,
    FinanceTransactionLogView,
    LearningPartnerCommissionDetailView,
    LearningPartnerCommissionSummaryView,
    SuperAdminPricingRequestDecideView,
)

app_name = "admin_finance"

urlpatterns = [
    path("dashboard/", FinanceDashboardView.as_view(), name="dashboard"),
    path("transactions/", FinanceTransactionLogView.as_view(), name="transactions"),
    path(
        "pricing-requests/",
        FinancePricingRequestListCreateView.as_view(),
        name="pricing-requests",
    ),
    path(
        "pricing-requests/<uuid:id>/decide/",
        SuperAdminPricingRequestDecideView.as_view(),
        name="pricing-request-decide",
    ),
    path(
        "learning-partners/",
        LearningPartnerCommissionSummaryView.as_view(),
        name="learning-partners",
    ),
    path(
        "learning-partners/<uuid:learning_partner_id>/",
        LearningPartnerCommissionDetailView.as_view(),
        name="learning-partner-detail",
    ),
]

"""URL configuration for the trust app (mounted at /api/v1/verify/)."""

from django.urls import path

from apps.trust.appeal_views import SuspensionAppealView, SuspensionAppealWithdrawView
from apps.trust.safety_views import BlockDetailView, BlockListView, ReportUserView
from apps.trust.views import (
    EmailOTPConfirmView,
    EmailOTPRequestView,
    MobileOTPConfirmView,
    MobileOTPRequestView,
    VerificationStatusView,
)

app_name = "trust"

urlpatterns = [
    path("status/", VerificationStatusView.as_view(), name="verification-status"),
    path("email/request/", EmailOTPRequestView.as_view(), name="otp-email-request"),
    path("email/confirm/", EmailOTPConfirmView.as_view(), name="otp-email-confirm"),
    path("mobile/request/", MobileOTPRequestView.as_view(), name="otp-mobile-request"),
    path("mobile/confirm/", MobileOTPConfirmView.as_view(), name="otp-mobile-confirm"),
]

# Mounted separately at /api/v1/safety/ from config/urls.py (Phase 8d).
safety_urlpatterns = [
    path("report/", ReportUserView.as_view(), name="report-user"),
    path("blocks/", BlockListView.as_view(), name="block-list"),
    path("blocks/<uuid:user_id>/", BlockDetailView.as_view(), name="block-detail"),
]

# Mounted separately at /api/v1/appeals/ from config/urls.py.
appeal_urlpatterns = [
    path("suspension/", SuspensionAppealView.as_view(), name="suspension"),
    path(
        "suspension/withdraw/",
        SuspensionAppealWithdrawView.as_view(),
        name="suspension-withdraw",
    ),
]

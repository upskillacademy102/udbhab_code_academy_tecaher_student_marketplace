"""
URL configuration for the payments app.

This app contributes to TWO separate top-level prefixes, matching
the spec's endpoint list exactly:

    /api/v1/token-packages/    -> token_package_urlpatterns
    /api/v1/payments/           -> payment_urlpatterns

Both pattern lists are exported from this single file and included
separately in config/urls.py, since Django's include() works with
any urlpatterns-like list, not just one per file.

Full resolved paths:
    GET/POST                /api/v1/token-packages/
    GET/PUT/PATCH/DELETE     /api/v1/token-packages/{id}/
    GET                      /api/v1/payments/
    POST                     /api/v1/payments/create-order/
    POST                     /api/v1/payments/verify/
    POST                     /api/v1/payments/webhook/
"""

from django.urls import path

from apps.payments.views import (
    CreateOrderView,
    PaymentHistoryView,
    RazorpayWebhookView,
    TokenPackageDetailView,
    TokenPackageListCreateView,
    VerifyPaymentView,
)

app_name = "payments"

token_package_urlpatterns = [
    path("", TokenPackageListCreateView.as_view(), name="token-package-list-create"),
    path("<uuid:id>/", TokenPackageDetailView.as_view(), name="token-package-detail"),
]

payment_urlpatterns = [
    path("", PaymentHistoryView.as_view(), name="payment-history"),
    path("create-order/", CreateOrderView.as_view(), name="create-order"),
    path("verify/", VerifyPaymentView.as_view(), name="verify-payment"),
    path("webhook/", RazorpayWebhookView.as_view(), name="webhook"),
]

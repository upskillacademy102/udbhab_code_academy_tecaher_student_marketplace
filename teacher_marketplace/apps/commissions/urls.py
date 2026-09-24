"""
LP-facing URL configuration for the commissions app.

Included from config/urls.py at the `api/v1/commissions/` prefix.
"""

from django.urls import path

from apps.commissions.views import (
    MyBankAccountView,
    MyCommissionWalletTransactionsView,
    MyCommissionWalletView,
    MyEarningsView,
    MyPayoutRequestsView,
)

app_name = "commissions"

urlpatterns = [
    path("wallet/", MyCommissionWalletView.as_view(), name="wallet"),
    path(
        "wallet/transactions/",
        MyCommissionWalletTransactionsView.as_view(),
        name="wallet-transactions",
    ),
    path("earnings/", MyEarningsView.as_view(), name="earnings"),
    path("bank-account/", MyBankAccountView.as_view(), name="bank-account"),
    path("payouts/", MyPayoutRequestsView.as_view(), name="payout-list-create"),
]

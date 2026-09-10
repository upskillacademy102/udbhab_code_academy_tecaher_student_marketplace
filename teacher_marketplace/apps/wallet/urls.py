"""
URL configuration for the wallet app.

Included from config/urls.py at the `api/v1/wallet/` prefix, so
the full paths resolve to:

    GET /api/v1/wallet/
    GET /api/v1/wallet/history/
"""

from django.urls import path

from apps.wallet.views import MyWalletView, WalletHistoryView

app_name = "wallet"

urlpatterns = [
    path("", MyWalletView.as_view(), name="my-wallet"),
    path("history/", WalletHistoryView.as_view(), name="wallet-history"),
]

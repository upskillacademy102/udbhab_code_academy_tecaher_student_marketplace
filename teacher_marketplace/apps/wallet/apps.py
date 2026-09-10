"""
App configuration for the wallet app.

This app owns Wallet and WalletTransaction - every Teacher's token
balance and its fully audited transaction history. All balance
mutations go through apps.wallet.services.WalletService; no other
module should modify Wallet.balance directly.
"""

from django.apps import AppConfig


class WalletConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.wallet"
    verbose_name = "Wallet"

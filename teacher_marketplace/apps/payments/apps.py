"""
App configuration for the payments app.

This app owns TokenPackage, Payment, and PaymentWebhook - the
Razorpay integration and payment lifecycle. On successful payment,
apps.payments.services.PaymentService credits the teacher's wallet
via apps.wallet.services.WalletService.
"""

from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
    verbose_name = "Payments"

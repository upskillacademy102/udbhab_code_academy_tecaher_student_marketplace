"""
App configuration for the commissions app.

Owns the Learning Partner commission ledger (Commission), the
Learning Partner's own wallet (LearningPartnerWallet +
LearningPartnerWalletTransaction), their saved bank details
(LearningPartnerBankAccount), and withdrawal requests
(PayoutRequest). Mirrors apps.wallet's role for teachers, one level
up for the partner organisations that referred them.
"""

from django.apps import AppConfig


class CommissionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.commissions"
    verbose_name = "Learning Partner Commissions"

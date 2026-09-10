"""
App configuration for the subscriptions app.

This app owns SubscriptionPlan, TeacherSubscription, and
MonthlyLeadQuota - membership tiers, a teacher's subscription
history, and monthly free-lead usage tracking. Subscribing credits
bonus_tokens via apps.wallet.services.WalletService; paid plans
require a completed apps.payments.Payment to activate (see
apps.subscriptions.views.ActivateSubscriptionView).
"""

from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.subscriptions"
    verbose_name = "Subscriptions"

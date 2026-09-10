"""
App configuration for the analytics app.

This app has no models of its own - it exposes a single role-aware
dashboard API that aggregates data from apps.accounts, apps.payments,
apps.lead_engine, apps.wallet, and apps.subscriptions.
"""

from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analytics"
    verbose_name = "Analytics"

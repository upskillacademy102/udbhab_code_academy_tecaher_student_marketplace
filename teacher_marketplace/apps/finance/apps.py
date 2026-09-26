"""
App configuration for the finance app.

Owns the Finance-department admin surface: the "request a pricing
change" workflow (PricingChangeRequest - Finance requests, Super Admin
approves/applies) plus the read-only aggregation views (dashboard KPIs,
the bank-style transaction log, Learning Partner commission summaries)
that back Finance's restricted panel. Does not own any money-moving
model itself - those stay in apps.payments (Payment) and apps.commissions
(Commission, PayoutRequest); this app only reads and aggregates them,
and mutates TokenPackage/SubscriptionPlan/LeadUnlockPricing pricing
fields on an approved request.
"""

from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finance"
    verbose_name = "Finance Admin"

"""
Seed the three baseline subscription plans (Free / Professional / Elite).

WHY THIS MIGRATION EXISTS
-------------------------
`SubscriptionService.get_effective_plan()` (apps/subscriptions/services.py) is
on the hot path of EVERY lead-generation run: it is called per candidate
teacher from `MatchingService._premium_score()` and again from
`SubscriptionPriorityService.get_priority_rank()` during lead distribution.

If no plan named "Free" exists it raises
``ValidationException("No Free plan is configured. Contact platform support.")``
- which surfaces as an HTTP 400 on `POST /api/v1/student-requirements/` the
moment a single verified teacher matches the requested subject, and as the
long-standing "teacher /dashboard/ returns 400" symptom.

Nothing else in the codebase guarantees these rows exist (no fixture, no
management command, no earlier data migration). The plan NAMES here are load
bearing - they must match ``settings.SUBSCRIPTION_PRIORITY_ORDER``
(``["Elite", "Professional", "Free"]``) exactly, or priority ranking silently
degrades every teacher to "unknown plan -> lowest tier".

The numeric perks (price, free_leads, bonus_tokens, ...) are ordinary
admin-editable configuration - these are conservative starting values, not a
business rule. An admin can change them at any time via the plans admin screen;
this migration only ever *creates* missing rows (get_or_create), it never
overwrites an existing plan an operator has already tuned.
"""

from decimal import Decimal

from django.db import migrations


DEFAULT_PLANS = [
    {
        "name": "Free",
        "monthly_price": Decimal("0.00"),
        "free_leads": 1,
        "priority_rank": 0,
        "is_featured_listing": False,
        "lead_multiplier": Decimal("1.00"),
        "bonus_tokens": 0,
    },
    {
        "name": "Professional",
        "monthly_price": Decimal("799.00"),
        "free_leads": 15,
        "priority_rank": 10,
        "is_featured_listing": True,
        "lead_multiplier": Decimal("1.50"),
        "bonus_tokens": 25,
    },
    {
        "name": "Elite",
        "monthly_price": Decimal("1999.00"),
        "free_leads": 40,
        "priority_rank": 20,
        "is_featured_listing": True,
        "lead_multiplier": Decimal("2.00"),
        "bonus_tokens": 100,
    },
]


def seed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    for spec in DEFAULT_PLANS:
        SubscriptionPlan.objects.get_or_create(
            name=spec["name"],
            defaults={**spec, "status": "active"},
        )


def unseed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    names = [spec["name"] for spec in DEFAULT_PLANS]
    # Only remove plans that were never attached to a subscription, so a
    # reverse migration can't orphan real teacher history.
    SubscriptionPlan.objects.filter(name__in=names, subscriptions__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_plans, unseed_plans),
    ]

"""
Update the Free / Professional / Elite plans to the new lead allowances and
launch pricing (approved 2026-09-09):

    Free          4 free leads/mo,  ₹0
    Professional  8 free leads/mo + a one-time 2-lead-worth sign-up bonus
                  (bonus_tokens, credited to the wallet on subscribe - see
                  SubscriptionService.subscribe), ₹99/mo (was ₹199 - shown
                  struck through via compare_at_price, ~50% off)
    Elite         35 free leads/mo + a one-time 5-lead-worth sign-up bonus,
                  ₹299/mo (was ₹599, ~50% off)

Bonus leads are expressed in tokens using the platform's own baseline lead-
unlock cost (10 tokens - see apps.lead_engine's DEFAULT_PRICING /
get_unlock_token_cost fallback): 2 leads -> 20 tokens, 5 leads -> 50 tokens.
The actual number of leads a teacher can unlock with that wallet credit
still depends on the category of lead they choose to unlock (some
categories cost more than 10 tokens) - this is an entry-level estimate for
the marketing copy, not a literal reserved allocation.

This UPDATEs the rows 0002_seed_default_plans created (get_or_create there
never touches them again) - it does not touch a plan's name, priority_rank,
is_featured_listing, or lead_multiplier, none of which changed here.
"""

from decimal import Decimal

from django.db import migrations

TOKENS_PER_BONUS_LEAD = 10

PLAN_UPDATES = {
    "Free": {
        "monthly_price": Decimal("0.00"),
        "compare_at_price": None,
        "free_leads": 4,
        "bonus_tokens": 0,
    },
    "Professional": {
        "monthly_price": Decimal("99.00"),
        "compare_at_price": Decimal("199.00"),
        "free_leads": 8,
        "bonus_tokens": 2 * TOKENS_PER_BONUS_LEAD,
    },
    "Elite": {
        "monthly_price": Decimal("299.00"),
        "compare_at_price": Decimal("599.00"),
        "free_leads": 35,
        "bonus_tokens": 5 * TOKENS_PER_BONUS_LEAD,
    },
}


def apply_pricing(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    for name, values in PLAN_UPDATES.items():
        SubscriptionPlan.objects.filter(name=name).update(**values)


def revert_pricing(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    previous = {
        "Free": {"monthly_price": Decimal("0.00"), "free_leads": 1, "bonus_tokens": 0},
        "Professional": {
            "monthly_price": Decimal("799.00"),
            "free_leads": 15,
            "bonus_tokens": 25,
        },
        "Elite": {
            "monthly_price": Decimal("1999.00"),
            "free_leads": 40,
            "bonus_tokens": 100,
        },
    }
    for name, values in previous.items():
        SubscriptionPlan.objects.filter(name=name).update(
            compare_at_price=None, **values
        )


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0004_subscriptionplan_compare_at_price_and_more"),
    ]

    operations = [
        migrations.RunPython(apply_pricing, revert_pricing),
    ]

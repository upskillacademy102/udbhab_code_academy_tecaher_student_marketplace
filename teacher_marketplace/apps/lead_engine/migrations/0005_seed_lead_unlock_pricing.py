"""
Seed the admin-configurable lead-unlock token pricing table.

The spec's "Token Pricing" section says an admin configures a token cost per
pricing tier. Until a row exists, `get_unlock_token_cost()` silently falls back
to a hard-coded 10 tokens for every tier (and logs a warning on every unlock),
so School Tuition and Corporate Training cost the same - which defeats the
point of having tiers.

These are conservative starting prices, not a business rule: an admin edits
them via the lead-pricing admin screen. This migration only creates missing
rows; it never overwrites a tier an operator has already priced.
"""

from django.db import migrations

DEFAULT_PRICING = [
    {"tier": "school_tuition", "token_cost": 10},
    {"tier": "higher_secondary", "token_cost": 15},
    {"tier": "competitive_exams", "token_cost": 25},
    {"tier": "corporate_training", "token_cost": 30},
]


def seed_pricing(apps, schema_editor):
    LeadUnlockPricing = apps.get_model("lead_engine", "LeadUnlockPricing")
    for spec in DEFAULT_PRICING:
        LeadUnlockPricing.objects.get_or_create(
            tier=spec["tier"],
            defaults={"token_cost": spec["token_cost"], "is_active": True},
        )


def unseed_pricing(apps, schema_editor):
    LeadUnlockPricing = apps.get_model("lead_engine", "LeadUnlockPricing")
    tiers = [spec["tier"] for spec in DEFAULT_PRICING]
    LeadUnlockPricing.objects.filter(tier__in=tiers).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("lead_engine", "0004_leadmatchscore"),
    ]

    operations = [
        migrations.RunPython(seed_pricing, unseed_pricing),
    ]

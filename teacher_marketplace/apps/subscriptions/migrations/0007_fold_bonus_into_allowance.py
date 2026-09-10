"""
Fold the signup bonus into the recurring monthly allowance
(approved 2026-09-09).

    Free          4 unlocks / cycle,  Rs.   0
    Professional  10 unlocks / cycle, Rs.  99  (was 8 + a one-time 2-lead bonus)
    Elite         40 unlocks / cycle, Rs. 299  (was 35 + a one-time 5-lead bonus)

0005 expressed the "+2" and "+5" as bonus_tokens - a ONE-TIME wallet
credit granted on subscribe, whose real purchasing power then varied with
the per-tier price of whichever leads the teacher chose to unlock. Under
the allowance model every lead costs exactly one unlock, so those bonuses
become plain, predictable, RECURRING allowance instead: 8+2 = 10 and
35+5 = 40, every cycle rather than once.

bonus_tokens drops to 0 on every plan. SubscriptionService.subscribe
already skips the wallet credit while TOKEN_SYSTEM_ENABLED is False, so
this is belt-and-braces: it also stops a re-enable of the token system
silently resurrecting a signup bonus that has since been priced into the
allowance.

Monthly prices are unchanged. Note the cycle is now a rolling 30 days
(settings.LEAD_UNLOCK_CYCLE_DAYS), not a calendar month - see
subscriptions/0006 for the period re-keying that goes with this.
"""

from django.db import migrations

PLAN_UPDATES = {
    "Free": {"free_leads": 4, "bonus_tokens": 0},
    "Professional": {"free_leads": 10, "bonus_tokens": 0},
    "Elite": {"free_leads": 40, "bonus_tokens": 0},
}

# What 0005 left behind, for a clean reverse.
PREVIOUS = {
    "Free": {"free_leads": 4, "bonus_tokens": 0},
    "Professional": {"free_leads": 8, "bonus_tokens": 20},
    "Elite": {"free_leads": 35, "bonus_tokens": 50},
}


def apply_allowances(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    for name, values in PLAN_UPDATES.items():
        SubscriptionPlan.objects.filter(name=name).update(**values)


def revert_allowances(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    for name, values in PREVIOUS.items():
        SubscriptionPlan.objects.filter(name=name).update(**values)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0006_period_keyed_lead_allowance"),
    ]

    operations = [
        migrations.RunPython(apply_allowances, revert_allowances),
    ]

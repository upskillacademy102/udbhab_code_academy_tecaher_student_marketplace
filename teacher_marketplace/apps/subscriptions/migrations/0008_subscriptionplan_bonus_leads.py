"""
Record how each plan's allowance is composed, so the pricing page can
advertise the bonus instead of only showing a flat total.

    Free          4  = 4 + 0
    Professional  10 = 8  + 2 bonus
    Elite         40 = 35 + 5 bonus

bonus_leads is DISPLAY ONLY and is already counted inside free_leads.
free_leads stays the single number LeadQuotaService spends against - adding
bonus_leads on top anywhere would grant the bonus twice. A CHECK constraint
enforces bonus_leads <= free_leads so the two cannot drift into nonsense.
"""

import django.core.validators
from django.db import migrations, models

BONUS_LEADS = {"Free": 0, "Professional": 2, "Elite": 5}


def set_bonus_split(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    for name, bonus in BONUS_LEADS.items():
        SubscriptionPlan.objects.filter(name=name).update(bonus_leads=bonus)


def clear_bonus_split(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    SubscriptionPlan.objects.update(bonus_leads=0)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0007_fold_bonus_into_allowance"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionplan",
            name="bonus_leads",
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    "How many of free_leads are advertised as a bonus, e.g. "
                    "Professional is '8 + 2 bonus' = 10. Display only - it is "
                    "already counted inside free_leads and must never be added "
                    "on top, or the teacher would be granted the bonus twice."
                ),
                validators=[django.core.validators.MaxValueValidator(100000)],
                verbose_name="bonus unlocks per cycle",
            ),
        ),
        migrations.AlterField(
            model_name="subscriptionplan",
            name="free_leads",
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    "TOTAL contact unlocks this plan grants per 30-day cycle - "
                    "base plus bonus. This is the single number the unlock "
                    "workflow spends against; bonus_leads only records how it "
                    "is composed for display."
                ),
                validators=[django.core.validators.MaxValueValidator(100000)],
                verbose_name="unlock allowance per cycle",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="subscriptionplan",
            name="subscription_plan_sane_ranges",
        ),
        migrations.AddConstraint(
            model_name="subscriptionplan",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(monthly_price__gte=0)
                    & models.Q(monthly_price__lte=1000000)
                    & models.Q(free_leads__lte=100000)
                    & models.Q(bonus_leads__lte=models.F("free_leads"))
                    & models.Q(priority_rank__lte=1000)
                    & models.Q(lead_multiplier__gte=0)
                    & models.Q(lead_multiplier__lte=10)
                    & models.Q(bonus_tokens__lte=1000000)
                ),
                name="subscription_plan_sane_ranges",
            ),
        ),
        migrations.RunPython(set_bonus_split, clear_bonus_split),
    ]

"""
Re-key MonthlyLeadQuota from a calendar month to a rolling entitlement
period (approved 2026-09-09).

The allowance window is now ``settings.LEAD_UNLOCK_CYCLE_DAYS`` (30) days
anchored to the teacher's active subscription start_date, replacing the
first-of-the-calendar-month ``month`` DateField. Billing and allowance
then share one clock; a calendar month is 28-31 days, so keeping the two
separate would drift them apart by roughly five days a year.

Existing quota rows are DELETED rather than back-filled. They are a pure
usage cache keyed on an anchor that no longer exists, so any value we
invented for period_start would be a guess; LeadQuotaService recreates
the row lazily on the teacher's next unlock or dashboard load. No
purchased balance is touched - top-ups live in the Wallet, not here.
"""

import django.utils.timezone
from django.db import migrations, models


def drop_stale_quota_rows(apps, schema_editor):
    """Usage rows keyed on the old calendar-month anchor cannot be re-anchored."""
    apps.get_model("subscriptions", "MonthlyLeadQuota").objects.all().delete()


def noop_reverse(apps, schema_editor):
    """Nothing to restore - the rows we dropped were regenerable cache."""


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0005_update_plan_pricing_2026_launch"),
    ]

    operations = [
        migrations.RunPython(drop_stale_quota_rows, noop_reverse),
        migrations.RemoveConstraint(
            model_name="monthlyleadquota",
            name="unique_quota_per_teacher_per_month",
        ),
        migrations.RemoveField(
            model_name="monthlyleadquota",
            name="month",
        ),
        migrations.AddField(
            model_name="monthlyleadquota",
            name="period_start",
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                help_text=(
                    "When this entitlement period opened. Anchored to the "
                    "teacher's active subscription start_date so billing and "
                    "allowance share one clock."
                ),
                verbose_name="period start",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="monthlyleadquota",
            name="period_end",
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                help_text=(
                    "When this period closes and the allowance resets. "
                    "period_start + LEAD_UNLOCK_CYCLE_DAYS."
                ),
                verbose_name="period end",
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="monthlyleadquota",
            name="total_free_leads",
            field=models.PositiveIntegerField(
                help_text=(
                    "Snapshot of the teacher's plan.free_leads for this period. "
                    "Raised in place on a mid-period upgrade (usage carries "
                    "forward); only a new period resets usage to zero."
                ),
                verbose_name="allowance this period",
            ),
        ),
        migrations.AlterField(
            model_name="monthlyleadquota",
            name="used_free_leads",
            field=models.PositiveIntegerField(
                default=0, verbose_name="allowance used"
            ),
        ),
        migrations.AlterModelOptions(
            name="monthlyleadquota",
            options={
                "ordering": ["-period_start"],
                "verbose_name": "Lead Unlock Allowance",
                "verbose_name_plural": "Lead Unlock Allowances",
            },
        ),
        migrations.AddIndex(
            model_name="monthlyleadquota",
            index=models.Index(
                fields=["teacher", "period_end"],
                name="sub_quota_teacher_period_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="monthlyleadquota",
            constraint=models.UniqueConstraint(
                fields=("teacher", "period_start"),
                name="unique_quota_per_teacher_per_period",
            ),
        ),
        migrations.AddConstraint(
            model_name="monthlyleadquota",
            constraint=models.CheckConstraint(
                check=models.Q(period_end__gt=models.F("period_start")),
                name="quota_period_ends_after_it_starts",
            ),
        ),
    ]

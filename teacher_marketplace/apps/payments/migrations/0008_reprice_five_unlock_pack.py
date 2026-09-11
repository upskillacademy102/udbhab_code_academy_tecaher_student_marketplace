"""
Reprice the 5-unlock pack to Rs. 60 inclusive (was Rs. 49).

Advertised prices are GST-INCLUSIVE, so TokenPackage.price stores the
back-computed base and final_price (base + 18% GST) is what reaches Razorpay:

    5 extra unlocks   base 50.85 + 9.15 GST = Rs. 60.00  (Rs. 12.00 each)

Unlike Rs. 49, Rs. 60 lands exactly on a two-decimal base: 50.85 * 1.18 is
60.0030, which quantizes to 60.00. No rounding fudge needed.

WHY THE INCREASE MATTERS BEYOND THE NUMBER
0007 set the pack at Rs. 9.80 an unlock, which undercut Elite's Rs. 8.31
marginal rate far enough that a teacher wanting only volume could beat the
subscription on price. At Rs. 12.00 an unlock the pack sits above Elite's
marginal rate again, so top-ups stay an overflow valve rather than a cheaper
substitute for upgrading. That ordering is the whole reason the single unlock
is dearer per unit than the pack.

This also corrects 0007's closing claim that top-ups are gated to paid plans.
settings.TOPUP_ELIGIBLE_PLANS has included Free since it was written: every
plan may BUY capacity, and the subscription sells PRIORITY instead — a Free
teacher holding twenty top-ups still sits at priority_rank 0 and sees leads
after every paid teacher in LeadDistributionService's cascade.
"""

from decimal import Decimal

from django.db import migrations

PACK_NAME = "5 extra unlocks"
OLD_BASE = Decimal("41.52")  # Rs. 48.99 inclusive
NEW_BASE = Decimal("50.85")  # Rs. 60.00 inclusive


def reprice(apps, schema_editor):
    TokenPackage = apps.get_model("payments", "TokenPackage")
    # Only touch a pack still sitting at the old price. An admin who has
    # already changed it through /super-admin/token-packages/ has made a
    # deliberate decision this migration must not silently overwrite.
    TokenPackage.objects.filter(name=PACK_NAME, price=OLD_BASE).update(price=NEW_BASE)


def unreprice(apps, schema_editor):
    TokenPackage = apps.get_model("payments", "TokenPackage")
    TokenPackage.objects.filter(name=PACK_NAME, price=NEW_BASE).update(price=OLD_BASE)


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0007_seed_extra_unlock_packs"),
    ]

    operations = [
        migrations.RunPython(reprice, unreprice),
    ]

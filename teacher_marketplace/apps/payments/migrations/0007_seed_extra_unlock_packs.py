"""
Seed the two extra-unlock packs sold under the allowance model
(approved 2026-09-09).

Advertised prices are GST-INCLUSIVE, so TokenPackage.price stores the
back-computed base and TokenPackage.final_price (base + 18% GST) is what
reaches Razorpay:

    1 extra unlock    base 12.71 + 2.29 GST = Rs. 15.00   (Rs. 15.00 each)
    5 extra unlocks   base 41.52 + 7.47 GST = Rs. 48.99   (Rs.  9.80 each)

Rs. 49.00 EXACTLY IS NOT REACHABLE at 18% on a two-decimal base: 41.53
resolves to 49.01 and 41.52 to 48.99, with nothing in between. We take
48.99 and advertise "Rs. 49" - charging a paisa under the advertised
price never draws a complaint, charging one over does.

Why the single costs more per unlock than the pack (Rs. 15.00 vs Rs. 9.80):
that ordering is the point. Elite's marginal rate is Rs. 8.31 per unlock
(Rs. 299 for 36 beyond the Free tier's 4), so both packs stay dearer than
simply upgrading, and a teacher who consistently needs more than ~30
unlocks a cycle is pushed to Elite rather than accumulating top-ups.
Top-ups are an overflow valve, never a substitute for the subscription -
which is also why apps.payments.views gates them to paid plans.

These rows are inert while TOKEN_SYSTEM_ENABLED is True; that mode sells
the original token packages instead, and an admin would re-seed those.
"""

from decimal import Decimal

from django.db import migrations

# name -> (unlocks, GST-exclusive base price, advertised inclusive price)
PACKS = {
    "1 extra unlock": (1, Decimal("12.71"), "15"),
    "5 extra unlocks": (5, Decimal("41.52"), "49"),
}


def seed_packs(apps, schema_editor):
    TokenPackage = apps.get_model("payments", "TokenPackage")
    for sort_order, (name, (unlocks, base_price, _advertised)) in enumerate(
        PACKS.items()
    ):
        TokenPackage.objects.get_or_create(
            name=name,
            defaults={
                "token_count": unlocks,
                "price": base_price,
                "gst_percentage": Decimal("18.00"),
                "discount_percentage": Decimal("0.00"),
                "is_active": True,
                "sort_order": sort_order,
            },
        )


def unseed_packs(apps, schema_editor):
    TokenPackage = apps.get_model("payments", "TokenPackage")
    # Only remove packs that were never bought - a TokenPackage behind a
    # Payment is PROTECTed and must survive for the historical order.
    TokenPackage.objects.filter(name__in=PACKS.keys(), payments__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0006_paymentdispute_wallet_hold_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_packs, unseed_packs),
    ]

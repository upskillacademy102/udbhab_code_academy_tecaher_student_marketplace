"""
Data-quality hardening for the admin commerce endpoints
`/api/v1/subscriptions/plans/` and `/api/v1/lead-unlock-pricing/`.

SubscriptionPlan: `name` -> taxonomy validator + not-blank CHECK; `monthly_price`
0..1,000,000; `free_leads` <= 100,000; `priority_rank` <= 1,000; `lead_multiplier`
0..10; `bonus_tokens` <= 1,000,000 - all via one `subscription_plan_sane_ranges`
DB CHECK. LeadUnlockPricing: `token_cost` 1..100,000 + DB CHECK.

Run: python manage.py test apps.subscriptions.tests.test_plan_validation \
     --settings=config.settings.test
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_named_admin, make_user
from apps.lead_engine.models import LeadUnlockPricing, PricingTier
from apps.subscriptions.models import SubscriptionPlan


class SubscriptionPlanValidationTests(APITestCase):
    def setUp(self):
        # Writing subscription plans is Finance-department only (apps.
        # accounts.api_permissions.DEPARTMENT_ROUTE_SCOPE).
        login(self.client, make_named_admin(department="Finance"))

    def _post(self, expect=201, **fields):
        body = {"name": "Base Plan", "monthly_price": "0.00", "free_leads": 5, **fields}
        r = self.client.post("/api/v1/subscriptions/plans/", body, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_valid(self):
        self._post(
            name="Gold Tier",
            monthly_price="999.00",
            free_leads=30,
            priority_rank=5,
            lead_multiplier="2.00",
            bonus_tokens=50,
        )

    def test_name_hygiene(self):
        self._post(400, name="99999")
        self._post(400, name="  ")
        self._post(400, name="bad <x>")

    def test_numeric_bounds(self):
        self._post(400, name="B1", monthly_price="9999999.00")
        self._post(400, name="B2", monthly_price="-1")
        self._post(400, name="B3", free_leads=200000)
        self._post(400, name="B4", priority_rank=99999)
        self._post(400, name="B5", lead_multiplier="50.00")
        self._post(400, name="B6", bonus_tokens=5_000_000)

    def test_db_check(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SubscriptionPlan.objects.create(
                name="X", monthly_price=Decimal("1"), free_leads=999999
            )

    def test_compare_at_price_above_monthly_price_is_accepted(self):
        r = self._post(
            name="Discounted Tier",
            monthly_price="99.00",
            compare_at_price="199.00",
        )
        self.assertEqual(r.json()["data"]["discount_percent"], 50)

    def test_compare_at_price_not_higher_than_monthly_price_is_rejected(self):
        self._post(
            400, name="Bad Discount 1", monthly_price="99.00", compare_at_price="99.00"
        )
        self._post(
            400, name="Bad Discount 2", monthly_price="99.00", compare_at_price="50.00"
        )

    def test_compare_at_price_db_check(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SubscriptionPlan.objects.create(
                name="Y",
                monthly_price=Decimal("99.00"),
                compare_at_price=Decimal("99.00"),
                free_leads=5,
            )


class LaunchPricingTests(APITestCase):
    """
    Locks in the Free / Professional / Elite unlock allowances and pricing
    approved 2026-09-09 (apps/subscriptions/migrations/
    0007_fold_bonus_into_allowance.py) so a future migration or admin edit
    can't silently drift from what was actually approved.

    The "+2" and "+5" that 0005 expressed as one-time bonus_tokens are now
    folded into the recurring allowance (8+2 = 10, 35+5 = 40), so
    bonus_tokens must be zero on every plan - a non-zero value would mean a
    signup bonus had been resurrected on top of an allowance that already
    prices it in.
    """

    def test_free_plan(self):
        p = SubscriptionPlan.objects.get(name="Free")
        self.assertEqual(p.free_leads, 4)
        self.assertEqual(p.monthly_price, Decimal("0.00"))
        self.assertIsNone(p.compare_at_price)
        self.assertEqual(p.bonus_tokens, 0)

    def test_professional_plan(self):
        p = SubscriptionPlan.objects.get(name="Professional")
        self.assertEqual(p.free_leads, 10)  # 8 + the 2 former bonus leads
        self.assertEqual(p.monthly_price, Decimal("99.00"))
        self.assertEqual(p.compare_at_price, Decimal("199.00"))
        self.assertEqual(p.discount_percent, 50)
        self.assertEqual(p.bonus_tokens, 0)

    def test_elite_plan(self):
        p = SubscriptionPlan.objects.get(name="Elite")
        self.assertEqual(p.free_leads, 40)  # 35 + the 5 former bonus leads
        self.assertEqual(p.monthly_price, Decimal("299.00"))
        self.assertEqual(p.compare_at_price, Decimal("599.00"))
        self.assertEqual(p.discount_percent, 50)
        self.assertEqual(p.bonus_tokens, 0)

    def test_plans_are_visible_with_the_new_pricing_via_the_api(self):
        login(self.client, make_user(role=UserRole.TEACHER))
        r = self.client.get("/api/v1/subscriptions/plans/")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()["data"]
        rows = data["results"] if isinstance(data, dict) else data
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["Professional"]["monthly_price"], "99.00")
        self.assertEqual(by_name["Professional"]["compare_at_price"], "199.00")
        self.assertEqual(by_name["Professional"]["discount_percent"], 50)
        self.assertEqual(by_name["Elite"]["monthly_price"], "299.00")
        self.assertEqual(by_name["Elite"]["compare_at_price"], "599.00")
        self.assertEqual(by_name["Elite"]["discount_percent"], 50)


class LeadUnlockPricingValidationTests(APITestCase):
    def setUp(self):
        # Writing lead-unlock pricing is Finance-department only (apps.
        # accounts.api_permissions.DEPARTMENT_ROUTE_SCOPE).
        login(self.client, make_named_admin(department="Finance"))
        # every tier is seeded - work by editing an existing row
        self.row = LeadUnlockPricing.objects.get(tier=PricingTier.SCHOOL_TUITION)

    def test_valid_edit(self):
        r = self.client.patch(
            f"/api/v1/lead-unlock-pricing/{self.row.id}/",
            {"token_cost": 25},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)

    def test_out_of_range_rejected(self):
        for bad in (0, 200000):
            r = self.client.patch(
                f"/api/v1/lead-unlock-pricing/{self.row.id}/",
                {"token_cost": bad},
                format="json",
            )
            self.assertEqual(r.status_code, 400, r.content)

    def test_db_check(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            LeadUnlockPricing.objects.filter(pk=self.row.pk).update(token_cost=999999)

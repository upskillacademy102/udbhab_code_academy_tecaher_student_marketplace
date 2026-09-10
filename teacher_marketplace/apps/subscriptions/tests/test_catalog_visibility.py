"""
Regression: deactivated commercial-catalog rows (token packages / subscription
plans / lead-unlock pricing) vanished from the ADMIN management list, because the
list endpoints hard-filtered to active rows for everyone. An admin who
deactivated an item then had no way to see, edit, or re-activate it in the UI.

Fix: the list is role-aware — Admin / Super Admin get every row; teachers (the
buyers) still get active rows only.

Run: python manage.py test apps.subscriptions.tests.test_catalog_visibility \
     --settings=config.settings.test
"""

from decimal import Decimal

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.lead_engine.models import LeadUnlockPricing, PricingTier
from apps.payments.models import TokenPackage
from apps.subscriptions.models import PlanStatus, SubscriptionPlan
from apps.teachers.models import Teacher


class AdminCatalogVisibilityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pkg_on = TokenPackage.objects.create(
            name="Live Pack", token_count=100, price=Decimal("499")
        )
        cls.pkg_off = TokenPackage.objects.create(
            name="Retired Pack", token_count=50, price=Decimal("299"), is_active=False
        )

        cls.plan_off = SubscriptionPlan.objects.create(
            name="Legacy Plan",
            monthly_price=Decimal("1"),
            free_leads=1,
            status=PlanStatus.INACTIVE,
        )
        # a seeded active plan already exists ("Free")
        cls.plan_on = SubscriptionPlan.objects.get(name="Free")

        cls.price_on = LeadUnlockPricing.objects.get(tier=PricingTier.SCHOOL_TUITION)
        cls.price_on.is_active = True
        cls.price_on.save(update_fields=["is_active"])
        cls.price_off = (
            LeadUnlockPricing.objects.filter(is_active=True)
            .exclude(pk=cls.price_on.pk)
            .first()
        )
        cls.price_off.is_active = False
        cls.price_off.save(update_fields=["is_active"])

    def _ids(self, resp):
        data = resp.json()["data"]
        rows = data["results"] if isinstance(data, dict) else data
        return {r["id"] for r in rows}

    def _as_teacher(self):
        u = make_user(role=UserRole.TEACHER)
        Teacher.objects.create(user=u)
        login(self.client, u)

    def _as_admin(self):
        login(self.client, make_user(role=UserRole.ADMIN))

    # ---- token packages ---------------------------------------------
    def test_teacher_sees_only_active_token_packages(self):
        self._as_teacher()
        ids = self._ids(self.client.get("/api/v1/token-packages/", {"page_size": 100}))
        self.assertIn(str(self.pkg_on.id), ids)
        self.assertNotIn(str(self.pkg_off.id), ids)

    def test_admin_sees_deactivated_token_packages(self):
        self._as_admin()
        ids = self._ids(self.client.get("/api/v1/token-packages/", {"page_size": 100}))
        self.assertIn(str(self.pkg_on.id), ids)
        self.assertIn(str(self.pkg_off.id), ids)

    # ---- subscription plans ----------------------------------------
    def test_teacher_sees_only_active_plans(self):
        self._as_teacher()
        ids = self._ids(
            self.client.get("/api/v1/subscriptions/plans/", {"page_size": 100})
        )
        self.assertIn(str(self.plan_on.id), ids)
        self.assertNotIn(str(self.plan_off.id), ids)

    def test_admin_sees_inactive_plans(self):
        self._as_admin()
        ids = self._ids(
            self.client.get("/api/v1/subscriptions/plans/", {"page_size": 100})
        )
        self.assertIn(str(self.plan_off.id), ids)

    # ---- lead unlock pricing -------------------------------------
    def test_teacher_sees_only_active_pricing(self):
        self._as_teacher()
        ids = self._ids(
            self.client.get("/api/v1/lead-unlock-pricing/", {"page_size": 100})
        )
        self.assertIn(str(self.price_on.id), ids)
        self.assertNotIn(str(self.price_off.id), ids)

    def test_admin_sees_deactivated_pricing(self):
        self._as_admin()
        ids = self._ids(
            self.client.get("/api/v1/lead-unlock-pricing/", {"page_size": 100})
        )
        self.assertIn(str(self.price_off.id), ids)


class AdminResourceSearchTests(APITestCase):
    """
    Regression: the admin resource pages wire a search box to `?search=`, but
    Token Packages / Subscription Plans / Lead Pricing / Subject & Language
    Aliases / Pincode Locations had no `SearchFilter`, so the param was silently
    ignored and the list never filtered.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.gis.geos import Point

        from apps.languages.models import Language
        from apps.matching.models import LanguageAlias, PincodeLocation, SubjectAlias
        from apps.subjects.models import Subject

        TokenPackage.objects.create(
            name="Alpha Bundle", token_count=10, price=Decimal("99")
        )
        TokenPackage.objects.create(
            name="Omega Bundle", token_count=20, price=Decimal("199")
        )
        SubscriptionPlan.objects.create(
            name="Zeta Tier", monthly_price=Decimal("9"), free_leads=9
        )

        subj = Subject.objects.create(name="Astronomy")
        lang = Language.objects.create(name="Sanskrit", code="sa")
        SubjectAlias.objects.create(subject=subj, alias_text="starstuff")
        LanguageAlias.objects.create(language=lang, alias_text="samskrutam")
        PincodeLocation.objects.create(
            pincode="AB1234", location=Point(88.0, 22.0, srid=4326), city="Testville"
        )

    def setUp(self):
        login(self.client, make_user(role=UserRole.ADMIN))

    def _count(self, path, **params):
        data = self.client.get(path, params).json()["data"]
        rows = data["results"] if isinstance(data, dict) else data
        return len(rows)

    def test_search_filters_each_admin_resource(self):
        # A matching term returns the row; a nonsense term returns nothing -
        # proves the filter is actually applied regardless of how many rows exist.
        cases = [
            ("/api/v1/token-packages/", "Omega"),
            ("/api/v1/subscriptions/plans/", "Zeta"),
            ("/api/v1/lead-unlock-pricing/", "school"),
            ("/api/v1/matching/subject-aliases/", "starstuff"),
            ("/api/v1/matching/language-aliases/", "samskrutam"),
            ("/api/v1/matching/pincode-locations/", "Testville"),
        ]
        for path, term in cases:
            total = self._count(path, page_size=100)
            self.assertGreaterEqual(total, 1, f"{path} has no rows to test")
            self.assertGreaterEqual(
                self._count(path, search=term, page_size=100),
                1,
                f"{path} search '{term}' found nothing",
            )
            self.assertEqual(
                self._count(path, search="zzz_no_such_row_zzz", page_size=100),
                0,
                f"{path} ignored the search param (nonsense term still returned rows)",
            )

    def test_teacher_facing_search_also_works(self):
        # token-packages / plans are teacher-visible too; search must still apply.
        u = make_user(role=UserRole.TEACHER)
        Teacher.objects.create(user=u)
        self.client.post("/api/v1/auth/logout/", {}, format="json")
        login(self.client, u)
        self.assertEqual(self._count("/api/v1/token-packages/", search="Omega"), 1)

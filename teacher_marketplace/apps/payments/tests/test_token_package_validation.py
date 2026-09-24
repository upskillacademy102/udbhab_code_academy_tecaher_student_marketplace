"""
Data-quality hardening for `/api/v1/token-packages/` (admin write).

`name` -> `validate_taxonomy_name` + not-blank DB CHECK; `token_count` 1..1,000,000;
`price` 0..1,000,000; `gst_percentage` / `discount_percentage` 0..100;
`sort_order` <= 100,000 - all with a single `token_package_sane_ranges` DB CHECK.

Run: python manage.py test apps.payments.tests.test_token_package_validation \
     --settings=config.settings.test
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from apps.payments.models import TokenPackage
from apps.accounts.tests.helpers import login, make_named_admin

EP = "/api/v1/token-packages/"


class TokenPackageValidationTests(APITestCase):
    def setUp(self):
        # Writing token packages is Finance-department only (apps.accounts.
        # api_permissions.DEPARTMENT_ROUTE_SCOPE).
        login(self.client, make_named_admin(department="Finance"))

    def _post(self, expect=201, **fields):
        body = {"name": "Base Pack", "token_count": 100, "price": "499.00", **fields}
        r = self.client.post(EP, body, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_valid(self):
        self._post(
            name="Starter Pack",
            token_count=100,
            price="499.00",
            gst_percentage="18.00",
            discount_percentage="10.00",
            sort_order=1,
        )

    def test_name_hygiene(self):
        self._post(400, name="12345")
        self._post(400, name="  ")
        self._post(400, name="bad <x>")

    def test_numeric_bounds(self):
        self._post(400, name="P1", token_count=0)
        self._post(400, name="P2", token_count=2_000_000)
        self._post(400, name="P3", price="5000000.00")
        self._post(400, name="P4", price="-1")
        self._post(400, name="P5", gst_percentage="150")
        self._post(400, name="P6", discount_percentage="200")
        self._post(400, name="P7", sort_order=999999)

    def test_db_check_blocks_bad_row(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TokenPackage.objects.create(
                name="X",
                token_count=5,
                price=Decimal("1"),
                gst_percentage=Decimal("500"),
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            TokenPackage.objects.create(name="   ", token_count=5, price=Decimal("1"))

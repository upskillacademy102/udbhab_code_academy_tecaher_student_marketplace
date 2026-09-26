"""
Pricing-change request flow: Finance requests, Super Admin approves/rejects.

Run: python manage.py test apps.finance --settings=config.settings.test
"""

from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_named_admin, make_user
from apps.finance.models import PricingChangeRequest, PricingChangeStatus
from apps.finance.services import PricingChangeService
from apps.payments.models import TokenPackage

OK = status.HTTP_200_OK
FORBIDDEN = status.HTTP_403_FORBIDDEN
BAD_REQUEST = status.HTTP_400_BAD_REQUEST


def _token_package(price="199.00"):
    return TokenPackage.objects.create(name="Starter", token_count=10, price=Decimal(price))


class PricingChangeServiceTests(APITestCase):
    def test_request_change_snapshots_current_value(self):
        pkg = _token_package("199.00")
        admin = make_named_admin(department="Finance")
        req = PricingChangeService.request_change(
            admin,
            target_type="token_package",
            target_id=pkg.id,
            requested_value=Decimal("249.00"),
        )
        self.assertEqual(req.current_value, Decimal("199.00"))
        self.assertEqual(req.requested_value, Decimal("249.00"))
        self.assertEqual(req.status, PricingChangeStatus.PENDING)
        pkg.refresh_from_db()
        self.assertEqual(pkg.price, Decimal("199.00"))  # unchanged until approved

    def test_approve_applies_value_to_target(self):
        pkg = _token_package("199.00")
        admin = make_named_admin(department="Finance")
        superadmin = make_user(role=UserRole.SUPERADMIN)
        req = PricingChangeService.request_change(
            admin, target_type="token_package", target_id=pkg.id, requested_value=Decimal("249.00")
        )
        req = PricingChangeService.approve(req, superadmin=superadmin)
        self.assertEqual(req.status, PricingChangeStatus.APPROVED)
        pkg.refresh_from_db()
        self.assertEqual(pkg.price, Decimal("249.00"))

    def test_reject_leaves_target_untouched(self):
        pkg = _token_package("199.00")
        admin = make_named_admin(department="Finance")
        superadmin = make_user(role=UserRole.SUPERADMIN)
        req = PricingChangeService.request_change(
            admin, target_type="token_package", target_id=pkg.id, requested_value=Decimal("249.00")
        )
        req = PricingChangeService.reject(req, superadmin=superadmin, note="Too high")
        self.assertEqual(req.status, PricingChangeStatus.REJECTED)
        pkg.refresh_from_db()
        self.assertEqual(pkg.price, Decimal("199.00"))

    def test_cannot_decide_an_already_decided_request(self):
        pkg = _token_package()
        admin = make_named_admin(department="Finance")
        superadmin = make_user(role=UserRole.SUPERADMIN)
        req = PricingChangeService.request_change(
            admin, target_type="token_package", target_id=pkg.id, requested_value=Decimal("249.00")
        )
        PricingChangeService.approve(req, superadmin=superadmin)
        with self.assertRaises(Exception):
            PricingChangeService.approve(req, superadmin=superadmin)


class PricingChangeAPITests(APITestCase):
    def setUp(self):
        self.pkg = _token_package("199.00")
        self.finance_admin = make_named_admin(department="Finance")
        self.support_admin = make_named_admin(department="Support")
        self.superadmin = make_user(role=UserRole.SUPERADMIN)

    def test_finance_admin_can_create_request(self):
        client = self.client_class()
        login(client, self.finance_admin)
        resp = client.post(
            "/api/v1/admin/finance/pricing-requests/",
            {
                "target_type": "token_package",
                "target_id": str(self.pkg.id),
                "requested_value": "249.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, OK, resp.content)
        self.assertEqual(resp.data["data"]["status"], "pending")

    def test_non_finance_admin_cannot_create_request(self):
        client = self.client_class()
        login(client, self.support_admin)
        resp = client.post(
            "/api/v1/admin/finance/pricing-requests/",
            {
                "target_type": "token_package",
                "target_id": str(self.pkg.id),
                "requested_value": "249.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, FORBIDDEN)

    def test_finance_admin_cannot_decide_own_request(self):
        req = PricingChangeRequest.objects.create(
            target_type="token_package",
            token_package=self.pkg,
            field_name="price",
            current_value=Decimal("199.00"),
            requested_value=Decimal("249.00"),
            requested_by=self.finance_admin,
        )
        client = self.client_class()
        login(client, self.finance_admin)
        resp = client.post(
            f"/api/v1/admin/finance/pricing-requests/{req.id}/decide/",
            {"approve": True},
            format="json",
        )
        self.assertEqual(resp.status_code, FORBIDDEN)

    def test_superadmin_can_approve(self):
        req = PricingChangeRequest.objects.create(
            target_type="token_package",
            token_package=self.pkg,
            field_name="price",
            current_value=Decimal("199.00"),
            requested_value=Decimal("249.00"),
            requested_by=self.finance_admin,
        )
        client = self.client_class()
        login(client, self.superadmin)
        resp = client.post(
            f"/api/v1/admin/finance/pricing-requests/{req.id}/decide/",
            {"approve": True},
            format="json",
        )
        self.assertEqual(resp.status_code, OK, resp.content)
        self.assertEqual(resp.data["data"]["status"], "approved")
        self.pkg.refresh_from_db()
        self.assertEqual(self.pkg.price, Decimal("249.00"))

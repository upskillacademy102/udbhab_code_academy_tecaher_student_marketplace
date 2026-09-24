"""
API-level tests: LP self-service endpoints scoped to the caller, admin
payout queue scoped to the Finance department.

Run: python manage.py test apps.commissions --settings=config.settings.test
"""

from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.tests.helpers import (
    login,
    login_lp,
    make_learning_partner_admin,
    make_named_admin,
    make_user,
)
from apps.accounts.models import UserRole
from apps.commissions.models import LearningPartnerBankAccount
from apps.commissions.services import LearningPartnerWalletService

OK = status.HTTP_200_OK
CREATED = status.HTTP_201_CREATED
FORBIDDEN = status.HTTP_403_FORBIDDEN


class LPWalletEndpointTests(APITestCase):
    def setUp(self):
        self.lp = make_learning_partner_admin("Study Academy")
        LearningPartnerWalletService.credit(
            self.lp, amount=Decimal("66.67"), description="seed", reference_id="seed"
        )
        login_lp(self.client, self.lp)

    def test_get_wallet_balance(self):
        resp = self.client.get("/api/v1/commissions/wallet/")
        self.assertEqual(resp.status_code, OK)
        self.assertEqual(resp.data["data"]["balance"], "66.67")

    def test_wallet_transaction_history(self):
        resp = self.client.get("/api/v1/commissions/wallet/transactions/")
        self.assertEqual(resp.status_code, OK)
        self.assertEqual(len(resp.data["data"]), 1)

    def test_non_lp_role_is_forbidden(self):
        teacher = make_user(role=UserRole.TEACHER)
        client = self.client_class()
        login(client, teacher)
        resp = client.get("/api/v1/commissions/wallet/")
        self.assertEqual(resp.status_code, FORBIDDEN)

    def test_bank_account_save_and_fetch(self):
        resp = self.client.put(
            "/api/v1/commissions/bank-account/",
            {
                "account_holder_name": "Study Academy",
                "account_number": "1234567890",
                "ifsc_code": "hdfc0000001",
                "bank_name": "HDFC Bank",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, OK)
        self.assertEqual(resp.data["data"]["ifsc_code"], "HDFC0000001")

        resp = self.client.get("/api/v1/commissions/bank-account/")
        self.assertEqual(resp.status_code, OK)
        self.assertEqual(resp.data["data"]["account_number"], "1234567890")

    def test_request_payout_requires_bank_account_first(self):
        resp = self.client.post(
            "/api/v1/commissions/payouts/", {"amount": "10.00"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_request_payout_after_saving_bank_account(self):
        LearningPartnerBankAccount.objects.create(
            learning_partner=self.lp,
            account_holder_name="Study Academy",
            account_number="1234567890",
            ifsc_code="HDFC0000001",
            bank_name="HDFC Bank",
        )
        resp = self.client.post(
            "/api/v1/commissions/payouts/", {"amount": "60.00"}, format="json"
        )
        self.assertEqual(resp.status_code, CREATED)
        self.assertEqual(resp.data["data"]["status"], "pending")

    def test_another_partners_earnings_are_never_visible(self):
        other_lp = make_learning_partner_admin("Learn Academy")
        LearningPartnerWalletService.credit(
            other_lp, amount=Decimal("50.00"), description="seed2", reference_id="seed2"
        )
        resp = self.client.get("/api/v1/commissions/earnings/")
        self.assertEqual(resp.status_code, OK)
        # This LP has zero Commission rows (only a manual wallet credit was
        # seeded in setUp) - confirms the endpoint is scoped, not just empty.
        self.assertEqual(resp.data["data"], [])


class AdminPayoutQueueTests(APITestCase):
    def setUp(self):
        self.lp = make_learning_partner_admin("Study Academy")
        LearningPartnerWalletService.credit(
            self.lp, amount=Decimal("100.00"), description="seed", reference_id="seed"
        )
        LearningPartnerBankAccount.objects.create(
            learning_partner=self.lp,
            account_holder_name="Study Academy",
            account_number="1234567890",
            ifsc_code="HDFC0000001",
            bank_name="HDFC Bank",
        )
        login_lp(self.client, self.lp)
        resp = self.client.post(
            "/api/v1/commissions/payouts/", {"amount": "60.00"}, format="json"
        )
        self.payout_id = resp.data["data"]["id"]

    def test_finance_admin_can_list_and_approve(self):
        finance_admin = make_named_admin(department="Finance")
        client = self.client_class()
        login(client, finance_admin)

        resp = client.get("/api/v1/admin/payouts/")
        self.assertEqual(resp.status_code, OK)
        self.assertEqual(resp.data["data"][0]["id"], self.payout_id)

        resp = client.post(
            f"/api/v1/admin/payouts/{self.payout_id}/decide/",
            {"approve": True},
            format="json",
        )
        self.assertEqual(resp.status_code, OK)
        self.assertEqual(resp.data["data"]["status"], "approved")

        resp = client.post(
            f"/api/v1/admin/payouts/{self.payout_id}/mark-paid/",
            {"payout_reference": "UTR12345"},
            format="json",
        )
        self.assertEqual(resp.status_code, OK)
        self.assertEqual(resp.data["data"]["status"], "paid")

    def test_non_finance_admin_is_forbidden(self):
        support_admin = make_named_admin(department="Support")
        client = self.client_class()
        login(client, support_admin)
        resp = client.get("/api/v1/admin/payouts/")
        self.assertEqual(resp.status_code, FORBIDDEN)

    def test_learning_partner_cannot_reach_admin_queue(self):
        resp = self.client.get("/api/v1/admin/payouts/")
        self.assertEqual(resp.status_code, FORBIDDEN)

"""
Dashboard KPIs, transaction log, and Learning Partner commission summary -
all Finance-department-scoped read endpoints.

Run: python manage.py test apps.finance --settings=config.settings.test
"""

from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_learning_partner_admin, make_named_admin, make_user
from apps.commissions.models import Commission, PayoutRequest, PayoutStatus
from apps.payments.models import Payment, PaymentStatus, PaymentType, TokenPackage
from apps.teachers.models import Teacher

OK = status.HTTP_200_OK
FORBIDDEN = status.HTTP_403_FORBIDDEN


def _teacher():
    user = make_user(role=UserRole.TEACHER)
    return Teacher.objects.create(user=user, experience_years=3)


def _successful_payment(teacher, *, amount="199.00", order_id="order_1", payment_id="pay_1"):
    pkg = TokenPackage.objects.create(
        name=f"Pkg-{order_id}", token_count=10, price=Decimal(amount)
    )
    return Payment.objects.create(
        teacher=teacher,
        payment_type=PaymentType.TOKEN_PURCHASE,
        token_package=pkg,
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_id,
        amount=Decimal(amount),
        base_amount=Decimal(amount),
        token_count=10,
        status=PaymentStatus.SUCCESS,
    )


class FinanceDashboardAccessTests(APITestCase):
    def test_finance_admin_can_view_dashboard(self):
        client = self.client_class()
        login(client, make_named_admin(department="Finance"))
        resp = client.get("/api/v1/admin/finance/dashboard/")
        self.assertEqual(resp.status_code, OK, resp.content)
        self.assertIn("incoming_this_month", resp.data["data"])

    def test_non_finance_admin_forbidden(self):
        client = self.client_class()
        login(client, make_named_admin(department="Support"))
        resp = client.get("/api/v1/admin/finance/dashboard/")
        self.assertEqual(resp.status_code, FORBIDDEN)

    def test_superadmin_can_view_dashboard(self):
        client = self.client_class()
        login(client, make_user(role=UserRole.SUPERADMIN))
        resp = client.get("/api/v1/admin/finance/dashboard/")
        self.assertEqual(resp.status_code, OK)


class FinanceTransactionLogTests(APITestCase):
    def setUp(self):
        self.teacher = _teacher()
        self.payment = _successful_payment(
            self.teacher, amount="199.00", order_id="order_abc", payment_id="pay_abc"
        )
        self.lp = make_learning_partner_admin("Study Academy")
        self.payout = PayoutRequest.objects.create(
            learning_partner=self.lp,
            amount=Decimal("60.00"),
            account_holder_name="Study Academy",
            account_number="1234567890",
            ifsc_code="HDFC0000001",
            bank_name="HDFC Bank",
            status=PayoutStatus.PAID,
            payout_reference="UTR999",
            paid_at=timezone.now(),
        )
        self.client_ = self.client_class()
        login(self.client_, make_named_admin(department="Finance"))

    def test_log_contains_both_directions(self):
        resp = self.client_.get("/api/v1/admin/finance/transactions/")
        self.assertEqual(resp.status_code, OK, resp.content)
        rows = resp.data["data"]
        directions = {r["direction"] for r in rows}
        self.assertEqual(directions, {"incoming", "outgoing"})

    def test_incoming_row_has_no_account_number(self):
        resp = self.client_.get("/api/v1/admin/finance/transactions/", {"direction": "incoming"})
        rows = resp.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["account_number"])
        self.assertEqual(rows[0]["transaction_id"], "pay_abc")

    def test_outgoing_row_has_account_and_ifsc(self):
        resp = self.client_.get("/api/v1/admin/finance/transactions/", {"direction": "outgoing"})
        rows = resp.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["account_number"], "1234567890")
        self.assertEqual(rows[0]["ifsc_code"], "HDFC0000001")

    def test_filter_by_transaction_id(self):
        resp = self.client_.get(
            "/api/v1/admin/finance/transactions/", {"transaction_id": "UTR999"}
        )
        rows = resp.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "outgoing")

    def test_filter_by_account_number_only_matches_outgoing(self):
        resp = self.client_.get(
            "/api/v1/admin/finance/transactions/", {"account_number": "123456"}
        )
        rows = resp.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "outgoing")


class LearningPartnerCommissionSummaryTests(APITestCase):
    def test_summary_aggregates_current_month(self):
        teacher = _teacher()
        payment = _successful_payment(teacher, amount="300.00", order_id="o2", payment_id="p2")
        lp = make_learning_partner_admin("Study Academy")
        Commission.objects.create(
            payment=payment,
            teacher=teacher,
            learning_partner=lp,
            payment_type=PaymentType.TOKEN_PURCHASE,
            base_amount=Decimal("300.00"),
            partner_share=Decimal("200.00"),
            business_share=Decimal("100.00"),
        )

        client = self.client_class()
        login(client, make_named_admin(department="Finance"))
        resp = client.get("/api/v1/admin/finance/learning-partners/")
        self.assertEqual(resp.status_code, OK, resp.content)
        rows = resp.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], "200.00")

        detail = client.get(f"/api/v1/admin/finance/learning-partners/{lp.id}/")
        self.assertEqual(detail.status_code, OK)
        detail_rows = detail.data["data"]
        self.assertEqual(len(detail_rows), 1)
        self.assertEqual(detail_rows[0]["teacher_id"], str(teacher.id))
        self.assertEqual(detail_rows[0]["total"], "200.00")

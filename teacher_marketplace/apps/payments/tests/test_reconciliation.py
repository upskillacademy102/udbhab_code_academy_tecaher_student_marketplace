"""
Phase 7f - daily payment-ledger reconciliation.

Run: python manage.py test apps.payments.tests.test_reconciliation --settings=config.settings.test
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_user
from apps.payments.models import Payment, PaymentStatus, PaymentType, TokenPackage
from apps.payments.reconciliation import ReconciliationService
from apps.payments.services import PaymentService
from apps.payments.tasks import reconcile_payments
from apps.teachers.models import Teacher
from apps.trust.models import ManualReviewItem, ManualReviewKind
from apps.wallet.models import TransactionType, WalletTransaction
from apps.wallet.services import WalletService


class ReconciliationTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        self.pkg = TokenPackage.objects.create(
            name="Recon", token_count=100, price=Decimal("499.00")
        )
        WalletService.get_or_create_wallet(self.teacher)

    def _payment(self, *, order, status=PaymentStatus.PENDING):
        return Payment.objects.create(
            teacher=self.teacher,
            payment_type=PaymentType.TOKEN_PURCHASE,
            token_package=self.pkg,
            razorpay_order_id=order,
            amount=self.pkg.final_price,
            token_count=self.pkg.token_count,
            status=status,
        )

    def _wide_run(self):
        now = timezone.now()
        return ReconciliationService.run(
            window_start=now - timedelta(days=2),
            window_end=now + timedelta(minutes=1),
        )

    def test_clean_ledger_reconciles(self):
        p = self._payment(order="rec_ok")
        PaymentService._mark_payment_successful(p)  # credits the wallet properly
        run = self._wide_run()
        self.assertTrue(run.ok)
        self.assertEqual(run.discrepancies, 0)
        self.assertGreaterEqual(run.payments_checked, 1)

    def test_success_payment_without_credit_is_drift(self):
        # Mark SUCCESS directly, bypassing the crediting path.
        p = self._payment(order="rec_nocredit")
        Payment.objects.filter(pk=p.pk).update(status=PaymentStatus.SUCCESS)
        run = self._wide_run()
        self.assertFalse(run.ok)
        self.assertEqual(run.discrepancies, 1)
        self.assertEqual(
            run.detail["discrepancies"][0]["issue"],
            "success_payment_without_wallet_credit",
        )
        self.assertTrue(
            ManualReviewItem.objects.filter(
                kind=ManualReviewKind.RECONCILIATION
            ).exists()
        )

    def test_credit_for_non_success_payment_is_drift(self):
        p = self._payment(order="rec_ghost", status=PaymentStatus.PENDING)
        wallet = WalletService.get_or_create_wallet(self.teacher)
        wallet.balance = 100
        wallet.save(update_fields=["balance"])
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=TransactionType.CREDIT,
            amount=100,
            balance_after=100,
            reference_id=str(p.id),
            description="ghost credit",
        )
        run = self._wide_run()
        self.assertFalse(run.ok)
        self.assertEqual(
            run.detail["discrepancies"][0]["issue"],
            "wallet_credit_for_non_success_payment",
        )

    def test_task_runs_and_returns_summary(self):
        p = self._payment(order="rec_task")
        PaymentService._mark_payment_successful(p)
        result = reconcile_payments()
        self.assertIn("run_id", result)
        self.assertTrue(result["ok"])

    def test_window_advances_between_runs(self):
        p1 = self._payment(order="rec_w1")
        PaymentService._mark_payment_successful(p1)
        run1 = self._wide_run()
        # Second run with no explicit start picks up where run1 ended.
        run2 = ReconciliationService.run()
        self.assertGreaterEqual(run2.window_start, run1.window_end)
        self.assertEqual(run2.payments_checked, 0)

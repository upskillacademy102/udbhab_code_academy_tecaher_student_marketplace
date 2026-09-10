"""
Regression: confirming a successful token purchase was wired to
`NotificationService.notify(..., context={...})` - same broken signature as the
subscription bug. Because it ran inside `_mark_payment_successful`'s
`transaction.atomic()`, the `TypeError` rolled back the payment-success state AND
the wallet credit: the teacher paid, Razorpay confirmed, and the tokens vanished.

Fix credits the wallet first, then sends the notification best-effort.

Run: python manage.py test apps.payments --settings=config.settings.test
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_user
from apps.notifications.models import Notification, NotificationEvent
from apps.payments.models import Payment, PaymentStatus, PaymentType, TokenPackage
from apps.payments.services import PaymentService
from apps.teachers.models import Teacher
from apps.wallet.services import WalletService


class TokenPurchaseSuccessTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        self.pkg = TokenPackage.objects.create(
            name="Starter", token_count=100, price=Decimal("499.00")
        )
        self.payment = Payment.objects.create(
            teacher=self.teacher,
            payment_type=PaymentType.TOKEN_PURCHASE,
            token_package=self.pkg,
            razorpay_order_id="order_test_1",
            amount=self.pkg.final_price,
            token_count=self.pkg.token_count,
            status=PaymentStatus.PENDING,
        )

    def test_marking_successful_credits_wallet_and_notifies(self):
        PaymentService._mark_payment_successful(self.payment)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(WalletService.get_balance(self.teacher), 100)
        self.assertTrue(
            Notification.objects.filter(
                user=self.teacher.user, event=NotificationEvent.PAYMENT_SUCCESS
            ).exists()
        )

    def test_wallet_credit_survives_a_broken_notification(self):
        with patch(
            "apps.notifications.services.NotificationService.payment_success",
            side_effect=RuntimeError("smtp exploded"),
        ):
            PaymentService._mark_payment_successful(self.payment)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(
            WalletService.get_balance(self.teacher), 100
        )  # NOT rolled back

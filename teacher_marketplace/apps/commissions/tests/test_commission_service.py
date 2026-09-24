"""
Split math, isolation between partners, idempotency, and reversal.

Run: python manage.py test apps.commissions --settings=config.settings.test
"""

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_learning_partner_admin, make_user
from apps.commissions.models import Commission, CommissionStatus
from apps.commissions.services import CommissionService, LearningPartnerWalletService
from apps.payments.disputes import DisputeService
from apps.payments.models import DisputeKind, Payment, PaymentStatus, PaymentType, TokenPackage
from apps.payments.services import PaymentService
from apps.subscriptions.models import PlanStatus, SubscriptionPlan
from apps.teachers.models import Teacher


def _teacher(learning_partner=None):
    user = make_user(role=UserRole.TEACHER, learning_partner=learning_partner)
    return Teacher.objects.create(user=user)


def _token_payment(teacher, *, price="100.00", order):
    pkg = TokenPackage.objects.create(
        name=f"Pack {order}", token_count=10, price=Decimal(price)
    )
    return Payment.objects.create(
        teacher=teacher,
        payment_type=PaymentType.TOKEN_PURCHASE,
        token_package=pkg,
        razorpay_order_id=order,
        amount=pkg.final_price,
        base_amount=pkg.discounted_price,
        token_count=pkg.token_count,
        status=PaymentStatus.PENDING,
    )


def _subscription_payment(teacher, *, price="100.00", order):
    plan = SubscriptionPlan.objects.create(
        name=f"Plan {order}", monthly_price=Decimal(price), status=PlanStatus.ACTIVE
    )
    return Payment.objects.create(
        teacher=teacher,
        payment_type=PaymentType.SUBSCRIPTION,
        subscription_plan=plan,
        razorpay_order_id=order,
        amount=plan.monthly_price,
        base_amount=plan.monthly_price,
        status=PaymentStatus.PENDING,
    )


class SplitMathTests(TestCase):
    def test_token_purchase_with_partner_excludes_gst_from_partner_share(self):
        lp = make_learning_partner_admin("Study Academy")
        teacher = _teacher(learning_partner=lp)
        payment = _token_payment(teacher, price="100.00", order="order_1")

        commission = CommissionService.credit_for_payment(payment)

        # price=100, 0% discount -> discounted_price=100.00 (base), 18% GST -> final=118.00
        self.assertEqual(commission.base_amount, Decimal("100.00"))
        self.assertEqual(payment.amount, Decimal("118.00"))
        self.assertEqual(commission.partner_share, Decimal("66.67"))  # round(100 * 2/3, 2)
        self.assertEqual(commission.business_share, Decimal("51.33"))  # 118.00 - 66.67
        self.assertEqual(
            commission.partner_share + commission.business_share, payment.amount
        )
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("66.67"))

    def test_subscription_has_no_gst_so_base_is_the_full_price(self):
        lp = make_learning_partner_admin("Study Academy")
        teacher = _teacher(learning_partner=lp)
        payment = _subscription_payment(teacher, price="100.00", order="order_sub_1")

        commission = CommissionService.credit_for_payment(payment)

        self.assertEqual(commission.base_amount, Decimal("100.00"))
        self.assertEqual(commission.partner_share, Decimal("66.67"))
        self.assertEqual(commission.business_share, Decimal("33.33"))
        self.assertEqual(
            commission.partner_share + commission.business_share, payment.amount
        )

    def test_teacher_without_partner_gives_business_everything(self):
        teacher = _teacher(learning_partner=None)
        payment = _token_payment(teacher, price="100.00", order="order_2")

        commission = CommissionService.credit_for_payment(payment)

        self.assertIsNone(commission.learning_partner)
        self.assertEqual(commission.partner_share, Decimal("0.00"))
        self.assertEqual(commission.business_share, payment.amount)

    def test_split_divides_evenly_with_no_rounding_leftover(self):
        lp = make_learning_partner_admin("Even Split Academy")
        teacher = _teacher(learning_partner=lp)
        # price=150, 0% discount -> base=150.00 (divides evenly by 3)
        payment = _token_payment(teacher, price="150.00", order="order_3")

        commission = CommissionService.credit_for_payment(payment)

        self.assertEqual(commission.partner_share, Decimal("100.00"))
        self.assertEqual(commission.business_share, Decimal("77.00"))  # 177.00 - 100.00


class PartnerIsolationTests(TestCase):
    """The exact scenario from the request: Raju/Study Academy, Shyam/Learn
    Academy, Ram/no partner - commissions never cross-credit."""

    def test_two_partners_and_an_unaffiliated_teacher_never_cross_credit(self):
        study_academy = make_learning_partner_admin("Study Academy")
        learn_academy = make_learning_partner_admin("Learn Academy")

        raju = _teacher(learning_partner=study_academy)
        shyam = _teacher(learning_partner=learn_academy)
        ram = _teacher(learning_partner=None)

        raju_payment = _token_payment(raju, price="150.00", order="raju_1")
        shyam_payment = _token_payment(shyam, price="150.00", order="shyam_1")
        ram_payment = _token_payment(ram, price="150.00", order="ram_1")

        CommissionService.credit_for_payment(raju_payment)
        CommissionService.credit_for_payment(shyam_payment)
        CommissionService.credit_for_payment(ram_payment)

        self.assertEqual(LearningPartnerWalletService.get_balance(study_academy), Decimal("100.00"))
        self.assertEqual(LearningPartnerWalletService.get_balance(learn_academy), Decimal("100.00"))
        # Ram's purchase must not have leaked into either partner's wallet.
        self.assertEqual(
            Commission.objects.filter(learning_partner=study_academy).count(), 1
        )
        self.assertEqual(
            Commission.objects.filter(learning_partner=learn_academy).count(), 1
        )
        ram_commission = Commission.objects.get(payment=ram_payment)
        self.assertIsNone(ram_commission.learning_partner)
        self.assertEqual(ram_commission.business_share, ram_payment.amount)


class IdempotencyTests(TestCase):
    def test_crediting_twice_only_credits_once(self):
        lp = make_learning_partner_admin("Study Academy")
        teacher = _teacher(learning_partner=lp)
        payment = _token_payment(teacher, price="150.00", order="order_4")

        first = CommissionService.credit_for_payment(payment)
        second = CommissionService.credit_for_payment(payment)

        self.assertEqual(first.id, second.id)
        self.assertEqual(Commission.objects.filter(payment=payment).count(), 1)
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("100.00"))

    def test_mark_payment_successful_via_payment_service_credits_commission(self):
        """End-to-end through the real hook point, not the service directly."""
        lp = make_learning_partner_admin("Study Academy")
        teacher = _teacher(learning_partner=lp)
        payment = _token_payment(teacher, price="150.00", order="order_5")

        PaymentService._mark_payment_successful(payment)
        PaymentService._mark_payment_successful(payment)  # webhook retry

        self.assertEqual(Commission.objects.filter(payment=payment).count(), 1)
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("100.00"))


class ReversalTests(TestCase):
    def _paid(self, price="150.00", order="rev_1"):
        lp = make_learning_partner_admin("Study Academy")
        teacher = _teacher(learning_partner=lp)
        payment = _token_payment(teacher, price=price, order=order)
        PaymentService._mark_payment_successful(payment)
        payment.refresh_from_db()
        return lp, payment

    def test_refund_reverses_commission(self):
        lp, payment = self._paid()
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("100.00"))

        DisputeService.open(
            payment=payment,
            kind=DisputeKind.REFUND,
            external_ref="refund_1",
            amount=payment.amount,
        )

        commission = Commission.objects.get(payment=payment)
        self.assertEqual(commission.status, CommissionStatus.REVERSED)
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("0.00"))

    def test_chargeback_lost_reverses_commission_but_open_does_not(self):
        lp, payment = self._paid(order="rev_2")

        dispute = DisputeService.open(
            payment=payment,
            kind=DisputeKind.CHARGEBACK,
            external_ref="dispute_1",
            amount=payment.amount,
        )
        # Still open - must NOT have reversed anything yet.
        commission = Commission.objects.get(payment=payment)
        self.assertEqual(commission.status, CommissionStatus.ACTIVE)
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("100.00"))

        DisputeService.resolve(dispute, won=False)

        commission.refresh_from_db()
        self.assertEqual(commission.status, CommissionStatus.REVERSED)
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("0.00"))

    def test_chargeback_won_does_not_reverse_commission(self):
        lp, payment = self._paid(order="rev_3")

        dispute = DisputeService.open(
            payment=payment,
            kind=DisputeKind.CHARGEBACK,
            external_ref="dispute_2",
            amount=payment.amount,
        )
        DisputeService.resolve(dispute, won=True)

        commission = Commission.objects.get(payment=payment)
        self.assertEqual(commission.status, CommissionStatus.ACTIVE)
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("100.00"))

    def test_reversal_can_take_balance_negative_after_payout(self):
        from apps.commissions.models import LearningPartnerBankAccount
        from apps.commissions.services import PayoutService

        lp, payment = self._paid(order="rev_4")
        LearningPartnerBankAccount.objects.create(
            learning_partner=lp,
            account_holder_name="Study Academy",
            account_number="1234567890",
            ifsc_code="HDFC0000001",
            bank_name="HDFC Bank",
        )
        payout = PayoutService.request_payout(lp, amount=Decimal("100.00"))
        PayoutService.decide(payout, admin=None, approve=True)
        PayoutService.mark_paid(payout, admin=None, payout_reference="UTR123")
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("0.00"))

        DisputeService.open(
            payment=payment,
            kind=DisputeKind.REFUND,
            external_ref="refund_after_payout",
            amount=payment.amount,
        )
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("-100.00"))

"""
Payout request lifecycle: request -> decide -> mark_paid.

Run: python manage.py test apps.commissions --settings=config.settings.test
"""

from decimal import Decimal

from django.test import TestCase

from apps.accounts.tests.helpers import make_learning_partner_admin, make_named_admin
from apps.commissions.models import LearningPartnerBankAccount, PayoutStatus
from apps.commissions.services import (
    InsufficientCommissionBalanceError,
    LearningPartnerWalletService,
    PayoutService,
)
from apps.core.exceptions.custom_exceptions import ValidationException


def _with_balance(amount="100.00", name="Study Academy"):
    lp = make_learning_partner_admin(name)
    LearningPartnerWalletService.credit(
        lp, amount=Decimal(amount), description="seed", reference_id="seed"
    )
    LearningPartnerBankAccount.objects.create(
        learning_partner=lp,
        account_holder_name=name,
        account_number="1234567890",
        ifsc_code="HDFC0000001",
        bank_name="HDFC Bank",
    )
    return lp


class RequestPayoutTests(TestCase):
    def test_requires_saved_bank_account(self):
        lp = make_learning_partner_admin("No Bank Academy")
        LearningPartnerWalletService.credit(
            lp, amount=Decimal("50.00"), description="seed", reference_id="seed"
        )
        with self.assertRaises(ValidationException):
            PayoutService.request_payout(lp, amount=Decimal("10.00"))

    def test_cannot_request_more_than_available_balance(self):
        lp = _with_balance("100.00")
        with self.assertRaises(InsufficientCommissionBalanceError):
            PayoutService.request_payout(lp, amount=Decimal("150.00"))

    def test_cannot_double_spend_across_two_pending_requests(self):
        lp = _with_balance("100.00")
        PayoutService.request_payout(lp, amount=Decimal("70.00"))
        with self.assertRaises(InsufficientCommissionBalanceError):
            PayoutService.request_payout(lp, amount=Decimal("40.00"))

    def test_available_balance_reflects_pending_reservation(self):
        lp = _with_balance("100.00")
        PayoutService.request_payout(lp, amount=Decimal("60.00"))
        self.assertEqual(
            LearningPartnerWalletService.available_balance(lp), Decimal("40.00")
        )
        # Raw balance is untouched until mark_paid.
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("100.00"))


class DecideAndMarkPaidTests(TestCase):
    def test_full_lifecycle(self):
        lp = _with_balance("100.00")
        admin = make_named_admin(department="Finance")
        payout = PayoutService.request_payout(lp, amount=Decimal("60.00"))

        payout = PayoutService.decide(payout, admin=admin, approve=True)
        self.assertEqual(payout.status, PayoutStatus.APPROVED)

        payout = PayoutService.mark_paid(payout, admin=admin, payout_reference="UTR999")
        self.assertEqual(payout.status, PayoutStatus.PAID)
        self.assertEqual(payout.payout_reference, "UTR999")
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("40.00"))

    def test_cannot_mark_paid_without_approval(self):
        lp = _with_balance("100.00")
        admin = make_named_admin(department="Finance")
        payout = PayoutService.request_payout(lp, amount=Decimal("60.00"))
        with self.assertRaises(ValidationException):
            PayoutService.mark_paid(payout, admin=admin, payout_reference="UTR1")

    def test_rejecting_frees_up_available_balance_again(self):
        lp = _with_balance("100.00")
        admin = make_named_admin(department="Finance")
        payout = PayoutService.request_payout(lp, amount=Decimal("60.00"))
        PayoutService.decide(payout, admin=admin, approve=False)

        self.assertEqual(
            LearningPartnerWalletService.available_balance(lp), Decimal("100.00")
        )
        self.assertEqual(LearningPartnerWalletService.get_balance(lp), Decimal("100.00"))

    def test_cannot_decide_twice(self):
        lp = _with_balance("100.00")
        admin = make_named_admin(department="Finance")
        payout = PayoutService.request_payout(lp, amount=Decimal("60.00"))
        PayoutService.decide(payout, admin=admin, approve=True)
        with self.assertRaises(ValidationException):
            PayoutService.decide(payout, admin=admin, approve=True)

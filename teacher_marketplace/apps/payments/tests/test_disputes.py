"""
Phase 7d - chargeback / dispute / refund handling + wallet holds.

Run: python manage.py test apps.payments.tests.test_disputes --settings=config.settings.test
"""

import hashlib
import hmac
import json
from decimal import Decimal

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_user
from apps.payments.models import (
    DisputeKind,
    DisputeStatus,
    Payment,
    PaymentDispute,
    PaymentStatus,
    PaymentType,
    TokenPackage,
)
from apps.teachers.models import Teacher
from apps.trust.models import (
    ManualReviewItem,
    ManualReviewKind,
    RiskSignal,
    RiskSignalKind,
)
from apps.wallet.models import WalletHold
from apps.wallet.services import InsufficientBalanceError, WalletService

WEBHOOK_URL = "/api/v1/payments/webhook/"


def _sign(raw: bytes) -> str:
    return hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(), raw, hashlib.sha256
    ).hexdigest()


class _Mixin:
    def _paid_payment(
        self, *, tokens=100, price="499.00", order="order_d1", pay_id="pay_d1"
    ):
        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        pkg = TokenPackage.objects.create(
            name=f"P {order}", token_count=tokens, price=Decimal(price)
        )
        payment = Payment.objects.create(
            teacher=teacher,
            payment_type=PaymentType.TOKEN_PURCHASE,
            token_package=pkg,
            razorpay_order_id=order,
            razorpay_payment_id=pay_id,
            amount=pkg.final_price,
            token_count=tokens,
            status=PaymentStatus.SUCCESS,
        )
        WalletService.get_or_create_wallet(teacher)
        WalletService.credit(
            teacher=teacher,
            amount=tokens,
            description="seed",
            reference_id=str(payment.id),
        )
        return teacher, payment


class WalletHoldTests(_Mixin, TestCase):
    def test_hold_reduces_spendable_but_not_balance(self):
        teacher, _p = self._paid_payment(tokens=100)
        WalletService.place_hold(teacher, 40, "test hold")
        self.assertEqual(WalletService.get_balance(teacher), 100)
        self.assertEqual(WalletService.available_balance(teacher), 60)
        self.assertTrue(WalletService.has_sufficient_balance(teacher, 60))
        self.assertFalse(WalletService.has_sufficient_balance(teacher, 61))

    def test_debit_cannot_touch_held_tokens(self):
        teacher, _p = self._paid_payment(tokens=100)
        WalletService.place_hold(teacher, 70, "test hold")
        WalletService.debit(teacher=teacher, amount=30, description="ok")
        with self.assertRaises(InsufficientBalanceError):
            WalletService.debit(teacher=teacher, amount=1, description="blocked")
        self.assertEqual(WalletService.get_balance(teacher), 70)

    def test_place_hold_clamped_to_balance(self):
        teacher, _p = self._paid_payment(tokens=50)
        hold = WalletService.place_hold(teacher, 200, "too big")
        self.assertEqual(hold.amount, 50)
        self.assertIn("only 50", hold.reason)

    def test_release_hold_restores_spendable(self):
        teacher, _p = self._paid_payment(tokens=100)
        hold = WalletService.place_hold(teacher, 40, "h")
        WalletService.release_hold(hold, resolution="won")
        self.assertEqual(WalletService.available_balance(teacher), 100)
        hold.refresh_from_db()
        self.assertFalse(hold.active)

    def test_settle_hold_as_debit_claws_back(self):
        teacher, _p = self._paid_payment(tokens=100)
        hold = WalletService.place_hold(teacher, 40, "h")
        WalletService.settle_hold_as_debit(hold, description="chargeback upheld")
        self.assertEqual(WalletService.get_balance(teacher), 60)
        self.assertEqual(WalletService.available_balance(teacher), 60)

    def test_spend_then_dispute_only_freezes_and_claws_what_is_left(self):
        # Realistic chargeback: teacher already spent most of the tokens
        # before the dispute arrives - the hold can only cover the remainder.
        teacher, _p = self._paid_payment(tokens=100)
        WalletService.debit(teacher=teacher, amount=80, description="unlocks")
        hold = WalletService.place_hold(teacher, 100, "chargeback (spent already)")
        self.assertEqual(hold.amount, 20)
        self.assertIn("only 20", hold.reason)
        WalletService.settle_hold_as_debit(hold, description="chargeback upheld")
        self.assertEqual(WalletService.get_balance(teacher), 0)


class DisputeWebhookTests(_Mixin, APITestCase):
    def _dispute_event(
        self, *, event, dispute_id, payment_id, amount_paise, reason="fraud"
    ):
        payload = {
            "id": f"evt_{dispute_id}_{event.split('.')[-1]}",
            "event": event,
            "payload": {
                "dispute": {
                    "entity": {
                        "id": dispute_id,
                        "payment_id": payment_id,
                        "amount": amount_paise,
                        "reason_code": reason,
                    }
                }
            },
        }
        raw = json.dumps(payload).encode()
        return self.client.post(
            WEBHOOK_URL,
            data=raw,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=_sign(raw),
        )

    @override_settings(TRUST_ENABLE_PAYMENT_RISK_CHECKS=True)
    def test_dispute_links_to_a_webhook_only_confirmed_payment(self):
        # Payment confirmed by the capture webhook (client never ran verify),
        # so razorpay_payment_id starts NULL - it must get persisted so a
        # later dispute webhook can find it by payment_id.
        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        pkg = TokenPackage.objects.create(
            name="WHonly", token_count=100, price=Decimal("499.00")
        )
        payment = Payment.objects.create(
            teacher=teacher,
            payment_type=PaymentType.TOKEN_PURCHASE,
            token_package=pkg,
            razorpay_order_id="o_whonly",
            amount=pkg.final_price,
            token_count=100,
            status=PaymentStatus.PENDING,
        )
        WalletService.get_or_create_wallet(teacher)
        cap = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_whonly_1",
                        "order_id": "o_whonly",
                        "amount": int(round(payment.amount * 100)),
                        "status": "captured",
                    }
                }
            },
        }
        raw = json.dumps(cap).encode()
        self.client.post(
            WEBHOOK_URL,
            data=raw,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=_sign(raw),
            HTTP_X_RAZORPAY_EVENT_ID="e_cap_1",
        )
        payment.refresh_from_db()
        self.assertEqual(payment.razorpay_payment_id, "pay_whonly_1")

        self._dispute_event(
            event="payment.dispute.created",
            dispute_id="disp_whonly",
            payment_id="pay_whonly_1",
            amount_paise=int(round(payment.amount * 100)),
        )
        d = PaymentDispute.objects.filter(external_ref="disp_whonly").first()
        self.assertIsNotNone(d)
        self.assertEqual(d.payment_id, payment.id)

    @override_settings(TRUST_ENABLE_PAYMENT_RISK_CHECKS=True)
    def test_dispute_created_freezes_tokens(self):
        teacher, payment = self._paid_payment(
            tokens=100, order="o_dw1", pay_id="pay_dw1"
        )
        r = self._dispute_event(
            event="payment.dispute.created",
            dispute_id="disp_1",
            payment_id="pay_dw1",
            amount_paise=int(round(payment.amount * 100)),
        )
        self.assertEqual(r.status_code, 200)
        d = PaymentDispute.objects.get(external_ref="disp_1")
        self.assertEqual(d.kind, DisputeKind.CHARGEBACK)
        self.assertEqual(d.tokens_frozen, 100)
        self.assertEqual(WalletService.available_balance(teacher), 0)
        self.assertEqual(WalletService.get_balance(teacher), 100)  # not clawed yet
        self.assertTrue(
            ManualReviewItem.objects.filter(
                kind=ManualReviewKind.PAYMENT_DISPUTE
            ).exists()
        )
        self.assertTrue(
            RiskSignal.objects.filter(
                user=teacher.user, kind=RiskSignalKind.PAYMENT_RISK
            ).exists()
        )

    @override_settings(TRUST_ENABLE_PAYMENT_RISK_CHECKS=True)
    def test_dispute_won_releases_hold(self):
        teacher, payment = self._paid_payment(
            tokens=100, order="o_dw2", pay_id="pay_dw2"
        )
        self._dispute_event(
            event="payment.dispute.created",
            dispute_id="disp_2",
            payment_id="pay_dw2",
            amount_paise=int(round(payment.amount * 100)),
        )
        self._dispute_event(
            event="payment.dispute.won",
            dispute_id="disp_2",
            payment_id="pay_dw2",
            amount_paise=int(round(payment.amount * 100)),
        )
        d = PaymentDispute.objects.get(external_ref="disp_2")
        self.assertEqual(d.status, DisputeStatus.WON)
        self.assertEqual(WalletService.available_balance(teacher), 100)

    @override_settings(TRUST_ENABLE_PAYMENT_RISK_CHECKS=True)
    def test_dispute_lost_claws_back(self):
        teacher, payment = self._paid_payment(
            tokens=100, order="o_dw3", pay_id="pay_dw3"
        )
        self._dispute_event(
            event="payment.dispute.created",
            dispute_id="disp_3",
            payment_id="pay_dw3",
            amount_paise=int(round(payment.amount * 100)),
        )
        self._dispute_event(
            event="payment.dispute.lost",
            dispute_id="disp_3",
            payment_id="pay_dw3",
            amount_paise=int(round(payment.amount * 100)),
        )
        d = PaymentDispute.objects.get(external_ref="disp_3")
        self.assertEqual(d.status, DisputeStatus.LOST)
        self.assertEqual(WalletService.get_balance(teacher), 0)  # clawed back

    def test_dispute_recorded_but_not_frozen_when_flag_off(self):
        teacher, payment = self._paid_payment(
            tokens=100, order="o_dw4", pay_id="pay_dw4"
        )
        self._dispute_event(
            event="payment.dispute.created",
            dispute_id="disp_4",
            payment_id="pay_dw4",
            amount_paise=int(round(payment.amount * 100)),
        )
        d = PaymentDispute.objects.get(external_ref="disp_4")
        self.assertEqual(d.tokens_frozen, 0)
        self.assertEqual(WalletService.available_balance(teacher), 100)
        self.assertFalse(WalletHold.objects.exists())
        # still recorded + queued for a human
        self.assertTrue(
            ManualReviewItem.objects.filter(
                kind=ManualReviewKind.PAYMENT_DISPUTE
            ).exists()
        )

    @override_settings(TRUST_ENABLE_PAYMENT_RISK_CHECKS=True)
    def test_duplicate_dispute_event_is_idempotent(self):
        teacher, payment = self._paid_payment(
            tokens=100, order="o_dw5", pay_id="pay_dw5"
        )
        for _ in range(2):
            self._dispute_event(
                event="payment.dispute.created",
                dispute_id="disp_5",
                payment_id="pay_dw5",
                amount_paise=int(round(payment.amount * 100)),
            )
        self.assertEqual(
            PaymentDispute.objects.filter(external_ref="disp_5").count(), 1
        )
        self.assertEqual(WalletHold.objects.filter(active=True).count(), 1)

    def test_refund_abuse_flagged_when_tokens_already_spent(self):
        # No risk flag needed for the freeze; abuse detection is not gated.
        teacher, payment = self._paid_payment(
            tokens=100, order="o_ab1", pay_id="pay_ab1"
        )
        WalletService.debit(teacher=teacher, amount=90, description="spent most")
        self._dispute_event(
            event="payment.dispute.created",
            dispute_id="disp_ab1",
            payment_id="pay_ab1",
            amount_paise=int(round(payment.amount * 100)),
        )
        # 90 of the 100 disputed tokens were already consumed -> abuse flag
        self.assertTrue(
            RiskSignal.objects.filter(
                user=teacher.user, kind=RiskSignalKind.PAYMENT_RISK
            ).exists()
        )
        self.assertTrue(
            ManualReviewItem.objects.filter(kind=ManualReviewKind.PAYMENT_RISK).exists()
        )

    def test_no_refund_abuse_flag_when_tokens_untouched(self):
        teacher, payment = self._paid_payment(
            tokens=100, order="o_ab2", pay_id="pay_ab2"
        )
        self._dispute_event(
            event="payment.dispute.created",
            dispute_id="disp_ab2",
            payment_id="pay_ab2",
            amount_paise=int(round(payment.amount * 100)),
        )
        self.assertFalse(
            ManualReviewItem.objects.filter(kind=ManualReviewKind.PAYMENT_RISK).exists()
        )

    @override_settings(TRUST_ENABLE_PAYMENT_RISK_CHECKS=True)
    def test_partial_refund_freezes_proportional_tokens(self):
        teacher, payment = self._paid_payment(
            tokens=100, order="o_ref1", pay_id="pay_ref1"
        )
        half_paise = int(round(payment.amount * 100)) // 2
        payload = {
            "id": "evt_ref1",
            "event": "refund.created",
            "payload": {
                "refund": {
                    "entity": {
                        "id": "rfnd_1",
                        "payment_id": "pay_ref1",
                        "amount": half_paise,
                    }
                }
            },
        }
        raw = json.dumps(payload).encode()
        self.client.post(
            WEBHOOK_URL,
            data=raw,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=_sign(raw),
        )
        d = PaymentDispute.objects.get(external_ref="rfnd_1")
        self.assertEqual(d.kind, DisputeKind.REFUND)
        self.assertEqual(d.tokens_frozen, 50)

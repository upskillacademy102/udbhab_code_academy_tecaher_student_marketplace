"""
Phase 7a / 7b - server-side amount verification + idempotency / re-entrancy
on the payment-confirmation path.

Run: python manage.py test apps.payments.tests.test_payment_fraud --settings=config.settings.test
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
from apps.ops.models import AuditLog
from apps.payments.exceptions import PaymentAmountMismatch
from apps.payments.models import (
    Payment,
    PaymentStatus,
    PaymentType,
    PaymentWebhook,
    TokenPackage,
)
from apps.payments.services import PaymentService
from apps.teachers.models import Teacher
from apps.trust.models import RiskSignal, RiskSignalKind
from apps.wallet.services import WalletService

WEBHOOK_URL = "/api/v1/payments/webhook/"


def _sign(raw: bytes) -> str:
    return hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(), raw, hashlib.sha256
    ).hexdigest()


class _PaymentMixin:
    def _pending_token_payment(self, *, price="499.00", order="order_pf_1"):
        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        pkg = TokenPackage.objects.create(
            name=f"Pack {order}", token_count=100, price=Decimal(price)
        )
        payment = Payment.objects.create(
            teacher=teacher,
            payment_type=PaymentType.TOKEN_PURCHASE,
            token_package=pkg,
            razorpay_order_id=order,
            amount=pkg.final_price,
            token_count=pkg.token_count,
            status=PaymentStatus.PENDING,
        )
        return teacher, pkg, payment


class AmountCheckTests(_PaymentMixin, TestCase):
    def test_matching_amount_credits_wallet(self):
        teacher, _pkg, payment = self._pending_token_payment()
        paise = int(round(payment.amount * 100))
        PaymentService._mark_payment_successful(payment, captured_amount_paise=paise)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(WalletService.get_balance(teacher), 100)

    def test_none_captured_amount_still_credits(self):
        # verify_payment passes None when Razorpay can't be queried (dev).
        teacher, _pkg, payment = self._pending_token_payment(order="order_pf_none")
        PaymentService._mark_payment_successful(payment, captured_amount_paise=None)
        self.assertEqual(WalletService.get_balance(teacher), 100)

    def test_mismatched_amount_is_rejected(self):
        teacher, _pkg, payment = self._pending_token_payment(order="order_pf_bad")
        wrong = int(round(payment.amount * 100)) - 5000  # paid 50 rupees less
        with self.assertRaises(PaymentAmountMismatch):
            PaymentService._mark_payment_successful(
                payment, captured_amount_paise=wrong
            )

        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.FAILED)
        self.assertIn("did not match", payment.failure_reason)
        self.assertEqual(WalletService.get_balance(teacher), 0)  # never credited
        self.assertTrue(
            RiskSignal.objects.filter(
                user=teacher.user, kind=RiskSignalKind.PAYMENT_RISK
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="payment_amount_mismatch").exists()
        )

    def test_rejected_payment_cannot_later_be_forced_success(self):
        _teacher, _pkg, payment = self._pending_token_payment(order="order_pf_bad2")
        with self.assertRaises(PaymentAmountMismatch):
            PaymentService._mark_payment_successful(payment, captured_amount_paise=1)
        # A subsequent correct-amount confirmation must not resurrect it.
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.FAILED)


class IdempotencyTests(_PaymentMixin, TestCase):
    def test_double_confirmation_credits_once(self):
        teacher, _pkg, payment = self._pending_token_payment(order="order_pf_idem")
        PaymentService._mark_payment_successful(payment)
        PaymentService._mark_payment_successful(payment)  # webhook after verify
        self.assertEqual(WalletService.get_balance(teacher), 100)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)


class WebhookTests(_PaymentMixin, APITestCase):
    def _event(self, *, event_id, order_id, amount_paise, event="payment.captured"):
        payload = {
            "id": event_id,
            "event": event,
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_x",
                        "order_id": order_id,
                        "amount": amount_paise,
                        "status": "captured",
                    }
                }
            },
        }
        raw = json.dumps(payload).encode()
        return raw, _sign(raw)

    def test_real_razorpay_shape_dedupes_on_the_header(self):
        # Real Razorpay webhooks carry NO 'id' in the body - the dedup id is
        # the X-Razorpay-Event-Id header.
        teacher, _pkg, payment = self._pending_token_payment(order="order_wh_hdr")
        payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "order_id": "order_wh_hdr",
                        "amount": int(round(payment.amount * 100)),
                        "status": "captured",
                    }
                }
            },
        }
        raw = json.dumps(payload).encode()
        for _ in range(2):
            r = self.client.post(
                WEBHOOK_URL,
                data=raw,
                content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE=_sign(raw),
                HTTP_X_RAZORPAY_EVENT_ID="evt_header_123",
            )
            self.assertEqual(r.status_code, 200)
        self.assertEqual(WalletService.get_balance(teacher), 100)  # credited once
        self.assertEqual(
            PaymentWebhook.objects.filter(razorpay_event_id="evt_header_123").count(), 1
        )

    def test_webhook_with_no_id_anywhere_still_records_once(self):
        teacher, _pkg, payment = self._pending_token_payment(order="order_wh_noid")
        payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "order_id": "order_wh_noid",
                        "amount": int(round(payment.amount * 100)),
                        "status": "captured",
                    }
                }
            },
        }
        raw = json.dumps(payload).encode()
        for _ in range(2):
            self.client.post(
                WEBHOOK_URL,
                data=raw,
                content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE=_sign(raw),
            )
        self.assertEqual(WalletService.get_balance(teacher), 100)
        self.assertEqual(PaymentWebhook.objects.count(), 1)

    def test_captured_webhook_with_right_amount_credits(self):
        teacher, _pkg, payment = self._pending_token_payment(order="order_wh_ok")
        raw, sig = self._event(
            event_id="evt_ok",
            order_id="order_wh_ok",
            amount_paise=int(round(payment.amount * 100)),
        )
        r = self.client.post(
            WEBHOOK_URL,
            data=raw,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=sig,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(WalletService.get_balance(teacher), 100)
        wh = PaymentWebhook.objects.get(razorpay_event_id="evt_ok")
        self.assertTrue(wh.is_processed)

    def test_captured_webhook_with_wrong_amount_rejects_and_still_200s(self):
        teacher, _pkg, payment = self._pending_token_payment(order="order_wh_bad")
        raw, sig = self._event(
            event_id="evt_bad", order_id="order_wh_bad", amount_paise=100
        )
        r = self.client.post(
            WEBHOOK_URL,
            data=raw,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=sig,
        )
        self.assertEqual(r.status_code, 200)  # Razorpay must stop retrying
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.FAILED)
        self.assertEqual(WalletService.get_balance(teacher), 0)
        wh = PaymentWebhook.objects.get(razorpay_event_id="evt_bad")
        self.assertFalse(wh.is_processed)
        self.assertTrue(wh.processing_error)

    def test_duplicate_event_id_is_noop(self):
        teacher, _pkg, payment = self._pending_token_payment(order="order_wh_dup")
        raw, sig = self._event(
            event_id="evt_dup",
            order_id="order_wh_dup",
            amount_paise=int(round(payment.amount * 100)),
        )
        for _ in range(2):
            self.client.post(
                WEBHOOK_URL,
                data=raw,
                content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE=sig,
            )
        self.assertEqual(WalletService.get_balance(teacher), 100)  # credited once
        self.assertEqual(
            PaymentWebhook.objects.filter(razorpay_event_id="evt_dup").count(), 1
        )

    def test_bad_signature_400(self):
        self._pending_token_payment(order="order_wh_sig")
        raw, _sig = self._event(
            event_id="evt_sig", order_id="order_wh_sig", amount_paise=100
        )
        r = self.client.post(
            WEBHOOK_URL,
            data=raw,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE="deadbeef",
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(PaymentWebhook.objects.exists())


class PaymentRiskTests(_PaymentMixin, APITestCase):
    def _captured(self, *, event_id, payment, entity_extra):
        entity = {
            "id": "pay_x",
            "order_id": payment.razorpay_order_id,
            "amount": int(round(payment.amount * 100)),
            "status": "captured",
            **entity_extra,
        }
        payload = {
            "id": event_id,
            "event": "payment.captured",
            "payload": {"payment": {"entity": entity}},
        }
        raw = json.dumps(payload).encode()
        self.client.post(
            WEBHOOK_URL,
            data=raw,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=_sign(raw),
        )

    @override_settings(
        TRUST_ENABLE_PAYMENT_RISK_CHECKS=True, TRUST_PAYMENT_INSTRUMENT_MAX_ACCOUNTS=3
    )
    def test_shared_upi_across_accounts_flags(self):
        vpa = {"method": "upi", "vpa": "fraudster@okhdfcbank"}
        users = []
        for i in range(3):
            teacher, _pkg, payment = self._pending_token_payment(order=f"o_upi_{i}")
            self._captured(event_id=f"e_upi_{i}", payment=payment, entity_extra=vpa)
            users.append(teacher.user)

        # First two: recorded but under threshold -> no signal.
        self.assertFalse(
            RiskSignal.objects.filter(
                user=users[0], kind=RiskSignalKind.PAYMENT_RISK
            ).exists()
        )
        # Third distinct account tips it over -> that account is flagged.
        self.assertTrue(
            RiskSignal.objects.filter(
                user=users[2], kind=RiskSignalKind.PAYMENT_RISK
            ).exists()
        )
        from apps.trust.models import ManualReviewItem, ManualReviewKind

        self.assertEqual(
            ManualReviewItem.objects.filter(kind=ManualReviewKind.PAYMENT_RISK).count(),
            1,  # deduped on the instrument hash
        )

    def test_shared_upi_noop_when_flag_off(self):
        vpa = {"method": "upi", "vpa": "someone@okaxis"}
        for i in range(4):
            _t, _p, payment = self._pending_token_payment(order=f"o_off_{i}")
            self._captured(event_id=f"e_off_{i}", payment=payment, entity_extra=vpa)
        self.assertFalse(
            RiskSignal.objects.filter(kind=RiskSignalKind.PAYMENT_RISK).exists()
        )
        from apps.payments.models import PaymentInstrumentSignature

        self.assertEqual(PaymentInstrumentSignature.objects.count(), 0)

    @override_settings(
        TRUST_ENABLE_PAYMENT_RISK_CHECKS=True, TRUST_PAYMENT_SPIKE_MULTIPLIER=3
    )
    def test_amount_spike_flags(self):
        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        small = TokenPackage.objects.create(
            name="S", token_count=10, price=Decimal("100.00")
        )
        big = TokenPackage.objects.create(
            name="B", token_count=9000, price=Decimal("90000.00")
        )

        p1 = Payment.objects.create(
            teacher=teacher,
            payment_type=PaymentType.TOKEN_PURCHASE,
            token_package=small,
            razorpay_order_id="o_spike_1",
            amount=small.final_price,
            token_count=small.token_count,
            status=PaymentStatus.PENDING,
        )
        self._captured(
            event_id="e_spike_1",
            payment=p1,
            entity_extra={"method": "upi", "vpa": "a@b"},
        )
        self.assertFalse(
            RiskSignal.objects.filter(kind=RiskSignalKind.PAYMENT_RISK).exists()
        )

        p2 = Payment.objects.create(
            teacher=teacher,
            payment_type=PaymentType.TOKEN_PURCHASE,
            token_package=big,
            razorpay_order_id="o_spike_2",
            amount=big.final_price,
            token_count=big.token_count,
            status=PaymentStatus.PENDING,
        )
        self._captured(
            event_id="e_spike_2",
            payment=p2,
            entity_extra={"method": "upi", "vpa": "a@b"},
        )
        self.assertTrue(
            RiskSignal.objects.filter(
                user=teacher.user, kind=RiskSignalKind.PAYMENT_RISK
            ).exists()
        )

    @override_settings(
        TRUST_ENABLE_PAYMENT_RISK_CHECKS=True, TRUST_PAYMENT_FAILED_BURST=3
    )
    def test_failed_attempt_burst_flags(self):
        from apps.payments.risk import PaymentRiskService

        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        for _ in range(2):
            PaymentRiskService.note_failed_payment(teacher)
        self.assertFalse(
            RiskSignal.objects.filter(kind=RiskSignalKind.PAYMENT_RISK).exists()
        )
        PaymentRiskService.note_failed_payment(teacher)  # 3rd -> threshold
        self.assertTrue(
            RiskSignal.objects.filter(
                user=teacher.user, kind=RiskSignalKind.PAYMENT_RISK
            ).exists()
        )

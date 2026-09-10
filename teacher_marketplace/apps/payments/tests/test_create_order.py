"""
Regression: `POST /api/v1/payments/create-order/` returned a raw 500 when the
Razorpay API call failed (provider outage / SSL / network / unconfigured keys) -
the exception in `PaymentService.create_order` was never caught.

It now:
  * short-circuits to a clean 503 when Razorpay credentials are placeholders /
    missing (dev + staging), and
  * catches Razorpay SDK + network errors and raises
    `ServiceUnavailableException` (503) instead of bubbling a stack trace.

Run: python manage.py test apps.payments.tests.test_create_order \
     --settings=config.settings.test
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import razorpay.errors as razorpay_errors
import requests
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.core.exceptions.custom_exceptions import ServiceUnavailableException
from apps.payments.models import Payment, TokenPackage
from apps.payments.services import PaymentService
from apps.teachers.models import Teacher

REAL_KEYS = dict(RAZORPAY_KEY_ID="rzp_live_abc123", RAZORPAY_KEY_SECRET="realsecret999")


def subscribe_to_paid_plan(teacher, plan_name="Professional"):
    """Put a teacher on a paid plan so they may buy extra-unlock packs."""
    from django.utils import timezone

    from apps.subscriptions.models import (
        SubscriptionPlan,
        SubscriptionStatus,
        TeacherSubscription,
    )

    now = timezone.now()
    return TeacherSubscription.objects.create(
        teacher=teacher,
        plan=SubscriptionPlan.objects.get(name=plan_name),
        status=SubscriptionStatus.ACTIVE,
        start_date=now,
        end_date=now + timedelta(days=30),
    )


class CreateOrderResilienceTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.TEACHER)
        self.teacher = Teacher.objects.create(user=self.user)
        self.pkg = TokenPackage.objects.create(
            name="Starter", token_count=100, price=Decimal("499")
        )
        # Extra-unlock packs are sold to paid plans only, so these
        # Razorpay-resilience tests need a subscribed teacher - otherwise
        # every request is rejected with TOPUP_REQUIRES_PAID_PLAN long
        # before it reaches the Razorpay call under test.
        subscribe_to_paid_plan(self.teacher)
        login(self.client, self.user)

    def test_unconfigured_keys_return_503_not_500(self):
        with override_settings(
            RAZORPAY_KEY_ID="rzp_test_your_key_id",
            RAZORPAY_KEY_SECRET="your_key_secret",
        ):
            resp = self.client.post(
                "/api/v1/payments/create-order/",
                {"token_package_id": str(self.pkg.id)},
                format="json",
            )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"]["code"], "SERVICE_UNAVAILABLE")
        self.assertFalse(Payment.objects.exists())  # no dangling PENDING row

    @override_settings(**REAL_KEYS)
    def test_razorpay_network_error_returns_503(self):
        with patch(
            "apps.payments.services.razorpay.Client.order",
            create=True,
        ):
            with patch(
                "razorpay.resources.order.Order.create",
                side_effect=requests.exceptions.SSLError("cert verify failed"),
            ):
                resp = self.client.post(
                    "/api/v1/payments/create-order/",
                    {"token_package_id": str(self.pkg.id)},
                    format="json",
                )
        self.assertEqual(resp.status_code, 503)
        self.assertFalse(Payment.objects.exists())

    @override_settings(**REAL_KEYS)
    def test_razorpay_gateway_error_returns_503(self):
        with patch(
            "razorpay.resources.order.Order.create",
            side_effect=razorpay_errors.ServerError("razorpay is down"),
        ):
            with self.assertRaises(ServiceUnavailableException):
                PaymentService.create_order(self.teacher, token_package=self.pkg)
        self.assertFalse(Payment.objects.exists())

    @override_settings(**REAL_KEYS)
    def test_happy_path_still_creates_the_order(self):
        with patch(
            "razorpay.resources.order.Order.create",
            return_value={"id": "order_TESTED123", "amount": 58882, "currency": "INR"},
        ):
            resp = self.client.post(
                "/api/v1/payments/create-order/",
                {"token_package_id": str(self.pkg.id)},
                format="json",
            )
        self.assertEqual(resp.status_code, 201, resp.content)
        p = Payment.objects.get()
        self.assertEqual(p.razorpay_order_id, "order_TESTED123")
        self.assertEqual(resp.json()["data"]["razorpay_order_id"], "order_TESTED123")

    def test_invalid_input_still_400(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/payments/create-order/", {}, format="json"
            ).status_code,
            400,
        )

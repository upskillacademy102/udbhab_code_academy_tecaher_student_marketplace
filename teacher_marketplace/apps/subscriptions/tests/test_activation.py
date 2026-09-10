"""
Regression: activating a subscription 500'd.

`SubscriptionService.subscribe()` fired the "subscription activated" notification
with `NotificationService.notify(..., event=..., context={...})` - but `notify()`
takes `title`/`message`, not `context`, and `context` is not a parameter at all
-> `TypeError` -> HTTP 500 on `POST /api/v1/subscriptions/activate/` for EVERY
plan (Free included). Fix routes through the `subscription_activated()` wrapper
and makes the notification best-effort.

Run: python manage.py test apps.subscriptions --settings=config.settings.test
"""

from unittest.mock import patch

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.notifications.models import Notification, NotificationEvent
from apps.subscriptions.models import (
    SubscriptionPlan,
    SubscriptionStatus,
    TeacherSubscription,
)
from apps.subscriptions.services import SubscriptionService
from apps.teachers.models import Teacher

ACTIVATE = "/api/v1/subscriptions/activate/"


class SubscriptionActivationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.free = SubscriptionPlan.objects.get(name="Free")
        cls.elite = SubscriptionPlan.objects.get(name="Elite")

    def _teacher(self):
        user = make_user(role=UserRole.TEACHER)
        Teacher.objects.create(user=user)
        login(self.client, user)
        return user

    def test_activate_free_plan_succeeds_and_notifies(self):
        user = self._teacher()
        resp = self.client.post(ACTIVATE, {"plan_id": str(self.free.id)}, format="json")

        self.assertEqual(resp.status_code, 201, resp.content)  # was 500
        sub = TeacherSubscription.objects.get(teacher__user=user)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(sub.plan_id, self.free.id)
        note = Notification.objects.get(
            user=user, event=NotificationEvent.SUBSCRIPTION_ACTIVATED
        )
        self.assertEqual(note.title, "Subscription Activated")
        self.assertIn("Free", note.message)

    def test_paid_plan_still_requires_a_payment(self):
        self._teacher()
        resp = self.client.post(
            ACTIVATE, {"plan_id": str(self.elite.id)}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("payment", resp.json()["error"]["message"].lower())

    def test_activation_survives_a_broken_notification(self):
        user = self._teacher()
        teacher = Teacher.objects.get(user=user)
        with patch(
            "apps.notifications.services.NotificationService.subscription_activated",
            side_effect=RuntimeError("smtp exploded"),
        ):
            sub = SubscriptionService.subscribe(teacher, self.free)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE)

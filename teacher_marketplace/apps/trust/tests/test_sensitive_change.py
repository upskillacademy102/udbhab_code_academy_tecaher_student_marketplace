"""
Step-up re-verification for email / mobile / password changes.

Run: python manage.py test apps.trust.tests.test_sensitive_change \
     --settings=config.settings.test
"""

from unittest import mock

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_user
from apps.trust.models import (
    SensitiveChangeField,
    SensitiveChangeRequest,
    SensitiveChangeState,
)
from apps.trust.services.sensitive_change_service import SensitiveChangeService

CE = "/api/v1/auth/change-email/"
CE_OK = "/api/v1/auth/change-email/confirm/"
CM = "/api/v1/auth/change-mobile/"
CM_OK = "/api/v1/auth/change-mobile/confirm/"
CP = "/api/v1/auth/change-password/"
CP_OK = "/api/v1/auth/change-password/confirm/"
LIST = "/api/v1/auth/sensitive-changes/"

FIXED = mock.patch(
    "apps.trust.services.otp_service.secrets.randbelow", return_value=123456
)


class ChangeEmailImmediateTests(APITestCase):
    """Step-up OFF: confirm applies the change straight away."""

    def setUp(self):
        self.user = make_user(role=UserRole.STUDENT, email="old@x.test")
        login(self.client, self.user)

    def test_wrong_password_is_rejected(self):
        r = self.client.post(
            CE, {"new_email": "new@x.test", "current_password": "nope"}, format="json"
        )
        self.assertEqual(r.status_code, 400, r.content)

    def test_happy_path(self):
        with FIXED:
            r = self.client.post(
                CE,
                {"new_email": "new@x.test", "current_password": TEST_PASSWORD},
                format="json",
            )
        self.assertEqual(r.status_code, 202, r.content)

        r = self.client.post(CE_OK, {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@x.test")
        self.assertTrue(self.user.is_email_verified)

    def test_duplicate_email_conflicts(self):
        make_user(role=UserRole.STUDENT, email="taken@x.test")
        with FIXED:
            r = self.client.post(
                CE,
                {"new_email": "taken@x.test", "current_password": TEST_PASSWORD},
                format="json",
            )
        self.assertEqual(r.status_code, 409, r.content)

    def test_same_email_rejected(self):
        r = self.client.post(
            CE,
            {"new_email": "old@x.test", "current_password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, 400, r.content)


@override_settings(
    TRUST_ENABLE_STEP_UP_REVERIFICATION=True, TRUST_SENSITIVE_CHANGE_COOLDOWN_MINUTES=30
)
class ChangeEmailStepUpTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.TEACHER, email="old@x.test")
        login(self.client, self.user)

    def _initiate_and_confirm(self):
        with FIXED:
            self.client.post(
                CE,
                {"new_email": "new@x.test", "current_password": TEST_PASSWORD},
                format="json",
            )
        return self.client.post(CE_OK, {"code": "123456"}, format="json")

    def test_confirm_schedules_not_applies(self):
        r = self._initiate_and_confirm()
        self.assertEqual(r.status_code, 200, r.content)
        scr = SensitiveChangeRequest.objects.get(
            user=self.user, field=SensitiveChangeField.EMAIL
        )
        self.assertEqual(scr.state, SensitiveChangeState.SCHEDULED)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@x.test")  # not yet

    def test_cooldown_then_apply_due(self):
        self._initiate_and_confirm()
        self.assertEqual(SensitiveChangeService.apply_due(), 0)  # cooldown not elapsed

        scr = SensitiveChangeRequest.objects.get(
            user=self.user, field=SensitiveChangeField.EMAIL
        )
        scr.apply_after = timezone.now() - timezone.timedelta(minutes=1)
        scr.save(update_fields=["apply_after"])
        self.assertEqual(SensitiveChangeService.apply_due(), 1)

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@x.test")

    def test_owner_can_cancel_during_cooldown(self):
        self._initiate_and_confirm()
        scr = SensitiveChangeRequest.objects.get(
            user=self.user, field=SensitiveChangeField.EMAIL
        )
        r = self.client.post(f"{LIST}{scr.id}/cancel/")
        self.assertEqual(r.status_code, 200, r.content)

        scr.apply_after = timezone.now() - timezone.timedelta(minutes=1)
        scr.save(update_fields=["apply_after"])
        self.assertEqual(
            SensitiveChangeService.apply_due(), 0
        )  # cancelled -> not applied
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@x.test")

    def test_list_shows_pending(self):
        self._initiate_and_confirm()
        rows = self.client.get(LIST).json()["data"]
        self.assertTrue(
            any(x["field"] == "email" and x["state"] == "scheduled" for x in rows)
        )


class ChangeMobileTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.TEACHER)
        login(self.client, self.user)

    def test_happy_path_immediate(self):
        with FIXED:
            r = self.client.post(
                CM,
                {"new_mobile": "919812345670", "current_password": TEST_PASSWORD},
                format="json",
            )
        self.assertEqual(r.status_code, 202, r.content)
        r = self.client.post(CM_OK, {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.mobile, "919812345670")
        self.assertTrue(self.user.is_mobile_verified)


class ChangePasswordTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.STUDENT)
        login(self.client, self.user)

    def test_step_up_off_is_one_step_unchanged(self):
        r = self.client.post(
            CP,
            {
                "old_password": TEST_PASSWORD,
                "new_password": "Str0ng!Pass2",
                "new_password_confirm": "Str0ng!Pass2",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Str0ng!Pass2"))

    @override_settings(TRUST_ENABLE_STEP_UP_REVERIFICATION=True)
    def test_step_up_on_requires_code(self):
        with FIXED:
            r = self.client.post(
                CP,
                {
                    "old_password": TEST_PASSWORD,
                    "new_password": "Str0ng!Pass2",
                    "new_password_confirm": "Str0ng!Pass2",
                },
                format="json",
            )
        self.assertEqual(r.status_code, 202, r.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(TEST_PASSWORD))  # not changed yet

        r = self.client.post(CP_OK, {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.user.refresh_from_db()
        self.assertTrue(
            self.user.check_password("Str0ng!Pass2")
        )  # applied immediately on confirm

    @override_settings(TRUST_ENABLE_STEP_UP_REVERIFICATION=True)
    def test_confirm_without_pending_is_400(self):
        r = self.client.post(CP_OK, {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)


class ExpiryTests(APITestCase):
    def test_expire_stale_awaiting_otp(self):
        user = make_user(role=UserRole.STUDENT)
        login(self.client, user)
        with FIXED:
            self.client.post(
                CE,
                {"new_email": "new@x.test", "current_password": TEST_PASSWORD},
                format="json",
            )
        scr = SensitiveChangeRequest.objects.get(user=user)
        scr.created_at = timezone.now() - timezone.timedelta(days=2)
        scr.save(update_fields=["created_at"])
        self.assertEqual(SensitiveChangeService.expire_stale(), 1)
        scr.refresh_from_db()
        self.assertEqual(scr.state, SensitiveChangeState.EXPIRED)

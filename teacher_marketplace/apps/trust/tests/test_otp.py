"""
Email / mobile OTP verification + the contact-verification gates.

Run: python manage.py test apps.trust.tests.test_otp --settings=config.settings.test
"""

from unittest import mock

from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.trust.models import OTPChallenge

STATUS = "/api/v1/verify/status/"
EMAIL_REQ = "/api/v1/verify/email/request/"
EMAIL_OK = "/api/v1/verify/email/confirm/"
MOBILE_REQ = "/api/v1/verify/mobile/request/"
MOBILE_OK = "/api/v1/verify/mobile/confirm/"

_FIXED = mock.patch(
    "apps.trust.services.otp_service.secrets.randbelow", return_value=123456
)


class EmailOTPFlowTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.STUDENT)
        login(self.client, self.user)

    def test_request_sends_a_code_and_confirm_verifies(self):
        with _FIXED:
            r = self.client.post(EMAIL_REQ)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("123456", mail.outbox[0].body)
        self.assertTrue(
            OTPChallenge.objects.filter(user=self.user, channel="email").exists()
        )

        r = self.client.post(EMAIL_OK, {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_email_verified)
        self.assertIsNotNone(self.user.trust_profile.verification_recomputed_at)

    def test_wrong_code_counts_an_attempt_and_fifth_wrong_locks(self):
        with _FIXED:
            self.client.post(EMAIL_REQ)
        for _ in range(5):
            r = self.client.post(EMAIL_OK, {"code": "000000"}, format="json")
            self.assertEqual(r.status_code, 400, r.content)
        # attempts exhausted -> even the correct code is refused now
        r = self.client.post(EMAIL_OK, {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_email_verified)

    def test_expired_code_is_rejected(self):
        with _FIXED:
            self.client.post(EMAIL_REQ)
        ch = OTPChallenge.objects.filter(user=self.user).latest("created_at")
        ch.expires_at = timezone.now() - timezone.timedelta(minutes=1)
        ch.save(update_fields=["expires_at"])
        r = self.client.post(EMAIL_OK, {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_reissue_supersedes_the_previous_code(self):
        with mock.patch(
            "apps.trust.services.otp_service.secrets.randbelow",
            side_effect=[111111, 222222],
        ):
            self.client.post(EMAIL_REQ)
            self.client.post(EMAIL_REQ)
        self.assertEqual(
            self.client.post(EMAIL_OK, {"code": "111111"}, format="json").status_code,
            400,
        )
        self.assertEqual(
            self.client.post(EMAIL_OK, {"code": "222222"}, format="json").status_code,
            200,
        )

    def test_confirm_without_a_pending_code(self):
        r = self.client.post(EMAIL_OK, {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_request_is_rate_limited(self):
        # THROTTLE_RATES is a class attr bound at import; override_settings
        # does not reach it, so patch the dict directly.
        with mock.patch.dict(
            SimpleRateThrottle.THROTTLE_RATES, {"otp_request": "2/hour"}
        ), mock.patch(
            "apps.trust.services.otp_service.secrets.randbelow", return_value=1
        ):
            self.assertEqual(self.client.post(EMAIL_REQ).status_code, 200)
            self.assertEqual(self.client.post(EMAIL_REQ).status_code, 200)
            self.assertEqual(self.client.post(EMAIL_REQ).status_code, 429)


class MobileOTPFlowTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.TEACHER)
        login(self.client, self.user)

    def test_sms_channel_verifies_mobile(self):
        with _FIXED:
            r = self.client.post(MOBILE_REQ)
        self.assertEqual(r.status_code, 200, r.content)
        ch = OTPChallenge.objects.filter(user=self.user, channel="sms").latest(
            "created_at"
        )
        self.assertEqual(ch.destination, self.user.mobile)

        r = self.client.post(MOBILE_OK, {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_mobile_verified)

    def test_status_endpoint(self):
        r = self.client.get(STATUS)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()["data"]
        self.assertIn("email_verified", body)
        self.assertIn("verification_score", body)


class ContactGateTests(APITestCase):
    """The gate is a no-op with flags OFF and blocks with a flag ON."""

    def setUp(self):
        self.teacher = make_user(role=UserRole.TEACHER)

    def _unlock_attempt(self):
        # The gate runs before the view body. A 403 means the gate blocked;
        # anything else (here 404 - no teacher profile) means it passed.
        login(self.client, self.teacher)
        return self.client.post("/api/v1/leads/unlock/", {}, format="json")

    def test_gate_off_by_default(self):
        self.assertNotEqual(self._unlock_attempt().status_code, 403)

    @override_settings(TRUST_REQUIRE_EMAIL_VERIFICATION=True)
    def test_gate_on_blocks_unverified(self):
        self.assertEqual(self._unlock_attempt().status_code, 403)

    @override_settings(TRUST_REQUIRE_EMAIL_VERIFICATION=True)
    def test_gate_on_passes_verified(self):
        self.teacher.is_email_verified = True
        self.teacher.save(update_fields=["is_email_verified"])
        self.assertNotEqual(self._unlock_attempt().status_code, 403)

    @override_settings(TRUST_REQUIRE_MOBILE_VERIFICATION=True)
    def test_mobile_gate_on_blocks_unverified(self):
        self.assertEqual(self._unlock_attempt().status_code, 403)

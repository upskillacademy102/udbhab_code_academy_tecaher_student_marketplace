"""
Conditional CAPTCHA on the auth endpoints.

Run: python manage.py test apps.trust.tests.test_captcha --settings=config.settings.test
"""

from unittest import mock

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import TEST_PASSWORD, make_user
from apps.trust.providers.stub import FAIL_SENTINEL
from apps.trust.services.captcha_service import CaptchaService

LOGIN = "/api/v1/auth/login/"
LOGOUT = "/api/v1/auth/logout/"
REGISTER = "/api/v1/auth/register/"


class SwitchTrackerUnitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.rf = RequestFactory()

    def _req(self):
        return self.rf.post("/api/v1/auth/login/", HTTP_USER_AGENT="pytest-agent")

    def test_distinct_users_accumulate(self):
        r = self._req()
        for uid in ("u1", "u2", "u2", "u3"):
            CaptchaService.record_account_use(r, uid)
        self.assertEqual(CaptchaService.switch_count(r), 3)

    @override_settings(TRUST_ENABLE_CAPTCHA=False, TRUST_CAPTCHA_SWITCH_THRESHOLD=2)
    def test_flag_off_never_requires_challenge(self):
        r = self._req()
        for uid in ("u1", "u2", "u3", "u4"):
            CaptchaService.record_account_use(r, uid)
        self.assertFalse(CaptchaService.challenge_required(r))

    @override_settings(TRUST_ENABLE_CAPTCHA=True, TRUST_CAPTCHA_SWITCH_THRESHOLD=3)
    def test_threshold(self):
        r = self._req()
        CaptchaService.record_account_use(r, "u1")
        CaptchaService.record_account_use(r, "u2")
        self.assertFalse(CaptchaService.challenge_required(r))
        CaptchaService.record_account_use(r, "u3")
        self.assertTrue(CaptchaService.challenge_required(r))

    @override_settings(TRUST_ENABLE_CAPTCHA=True, TRUST_CAPTCHA_SWITCH_THRESHOLD=1)
    def test_verify_or_raise_needs_valid_token(self):
        from apps.trust.exceptions import CaptchaRequiredException

        r = self.rf.post("/x", {"captcha_token": ""}, content_type="application/json")
        r.data = {"captcha_token": ""}
        CaptchaService.record_account_use(r, "u1")
        with self.assertRaises(CaptchaRequiredException):
            CaptchaService.verify_or_raise(r)

        r.data = {"captcha_token": "solved"}
        CaptchaService.verify_or_raise(r)  # no raise

    def test_cache_failure_fails_open(self):
        r = self._req()
        with mock.patch(
            "apps.trust.services.captcha_service.cache.get", side_effect=RuntimeError
        ):
            self.assertEqual(CaptchaService.switch_count(r), 0)
            self.assertFalse(CaptchaService.challenge_required(r))


class LoginCaptchaIntegrationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.users = [
            make_user(role=UserRole.STUDENT, email=f"u{i}@x.test") for i in range(4)
        ]

    def _login(self, user, **extra):
        return self.client.post(
            LOGIN,
            {"email": user.email, "password": TEST_PASSWORD, **extra},
            format="json",
        )

    def test_not_challenged_below_threshold(self):
        with override_settings(
            TRUST_ENABLE_CAPTCHA=True, TRUST_CAPTCHA_SWITCH_THRESHOLD=5
        ):
            self.assertEqual(self._login(self.users[0]).status_code, 200)

    def test_challenged_at_threshold_and_token_clears_it(self):
        with override_settings(
            TRUST_ENABLE_CAPTCHA=True, TRUST_CAPTCHA_SWITCH_THRESHOLD=2
        ):
            self.assertEqual(self._login(self.users[0]).status_code, 200)
            self.client.post(LOGOUT)
            self.assertEqual(self._login(self.users[1]).status_code, 200)
            self.client.post(LOGOUT)

            # 2 distinct users recorded -> next login is challenged
            blocked = self._login(self.users[2])
            self.assertEqual(blocked.status_code, 400, blocked.content)
            self.assertEqual(blocked.json()["error"]["code"], "CAPTCHA_REQUIRED")

            bad = self._login(self.users[2], captcha_token=FAIL_SENTINEL)
            self.assertEqual(bad.status_code, 400, bad.content)

            ok = self._login(self.users[2], captcha_token="solved")
            self.assertEqual(ok.status_code, 200, ok.content)

    def test_flag_off_default_never_challenges(self):
        for u in self.users:
            r = self.client.post(
                LOGIN, {"email": u.email, "password": TEST_PASSWORD}, format="json"
            )
            self.assertEqual(r.status_code, 200, r.content)
            self.client.post(LOGOUT)

    def test_register_counts_toward_switches(self):
        with override_settings(
            TRUST_ENABLE_CAPTCHA=True, TRUST_CAPTCHA_SWITCH_THRESHOLD=2
        ):
            self.assertEqual(self._login(self.users[0]).status_code, 200)
            self.client.post(LOGOUT)
            payload = {
                "email": "fresh@x.test",
                "mobile": "919800111222",
                "password": TEST_PASSWORD,
                "password_confirm": TEST_PASSWORD,
                "role": "student",
                "first_name": "Fresh",
                "last_name": "Face",
            }
            self.assertEqual(
                self.client.post(REGISTER, payload, format="json").status_code, 201
            )
            # login(u0) + register(fresh) = 2 distinct -> next login challenged
            blocked = self._login(self.users[1])
            self.assertEqual(blocked.status_code, 400, blocked.content)

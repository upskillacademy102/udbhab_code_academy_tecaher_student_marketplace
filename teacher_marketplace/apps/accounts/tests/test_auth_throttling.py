"""
Brute-force / enumeration throttling on the unauthenticated auth endpoints.

The global anon/user throttles are disabled in config.settings.test (their
shared counter otherwise leaks across the whole suite). Each test re-enables
just the scope it exercises by patching the throttle-rate table, and clears
the cache in setUp so counts never leak between tests.

Run: python manage.py test apps.accounts.tests.test_auth_throttling \
     --settings=config.settings.test
"""

from unittest import mock

from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import TEST_PASSWORD, make_user

LOGIN = "/api/v1/auth/login/"
REGISTER = "/api/v1/auth/register/"
FORGOT = "/api/v1/auth/forgot-password/"


def rates(**over):
    """Context manager: temporarily set named throttle scopes."""
    return mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, over, clear=False)


def _register_payload(i):
    return {
        "email": f"n{i}@x.test",
        "mobile": f"9198000111{i:02d}",
        "password": TEST_PASSWORD,
        "password_confirm": TEST_PASSWORD,
        "role": "student",
        "first_name": "Ann",
        "last_name": "Bee",
    }


class LoginThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user(role=UserRole.STUDENT, email="victim@x.test")

    def test_repeated_bad_logins_get_429_with_envelope(self):
        with rates(login="3/min"):
            for _ in range(3):
                r = self.client.post(
                    LOGIN,
                    {"email": "victim@x.test", "password": "wrong"},
                    format="json",
                )
                self.assertIn(r.status_code, (400, 401), r.content)
            r = self.client.post(
                LOGIN, {"email": "victim@x.test", "password": "wrong"}, format="json"
            )
        self.assertEqual(r.status_code, 429, r.content)
        body = r.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "THROTTLED")

    def test_throttle_is_per_email_not_shared(self):
        make_user(role=UserRole.STUDENT, email="other@x.test")
        with rates(login="3/min"):
            for _ in range(4):
                self.client.post(
                    LOGIN,
                    {"email": "victim@x.test", "password": "wrong"},
                    format="json",
                )
            r = self.client.post(
                LOGIN,
                {"email": "other@x.test", "password": TEST_PASSWORD},
                format="json",
            )
        self.assertEqual(r.status_code, 200, r.content)

    def test_successful_attempts_also_count(self):
        with rates(login="3/min"):
            for _ in range(3):
                self.client.post(
                    LOGIN,
                    {"email": "victim@x.test", "password": TEST_PASSWORD},
                    format="json",
                )
                self.client.post("/api/v1/auth/logout/")
            r = self.client.post(
                LOGIN,
                {"email": "victim@x.test", "password": TEST_PASSWORD},
                format="json",
            )
        self.assertEqual(r.status_code, 429, r.content)


class RegisterThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_signup_flood_from_one_ip_is_capped(self):
        with rates(register="2/hour"):
            self.assertEqual(
                self.client.post(
                    REGISTER, _register_payload(1), format="json"
                ).status_code,
                201,
            )
            self.assertEqual(
                self.client.post(
                    REGISTER, _register_payload(2), format="json"
                ).status_code,
                201,
            )
            r = self.client.post(REGISTER, _register_payload(3), format="json")
        self.assertEqual(r.status_code, 429, r.content)


class PasswordResetThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()
        make_user(role=UserRole.STUDENT, email="real@x.test")

    def test_forgot_password_flood_is_capped(self):
        with rates(password_reset="2/hour"):
            for _ in range(2):
                r = self.client.post(FORGOT, {"email": "real@x.test"}, format="json")
                self.assertEqual(r.status_code, 200, r.content)
            r = self.client.post(FORGOT, {"email": "real@x.test"}, format="json")
        self.assertEqual(r.status_code, 429, r.content)

    def test_no_throttle_configured_means_no_limit(self):
        for _ in range(6):
            r = self.client.post(FORGOT, {"email": "real@x.test"}, format="json")
            self.assertEqual(r.status_code, 200, r.content)

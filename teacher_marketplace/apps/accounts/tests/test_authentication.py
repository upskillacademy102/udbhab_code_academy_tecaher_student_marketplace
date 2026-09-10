"""
Authentication behaviour: login, credential failures, and every way a
token can be unacceptable (expired / malformed / bad-signature /
revoked-by-logout / superseded-session). Every failure must be 401 and
must never return a successful body.
"""

from datetime import timedelta

from django.conf import settings
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import UserRole, UserSession
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_user

PROTECTED_URL = "/api/v1/notifications/"  # granted to every role
REFRESH_URL = "/api/v1/auth/refresh/"


class LoginTests(APITestCase):
    def setUp(self):
        self.user = make_user(UserRole.STUDENT)

    def test_login_success_returns_tokens_and_sets_cookies(self):
        resp = login(self.client, self.user)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])
        self.assertIn("access", resp.data["data"])
        self.assertIn("refresh", resp.data["data"])
        self.assertIn(settings.JWT_AUTH_COOKIE, resp.cookies)
        self.assertIn(settings.JWT_REFRESH_COOKIE, resp.cookies)
        self.assertTrue(resp.cookies[settings.JWT_AUTH_COOKIE]["httponly"])

    def test_login_wrong_password_is_401(self):
        resp = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "Wr0ng!Password"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(resp.data["success"])

    def test_login_unknown_email_is_401(self):
        resp = self.client.post(
            "/api/v1/auth/login/",
            {"email": "nobody@example.com", "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_inactive_account_is_rejected(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        resp = login(self.client, self.user)
        self.assertIn(
            resp.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED),
        )
        self.assertFalse(resp.data["success"])


class AccessTokenValidationTests(APITestCase):
    def setUp(self):
        self.user = make_user(UserRole.STUDENT)
        login_client = self.client_class()
        self.access = login(login_client, self.user).data["data"]["access"]
        # Fresh client with NO cookies, so header behaviour is isolated.
        self.client = self.client_class()

    def _get(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return self.client.get(PROTECTED_URL)

    def test_valid_token_is_accepted(self):
        self.assertEqual(self._get(self.access).status_code, status.HTTP_200_OK)

    def test_malformed_token_is_401(self):
        self.assertEqual(
            self._get("not-a-jwt").status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_bad_signature_token_is_401(self):
        tampered = self.access[:-3] + (
            "aaa" if not self.access.endswith("aaa") else "bbb"
        )
        self.assertEqual(self._get(tampered).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_token_is_401(self):
        token = AccessToken()
        token["user_id"] = str(self.user.id)
        token["sid"] = str(UserSession.active_sid_for(self.user.id))
        token.set_exp(lifetime=-timedelta(minutes=5))
        self.assertEqual(
            self._get(str(token)).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_token_without_session_claim_is_401(self):
        token = AccessToken()
        token["user_id"] = str(self.user.id)  # no `sid`
        self.assertEqual(
            self._get(str(token)).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_no_credentials_is_401(self):
        self.client.credentials()
        self.assertEqual(
            self.client.get(PROTECTED_URL).status_code, status.HTTP_401_UNAUTHORIZED
        )


class RefreshFlowTests(APITestCase):
    def setUp(self):
        self.user = make_user(UserRole.STUDENT)
        self.refresh = login(self.client, self.user).data["data"]["refresh"]

    def test_refresh_returns_a_new_access_token(self):
        self.client.credentials()
        resp = self.client.post(REFRESH_URL, {"refresh": self.refresh}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data["data"])

    def test_refresh_after_logout_is_401(self):
        self.client.post(
            "/api/v1/auth/logout/", {"refresh": self.refresh}, format="json"
        )
        self.client.credentials()
        resp = self.client.post(REFRESH_URL, {"refresh": self.refresh}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_from_superseded_session_is_401(self):
        # A second login on a different client rotates the session id.
        other = self.client_class()
        login(other, self.user)
        self.client.credentials()
        resp = self.client.post(REFRESH_URL, {"refresh": self.refresh}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_garbage_refresh_is_401(self):
        self.client.credentials()
        resp = self.client.post(REFRESH_URL, {"refresh": "not-a-token"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

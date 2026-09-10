"""
Single-active-account policy:

    * a second login while a session is live is rejected with 409,
    * after logout the previous account's tokens are dead,
    * only then can a different account log in,
    * account A's old credentials can never touch account B's data.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.accounts.views import LoginView

PROTECTED_URL = "/api/v1/notifications/"


class SingleActiveAccountTests(APITestCase):
    def setUp(self):
        self.account_a = make_user(UserRole.STUDENT, email="a@example.com")
        self.account_b = make_user(UserRole.TEACHER, email="b@example.com")

    def test_second_login_via_cookie_is_conflict(self):
        self.assertEqual(login(self.client, self.account_a).status_code, 200)
        resp = login(self.client, self.account_b)  # same client still holds A's cookie
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], "CONFLICT")
        self.assertEqual(
            resp.data["error"]["message"], LoginView.ALREADY_LOGGED_IN_DETAIL
        )

    def test_second_login_via_bearer_header_is_conflict(self):
        access = login(self.client, self.account_a).data["data"]["access"]
        fresh = self.client_class()
        fresh.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = login(fresh, self.account_b)
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_logout_then_switch_accounts(self):
        a_tokens = login(self.client, self.account_a).data["data"]
        a_access = a_tokens["access"]

        # logout A
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/logout/", {"refresh": a_tokens["refresh"]}, format="json"
            ).status_code,
            status.HTTP_200_OK,
        )

        # A's old access token is now dead
        dead = self.client_class()
        dead.credentials(HTTP_AUTHORIZATION=f"Bearer {a_access}")
        self.assertEqual(
            dead.get(PROTECTED_URL).status_code, status.HTTP_401_UNAUTHORIZED
        )

        # now B can log in on the same client
        self.assertEqual(
            login(self.client, self.account_b).status_code, status.HTTP_200_OK
        )

        # ...and A's stale token still cannot be used
        self.assertEqual(
            dead.get(PROTECTED_URL).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_stale_token_cannot_act_as_other_account(self):
        a_access = login(self.client, self.account_a).data["data"]["access"]
        self.client.post("/api/v1/auth/logout/", {}, format="json")
        login(self.client, self.account_b)  # B now active on this client

        stale = self.client_class()
        stale.credentials(HTTP_AUTHORIZATION=f"Bearer {a_access}")
        resp = stale.get(PROTECTED_URL)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

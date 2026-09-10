"""
Logout must tear down every layer, not just the client's copy of the
token:

    * the httpOnly auth cookies are cleared on the response,
    * the UserSession is deactivated (kills the access token immediately),
    * the refresh token is blacklisted (cannot mint new access tokens),
    * a stale access token from before logout is rejected.
"""

from django.conf import settings
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import UserRole, UserSession
from apps.accounts.tests.helpers import login, make_user

PROTECTED_URL = "/api/v1/notifications/"


class LogoutCleanupTests(APITestCase):
    def setUp(self):
        self.user = make_user(UserRole.STUDENT)
        tokens = login(self.client, self.user).data["data"]
        self.access = tokens["access"]
        self.refresh = tokens["refresh"]

    def _logout(self):
        return self.client.post(
            "/api/v1/auth/logout/", {"refresh": self.refresh}, format="json"
        )

    def test_logout_clears_cookies(self):
        resp = self._logout()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        for name in (settings.JWT_AUTH_COOKIE, settings.JWT_REFRESH_COOKIE):
            self.assertIn(name, resp.cookies)
            self.assertEqual(resp.cookies[name].value, "")

    def test_logout_deactivates_session(self):
        self._logout()
        session = UserSession.objects.get(user=self.user)
        self.assertFalse(session.is_active)
        self.assertIsNone(UserSession.active_sid_for(self.user.id))

    def test_logout_blacklists_refresh_token(self):
        self._logout()
        jti = RefreshToken(self.refresh, verify=False)["jti"]
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=jti).exists())

    def test_access_token_dead_after_logout(self):
        self._logout()
        stale = self.client_class()
        stale.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        self.assertEqual(
            stale.get(PROTECTED_URL).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_refresh_token_dead_after_logout(self):
        self._logout()
        clean = self.client_class()
        resp = clean.post(
            "/api/v1/auth/refresh/", {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_is_idempotent(self):
        self.assertEqual(self._logout().status_code, status.HTTP_200_OK)
        # second logout: session already dead -> the request itself is now
        # unauthenticated, so 401 is the correct answer.
        self.assertEqual(self._logout().status_code, status.HTTP_401_UNAUTHORIZED)

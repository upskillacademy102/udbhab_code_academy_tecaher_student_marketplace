"""
The hidden-gateway staff-login endpoints:
  POST /api/v1/auth/staff/login-superadmin/         (email + password)
  POST /api/v1/auth/staff/login-admin/               (account_name + password)
  POST /api/v1/auth/staff/login-learning-partner/    (account_name + password)

Distinct from the old approval-queue flow at /api/v1/auth/admin/login/,
which stays untouched for admins that predate this feature (no
admin_account_name set).

The Admin and Learning Partner endpoints are two separate doors sharing the
same account-name shape: a Learning Partner account name is refused outright
on the Admin endpoint (LearningPartnerWrongPortalException, distinct
error_code so the frontend redirects rather than showing it inline), and an
Admin account name is refused on the Learning Partner endpoint the ordinary
"no such account" way (the role filter there is exact, not role__in).

Run: python manage.py test apps.accounts.tests.test_staff_login \
     --settings=config.settings.test
"""

from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User, UserRole
from apps.accounts.tests.helpers import (
    TEST_PASSWORD,
    login,
    make_learning_partner_admin,
    make_named_admin as _make_named_admin,
    make_user,
)

SUPERADMIN_LOGIN = "/api/v1/auth/staff/login-superadmin/"
ADMIN_LOGIN = "/api/v1/auth/staff/login-admin/"
LEARNING_PARTNER_LOGIN = "/api/v1/auth/staff/login-learning-partner/"


class StaffSuperAdminLoginTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_superadmin_signs_in_directly(self):
        sa = make_user(role=UserRole.SUPERADMIN)
        r = self.client.post(
            SUPERADMIN_LOGIN,
            {"email": sa.email, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertIn("access", r.cookies)

    def test_wrong_password_rejected(self):
        sa = make_user(role=UserRole.SUPERADMIN)
        r = self.client.post(
            SUPERADMIN_LOGIN, {"email": sa.email, "password": "wrong"}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_superadmin_role_rejected(self):
        for role in (UserRole.STUDENT, UserRole.TEACHER, UserRole.ADMIN):
            u = make_user(role=role, email=f"nope-{role}@example.com")
            r = self.client.post(
                SUPERADMIN_LOGIN, {"email": u.email, "password": TEST_PASSWORD}, format="json"
            )
            self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_email_rejected(self):
        r = self.client.post(
            SUPERADMIN_LOGIN,
            {"email": "nobody@example.com", "password": "whatever"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class StaffAdminLoginTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_admin_signs_in_with_account_name(self):
        admin = _make_named_admin()
        r = self.client.post(
            ADMIN_LOGIN,
            {"account_name": admin.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertIn("access", r.cookies)

    def test_first_login_notice_shown_exactly_once(self):
        admin = _make_named_admin(email="once@example.com", mobile="919000000201")
        r1 = self.client.post(
            ADMIN_LOGIN,
            {"account_name": admin.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertTrue(r1.json()["data"]["first_login_notice"])
        admin.refresh_from_db()
        self.assertTrue(admin.has_seen_admin_credentials_notice)

        r2 = self.client.post(
            ADMIN_LOGIN,
            {"account_name": admin.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertFalse(r2.json()["data"]["first_login_notice"])

    def test_wrong_password_rejected(self):
        admin = _make_named_admin(email="wrongpw@example.com", mobile="919000000202")
        r = self.client.post(
            ADMIN_LOGIN,
            {"account_name": admin.admin_account_name, "password": "wrong"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_account_name_rejected(self):
        r = self.client.post(
            ADMIN_LOGIN,
            {"account_name": "NobodyHere@Finance", "password": "whatever"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_legacy_admin_without_account_name_cannot_use_this_endpoint(self):
        legacy_admin = make_user(role=UserRole.ADMIN, email="legacy@example.com")
        r = self.client.post(
            ADMIN_LOGIN,
            {"account_name": legacy_admin.email, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_named_admin_cannot_use_old_email_login_endpoint(self):
        admin = _make_named_admin(email="oldpath@example.com", mobile="919000000203")
        r = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": admin.email, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)

    def test_legacy_admin_still_works_on_old_email_login_endpoint(self):
        legacy_admin = make_user(role=UserRole.ADMIN, email="stilllegacy@example.com")
        r = login(self.client, legacy_admin)
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_learning_partner_account_name_rejected_with_wrong_portal_code(self):
        """
        The core "prohibit every Learning Partner login attempt from the
        Admin page" rule: a Learning Partner account name - even with the
        CORRECT password - never signs in here. It gets a distinct
        error_code (LEARNING_PARTNER_WRONG_PORTAL) so the frontend can
        redirect to /learning-partner/login/ instead of showing the error
        inline (see static/js/auth.js's staffAdminLogin.submit()).
        """
        lp = make_learning_partner_admin("WrongPortalOrg", mobile="919000000210")
        r = self.client.post(
            ADMIN_LOGIN,
            {"account_name": lp.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assertEqual(
            r.json()["error"]["code"], "LEARNING_PARTNER_WRONG_PORTAL"
        )

    def test_learning_partner_account_name_rejected_even_with_wrong_password(self):
        # Prohibited outright, before any password check - not merely a
        # "bad credentials" style rejection.
        lp = make_learning_partner_admin("WrongPortalOrg2", mobile="919000000211")
        r = self.client.post(
            ADMIN_LOGIN,
            {"account_name": lp.admin_account_name, "password": "whatever-wrong"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assertEqual(
            r.json()["error"]["code"], "LEARNING_PARTNER_WRONG_PORTAL"
        )


class StaffLearningPartnerLoginTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_learning_partner_signs_in_with_account_name(self):
        lp = make_learning_partner_admin("LearnAcademy", mobile="919000000220")
        r = self.client.post(
            LEARNING_PARTNER_LOGIN,
            {"account_name": lp.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertIn("access", r.cookies)
        self.assertEqual(r.json()["data"]["user"]["role"], UserRole.LEARNING_PARTNER)

    def test_first_login_notice_shown_exactly_once(self):
        lp = make_learning_partner_admin("OnceOrg", mobile="919000000221")
        r1 = self.client.post(
            LEARNING_PARTNER_LOGIN,
            {"account_name": lp.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertTrue(r1.json()["data"]["first_login_notice"])
        lp.refresh_from_db()
        self.assertTrue(lp.has_seen_admin_credentials_notice)

        r2 = self.client.post(
            LEARNING_PARTNER_LOGIN,
            {"account_name": lp.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertFalse(r2.json()["data"]["first_login_notice"])

    def test_wrong_password_rejected(self):
        lp = make_learning_partner_admin("WrongPwOrg", mobile="919000000222")
        r = self.client.post(
            LEARNING_PARTNER_LOGIN,
            {"account_name": lp.admin_account_name, "password": "wrong"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_account_name_rejected(self):
        r = self.client.post(
            LEARNING_PARTNER_LOGIN,
            {"account_name": "NobodyHere@LearningPartner", "password": "whatever"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_account_name_rejected_on_learning_partner_endpoint(self):
        """The mirror-image rule: this endpoint only ever signs in role=learning_partner."""
        admin = _make_named_admin(
            email="notanlp@example.com", mobile="919000000223"
        )
        r = self.client.post(
            LEARNING_PARTNER_LOGIN,
            {"account_name": admin.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        # Ordinary "no such account" rejection, not the wrong-portal code -
        # there is no dedicated door to bounce an Admin to from here.
        self.assertNotEqual(
            r.json().get("error", {}).get("code"), "LEARNING_PARTNER_WRONG_PORTAL"
        )

    def test_inactive_learning_partner_cannot_sign_in(self):
        lp = make_learning_partner_admin(
            "InactiveOrg", mobile="919000000224", is_active=False
        )
        r = self.client.post(
            LEARNING_PARTNER_LOGIN,
            {"account_name": lp.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

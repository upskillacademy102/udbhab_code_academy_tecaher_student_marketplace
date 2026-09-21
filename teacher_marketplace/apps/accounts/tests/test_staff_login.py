"""
The hidden-gateway staff-login endpoints:
  POST /api/v1/auth/staff/login-superadmin/   (email + password)
  POST /api/v1/auth/staff/login-admin/        (account_name + password)

Distinct from the old approval-queue flow at /api/v1/auth/admin/login/,
which stays untouched for admins that predate this feature (no
admin_account_name set).

Run: python manage.py test apps.accounts.tests.test_staff_login \
     --settings=config.settings.test
"""

from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import AdminDepartment, User, UserRole
from apps.accounts.services.admin_account_naming import build_admin_account_name
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_user

SUPERADMIN_LOGIN = "/api/v1/auth/staff/login-superadmin/"
ADMIN_LOGIN = "/api/v1/auth/staff/login-admin/"


def _make_named_admin(**over):
    department, _ = AdminDepartment.objects.get_or_create(name="Finance")
    defaults = dict(
        first_name="Raju",
        last_name="Das",
        email="raju-named@example.com",
        mobile="919000000200",
    )
    defaults.update(over)
    account_name = build_admin_account_name(
        defaults["first_name"], defaults["last_name"], department
    )
    user = User.objects.create_user(
        password=TEST_PASSWORD,
        role=UserRole.ADMIN,
        admin_account_name=account_name,
        admin_department=department,
        **defaults,
    )
    return user


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

"""
Unit + DB tests for apps.accounts.services.admin_account_naming - the
FirstLast@Department admin login-identifier generator used by the
admin-account-request approval flow.

Run: python manage.py test apps.accounts.tests.test_admin_account_naming \
     --settings=config.settings.test
"""

from django.test import TestCase
from rest_framework.test import APITestCase

from apps.accounts.models import AdminAccountRequest, AdminDepartment, User, UserRole
from apps.accounts.services.admin_account_naming import (
    approve_and_create_admin,
    build_admin_account_name,
    normalize_name_part,
)
from apps.accounts.tests.helpers import make_user


class NormalizeNamePartTests(TestCase):
    def test_title_cases_each_token(self):
        self.assertEqual(normalize_name_part("raju"), "Raju")
        self.assertEqual(normalize_name_part("DAS"), "Das")
        self.assertEqual(normalize_name_part("van der Berg"), "VanDerBerg")

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(normalize_name_part("  Grace  "), "Grace")

    def test_empty_string(self):
        self.assertEqual(normalize_name_part(""), "")
        self.assertEqual(normalize_name_part("   "), "")


class BuildAdminAccountNameTests(TestCase):
    def setUp(self):
        # get_or_create: "Finance" already exists from the
        # 0006_seed_admin_departments data migration.
        self.department, _ = AdminDepartment.objects.get_or_create(name="Finance")

    def test_basic_format(self):
        self.assertEqual(
            build_admin_account_name("Raju", "Das", self.department), "RajuDas@Finance"
        )

    def test_normalizes_case(self):
        self.assertEqual(
            build_admin_account_name("raju", "DAS", self.department), "RajuDas@Finance"
        )

    def test_department_spaces_stripped(self):
        multi_word, _ = AdminDepartment.objects.get_or_create(name="Content Moderation")
        self.assertEqual(
            build_admin_account_name("Jane", "Doe", multi_word),
            "JaneDoe@ContentModeration",
        )


class ApproveAndCreateAdminTests(APITestCase):
    def setUp(self):
        self.department, _ = AdminDepartment.objects.get_or_create(name="Finance")
        self.superadmin = make_user(role=UserRole.SUPERADMIN)

    def _pending_request(self, **over):
        defaults = dict(
            email="raju@example.com",
            mobile="919000000100",
            first_name="Raju",
            last_name="Das",
            password_hash="pbkdf2_sha256$dummy$hash$value",
        )
        defaults.update(over)
        return AdminAccountRequest.objects.create(**defaults)

    def test_creates_user_with_generated_name_and_department(self):
        req = self._pending_request()
        user = approve_and_create_admin(
            req, department=self.department, reviewed_by=self.superadmin
        )
        self.assertEqual(user.role, UserRole.ADMIN)
        self.assertEqual(user.admin_account_name, "RajuDas@Finance")
        self.assertEqual(user.admin_department, self.department)
        self.assertTrue(user.is_active)

        req.refresh_from_db()
        self.assertEqual(req.status, "approved")
        self.assertEqual(req.created_user, user)
        self.assertEqual(req.department, self.department)
        self.assertEqual(req.reviewed_by, self.superadmin)
        self.assertIsNotNone(req.reviewed_at)

    def test_password_hash_copied_verbatim_not_rehashed(self):
        req = self._pending_request(
            email="verbatim@example.com", mobile="919000000101"
        )
        user = approve_and_create_admin(
            req, department=self.department, reviewed_by=self.superadmin
        )
        self.assertEqual(user.password, req.password_hash)

    def test_collision_gets_numeric_suffix(self):
        req1 = self._pending_request(
            email="raju1@example.com", mobile="919000000102"
        )
        user1 = approve_and_create_admin(
            req1, department=self.department, reviewed_by=self.superadmin
        )
        self.assertEqual(user1.admin_account_name, "RajuDas@Finance")

        req2 = self._pending_request(
            email="raju2@example.com", mobile="919000000103"
        )
        user2 = approve_and_create_admin(
            req2, department=self.department, reviewed_by=self.superadmin
        )
        self.assertEqual(user2.admin_account_name, "RajuDas2@Finance")

        req3 = self._pending_request(
            email="raju3@example.com", mobile="919000000104"
        )
        user3 = approve_and_create_admin(
            req3, department=self.department, reviewed_by=self.superadmin
        )
        self.assertEqual(user3.admin_account_name, "RajuDas3@Finance")

    def test_unrelated_name_sharing_a_prefix_does_not_false_positive(self):
        # "RajuDasgupta@Finance" starts with "RajuDas" and ends with
        # "@Finance" but is NOT a collision with "RajuDas@Finance" - a naive
        # startswith/endswith check would wrongly treat it as the "2" slot
        # being taken.
        req_gupta = self._pending_request(
            email="gupta@example.com",
            mobile="919000000107",
            first_name="Raju",
            last_name="Dasgupta",
        )
        user_gupta = approve_and_create_admin(
            req_gupta, department=self.department, reviewed_by=self.superadmin
        )
        self.assertEqual(user_gupta.admin_account_name, "RajuDasgupta@Finance")

        req_das = self._pending_request(
            email="das@example.com", mobile="919000000108"
        )
        user_das = approve_and_create_admin(
            req_das, department=self.department, reviewed_by=self.superadmin
        )
        self.assertEqual(user_das.admin_account_name, "RajuDas@Finance")

    def test_same_name_different_department_no_collision(self):
        support, _ = AdminDepartment.objects.get_or_create(name="Support")
        req1 = self._pending_request(email="a@example.com", mobile="919000000105")
        user1 = approve_and_create_admin(
            req1, department=self.department, reviewed_by=self.superadmin
        )
        req2 = self._pending_request(email="b@example.com", mobile="919000000106")
        user2 = approve_and_create_admin(
            req2, department=support, reviewed_by=self.superadmin
        )
        self.assertEqual(user1.admin_account_name, "RajuDas@Finance")
        self.assertEqual(user2.admin_account_name, "RajuDas@Support")

"""
Support-department admin's trimmed view of admin_users:list/detail
(apps.accounts.admin_api.SupportContactUserSerializer) - name, email, and
phone only, and only for student/teacher/learning_partner accounts.

Run: python manage.py test apps.accounts.tests.test_support_contact_serializer \
     --settings=config.settings.test
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_named_admin, make_user

OK = status.HTTP_200_OK
NOT_FOUND = status.HTTP_404_NOT_FOUND

_TRIMMED_FIELDS = {"id", "full_name", "email", "mobile", "role", "created_at"}
_FULL_ONLY_FIELDS = {"is_active", "is_staff", "profile_type", "admin_department_id"}


def _support_client(test):
    admin = make_named_admin(department="Support")
    c = test.client_class()
    login(c, admin)
    return admin, c


class SupportContactSerializerTests(APITestCase):
    def test_support_admin_sees_only_trimmed_fields_in_list(self):
        make_user(role=UserRole.STUDENT, first_name="Anita")
        _, c = _support_client(self)
        r = c.get("/api/v1/admin/users/")
        self.assertEqual(r.status_code, OK, r.content)
        items = r.data["data"]
        self.assertGreaterEqual(len(items), 1)
        row = items[0]
        self.assertEqual(set(row.keys()), _TRIMMED_FIELDS)
        self.assertFalse(_FULL_ONLY_FIELDS & set(row.keys()))

    def test_support_admin_sees_only_trimmed_fields_in_detail(self):
        student = make_user(role=UserRole.STUDENT)
        _, c = _support_client(self)
        r = c.get(f"/api/v1/admin/users/{student.id}/")
        self.assertEqual(r.status_code, OK, r.content)
        self.assertEqual(set(r.data["data"].keys()), _TRIMMED_FIELDS)

    def test_support_admin_list_excludes_admins_and_superadmins(self):
        make_user(role=UserRole.STUDENT)
        other_admin = make_named_admin(department="Finance", email="fin@x.test")
        sa = make_user(role=UserRole.SUPERADMIN)
        _, c = _support_client(self)
        r = c.get("/api/v1/admin/users/")
        self.assertEqual(r.status_code, OK, r.content)
        ids = {row["id"] for row in r.data["data"]}
        self.assertNotIn(str(other_admin.id), ids)
        self.assertNotIn(str(sa.id), ids)

    def test_support_admin_list_role_filter_ignores_admin_role(self):
        # Even if a Support admin explicitly asks for ?role=admin, the base
        # queryset is already restricted to student/teacher/learning_partner
        # before the ?role= filter is applied.
        make_named_admin(department="Finance", email="fin2@x.test")
        _, c = _support_client(self)
        r = c.get("/api/v1/admin/users/", {"role": "admin"})
        self.assertEqual(r.status_code, OK, r.content)
        self.assertEqual(r.data["data"], [])

    def test_support_admin_cannot_view_another_admins_detail(self):
        other_admin = make_named_admin(department="Finance", email="fin3@x.test")
        _, c = _support_client(self)
        r = c.get(f"/api/v1/admin/users/{other_admin.id}/")
        self.assertEqual(r.status_code, NOT_FOUND, r.content)

    def test_support_admin_can_view_learning_partner_detail(self):
        from apps.accounts.tests.helpers import make_learning_partner_admin

        lp = make_learning_partner_admin("Acme Tutors")
        _, c = _support_client(self)
        r = c.get(f"/api/v1/admin/users/{lp.id}/")
        self.assertEqual(r.status_code, OK, r.content)
        self.assertEqual(set(r.data["data"].keys()), _TRIMMED_FIELDS)

    def test_other_admin_still_sees_full_fields(self):
        # A departmentless admin (admin_users:list is denied to Finance
        # specifically, not to every other department/no department).
        make_user(role=UserRole.STUDENT)
        plain_admin = make_named_admin(department="Verification", email="ver4@x.test")
        c = self.client_class()
        login(c, plain_admin)
        r = c.get("/api/v1/admin/users/")
        self.assertEqual(r.status_code, OK, r.content)
        row = r.data["data"][0]
        self.assertIn("is_active", row)
        self.assertIn("profile_type", row)

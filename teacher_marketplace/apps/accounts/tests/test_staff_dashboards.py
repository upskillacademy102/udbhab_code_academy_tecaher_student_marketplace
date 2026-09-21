"""
Phase 4: the Super Admin dashboard overview extension, the sanctions
source/source_prefix filter, and the full ban -> unban round trip through
the API a real Super Admin's Users screen drives.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import AdminAccountRequest, AdminDepartment, UserRole
from apps.accounts.services.admin_account_naming import approve_and_create_admin
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_user
from apps.trust.models import AccountSanction, AccountSanctionSource
from apps.trust.services.sanction_service import SanctionService

FORBIDDEN = status.HTTP_403_FORBIDDEN
OK = status.HTTP_200_OK


def as_role(test, role):
    u = make_user(role)
    c = test.client_class()
    login(c, u)
    return u, c


class OpsOverviewExtensionTests(APITestCase):
    def test_overview_includes_taxonomy_and_pending_admin_account_requests(self):
        dept, _ = AdminDepartment.objects.get_or_create(name="Overview-Test-Dept")
        AdminAccountRequest.objects.create(
            email="pending-overview@udbhab.test",
            mobile="9199999601",
            first_name="Pending",
            last_name="One",
            password_hash="x",
        )
        _, sc = as_role(self, UserRole.SUPERADMIN)

        r = sc.get("/api/v1/ops/overview/")
        self.assertEqual(r.status_code, OK)
        data = r.data["data"]
        self.assertIn("taxonomy", data)
        self.assertIn("subjects", data["taxonomy"])
        self.assertIn("languages", data["taxonomy"])
        self.assertGreaterEqual(data["pending_admin_account_requests"], 1)
        dept.delete()

    def test_overview_still_super_admin_only(self):
        _, ac = as_role(self, UserRole.ADMIN)
        self.assertEqual(ac.get("/api/v1/ops/overview/").status_code, FORBIDDEN)


class OpsSanctionFilterTests(APITestCase):
    def test_source_and_source_prefix_filters(self):
        student = make_user(UserRole.STUDENT)
        teacher = make_user(UserRole.TEACHER)
        SanctionService.apply(student, source=AccountSanctionSource.MANUAL, reason="manual ban")
        SanctionService.apply(
            teacher,
            source=AccountSanctionSource.AUTO_STAFF_LOGIN_BRUTEFORCE,
            reason="10 failed attempts",
        )
        _, sc = as_role(self, UserRole.SUPERADMIN)

        r = sc.get("/api/v1/ops/sanctions/", {"source": "manual"})
        emails = [row["user_email"] for row in r.data["data"]]
        self.assertIn(student.email, emails)
        self.assertNotIn(teacher.email, emails)

        r = sc.get("/api/v1/ops/sanctions/", {"source_prefix": "auto_"})
        emails = [row["user_email"] for row in r.data["data"]]
        self.assertIn(teacher.email, emails)
        self.assertNotIn(student.email, emails)


class BanUnbanRoundTripTests(APITestCase):
    """
    The exact sequence the new Users.tsx / UserDetail.tsx screens drive:
    ban an admin (now sanctionable per the Phase 1 _PROTECTED_ROLES fix),
    confirm they're signed out and can't log back in, then unban and
    confirm they can.
    """

    def test_ban_then_unban_an_admin_via_the_dashboard_endpoints(self):
        dept, _ = AdminDepartment.objects.get_or_create(name="BanUnban-Test-Dept")
        req = AdminAccountRequest.objects.create(
            email="banunban@udbhab.test",
            mobile="9199999602",
            first_name="Ban",
            last_name="Target",
            password_hash="",
        )
        from django.contrib.auth.hashers import make_password

        req.password_hash = make_password(TEST_PASSWORD)
        req.save(update_fields=["password_hash"])
        admin = approve_and_create_admin(req, department=dept, reviewed_by=None)

        _, sc = as_role(self, UserRole.SUPERADMIN)

        # can log in before any sanction
        login_ok = self.client.post(
            "/api/v1/auth/staff/login-admin/",
            {"account_name": admin.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(login_ok.status_code, OK)

        # ban via the same endpoint the Users screen calls
        r = sc.post(
            "/api/v1/ops/sanctions/",
            {"user_id": str(admin.id), "kind": "ban", "reason": "test ban"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        sanction_id = r.data["data"]["id"]

        admin.refresh_from_db()
        self.assertFalse(admin.is_active)

        blocked = self.client.post(
            "/api/v1/auth/staff/login-admin/",
            {"account_name": admin.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)

        # unban via the lift endpoint the Users/UserDetail screens call
        r = sc.post(f"/api/v1/ops/sanctions/{sanction_id}/lift/", {}, format="json")
        self.assertEqual(r.status_code, OK)

        admin.refresh_from_db()
        self.assertTrue(admin.is_active)

        allowed_again = self.client.post(
            "/api/v1/auth/staff/login-admin/",
            {"account_name": admin.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(allowed_again.status_code, OK)

        self.assertFalse(AccountSanction.objects.get(id=sanction_id).active)

    def test_super_admin_cannot_be_banned(self):
        target = make_user(UserRole.SUPERADMIN)
        _, sc = as_role(self, UserRole.SUPERADMIN)
        r = sc.post(
            "/api/v1/ops/sanctions/",
            {"user_id": str(target.id), "kind": "ban"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_cannot_ban_anyone(self):
        target = make_user(UserRole.STUDENT)
        _, ac = as_role(self, UserRole.ADMIN)
        r = ac.post(
            "/api/v1/ops/sanctions/",
            {"user_id": str(target.id), "kind": "ban"},
            format="json",
        )
        self.assertEqual(r.status_code, FORBIDDEN)


class AdminUsersDirectoryPermissionTests(APITestCase):
    """Admin's read-only Users screen vs Super Admin's full one."""

    def test_admin_gets_list_and_detail_but_not_write(self):
        target = make_user(UserRole.STUDENT)
        _, ac = as_role(self, UserRole.ADMIN)
        self.assertEqual(ac.get("/api/v1/admin/users/").status_code, OK)
        self.assertEqual(ac.get(f"/api/v1/admin/users/{target.id}/").status_code, OK)
        self.assertEqual(
            ac.patch(
                f"/api/v1/admin/users/{target.id}/", {"is_active": False}, format="json"
            ).status_code,
            FORBIDDEN,
        )

    def test_superadmin_gets_full_access(self):
        target = make_user(UserRole.STUDENT)
        _, sc = as_role(self, UserRole.SUPERADMIN)
        self.assertEqual(sc.get("/api/v1/admin/users/").status_code, OK)
        self.assertEqual(
            sc.patch(
                f"/api/v1/admin/users/{target.id}/",
                {"is_mobile_verified": True},
                format="json",
            ).status_code,
            OK,
        )

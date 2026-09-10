"""
Centralised role -> method -> endpoint authorisation (the approved
permission matrix, 2026-08-29).

Covers: the registry decision function (default-deny + Super Admin
short-circuit), the role matrix at the HTTP layer, the search-privacy
rules, and "Super Admin can reach everything".
"""

import uuid

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.api_permissions import ROLE_API_PERMISSIONS, is_allowed, is_public
from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user

FORBIDDEN = status.HTTP_403_FORBIDDEN
UNAUTH = status.HTTP_401_UNAUTHORIZED
OK = status.HTTP_200_OK


def _client_for(test, user):
    c = test.client_class()
    login(c, user)
    return c


class RegistryUnitTests(APITestCase):
    def test_default_deny_unknown_role_route_method(self):
        self.assertFalse(is_allowed("wizard", "GET", "subjects:subject-list-create"))
        self.assertFalse(is_allowed(UserRole.ADMIN, "GET", "does:not-exist"))
        self.assertFalse(
            is_allowed(
                UserRole.STUDENT,
                "DELETE",
                "student_requirement:requirement-list-create",
            )
        )

    def test_super_admin_allowed_everywhere_including_unregistered(self):
        self.assertTrue(
            is_allowed(UserRole.SUPERADMIN, "GET", "subjects:subject-list-create")
        )
        self.assertTrue(is_allowed(UserRole.SUPERADMIN, "DELETE", "leads:whatever"))
        self.assertTrue(
            is_allowed(
                UserRole.SUPERADMIN, "POST", "brand:new-endpoint-nobody-registered"
            )
        )

    def test_method_level_grants(self):
        self.assertTrue(
            is_allowed(UserRole.ADMIN, "POST", "subjects:subject-list-create")
        )
        self.assertFalse(
            is_allowed(UserRole.TEACHER, "POST", "subjects:subject-list-create")
        )
        self.assertTrue(
            is_allowed(UserRole.TEACHER, "GET", "subjects:subject-list-create")
        )
        self.assertFalse(
            is_allowed(
                UserRole.STUDENT, "GET", "token-packages:token-package-list-create"
            )
        )
        self.assertTrue(
            is_allowed(
                UserRole.TEACHER, "GET", "token-packages:token-package-list-create"
            )
        )

    def test_search_rules_in_registry(self):
        # teacher search: student + admin yes, teacher no
        self.assertTrue(is_allowed(UserRole.STUDENT, "GET", "search:teacher-search"))
        self.assertTrue(is_allowed(UserRole.ADMIN, "GET", "search:teacher-search"))
        self.assertFalse(is_allowed(UserRole.TEACHER, "GET", "search:teacher-search"))
        # student/user search: admin only
        self.assertFalse(is_allowed(UserRole.STUDENT, "GET", "students:student-list"))
        self.assertFalse(is_allowed(UserRole.TEACHER, "GET", "students:student-list"))
        self.assertTrue(is_allowed(UserRole.ADMIN, "GET", "students:student-list"))

    def test_search_routes_are_no_longer_public(self):
        for route in (
            "search:teacher-search",
            "matching:eligible-search",
            "teacher-best-slots:teacher-best-slots",
        ):
            self.assertFalse(is_public(route), route)
        self.assertTrue(is_public("accounts:login"))

    def test_every_role_has_a_policy_table(self):
        self.assertEqual(
            set(ROLE_API_PERMISSIONS),
            {UserRole.STUDENT, UserRole.TEACHER, UserRole.ADMIN, UserRole.SUPERADMIN},
        )


class RoleMatrixTests(APITestCase):
    def setUp(self):
        self.student = make_user(UserRole.STUDENT)
        self.teacher = make_user(UserRole.TEACHER)
        self.admin = make_user(UserRole.ADMIN)
        self.superadmin = make_user(UserRole.SUPERADMIN)

    # ---- student ----------------------------------------------------------
    def test_student_own_workspace_ok(self):
        self.assertEqual(
            _client_for(self, self.student)
            .get("/api/v1/student-requirements/")
            .status_code,
            OK,
        )

    def test_student_denied_teacher_and_admin_routes(self):
        c = _client_for(self, self.student)
        self.assertEqual(c.get("/api/v1/leads/").status_code, FORBIDDEN)
        self.assertEqual(c.get("/api/v1/dashboard/").status_code, FORBIDDEN)
        self.assertEqual(c.get("/api/v1/students/").status_code, FORBIDDEN)
        self.assertEqual(
            c.post("/api/v1/subjects/", {"name": "X"}, format="json").status_code,
            FORBIDDEN,
        )

    # ---- teacher ---------------------------------------------------------
    def test_teacher_own_workspace_not_forbidden(self):
        c = _client_for(self, self.teacher)
        # 200 or 404 (no teacher profile yet) - never 401/403
        self.assertIn(
            c.get("/api/v1/leads/").status_code, (OK, status.HTTP_404_NOT_FOUND)
        )
        self.assertIn(
            c.get("/api/v1/wallet/").status_code, (OK, status.HTTP_404_NOT_FOUND)
        )

    def test_teacher_denied_search_and_admin(self):
        c = _client_for(self, self.teacher)
        self.assertEqual(c.get("/api/v1/students/").status_code, FORBIDDEN)
        self.assertEqual(c.get("/api/v1/teachers/").status_code, FORBIDDEN)
        self.assertEqual(c.get("/api/v1/search/teachers/").status_code, FORBIDDEN)
        self.assertEqual(
            c.post("/api/v1/subjects/", {}, format="json").status_code, FORBIDDEN
        )

    def test_teacher_reference_read_ok(self):
        self.assertEqual(
            _client_for(self, self.teacher).get("/api/v1/subjects/").status_code, OK
        )

    # ---- admin ---------------------------------------------------------
    def test_admin_can_search_people_and_write_reference(self):
        c = _client_for(self, self.admin)
        self.assertEqual(c.get("/api/v1/students/").status_code, OK)
        self.assertEqual(c.get("/api/v1/teachers/").status_code, OK)
        self.assertEqual(c.get("/api/v1/search/teachers/").status_code, OK)
        self.assertNotIn(
            c.post("/api/v1/subjects/", {}, format="json").status_code,
            (UNAUTH, FORBIDDEN),
        )

    def test_admin_denied_teacher_workflow(self):
        c = _client_for(self, self.admin)
        self.assertEqual(c.get("/api/v1/leads/").status_code, FORBIDDEN)
        self.assertEqual(c.get("/api/v1/wallet/").status_code, FORBIDDEN)
        self.assertEqual(c.get("/api/v1/subscriptions/quota/").status_code, FORBIDDEN)

    # ---- super admin ---------------------------------------------------
    def test_super_admin_reaches_everything(self):
        c = _client_for(self, self.superadmin)
        for url in (
            "/api/v1/students/",
            "/api/v1/teachers/",
            "/api/v1/search/teachers/",
            "/api/v1/subjects/",
            "/api/v1/leads/",
            "/api/v1/wallet/",
            "/api/v1/dashboard/",
            "/api/v1/matching/config/",
        ):
            self.assertNotIn(c.get(url).status_code, (UNAUTH, FORBIDDEN), msg=url)
        self.assertNotIn(
            c.post("/api/v1/subjects/", {}, format="json").status_code,
            (UNAUTH, FORBIDDEN),
        )


class SearchPrivacyTests(APITestCase):
    """The explicit search-security rules from the master prompt."""

    def setUp(self):
        self.student = make_user(UserRole.STUDENT)
        self.teacher = make_user(UserRole.TEACHER)
        self.admin = make_user(UserRole.ADMIN)
        self.superadmin = make_user(UserRole.SUPERADMIN)
        self.best_slots = f"/api/v1/teachers/{uuid.uuid4()}/best-slots/"

    def test_anonymous_cannot_search_teachers(self):
        self.assertEqual(
            self.client.get("/api/v1/search/teachers/").status_code, UNAUTH
        )
        self.assertEqual(self.client.get("/api/v1/teachers/").status_code, UNAUTH)
        self.assertEqual(self.client.get(self.best_slots).status_code, UNAUTH)
        self.assertEqual(
            self.client.get("/api/v1/matching/search/teachers/").status_code, UNAUTH
        )

    def test_student_teacher_search_yes_student_search_no(self):
        c = _client_for(self, self.student)
        self.assertEqual(c.get("/api/v1/search/teachers/").status_code, OK)
        self.assertEqual(c.get("/api/v1/teachers/").status_code, OK)
        self.assertNotIn(c.get(self.best_slots).status_code, (UNAUTH, FORBIDDEN))
        self.assertNotIn(
            c.get("/api/v1/matching/search/teachers/").status_code, (UNAUTH, FORBIDDEN)
        )
        # ...but never students / users
        self.assertEqual(c.get("/api/v1/students/").status_code, FORBIDDEN)

    def test_teacher_cannot_search_students_or_teachers(self):
        c = _client_for(self, self.teacher)
        self.assertEqual(c.get("/api/v1/students/").status_code, FORBIDDEN)
        self.assertEqual(c.get("/api/v1/search/teachers/").status_code, FORBIDDEN)
        self.assertEqual(c.get("/api/v1/teachers/").status_code, FORBIDDEN)
        self.assertEqual(c.get(self.best_slots).status_code, FORBIDDEN)
        self.assertEqual(
            c.get("/api/v1/matching/search/teachers/").status_code, FORBIDDEN
        )

    def test_admin_can_search_students_and_teachers(self):
        c = _client_for(self, self.admin)
        self.assertEqual(c.get("/api/v1/students/").status_code, OK)
        self.assertEqual(c.get("/api/v1/teachers/").status_code, OK)
        self.assertEqual(c.get("/api/v1/search/teachers/").status_code, OK)

    def test_super_admin_can_search_everything(self):
        c = _client_for(self, self.superadmin)
        for url in (
            "/api/v1/students/",
            "/api/v1/teachers/",
            "/api/v1/search/teachers/",
            self.best_slots,
            "/api/v1/matching/search/teachers/",
        ):
            self.assertNotIn(c.get(url).status_code, (UNAUTH, FORBIDDEN), msg=url)


class AnonymousAccessTests(APITestCase):
    def test_reference_read_requires_auth(self):
        self.assertEqual(self.client.get("/api/v1/subjects/").status_code, UNAUTH)

    def test_public_infra_still_open(self):
        # login endpoint reachable without auth (405/400 is fine, not 401)
        self.assertNotEqual(self.client.get("/api/v1/auth/login/").status_code, UNAUTH)

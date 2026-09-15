"""
Dual-role accounts: a Student adding/switching to a Teacher profile on
the same account, and vice versa. See apps.accounts.role_switch.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.role_switch import switch_active_role
from apps.accounts.tests.helpers import login, make_user
from apps.students.models import Student
from apps.teachers.models import Teacher


class SwitchActiveRoleUnitTests(APITestCase):
    def test_creates_missing_teacher_profile_and_flips_role(self):
        user = make_user(role=UserRole.STUDENT)
        self.assertFalse(Teacher.objects.filter(user=user).exists())

        created = switch_active_role(user, UserRole.TEACHER)

        self.assertTrue(created)
        self.assertTrue(Teacher.objects.filter(user=user).exists())
        user.refresh_from_db()
        self.assertEqual(user.role, UserRole.TEACHER)

    def test_creates_missing_student_profile_and_flips_role(self):
        user = make_user(role=UserRole.TEACHER)
        self.assertFalse(Student.objects.filter(user=user).exists())

        created = switch_active_role(user, UserRole.STUDENT)

        self.assertTrue(created)
        self.assertTrue(Student.objects.filter(user=user).exists())
        user.refresh_from_db()
        self.assertEqual(user.role, UserRole.STUDENT)

    def test_idempotent_for_a_user_who_already_has_both(self):
        user = make_user(role=UserRole.STUDENT)
        Teacher.objects.create(user=user)

        created = switch_active_role(user, UserRole.TEACHER)

        self.assertFalse(created)
        self.assertEqual(Teacher.objects.filter(user=user).count(), 1)
        user.refresh_from_db()
        self.assertEqual(user.role, UserRole.TEACHER)

    def test_rejects_admin_and_superadmin_targets(self):
        user = make_user(role=UserRole.STUDENT)
        with self.assertRaises(Exception):
            switch_active_role(user, UserRole.ADMIN)
        with self.assertRaises(Exception):
            switch_active_role(user, UserRole.SUPERADMIN)


class SwitchRoleEndpointTests(APITestCase):
    def test_student_can_add_teacher_role(self):
        user = make_user(role=UserRole.STUDENT)
        client = self.client_class()
        login(client, user)

        resp = client.post(
            "/api/v1/auth/switch-role/", {"role": "teacher"}, format="json"
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.json()
        self.assertEqual(body["data"]["user"]["role"], "teacher")
        self.assertTrue(body["data"]["profile_created"])
        self.assertTrue(body["data"]["user"]["has_teacher_profile"])
        # No Student row exists for this user (make_user only creates the
        # bare User) - has_student_profile correctly stays False; adding
        # the Teacher role must never touch the Student side either way.
        self.assertFalse(body["data"]["user"]["has_student_profile"])

    def test_switching_back_does_not_duplicate_or_lose_the_other_profile(self):
        user = make_user(role=UserRole.STUDENT)
        client = self.client_class()
        login(client, user)

        client.post("/api/v1/auth/switch-role/", {"role": "teacher"}, format="json")
        resp = client.post(
            "/api/v1/auth/switch-role/", {"role": "student"}, format="json"
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["data"]["user"]["role"], "student")
        self.assertEqual(Teacher.objects.filter(user=user).count(), 1)
        self.assertEqual(Student.objects.filter(user=user).count(), 1)

    def test_switch_role_requires_authentication(self):
        client = self.client_class()
        resp = client.post(
            "/api/v1/auth/switch-role/", {"role": "teacher"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_role_is_rejected(self):
        user = make_user(role=UserRole.STUDENT)
        client = self.client_class()
        login(client, user)

        resp = client.post(
            "/api/v1/auth/switch-role/", {"role": "superadmin"}, format="json"
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

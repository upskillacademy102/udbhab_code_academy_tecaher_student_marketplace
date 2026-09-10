"""
Home / registration / login UX + the auth gateway.

Run:  python manage.py test apps.web --settings=config.settings.test
"""

from django.test import TestCase
from rest_framework.test import APITestCase

from apps.accounts.models import User, UserRole
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_user

REG = "/api/v1/auth/register/"


class PublicPageTests(TestCase):

    def test_landing_offers_both_create_account_and_login(self):
        html = self.client.get("/").content.decode()
        self.assertIn("/register/", html)
        self.assertIn("/login/", html)
        self.assertIn("Create", html)

    def test_register_page_renders_for_anonymous(self):
        resp = self.client.get("/register/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Create your account", resp.content.decode())

    def test_register_page_only_mentions_student_and_teacher(self):
        html = self.client.get("/register/").content.decode().lower()
        self.assertIn("student", html)
        self.assertIn("teacher", html)
        # No public path to privileged roles from the registration screen.
        self.assertNotIn("super admin", html)
        self.assertNotIn('"admin"', html)

    def test_login_page_links_to_registration(self):
        html = self.client.get("/login/").content.decode()
        self.assertIn("/register/", html)

    def test_login_page_accepts_registered_and_email_hints(self):
        resp = self.client.get("/login/?as=student&registered=1&email=x@y.com")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("x@y.com", resp.content.decode())

    def test_authenticated_user_is_redirected_away_from_register(self):
        client = self.client_class()
        student = make_user(role=UserRole.STUDENT)
        login(client, student)
        resp = client.get("/register/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/student/")


class RequirementScheduleUiTests(TestCase):
    """H.3: the requirement form collects structured day/time windows."""

    def test_form_renders_structured_schedule_controls(self):
        client = self.client_class()
        login(client, make_user(role=UserRole.STUDENT))
        html = client.get("/student/requirements/").content.decode()
        self.assertIn("When can you attend?", html)
        self.assertIn("schedule_preferences", html)  # transform builds this key
        self.assertIn("model.windows", html)  # repeatable day/time rows
        self.assertIn("Timing notes", html)  # free-text kept, now optional


class AuthGatewayTests(TestCase):

    def test_anonymous_protected_page_redirects_to_login_with_next(self):
        resp = self.client.get("/student/requirements/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/?next=", resp["Location"])
        self.assertIn("requirements", resp["Location"])

    def test_wrong_role_gets_403_not_redirect(self):
        client = self.client_class()
        login(client, make_user(role=UserRole.TEACHER))
        resp = client.get("/student/requirements/")
        self.assertEqual(resp.status_code, 403)


class RegistrationApiTests(APITestCase):

    BASE = {
        "first_name": "Rahul",
        "last_name": "Sharma",
        "mobile": "9800011122",
        "password": TEST_PASSWORD,
        "password_confirm": TEST_PASSWORD,
    }

    def test_student_can_register_then_log_in_to_the_student_area(self):
        resp = self.client.post(
            REG,
            {**self.BASE, "email": "rahul@student.test", "role": "student"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        user = User.objects.get(email="rahul@student.test")
        self.assertEqual(user.role, UserRole.STUDENT)

        login_resp = self.client.post(
            "/api/v1/auth/login/",
            {"email": "rahul@student.test", "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(login_resp.status_code, 200)
        self.assertEqual(login_resp.json()["data"]["user"]["role"], "student")

    def test_teacher_can_register(self):
        resp = self.client.post(
            REG,
            {
                **self.BASE,
                "email": "t@teacher.test",
                "mobile": "9800011133",
                "role": "teacher",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_duplicate_email_is_rejected_without_creating_a_second_account(self):
        make_user(role=UserRole.STUDENT, email="taken@x.test", mobile="9811100011")
        resp = self.client.post(
            REG,
            {**self.BASE, "email": "taken@x.test", "role": "student"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        # The frontend keys the "log in instead" branch off this text.
        self.assertIn("exist", str(resp.json()).lower())
        self.assertEqual(User.objects.filter(email__iexact="taken@x.test").count(), 1)

    def test_admin_role_cannot_self_register(self):
        for role in ("admin", "superadmin"):
            resp = self.client.post(
                REG,
                {
                    **self.BASE,
                    "email": f"{role}@x.test",
                    "mobile": "981110" + role[:4].ljust(4, "0"),
                    "role": role,
                },
                format="json",
            )
            self.assertEqual(resp.status_code, 400, role)
            self.assertFalse(User.objects.filter(email=f"{role}@x.test").exists())

    def test_weak_password_is_rejected_with_a_field_error(self):
        resp = self.client.post(
            REG,
            {
                **self.BASE,
                "email": "weak@x.test",
                "password": "password",
                "password_confirm": "password",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("password", str(resp.json()).lower())

    def test_password_mismatch_is_rejected(self):
        resp = self.client.post(
            REG,
            {**self.BASE, "email": "mm@x.test", "password_confirm": "Different1!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

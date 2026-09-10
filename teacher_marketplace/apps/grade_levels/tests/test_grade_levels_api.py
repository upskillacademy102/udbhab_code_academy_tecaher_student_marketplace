"""
`/api/v1/grade-levels/` - the admin-manageable class/year taxonomy that
feeds the Student profile and requirement-posting dropdowns.

Run: python manage.py test apps.grade_levels --settings=config.settings.test
"""

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.grade_levels.models import GradeLevel

LIST_URL = "/api/v1/grade-levels/"


class GradeLevelSeedTests(APITestCase):
    def test_seed_data_is_present(self):
        names = set(GradeLevel.objects.values_list("name", flat=True))
        for expected in ("Class 10", "Undergraduate", "Adult Learner"):
            self.assertIn(expected, names)

    def test_seed_data_is_sorted_naturally_not_alphabetically(self):
        ordered = list(GradeLevel.objects.values_list("name", flat=True))
        self.assertLess(ordered.index("Class 2"), ordered.index("Class 10"))


class GradeLevelReadAccessTests(APITestCase):
    def test_any_authenticated_role_can_list(self):
        for role in (UserRole.STUDENT, UserRole.TEACHER, UserRole.ADMIN):
            c = self.client_class()
            login(c, make_user(role=role, email=f"read-{role}@x.test"))
            self.assertEqual(c.get(LIST_URL).status_code, 200)

    def test_anonymous_cannot_list(self):
        self.assertEqual(self.client.get(LIST_URL).status_code, 401)


class GradeLevelValidationTests(APITestCase):
    def setUp(self):
        login(self.client, make_user(role=UserRole.ADMIN))

    def _post(self, expect=201, **fields):
        r = self.client.post(LIST_URL, fields, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_valid(self):
        self._post(name="Diploma", sort_order=13)

    def test_junk_names_rejected(self):
        for n in ("12345", "!!! @@@", "bad <name>", "   "):
            self._post(400, name=n)

    def test_duplicate_name_rejected_case_insensitively(self):
        self._post(name="Foundation Year")
        self._post(400, name="foundation year")

    def test_db_check_blocks_blank_name(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            GradeLevel.objects.create(name="   ")

    def test_student_cannot_write(self):
        c = self.client_class()
        login(c, make_user(role=UserRole.STUDENT))
        r = c.post(LIST_URL, {"name": "Should Fail"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_admin_can_deactivate(self):
        row = GradeLevel.objects.get(name="Hobby / Other")
        r = self.client.patch(
            f"{LIST_URL}{row.id}/", {"is_active": False}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.content)
        row.refresh_from_db()
        self.assertFalse(row.is_active)

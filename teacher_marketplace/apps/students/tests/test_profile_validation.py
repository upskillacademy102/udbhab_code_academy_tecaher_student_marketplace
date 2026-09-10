"""
Data-quality hardening for the student profile endpoint (`/api/v1/students/me/`).

The optional text fields (city / state / country / grade_or_year /
preferred_subjects / bio) used to accept anything up to their max_length -
digits-only cities, injection strings, 500-char "subjects", blank strings, etc.
They are now validated at the model layer (propagated to the serializer) plus a
DB CHECK constraint that forbids whitespace-only values.

Run: python manage.py test apps.students.tests.test_profile_validation \
     --settings=config.settings.test
"""

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.students.models import Student

ME = "/api/v1/students/me/"


class StudentProfileValidationTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.STUDENT)
        login(self.client, self.user)
        self.client.post(ME, {"bio": "hi"}, format="json")  # ensure profile exists

    def _patch(self, **fields):
        return self.client.patch(ME, fields, format="json")

    # ---- valid input still works --------------------------------------
    def test_realistic_profile_saves(self):
        resp = self._patch(
            city="Kolkata",
            state="West Bengal",
            country="India",
            grade_or_year="Grade 10",
            education_level="high_school",
            preferred_subjects="Maths, Physics, Chemistry",
            bio="Looking for JEE preparation help.",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_place_names_with_legitimate_punctuation_pass(self):
        for city in (
            "St. John's",
            "Sector-21, Gurugram",
            "Al Ain",
            "Stratford-upon-Avon",
        ):
            self.assertEqual(self._patch(city=city).status_code, 200, city)

    def test_whitespace_is_trimmed(self):
        self._patch(city="  Pune  ", grade_or_year="  2nd Year B.Sc  ")
        s = Student.objects.get(user=self.user)
        self.assertEqual(s.city, "Pune")
        self.assertEqual(s.grade_or_year, "2nd Year B.Sc")

    # ---- junk is rejected -------------------------------------------
    def test_junk_place_names_are_rejected(self):
        for bad in ("12345", "!!!@@@", "asdf<script>", "   .  "):
            self.assertEqual(self._patch(city=bad).status_code, 400, bad)

    def test_control_characters_and_angle_brackets_rejected(self):
        self.assertEqual(self._patch(grade_or_year="line1\nline2\x00").status_code, 400)
        self.assertEqual(
            self._patch(preferred_subjects="Maths<>Physics").status_code, 400
        )

    def test_length_caps_enforced(self):
        self.assertEqual(self._patch(country="x" * 150).status_code, 400)
        self.assertEqual(self._patch(bio="y" * 1001).status_code, 400)

    def test_invalid_education_level_choice_rejected(self):
        self.assertEqual(self._patch(education_level="phd_wizardry").status_code, 400)

    # ---- preferred_subjects normalisation -------------------------
    def test_preferred_subjects_dedupes_and_caps(self):
        r = self._patch(preferred_subjects="Maths, maths, MATHS, Physics")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            Student.objects.get(user=self.user).preferred_subjects, "Maths, Physics"
        )

        self.assertEqual(
            self._patch(
                preferred_subjects=", ".join(f"Subj{i}" for i in range(20))
            ).status_code,
            400,
        )
        self.assertEqual(self._patch(preferred_subjects="z" * 70).status_code, 400)

    # ---- blank strings never reach the DB -------------------------
    def test_whitespace_only_optional_field_becomes_null(self):
        self.assertEqual(self._patch(city="   ").status_code, 200)
        self.assertIsNone(Student.objects.get(user=self.user).city)

    def test_db_constraint_blocks_a_blank_string_written_directly(self):
        from django.db import IntegrityError, transaction

        s = Student.objects.get(user=self.user)
        s.city = "   "
        with self.assertRaises(IntegrityError), transaction.atomic():
            s.save(update_fields=["city"])

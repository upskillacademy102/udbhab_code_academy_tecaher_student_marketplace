"""
Data-quality hardening for the teacher-facing write endpoints:
  - `POST /api/v1/teachers/me/`                         (basic profile)
  - `POST /api/v1/teachers/profile/`                    (marketplace profile)
  - `POST /api/v1/teachers/profile/weekly-availability/`
  - `POST /api/v1/teachers/profile/schedule-exceptions/`

Run: python manage.py test apps.teacher_profile.tests.test_profile_validation \
     --settings=config.settings.test
"""

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.languages.models import Language
from apps.subjects.models import Subject
from apps.teacher_profile.models import (
    TeacherProfile,
    TeacherScheduleException,
    TeacherWeeklyAvailability,
)
from apps.teachers.models import Teacher


class TeacherBasicProfileValidationTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.TEACHER)
        Teacher.objects.create(user=self.user)
        login(self.client, self.user)

    def _post(self, expect=200, **fields):
        r = self.client.post("/api/v1/teachers/me/", fields, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_valid_profile(self):
        self._post(
            bio="15 years teaching maths.",
            experience_years=15,
            qualification_level="masters",
            qualification_detail="M.Sc Physics, DU",
            subjects_taught="Maths, Physics",
            city="Kolkata",
            state="West Bengal",
            country="India",
        )
        self._post(city="St. John's", qualification_detail="B.Ed (Hons.)")

    def test_junk_rejected(self):
        self._post(400, experience_years=200)
        self._post(400, experience_years=-1)
        self._post(400, bio="z" * 2001)
        self._post(400, city="99999")
        self._post(400, state="hi <b>")
        self._post(400, qualification_detail="M.Sc\x00Physics")
        self._post(400, qualification_level="space_wizard")
        self._post(400, subjects_taught=", ".join(f"Subj{i}" for i in range(25)))
        self._post(400, subjects_taught="z" * 70)

    def test_subjects_taught_dedupes(self):
        self._post(subjects_taught="Maths, maths, MATHS, Physics")
        self.assertEqual(
            Teacher.objects.get(user=self.user).subjects_taught, "Maths, Physics"
        )

    def test_whitespace_only_becomes_null_and_db_blocks_blank(self):
        self._post(city="   ")
        self.assertIsNone(Teacher.objects.get(user=self.user).city)
        t = Teacher.objects.get(user=self.user)
        t.city = "  "
        with self.assertRaises(IntegrityError), transaction.atomic():
            t.save(update_fields=["city"])


class TeacherMarketplaceProfileValidationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.math = Subject.objects.create(name="Mathematics")
        cls.eng = Language.objects.create(name="English", code="en")

    def setUp(self):
        self.user = make_user(role=UserRole.TEACHER)
        Teacher.objects.create(user=self.user)
        login(self.client, self.user)

    def _post(self, expect=200, **fields):
        r = self.client.post("/api/v1/teachers/profile/", fields, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_valid(self):
        self._post(
            201,
            headline="Experienced tutor",
            teaching_mode="online",
            hourly_rate="800.00",
            subjects=[self.math.id],
            languages=[self.eng.id],
        )

    def test_junk_rejected(self):
        self._post(400, headline="bad <headline>")
        self._post(400, headline="ok\x00nope")
        self._post(400, hourly_rate="9999999.00")
        self._post(400, hourly_rate="-1")
        self._post(400, teaching_mode="hologram")
        self._post(400, subjects=[self.math.id] * 40)

    def test_headline_whitespace_becomes_null_and_db_blocks_blank(self):
        self._post(201, headline="   ", hourly_rate="100")
        p = TeacherProfile.objects.get(teacher__user=self.user)
        self.assertIsNone(p.headline)
        p.headline = "  "
        with self.assertRaises(IntegrityError), transaction.atomic():
            p.save(update_fields=["headline"])


class TeacherAvailabilityValidationTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.TEACHER)
        t = Teacher.objects.create(user=self.user)
        self.profile = TeacherProfile.objects.create(teacher=t)
        login(self.client, self.user)

    def test_weekly_availability_db_checks(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeacherWeeklyAvailability.objects.create(
                teacher_profile=self.profile,
                day_of_week=1,
                start_time="20:00",
                end_time="18:00",
                timezone="Asia/Kolkata",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeacherWeeklyAvailability.objects.create(
                teacher_profile=self.profile,
                day_of_week=1,
                start_time="10:00",
                end_time="11:00",
                timezone="   ",
            )

    def test_schedule_exception_api_and_db(self):
        # half-specified time range -> 400
        self.assertEqual(
            self.client.post(
                "/api/v1/teachers/profile/schedule-exceptions/",
                {
                    "date": "2026-12-26",
                    "exception_type": "temporary_unavailable",
                    "start_time": "10:00",
                    "timezone": "Asia/Kolkata",
                },
                format="json",
            ).status_code,
            400,
        )
        # control char in reason -> 400
        self.assertEqual(
            self.client.post(
                "/api/v1/teachers/profile/schedule-exceptions/",
                {
                    "date": "2026-12-27",
                    "reason": "x\x00y",
                    "exception_type": "holiday",
                    "timezone": "Asia/Kolkata",
                },
                format="json",
            ).status_code,
            400,
        )
        # DB CHECK: end before start
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeacherScheduleException.objects.create(
                teacher_profile=self.profile,
                date="2026-12-28",
                start_time="18:00",
                end_time="10:00",
                timezone="Asia/Kolkata",
            )

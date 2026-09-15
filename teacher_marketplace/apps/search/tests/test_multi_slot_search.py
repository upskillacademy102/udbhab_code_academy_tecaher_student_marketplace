"""
Multi-slot schedule-aware search: a student free at more than one
distinct day+time (e.g. Monday 7pm AND Tuesday 8am - different times,
not one time applied to both days) via `preferred_slots`.

Run:  python manage.py test apps.search --settings=config.settings.test
"""

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.subjects.models import Subject
from apps.teacher_profile.models import (
    TeacherProfile,
    TeacherWeeklyAvailability,
    TeachingMode,
    VerificationStatus,
)
from apps.teachers.models import Teacher

URL = "/api/v1/search/teachers/"
TZ = "Asia/Kolkata"


class MultiSlotSearchTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.subject = Subject.objects.create(name="Violin")

        # Only free Tuesday mornings - matches the student's SECOND slot only.
        u1 = make_user(role=UserRole.TEACHER, email="tue.only@g.test", first_name="TueOnly")
        t1 = Teacher.objects.create(user=u1)
        cls.p1 = TeacherProfile.objects.create(
            teacher=t1, teaching_mode=TeachingMode.BOTH,
            verification_status=VerificationStatus.VERIFIED,
        )
        cls.p1.subjects.set([cls.subject])
        TeacherWeeklyAvailability.objects.create(
            teacher_profile=cls.p1, day_of_week=2, start_time="08:00", end_time="09:00",
            timezone=TZ, is_active=True,
        )

        # Only free Monday evenings - matches the student's FIRST slot only.
        u2 = make_user(role=UserRole.TEACHER, email="mon.only@g.test", first_name="MonOnly")
        t2 = Teacher.objects.create(user=u2)
        cls.p2 = TeacherProfile.objects.create(
            teacher=t2, teaching_mode=TeachingMode.BOTH,
            verification_status=VerificationStatus.VERIFIED,
        )
        cls.p2.subjects.set([cls.subject])
        TeacherWeeklyAvailability.objects.create(
            teacher_profile=cls.p2, day_of_week=1, start_time="19:00", end_time="20:00",
            timezone=TZ, is_active=True,
        )

        # Free neither - matches nothing.
        u3 = make_user(role=UserRole.TEACHER, email="neither@g.test", first_name="Neither")
        t3 = Teacher.objects.create(user=u3)
        cls.p3 = TeacherProfile.objects.create(
            teacher=t3, teaching_mode=TeachingMode.BOTH,
            verification_status=VerificationStatus.VERIFIED,
        )
        cls.p3.subjects.set([cls.subject])
        TeacherWeeklyAvailability.objects.create(
            teacher_profile=cls.p3, day_of_week=3, start_time="10:00", end_time="11:00",
            timezone=TZ, is_active=True,
        )

    def setUp(self):
        login(self.client, make_user(role=UserRole.STUDENT))

    def test_teacher_matching_either_slot_scores_above_zero(self):
        import json

        slots = json.dumps([
            {"day": 1, "start_time": "19:00", "end_time": "20:00"},  # Monday 7pm
            {"day": 2, "start_time": "08:00", "end_time": "09:00"},  # Tuesday 8am
        ])
        resp = self.client.get(URL, {
            "subject": "Violin", "preferred_slots": slots, "timezone": TZ,
        })
        self.assertEqual(resp.status_code, 200)
        by_name = {
            r["teacher"]["user"]["full_name"]: r["match_percentage"]
            for r in resp.json()["data"]
        }
        self.assertGreater(by_name["TueOnly User"], 0)
        self.assertGreater(by_name["MonOnly User"], 0)
        self.assertEqual(by_name["Neither User"], 0)

    def test_malformed_preferred_slots_is_a_clean_400(self):
        resp = self.client.get(URL, {"subject": "Violin", "preferred_slots": "not json"})
        self.assertEqual(resp.status_code, 400)

    def test_empty_preferred_slots_array_is_a_clean_400(self):
        resp = self.client.get(URL, {"subject": "Violin", "preferred_slots": "[]"})
        self.assertEqual(resp.status_code, 400)

    def test_legacy_single_slot_params_still_work(self):
        resp = self.client.get(URL, {
            "subject": "Violin", "preferred_day": 1,
            "preferred_start_time": "19:00", "preferred_end_time": "20:00",
            "timezone": TZ,
        })
        self.assertEqual(resp.status_code, 200)
        by_name = {
            r["teacher"]["user"]["full_name"]: r["match_percentage"]
            for r in resp.json()["data"]
        }
        self.assertGreater(by_name["MonOnly User"], 0)
        self.assertEqual(by_name["TueOnly User"], 0)

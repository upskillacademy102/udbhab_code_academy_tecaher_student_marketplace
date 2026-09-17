"""
Data-quality hardening for the student requirement endpoint
(`/api/v1/student-requirements/`) and its schedule preference / exception rows.

Adds: budget ceiling (10,000,000 - a per-month figure) + DB CHECK `budget_min <= budget_max`;
duration DB CHECK 15-480; `description` capped at 2000 chars; control-char
rejection on `student_class` / `preferred_timing` / exception `reason`;
`""`/whitespace normalised to NULL with a DB not-blank CHECK; max 20 schedule
windows; DB CHECK `start_time < end_time` on preference rows.

Run: python manage.py test apps.student_requirement.tests.test_requirement_validation \
     --settings=config.settings.test
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.languages.models import Language
from apps.lead_engine.models import Lead
from apps.student_requirement.models import (
    RequirementStatus,
    StudentRequirement,
    StudentSchedulePreference,
)
from apps.subjects.models import Subject
from apps.teacher_profile.models import TeacherProfile, VerificationStatus
from apps.teachers.models import Teacher

REQS = "/api/v1/student-requirements/"


class RequirementValidationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Subject.objects.get_or_create(name="Mathematics")
        Language.objects.get_or_create(name="English", defaults={"code": "en"})

    def setUp(self):
        self.user = make_user(role=UserRole.STUDENT)
        login(self.client, self.user)

    def _post(self, expect=202, **extra):
        StudentRequirement.objects.filter(student=self.user).delete()
        body = {
            "subject": "Mathematics",
            "preferred_languages": ["English"],
            "teaching_mode": "online",
            "class_duration_minutes": 60,
            **extra,
        }
        resp = self.client.post(REQS, body, format="json")
        self.assertEqual(resp.status_code, expect, resp.content)
        return resp

    # ---- valid -------------------------------------------------------
    def test_normal_requirement(self):
        self._post(
            student_class="Grade 10",
            budget_min=200,
            budget_max=1500,
            preferred_timing="Weekday evenings",
            description="JEE prep",
            class_duration_minutes=90,
        )

    def test_preset_durations_ok_custom_rejected(self):
        for d in (30, 45, 60, 90, 120):
            self._post(class_duration_minutes=d)
        self._post(expect=400, class_duration_minutes=37)
        self._post(expect=400, class_duration_minutes=5)
        self._post(expect=400, class_duration_minutes=600)

    # ---- budget ----------------------------------------------------
    def test_budget_rules(self):
        self._post(expect=400, budget_min=900, budget_max=100)  # min > max
        self._post(expect=400, budget_min=-1)  # negative
        self._post(expect=400, budget_max="50000000")  # over ceiling
        self._post(budget_min=0, budget_max=0)  # zero ok

    def test_db_check_blocks_inverted_budget_written_directly(self):
        s = Subject.objects.get(name="Mathematics")
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentRequirement.objects.create(
                student=self.user,
                subject=s,
                budget_min=Decimal("500"),
                budget_max=Decimal("100"),
                class_duration_minutes=60,
            )

    # ---- free text -----------------------------------------------
    def test_text_field_hygiene(self):
        self._post(expect=400, student_class="Grade\x0010")
        self._post(expect=400, preferred_timing="evenings <script>")
        self._post(expect=400, description="d" * 2001)
        self._post(description="d" * 2000)  # exactly at cap

    def test_whitespace_only_text_becomes_null(self):
        self._post(student_class="   ", preferred_timing="  ")
        r = StudentRequirement.objects.get(student=self.user)
        self.assertIsNone(r.student_class)
        self.assertIsNone(r.preferred_timing)

    # ---- schedule preferences -----------------------------------
    def test_at_most_20_schedule_windows(self):
        windows = [
            {
                "day_of_week": (i % 7) + 1,
                "start_time": f"{6 + i % 12:02d}:00",
                "end_time": f"{7 + i % 12:02d}:00",
                "timezone": "Asia/Kolkata",
            }
            for i in range(21)
        ]
        self._post(expect=400, schedule_preferences=windows)

    def test_preference_end_must_be_after_start(self):
        self._post(
            expect=400,
            schedule_preferences=[
                {
                    "day_of_week": 1,
                    "start_time": "20:00",
                    "end_time": "18:00",
                    "timezone": "Asia/Kolkata",
                }
            ],
        )

    def test_db_check_blocks_bad_preference_written_directly(self):
        s = Subject.objects.get(name="Mathematics")
        req = StudentRequirement.objects.create(
            student=self.user, subject=s, class_duration_minutes=60
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentSchedulePreference.objects.create(
                student_requirement=req,
                day_of_week=1,
                start_time="19:00",
                end_time="18:00",
                timezone="Asia/Kolkata",
            )


class RequirementEditLockTests(APITestCase):
    """
    A requirement stays editable regardless of `status` - MATCHED included,
    since that flips the moment a teacher is merely soft-matched (a Lead
    row exists), long before anyone unlocks anything. The real lock is a
    teacher actually unlocking the requirement's contact details.
    """

    @classmethod
    def setUpTestData(cls):
        Subject.objects.get_or_create(name="Mathematics")
        Language.objects.get_or_create(name="English", defaults={"code": "en"})

    def setUp(self):
        self.user = make_user(role=UserRole.STUDENT)
        login(self.client, self.user)
        self.subject = Subject.objects.get(name="Mathematics")

    def _make_teacher_profile(self):
        teacher_user = make_user(role=UserRole.TEACHER)
        teacher = Teacher.objects.create(user=teacher_user)
        return TeacherProfile.objects.create(
            teacher=teacher, verification_status=VerificationStatus.VERIFIED
        )

    def test_matched_requirement_with_no_unlock_is_still_editable(self):
        req = StudentRequirement.objects.create(
            student=self.user,
            subject=self.subject,
            teaching_mode="online",
            class_duration_minutes=60,
            no_language_preference=True,
            status=RequirementStatus.MATCHED,
        )
        Lead.objects.create(
            student_requirement=req,
            teacher_profile=self._make_teacher_profile(),
            contact_unlocked=False,
        )
        resp = self.client.patch(
            f"{REQS}{req.id}/", {"description": "updated"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.json()["data"]["has_unlocked_lead"])

    def test_unlocked_requirement_cannot_be_edited(self):
        req = StudentRequirement.objects.create(
            student=self.user,
            subject=self.subject,
            class_duration_minutes=60,
            no_language_preference=True,
            status=RequirementStatus.MATCHED,
        )
        Lead.objects.create(
            student_requirement=req,
            teacher_profile=self._make_teacher_profile(),
            contact_unlocked=True,
        )
        resp = self.client.patch(
            f"{REQS}{req.id}/", {"description": "updated"}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        req.refresh_from_db()
        self.assertIsNone(req.description)  # unchanged

    def test_list_and_detail_report_has_unlocked_lead(self):
        req = StudentRequirement.objects.create(
            student=self.user,
            subject=self.subject,
            class_duration_minutes=60,
            no_language_preference=True,
        )
        Lead.objects.create(
            student_requirement=req,
            teacher_profile=self._make_teacher_profile(),
            contact_unlocked=True,
        )
        list_resp = self.client.get(REQS)
        self.assertTrue(list_resp.json()["data"][0]["has_unlocked_lead"])
        detail_resp = self.client.get(f"{REQS}{req.id}/")
        self.assertTrue(detail_resp.json()["data"]["has_unlocked_lead"])

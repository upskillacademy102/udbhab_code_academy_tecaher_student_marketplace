"""
Onboarding call queue + Super Admin scheduling.

Run: python manage.py test apps.teacher_profile.tests.test_onboarding_calls \
     --settings=config.settings.test
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_named_admin, make_user
from apps.teacher_profile.models import TeacherProfile
from apps.teachers.models import Teacher
from apps.trust.models import OnboardingCallRequest
from apps.trust.services.verification_service import VerificationService

LIST_URL = "/api/v1/admin/onboarding-calls/"


class OnboardingCallQueueTests(APITestCase):
    def setUp(self):
        self.tuser = make_user(role=UserRole.TEACHER)
        self.teacher = Teacher.objects.create(user=self.tuser, experience_years=2)
        TeacherProfile.objects.create(teacher=self.teacher)
        VerificationService.submit_reviewed_item(
            self.teacher, "video_interview", payload={}
        )
        self.call = OnboardingCallRequest.objects.get(item__teacher=self.teacher)
        self.schedule_url = f"/api/v1/admin/onboarding-calls/{self.teacher.id}/schedule/"

    def test_support_admin_can_see_the_queue(self):
        # The queue is Support-department-only since Support took over
        # onboarding calls - see test_onboarding_call_accept for the
        # other-department / departmentless denials.
        login(self.client, make_named_admin(department="Support"))
        r = self.client.get(LIST_URL)
        self.assertEqual(r.status_code, 200, r.content)
        rows = r.json()["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["teacher_email"], self.tuser.email)
        self.assertIsNone(rows[0]["scheduled_at"])

    def test_superadmin_can_see_the_queue(self):
        login(self.client, make_user(role=UserRole.SUPERADMIN))
        r = self.client.get(LIST_URL)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()["data"]), 1)

    def test_teacher_and_student_cannot_see_the_queue(self):
        for role in (UserRole.TEACHER, UserRole.STUDENT):
            c = self.client_class()
            login(c, make_user(role=role))
            self.assertEqual(c.get(LIST_URL).status_code, 403)

    def test_decided_calls_are_excluded_by_default(self):
        self.call.item.status = "verified"
        self.call.item.save(update_fields=["status"])
        login(self.client, make_named_admin(department="Support"))
        self.assertEqual(len(self.client.get(LIST_URL).json()["data"]), 0)
        self.assertEqual(
            len(self.client.get(LIST_URL, {"status": "all"}).json()["data"]), 1
        )

    def test_admin_cannot_schedule(self):
        assignee = make_user(role=UserRole.ADMIN, email="assignee@x.test")
        login(self.client, make_user(role=UserRole.ADMIN))
        r = self.client.post(
            self.schedule_url, {"assigned_admin_id": str(assignee.id)}, format="json"
        )
        self.assertEqual(r.status_code, 403)

    def test_superadmin_schedules_it(self):
        assignee = make_user(role=UserRole.ADMIN, email="assignee2@x.test")
        login(self.client, make_user(role=UserRole.SUPERADMIN))
        before = timezone.now()
        r = self.client.post(
            self.schedule_url, {"assigned_admin_id": str(assignee.id)}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.call.refresh_from_db()
        self.assertEqual(self.call.assigned_admin, assignee)
        self.assertIsNotNone(self.call.scheduled_by)
        self.assertTrue(
            before + timedelta(hours=23, minutes=59) <= self.call.scheduled_at
            <= before + timedelta(hours=24, minutes=1)
        )

    def test_invalid_assignee_is_400(self):
        login(self.client, make_user(role=UserRole.SUPERADMIN))
        student = make_user(role=UserRole.STUDENT)
        r = self.client.post(
            self.schedule_url, {"assigned_admin_id": str(student.id)}, format="json"
        )
        self.assertEqual(r.status_code, 400, r.content)

    def test_missing_assignee_is_400(self):
        login(self.client, make_user(role=UserRole.SUPERADMIN))
        r = self.client.post(self.schedule_url, {}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_schedule_for_teacher_without_request_404s(self):
        other = Teacher.objects.create(
            user=make_user(role=UserRole.TEACHER, email="other@x.test"),
            experience_years=1,
        )
        login(self.client, make_user(role=UserRole.SUPERADMIN))
        assignee = make_user(role=UserRole.ADMIN, email="assignee3@x.test")
        r = self.client.post(
            f"/api/v1/admin/onboarding-calls/{other.id}/schedule/",
            {"assigned_admin_id": str(assignee.id)},
            format="json",
        )
        self.assertEqual(r.status_code, 404, r.content)

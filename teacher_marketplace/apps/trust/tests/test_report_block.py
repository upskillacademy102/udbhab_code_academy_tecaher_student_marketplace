"""
Phase 8d - report a user + personal block list (filters search + leads).

Run: python manage.py test apps.trust.tests.test_report_block --settings=config.settings.test
"""

from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.lead_engine.tests.test_lead_pipeline import PipelineFixtureMixin
from apps.trust.models import (
    ManualReviewItem,
    ManualReviewKind,
    RiskSignal,
    RiskSignalKind,
    UserBlock,
    UserReport,
)
from apps.trust.services.report_block_service import ReportBlockService


class ReportTests(TestCase):
    def test_report_creates_record_signal_and_review_item(self):
        a = make_user(role=UserRole.STUDENT)
        b = make_user(role=UserRole.TEACHER)
        ReportBlockService.report_user(
            reporter=a, reported=b, reason="off_platform", detail="asked for gpay"
        )
        self.assertTrue(UserReport.objects.filter(reporter=a, reported=b).exists())
        self.assertTrue(
            ManualReviewItem.objects.filter(kind=ManualReviewKind.USER_REPORT).exists()
        )
        self.assertTrue(
            RiskSignal.objects.filter(user=b, kind=RiskSignalKind.USER_REPORT).exists()
        )

    def test_duplicate_open_report_is_deduped(self):
        a = make_user(role=UserRole.STUDENT)
        b = make_user(role=UserRole.TEACHER)
        r1 = ReportBlockService.report_user(reporter=a, reported=b, reason="spam")
        r2 = ReportBlockService.report_user(reporter=a, reported=b, reason="spam")
        self.assertEqual(r1.id, r2.id)
        self.assertEqual(UserReport.objects.filter(reporter=a, reported=b).count(), 1)

    def test_cannot_report_self(self):
        from apps.core.exceptions.custom_exceptions import ValidationException

        a = make_user(role=UserRole.STUDENT)
        with self.assertRaises(ValidationException):
            ReportBlockService.report_user(reporter=a, reported=a, reason="spam")


class BlockApiTests(APITestCase):
    def test_block_unblock_flow(self):
        student = make_user(role=UserRole.STUDENT)
        teacher = make_user(role=UserRole.TEACHER)
        login(self.client, student)

        r = self.client.post(
            "/api/v1/safety/blocks/", {"user_id": str(teacher.id)}, format="json"
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(
            UserBlock.objects.filter(blocker=student, blocked=teacher).exists()
        )

        r = self.client.get("/api/v1/safety/blocks/")
        self.assertEqual(len(r.json()["data"]), 1)

        r = self.client.delete(f"/api/v1/safety/blocks/{teacher.id}/")
        self.assertIn(r.status_code, (200, 204))
        self.assertFalse(
            UserBlock.objects.filter(blocker=student, blocked=teacher).exists()
        )

    def test_report_endpoint(self):
        student = make_user(role=UserRole.STUDENT)
        teacher = make_user(role=UserRole.TEACHER)
        login(self.client, student)
        r = self.client.post(
            "/api/v1/safety/report/",
            {"user_id": str(teacher.id), "reason": "abuse", "detail": "rude"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)


class BlockFilterTests(PipelineFixtureMixin, TestCase):
    def test_blocked_teacher_hidden_from_lead_candidates_when_flag_on(self):
        from apps.lead_engine.services.lead_generation_service import (
            find_candidate_teacher_profiles,
        )

        blocked_profile = self.make_teacher("Blk", plan=self.free_plan)
        ok_profile = self.make_teacher("Okay", plan=self.free_plan)
        student = make_user(role=UserRole.STUDENT)
        req = self.make_requirement(student=student)

        UserBlock.objects.create(blocker=student, blocked=blocked_profile.teacher.user)

        with override_settings(TRUST_ENABLE_USER_BLOCKING=True):
            ids = set(find_candidate_teacher_profiles(req).values_list("id", flat=True))
        self.assertIn(ok_profile.id, ids)
        self.assertNotIn(blocked_profile.id, ids)

    def test_block_has_no_effect_when_flag_off(self):
        from apps.lead_engine.services.lead_generation_service import (
            find_candidate_teacher_profiles,
        )

        blocked_profile = self.make_teacher("Blk2", plan=self.free_plan)
        student = make_user(role=UserRole.STUDENT)
        req = self.make_requirement(student=student)
        UserBlock.objects.create(blocker=student, blocked=blocked_profile.teacher.user)

        ids = set(find_candidate_teacher_profiles(req).values_list("id", flat=True))
        self.assertIn(blocked_profile.id, ids)  # flag OFF -> not filtered

    @override_settings(TRUST_ENABLE_USER_BLOCKING=True)
    def test_teacher_blocking_student_also_hides_that_teacher(self):
        from apps.lead_engine.services.lead_generation_service import (
            find_candidate_teacher_profiles,
        )

        prof = self.make_teacher("Mutual", plan=self.free_plan)
        student = make_user(role=UserRole.STUDENT)
        req = self.make_requirement(student=student)
        # teacher blocked the student (reverse direction)
        UserBlock.objects.create(blocker=prof.teacher.user, blocked=student)
        ids = set(find_candidate_teacher_profiles(req).values_list("id", flat=True))
        self.assertNotIn(prof.id, ids)

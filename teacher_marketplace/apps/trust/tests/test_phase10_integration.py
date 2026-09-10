"""
Phase 10 - full-stack integration with EVERY trust/fraud flag ON at once.

Unit tests already prove each gate in isolation; these prove the whole
chain holds together under enforcement (the "matrix run" the plan asks for).

Run: python manage.py test apps.trust.tests.test_phase10_integration --settings=config.settings.test
"""

from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.lead_engine.models import Lead, LeadUnlockHistory
from apps.lead_engine.tests.test_lead_pipeline import PipelineFixtureMixin
from apps.lead_engine.unlock_service import unlock_lead_contact
from apps.student_requirement.models import LeadDistributionStatus, StudentRequirement
from apps.trust.exceptions import LeadContactUnreachable
from apps.trust.models import (
    ManualReviewItem,
    ManualReviewKind,
    RiskSignalKind,
    UserBlock,
)
from apps.trust.services.risk_service import RiskService

ALL_ON = {
    "TRUST_REQUIRE_EMAIL_VERIFICATION": True,
    "TRUST_REQUIRE_MOBILE_VERIFICATION": True,
    "TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST": True,
    "TRUST_TEACHER_FLOOR_FOR_LEADS": True,
    "TRUST_VERIFICATION_SCORE_AFFECTS_RANKING": True,
    "TRUST_ENABLE_CAPTCHA": True,
    "TRUST_ENABLE_DEDUP_BLOCKING": True,
    "TRUST_ENABLE_STEP_UP_REVERIFICATION": True,
    "TRUST_ENABLE_REQUIREMENT_VELOCITY": True,
    "TRUST_ENABLE_PHONE_REACHABILITY_CHECK": True,
    "TRUST_ENABLE_LEAD_QUALITY_CLAWBACK": True,
    "TRUST_ENABLE_PAYMENT_RISK_CHECKS": True,
    "TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN": True,
    "TRUST_ENABLE_CONTACT_LEAKAGE_SCAN": True,
    "TRUST_ENABLE_REVIEW_SYSTEM": True,
    "TRUST_ENABLE_USER_BLOCKING": True,
    "TRUST_ENABLE_ANOMALY_ALERTS": True,
    "TRUST_ENABLE_RISK_AUTO_ACTIONS": True,
    "TRUST_ENABLE_SUSPENSION_APPEALS": True,
    # The test client's fingerprint is constant, so the CAPTCHA
    # account-switch counter would trip mid-suite; keep CAPTCHA "on" but
    # push the threshold out of reach for these journey tests.
    "TRUST_CAPTCHA_SWITCH_THRESHOLD": 100000,
}

_RQ = "/api/v1/student-requirements/"
_PAYLOAD = {
    "subject": "Mathematics",
    "preferred_language": "English",
    "teaching_mode": "online",
    "class_duration_minutes": 60,
    "schedule_preferences": [
        {
            "day_of_week": 1,
            "start_time": "18:00",
            "end_time": "19:00",
            "timezone": "Asia/Kolkata",
        }
    ],
}


def _verify_contacts(user):
    user.is_email_verified = True
    user.is_mobile_verified = True
    user.save(update_fields=["is_email_verified", "is_mobile_verified"])


@override_settings(**ALL_ON)
class StudentGauntletTests(PipelineFixtureMixin, APITestCase):
    def setUp(self):
        cache.clear()

    def test_unverified_student_blocked_then_allowed(self):
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        r = self.client.post(_RQ, _PAYLOAD, format="json")
        self.assertEqual(r.status_code, 403)  # verified-to-post gate

        _verify_contacts(student)
        r = self.client.post(_RQ, _PAYLOAD, format="json")
        self.assertEqual(r.status_code, 202, r.content)

    def test_risk_limited_student_requirement_is_held(self):
        student = make_user(role=UserRole.STUDENT)
        _verify_contacts(student)
        RiskService.add_signal(
            student, kind=RiskSignalKind.LEAD_QUALITY, weight=45
        )  # -> limited
        login(self.client, student)
        r = self.client.post(_RQ, _PAYLOAD, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        req = StudentRequirement.objects.get(student=student)
        self.assertEqual(req.lead_distribution_status, LeadDistributionStatus.HELD)

    def test_suspended_student_cannot_post_at_all(self):
        student = make_user(role=UserRole.STUDENT)
        _verify_contacts(student)
        RiskService.add_signal(
            student, kind=RiskSignalKind.LEAD_QUALITY, weight=95
        )  # -> suspended
        login(self.client, student)
        r = self.client.post(_RQ, _PAYLOAD, format="json")
        self.assertEqual(r.status_code, 403)  # NotRiskSuspended gate

    def test_blocked_teacher_excluded_from_student_leads(self):
        from apps.lead_engine.services.lead_generation_service import (
            find_candidate_teacher_profiles,
        )

        student = make_user(role=UserRole.STUDENT)
        blocked = self._onboarded_teacher("Blocked")
        ok = self._onboarded_teacher("Fine")
        UserBlock.objects.create(blocker=student, blocked=blocked.teacher.user)
        req = self.make_requirement(student=student)

        ids = set(find_candidate_teacher_profiles(req).values_list("id", flat=True))
        self.assertIn(ok.id, ids)
        self.assertNotIn(blocked.id, ids)

    # -- helper: a teacher that clears the Phase-5 floor --------------
    def _onboarded_teacher(self, name):
        from apps.trust.services.verification_service import VerificationService

        profile = self.make_teacher(name, plan=self.free_plan)
        t = profile.teacher
        _verify_contacts(t.user)
        t.bio = "Ten years teaching maths."
        t.experience_years = 10
        t.qualification_level = "masters"
        t.save(update_fields=["bio", "experience_years", "qualification_level"])
        VerificationService.recompute(t)
        return profile


@override_settings(**ALL_ON)
class TeacherGauntletTests(PipelineFixtureMixin, TestCase):
    def _onboarded_teacher(self, name, **kw):
        from apps.trust.services.verification_service import VerificationService

        profile = self.make_teacher(name, plan=self.free_plan, **kw)
        t = profile.teacher
        _verify_contacts(t.user)
        t.bio = "Ten years teaching maths."
        t.experience_years = 10
        t.qualification_level = "masters"
        t.save(update_fields=["bio", "experience_years", "qualification_level"])
        VerificationService.recompute(t)
        return profile

    def test_below_floor_no_leads_above_floor_gets_leads(self):
        # a teacher who never verified contacts -> below the floor
        below = self.make_teacher("Below", plan=self.free_plan)
        above = self._onboarded_teacher("Above")
        req = self.make_requirement()

        leads, _ = self.run_pipeline(req)
        tp_ids = {lead.teacher_profile_id for lead in leads}
        self.assertIn(above.id, tp_ids)
        self.assertNotIn(below.id, tp_ids)

    def test_unlock_blocked_and_uncharged_on_unreachable_student(self):
        teacher = self._onboarded_teacher("Reach")
        student = make_user(
            role=UserRole.STUDENT, mobile=""
        )  # empty -> unreachable stub
        req = self.make_requirement(student=student)
        lead = Lead.objects.create(student_requirement=req, teacher_profile=teacher)

        with self.assertRaises(LeadContactUnreachable):
            unlock_lead_contact(teacher.teacher, lead)
        lead.refresh_from_db()
        self.assertFalse(lead.contact_unlocked)
        self.assertFalse(LeadUnlockHistory.objects.filter(lead=lead).exists())

    def test_unlock_succeeds_on_reachable_student(self):
        teacher = self._onboarded_teacher("Reach2")
        student = make_user(role=UserRole.STUDENT)  # numeric mobile -> reachable
        req = self.make_requirement(student=student)
        lead = Lead.objects.create(student_requirement=req, teacher_profile=teacher)
        unlock_lead_contact(teacher.teacher, lead)
        self.assertTrue(LeadUnlockHistory.objects.filter(lead=lead).exists())

    def test_new_account_big_purchase_capped(self):
        from apps.payments.exceptions import PaymentHeldForReview
        from apps.payments.models import TokenPackage
        from apps.payments.services import PaymentService

        teacher = self._onboarded_teacher("Buyer")
        big = TokenPackage.objects.create(
            name="Whale", token_count=99999, price=Decimal("50000.00")
        )
        with self.assertRaises(PaymentHeldForReview):
            PaymentService.create_order(teacher.teacher, token_package=big)


@override_settings(**ALL_ON)
class OpsQueueEndToEndTests(PipelineFixtureMixin, APITestCase):
    def setUp(self):
        cache.clear()

    def test_queue_surfaces_multiple_kinds_and_resolves(self):
        from apps.trust.services.content_scan_service import ContentScanService
        from apps.trust.services.report_block_service import ReportBlockService

        # 1) content flag
        prof = self.make_teacher("Leaky", plan=self.free_plan)
        prof.headline = "pay me on gpay 9876543210"
        prof.save(update_fields=["headline"])
        ContentScanService.scan_teacher_profile(prof)

        # 2) user report
        reporter = make_user(role=UserRole.STUDENT)
        ReportBlockService.report_user(
            reporter=reporter, reported=prof.teacher.user, reason="off_platform"
        )

        # 3) risk escalation (from the report's risk signal + a manual push)
        RiskService.add_signal(
            prof.teacher.user, kind=RiskSignalKind.PAYMENT_RISK, weight=60
        )

        superadmin = make_user(role=UserRole.SUPERADMIN)
        login(self.client, superadmin)

        r = self.client.get("/api/v1/ops/review-queue/")
        self.assertEqual(r.status_code, 200)
        kinds = {it["kind"] for it in r.json()["data"]}
        self.assertIn(ManualReviewKind.CONTENT_FLAG, kinds)
        self.assertIn(ManualReviewKind.USER_REPORT, kinds)
        self.assertIn(ManualReviewKind.RISK_ESCALATION, kinds)

        item = ManualReviewItem.objects.filter(
            kind=ManualReviewKind.CONTENT_FLAG
        ).first()
        r = self.client.post(
            f"/api/v1/ops/review-queue/{item.id}/resolve/",
            {"resolution": "cleared"},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.status, "resolved")

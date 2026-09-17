"""
Phase 6 - student verification gate, phone-reachability, requirement
velocity / shadow-limit, and lead-quality feedback + clawback.

Run: python manage.py test apps.trust.tests.test_phase6 --settings=config.settings.test
"""

from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.lead_engine.models import Lead, LeadUnlockHistory
from apps.lead_engine.tests.test_lead_pipeline import PipelineFixtureMixin
from apps.lead_engine.unlock_service import unlock_lead_contact
from apps.student_requirement.models import LeadDistributionStatus, StudentRequirement
from apps.subscriptions.services import LeadQuotaService
from apps.trust.exceptions import LeadContactUnreachable
from apps.trust.models import (
    LeadQualityRating,
    LeadQualityVerdict,
    RiskSignal,
    RiskSignalKind,
)
from apps.trust.providers.stub import FAIL_SENTINEL
from apps.trust.services.lead_quality_service import LeadQualityService
from apps.trust.services.risk_service import RiskService
from apps.wallet.services import WalletService

RQ = "/api/v1/student-requirements/"
_PAYLOAD = {
    "subject": "Mathematics",
    "student_class": "10",
    "preferred_languages": ["English"],
    "budget_min": 200,
    "budget_max": 900,
    "teaching_mode": "online",
    "description": "help",
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


class _LeadMixin(PipelineFixtureMixin):
    def _lead(self, *, student, teacher_name="Anita"):
        req = self.make_requirement(student=student)
        profile = self.make_teacher(teacher_name, plan=self.free_plan)
        return (
            Lead.objects.create(student_requirement=req, teacher_profile=profile),
            profile.teacher,
        )

    def _paid_unlocked_lead(self, *, student, teacher_name):
        """
        A lead the teacher unlocked from their PURCHASED balance, with the
        plan allowance exhausted first.

        The teacher is put on Professional deliberately: purchased unlocks
        are only spendable on a paid plan
        (unlock_service.can_spend_purchased_unlocks), so a Free teacher
        would be refused here no matter how large their balance.
        """
        req = self.make_requirement(student=student)
        profile = self.make_teacher(teacher_name, plan=self.pro_plan)
        teacher = profile.teacher
        lead = Lead.objects.create(student_requirement=req, teacher_profile=profile)

        WalletService.get_or_create_wallet(teacher)
        WalletService.credit(teacher=teacher, amount=500, description="seed")
        quota = LeadQuotaService.get_or_create_current_quota(teacher)
        quota.used_free_leads = quota.total_free_leads
        quota.save(update_fields=["used_free_leads"])
        unlock_lead_contact(teacher, lead)
        return lead, teacher


class StudentVerifiedToPostGateTests(PipelineFixtureMixin, APITestCase):
    def _post(self):
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        return self.client.post(RQ, _PAYLOAD, format="json")

    def test_gate_off_by_default(self):
        self.assertEqual(self._post().status_code, 202)

    @override_settings(TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST=True)
    def test_gate_on_blocks_unverified(self):
        self.assertEqual(self._post().status_code, 403)

    @override_settings(TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST=True)
    def test_gate_on_allows_verified(self):
        student = make_user(
            role=UserRole.STUDENT, is_email_verified=True, is_mobile_verified=True
        )
        login(self.client, student)
        self.assertEqual(self.client.post(RQ, _PAYLOAD, format="json").status_code, 202)


class ReachabilityTests(_LeadMixin, TestCase):
    def test_off_by_default_unlock_proceeds(self):
        student = make_user(role=UserRole.STUDENT)
        lead, teacher = self._lead(student=student)
        unlock_lead_contact(teacher, lead)
        self.assertTrue(
            LeadUnlockHistory.objects.filter(teacher=teacher, lead=lead).exists()
        )

    @override_settings(TRUST_ENABLE_PHONE_REACHABILITY_CHECK=True)
    def test_reachable_number_unlocks(self):
        student = make_user(role=UserRole.STUDENT)  # numeric mobile -> reachable stub
        lead, teacher = self._lead(student=student)
        unlock_lead_contact(teacher, lead)
        self.assertTrue(
            LeadUnlockHistory.objects.filter(teacher=teacher, lead=lead).exists()
        )

    @override_settings(TRUST_ENABLE_PHONE_REACHABILITY_CHECK=True)
    def test_unreachable_number_blocks_without_charging(self):
        student = make_user(role=UserRole.STUDENT, mobile="")  # empty -> stub failure
        lead, teacher = self._lead(student=student)
        WalletService.get_or_create_wallet(teacher)
        before = WalletService.get_balance(teacher)
        with self.assertRaises(LeadContactUnreachable):
            unlock_lead_contact(teacher, lead)
        lead.refresh_from_db()
        self.assertFalse(lead.contact_unlocked)
        self.assertFalse(
            LeadUnlockHistory.objects.filter(teacher=teacher, lead=lead).exists()
        )
        self.assertEqual(WalletService.get_balance(teacher), before)
        self.assertTrue(
            RiskSignal.objects.filter(
                user=student, kind=RiskSignalKind.PHONE_UNREACHABLE
            ).exists()
        )

    @override_settings(TRUST_ENABLE_PHONE_REACHABILITY_CHECK=True)
    def test_sentinel_number_blocks(self):
        student = make_user(role=UserRole.STUDENT, mobile=FAIL_SENTINEL)
        lead, teacher = self._lead(student=student)
        with self.assertRaises(LeadContactUnreachable):
            unlock_lead_contact(teacher, lead)

    def test_check_requirement_is_idempotent(self):
        from apps.trust.models import RequirementContactCheck
        from apps.trust.services.reachability_service import ReachabilityService

        student = make_user(role=UserRole.STUDENT)
        req = self.make_requirement(student=student)
        first = ReachabilityService.check_requirement(req)
        second = ReachabilityService.check_requirement(req)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            RequirementContactCheck.objects.filter(requirement=req).count(), 1
        )


class VelocityTests(PipelineFixtureMixin, APITestCase):
    @override_settings(
        TRUST_ENABLE_REQUIREMENT_VELOCITY=True, TRUST_REQUIREMENT_MAX_PER_DAY=2
    )
    def test_per_day_cap(self):
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        self.assertEqual(self.client.post(RQ, _PAYLOAD, format="json").status_code, 202)
        self.assertEqual(
            self.client.post(
                RQ, {**_PAYLOAD, "subject": "Physics"}, format="json"
            ).status_code,
            202,
        )
        r3 = self.client.post(
            RQ,
            {
                **_PAYLOAD,
                "subject": "Mathematics",
                "teaching_mode": "offline",
                "city": "Kolkata",
            },
            format="json",
        )
        self.assertEqual(r3.status_code, 429, r3.content)

    def test_per_day_cap_noop_when_flag_off(self):
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        combos = (
            {"subject": "Mathematics"},
            {"subject": "Mathematics", "teaching_mode": "offline", "city": "Kolkata"},
            {"subject": "Physics"},
        )
        for extra in combos:
            r = self.client.post(RQ, {**_PAYLOAD, **extra}, format="json")
            self.assertIn(r.status_code, (202, 201), r.content)

    @override_settings(TRUST_ENABLE_REQUIREMENT_VELOCITY=True)
    def test_shadow_limited_student_requirement_is_held(self):
        student = make_user(role=UserRole.STUDENT)
        RiskService.add_signal(student, kind=RiskSignalKind.LEAD_QUALITY, weight=60)
        login(self.client, student)
        r = self.client.post(RQ, _PAYLOAD, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        req = StudentRequirement.objects.get(student=student)
        self.assertEqual(req.lead_distribution_status, LeadDistributionStatus.HELD)

    def _abandoning_student(self, *, status, n=6):
        student = make_user(role=UserRole.STUDENT)
        for _ in range(n):
            StudentRequirement.objects.create(
                student=student,
                subject=self.math,
                no_language_preference=True,
                teaching_mode="online",
                class_duration_minutes=60,
                status=status,
            )
        return student

    @override_settings(TRUST_ENABLE_REQUIREMENT_VELOCITY=True)
    def test_abandonment_signal(self):
        from apps.student_requirement.models import RequirementStatus
        from apps.trust.services.requirement_velocity_service import (
            RequirementVelocityService,
        )

        student = self._abandoning_student(status=RequirementStatus.EXPIRED)
        RequirementVelocityService.note_abandonment(student)
        self.assertTrue(
            RiskSignal.objects.filter(
                user=student, kind=RiskSignalKind.REQUIREMENT_ABANDONMENT
            ).exists()
        )

    @override_settings(TRUST_ENABLE_REQUIREMENT_VELOCITY=True)
    def test_abandonment_ignores_still_open_requirements(self):
        from apps.student_requirement.models import RequirementStatus
        from apps.trust.services.requirement_velocity_service import (
            RequirementVelocityService,
        )

        student = self._abandoning_student(status=RequirementStatus.OPEN)
        RequirementVelocityService.note_abandonment(student)
        self.assertFalse(
            RiskSignal.objects.filter(
                user=student, kind=RiskSignalKind.REQUIREMENT_ABANDONMENT
            ).exists()
        )

    def test_abandonment_noop_when_flag_off(self):
        from apps.student_requirement.models import RequirementStatus
        from apps.trust.services.requirement_velocity_service import (
            RequirementVelocityService,
        )

        student = self._abandoning_student(status=RequirementStatus.EXPIRED)
        RequirementVelocityService.note_abandonment(student)
        self.assertFalse(RiskSignal.objects.filter(user=student).exists())


class LeadQualityTests(_LeadMixin, TestCase):
    def test_rate_requires_an_unlock(self):
        from apps.core.exceptions.custom_exceptions import ValidationException

        student = make_user(role=UserRole.STUDENT)
        lead, teacher = self._lead(student=student, teacher_name="Zed")
        with self.assertRaises(ValidationException):
            LeadQualityService.rate(teacher=teacher, lead=lead, verdict="fake")

    def test_single_rating_updates_score(self):
        student = make_user(role=UserRole.STUDENT)
        lead, teacher = self._lead(student=student, teacher_name="Uno")
        unlock_lead_contact(teacher, lead)  # free unlock is fine here
        LeadQualityService.rate(
            teacher=teacher, lead=lead, verdict=LeadQualityVerdict.FAKE
        )
        student.trust_profile.refresh_from_db()
        self.assertEqual(student.trust_profile.lead_quality_score, Decimal("0.000"))

    @override_settings(
        TRUST_ENABLE_LEAD_QUALITY_CLAWBACK=True, TRUST_LEAD_QUALITY_CORROBORATION=2
    )
    def test_corroborated_fakes_claw_back_tokens(self):
        student = make_user(role=UserRole.STUDENT)
        lead_a, t_a = self._paid_unlocked_lead(student=student, teacher_name="AaA")
        lead_b, t_b = self._paid_unlocked_lead(student=student, teacher_name="BbB")
        cost_a = LeadUnlockHistory.objects.get(teacher=t_a, lead=lead_a).tokens_deducted
        self.assertGreater(cost_a, 0)
        bal_a_before = WalletService.get_balance(t_a)

        LeadQualityService.rate(teacher=t_a, lead=lead_a, verdict="fake")
        self.assertEqual(
            WalletService.get_balance(t_a), bal_a_before
        )  # not corroborated yet

        LeadQualityService.rate(teacher=t_b, lead=lead_b, verdict="unreachable")
        self.assertEqual(
            WalletService.get_balance(t_a), bal_a_before + cost_a
        )  # refunded
        self.assertTrue(
            LeadQualityRating.objects.get(teacher=t_a, lead=lead_a).clawed_back
        )
        self.assertTrue(
            RiskSignal.objects.filter(
                user=student, kind=RiskSignalKind.LEAD_QUALITY
            ).exists()
        )

    @override_settings(TRUST_LEAD_QUALITY_CORROBORATION=2)  # clawback flag OFF
    def test_corroboration_without_clawback_flag_still_signals(self):
        student = make_user(role=UserRole.STUDENT)
        lead_a, t_a = self._paid_unlocked_lead(student=student, teacher_name="CcC")
        lead_b, t_b = self._paid_unlocked_lead(student=student, teacher_name="DdD")
        bal_a_before = WalletService.get_balance(t_a)
        LeadQualityService.rate(teacher=t_a, lead=lead_a, verdict="fake")
        LeadQualityService.rate(teacher=t_b, lead=lead_b, verdict="fake")
        self.assertEqual(WalletService.get_balance(t_a), bal_a_before)  # NO refund
        self.assertTrue(
            RiskSignal.objects.filter(
                user=student, kind=RiskSignalKind.LEAD_QUALITY
            ).exists()
        )


class LeadRateApiTests(_LeadMixin, APITestCase):
    def test_endpoint(self):
        student = make_user(role=UserRole.STUDENT)
        lead, teacher = self._lead(student=student, teacher_name="Api")
        unlock_lead_contact(teacher, lead)
        login(self.client, teacher.user)
        r = self.client.post(
            f"/api/v1/leads/{lead.id}/rate/", {"verdict": "genuine"}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(LeadQualityRating.objects.filter(lead=lead).exists())

    def test_student_cannot_rate(self):
        student = make_user(role=UserRole.STUDENT)
        lead, teacher = self._lead(student=student, teacher_name="Api2")
        login(self.client, student)
        r = self.client.post(
            f"/api/v1/leads/{lead.id}/rate/", {"verdict": "fake"}, format="json"
        )
        self.assertEqual(r.status_code, 403)

"""
Phase LP-4: a Learning Partner endorsing an existing fake-lead signal on
one of their own referred students.

  * FakeLeadEndorsement is unique per (student, learning_partner) - one
    partner, one vote, per student.
  * LeadQualityService.fake_report_stats folds each endorsement into the
    SAME rolling-window "distinct teachers" counts a real teacher's fake
    rating would, weighted by settings.LEARNING_PARTNER_FAKE_REPORT_WEIGHT
    (default 5) - `total_reports` is untouched (real teacher ratings only).
  * reassess_fake_reports_after_endorsement re-runs the exact same auto-ban
    decision as a fresh teacher report and preserves whatever
    `latest_report` the existing review item already had.

The "can an LP even endorse" business rule (must be their own student, must
already have an open report, one endorsement each) is an API-level concern
- see apps.learning_partner.tests.test_views for those. This file tests the
service-layer arithmetic in isolation.

Run: python manage.py test apps.trust.tests.test_learning_partner_endorsement \
     --settings=config.settings.test
"""

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_learning_partner_admin, make_user
from apps.lead_engine.models import Lead
from apps.lead_engine.tests.test_lead_pipeline import PipelineFixtureMixin
from apps.lead_engine.unlock_service import unlock_lead_contact
from apps.trust.models import FakeLeadEndorsement, ManualReviewItem, ManualReviewKind
from apps.trust.services.lead_quality_service import LeadQualityService

_SMALL = dict(
    FAKE_LEAD_AUTOBAN_WEEKLY=10,
    FAKE_LEAD_AUTOBAN_MONTHLY=15,
    FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS=3,
    LEARNING_PARTNER_FAKE_REPORT_WEIGHT=5,
)


class _Mixin(PipelineFixtureMixin):
    def _report_fake(self, student, teacher_name, *, note="", verdict="fake"):
        req = self.make_requirement(student=student)
        profile = self.make_teacher(teacher_name, plan=self.free_plan)
        lead = Lead.objects.create(student_requirement=req, teacher_profile=profile)
        unlock_lead_contact(profile.teacher, lead)
        return LeadQualityService.rate(
            teacher=profile.teacher, lead=lead, verdict=verdict, note=note
        )

    def _fake_item(self, student):
        return ManualReviewItem.objects.filter(
            kind=ManualReviewKind.FAKE_LEAD_REPORT, subject_user=student
        ).first()


class FakeLeadEndorsementModelTests(TestCase):
    def test_unique_per_partner_per_student(self):
        lp = make_learning_partner_admin("EndorseModelPartner")
        student = make_user(role=UserRole.STUDENT)
        FakeLeadEndorsement.objects.create(student=student, learning_partner=lp)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FakeLeadEndorsement.objects.create(student=student, learning_partner=lp)

    def test_same_student_can_be_endorsed_by_different_partners(self):
        lp_a = make_learning_partner_admin("EndorseModelPartnerA")
        lp_b = make_learning_partner_admin("EndorseModelPartnerB")
        student = make_user(role=UserRole.STUDENT)
        FakeLeadEndorsement.objects.create(student=student, learning_partner=lp_a)
        FakeLeadEndorsement.objects.create(student=student, learning_partner=lp_b)


@override_settings(**_SMALL)
class FakeReportStatsWeightingTests(_Mixin, TestCase):
    def test_endorsement_adds_weight_to_distinct_teacher_counts(self):
        lp = make_learning_partner_admin("StatsPartner")
        student = make_user(role=UserRole.STUDENT, learning_partner=lp)
        self._report_fake(student, "T1")

        stats = LeadQualityService.fake_report_stats(student)
        self.assertEqual(stats["distinct_teachers_all"], 1)
        self.assertEqual(stats["total_reports"], 1)

        FakeLeadEndorsement.objects.create(student=student, learning_partner=lp)
        stats = LeadQualityService.fake_report_stats(student)
        self.assertEqual(stats["distinct_teachers_all"], 1 + 5)
        self.assertEqual(stats["distinct_teachers_7d"], 1 + 5)
        self.assertEqual(stats["total_reports"], 1)  # unaffected - real reports only

    def test_two_endorsements_alone_do_not_cross_the_weekly_line(self):
        # Matches the documented arithmetic: weight 5, threshold strictly >10,
        # so 2 endorsements (10) sit AT the line, not over it.
        student = make_user(role=UserRole.STUDENT)
        for i in range(2):
            lp = make_learning_partner_admin(f"TwoLinePartner{i}")
            FakeLeadEndorsement.objects.create(student=student, learning_partner=lp)
            LeadQualityService.reassess_fake_reports_after_endorsement(student)
        student.refresh_from_db()
        self.assertTrue(student.is_active)

    def test_three_endorsements_alone_cross_the_weekly_line_and_ban(self):
        student = make_user(role=UserRole.STUDENT)
        for i in range(3):
            lp = make_learning_partner_admin(f"ThreeLinePartner{i}")
            FakeLeadEndorsement.objects.create(student=student, learning_partner=lp)
            LeadQualityService.reassess_fake_reports_after_endorsement(student)
        student.refresh_from_db()
        self.assertFalse(student.is_active)
        item = self._fake_item(student)
        self.assertTrue(item.payload["auto_banned"])

    def test_endorsement_preserves_the_existing_latest_teacher_report(self):
        student = make_user(role=UserRole.STUDENT)
        self._report_fake(student, "OrigTeacher", note="original complaint")
        original_latest = self._fake_item(student).payload["latest_report"]

        lp = make_learning_partner_admin("PreservePartner")
        FakeLeadEndorsement.objects.create(student=student, learning_partner=lp)
        LeadQualityService.reassess_fake_reports_after_endorsement(student)

        item_after = self._fake_item(student)
        self.assertEqual(item_after.payload["latest_report"], original_latest)
        self.assertEqual(item_after.payload["distinct_teachers_all"], 1 + 5)

    def test_endorsement_with_no_prior_review_item_still_opens_one(self):
        student = make_user(role=UserRole.STUDENT)
        lp = make_learning_partner_admin("NoPriorPartner")
        FakeLeadEndorsement.objects.create(student=student, learning_partner=lp)
        LeadQualityService.reassess_fake_reports_after_endorsement(student)

        item = self._fake_item(student)
        self.assertIsNotNone(item)
        self.assertIsNone(item.payload["latest_report"])
        self.assertEqual(item.payload["distinct_teachers_all"], 5)

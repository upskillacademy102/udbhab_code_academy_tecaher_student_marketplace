"""
Fake-lead reporting -> Super Admin alerts + automatic ban.

  * Every "fake" rating opens or updates that student's FAKE_LEAD_REPORT
    review item (the Super Admin dashboard alert), with running
    distinct-teacher counts.
  * Counting is by DISTINCT teacher over rolling 7 / 30-day windows.
  * A student is permanently banned once the distinct-teacher count
    exceeds settings.FAKE_LEAD_AUTOBAN_WEEKLY (7d) or
    FAKE_LEAD_AUTOBAN_MONTHLY (30d), never below
    FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS.
  * Super Admin can ban / suspend / reactivate from the ops API.

Run: python manage.py test apps.trust.tests.test_fake_lead_reports \
     --settings=config.settings.test
"""

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole, UserSession
from apps.accounts.tests.helpers import login, make_user
from apps.lead_engine.models import Lead
from apps.lead_engine.tests.test_lead_pipeline import PipelineFixtureMixin
from apps.lead_engine.unlock_service import unlock_lead_contact
from apps.trust.models import (
    AccountSanction,
    LeadQualityRating,
    LeadQualityVerdict,
    ManualReviewItem,
    ManualReviewKind,
    ManualReviewStatus,
)
from apps.trust.services.lead_quality_service import LeadQualityService
from apps.trust.services.sanction_service import SanctionService

# Small, deterministic auto-ban thresholds for this file only (test.py pins
# them out of reach for the rest of the suite).
_SMALL = dict(
    FAKE_LEAD_AUTOBAN_WEEKLY=3,
    FAKE_LEAD_AUTOBAN_MONTHLY=5,
    FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS=3,
)


class _Mixin(PipelineFixtureMixin):
    def _report_fake(self, student, teacher_name, *, note="", verdict="fake"):
        """One teacher unlocks a fresh lead for `student` and rates it."""
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


class FakeLeadAlertTests(_Mixin, TestCase):
    def test_first_fake_report_opens_the_alert(self):
        student = make_user(role=UserRole.STUDENT)
        self._report_fake(student, "T1", note="never picked up")

        item = self._fake_item(student)
        self.assertIsNotNone(item)
        self.assertEqual(item.status, ManualReviewStatus.OPEN)
        self.assertEqual(item.payload["distinct_teachers_all"], 1)
        self.assertEqual(item.payload["total_reports"], 1)
        self.assertEqual(item.payload["latest_report"]["note"], "never picked up")
        self.assertFalse(item.payload["auto_banned"])

    def test_subsequent_reports_update_the_same_alert(self):
        student = make_user(role=UserRole.STUDENT)
        self._report_fake(student, "T1")
        self._report_fake(student, "T2")

        items = ManualReviewItem.objects.filter(
            kind=ManualReviewKind.FAKE_LEAD_REPORT, subject_user=student
        )
        self.assertEqual(items.count(), 1)  # updated, not duplicated
        self.assertEqual(items.first().payload["distinct_teachers_all"], 2)

    def test_one_teacher_flagging_many_leads_counts_once(self):
        student = make_user(role=UserRole.STUDENT)
        profile = self.make_teacher("Serial", plan=self.free_plan)
        for _ in range(3):
            req = self.make_requirement(student=student)
            lead = Lead.objects.create(
                student_requirement=req, teacher_profile=profile
            )
            unlock_lead_contact(profile.teacher, lead)
            LeadQualityService.rate(
                teacher=profile.teacher, lead=lead, verdict="fake"
            )

        item = self._fake_item(student)
        self.assertEqual(item.payload["distinct_teachers_all"], 1)
        self.assertEqual(item.payload["total_reports"], 3)
        self.assertTrue(student.is_active)  # one teacher can't get anyone banned

    def test_genuine_and_unreachable_do_not_open_a_fake_alert(self):
        student = make_user(role=UserRole.STUDENT)
        self._report_fake(student, "G1", verdict="genuine")
        self._report_fake(student, "U1", verdict="unreachable")
        self.assertIsNone(self._fake_item(student))

    @override_settings(
        TRUST_ENABLE_LEAD_QUALITY_CLAWBACK=True, TRUST_LEAD_QUALITY_CORROBORATION=2
    )
    def test_clawback_does_not_500_for_an_allowance_only_teacher(self):
        """
        Regression: a teacher who has only ever spent plan allowance has no
        Wallet row; the corroborated-fake clawback used to blow up reading
        one. It must create the wallet and land the refund instead.
        """
        from apps.wallet.services import WalletService

        student = make_user(role=UserRole.STUDENT)
        r1 = self._report_fake(student, "AllowA")
        self._report_fake(student, "AllowB")  # 2nd distinct teacher -> corroborated

        self.assertEqual(WalletService.get_balance(r1.teacher), 1)  # refunded, no crash


@override_settings(**_SMALL)
class AutoBanTests(_Mixin, TestCase):
    def test_ban_fires_past_the_weekly_threshold(self):
        student = make_user(role=UserRole.STUDENT)
        for i in range(3):  # == threshold, not yet over
            self._report_fake(student, f"W{i}")
        student.refresh_from_db()
        self.assertTrue(student.is_active)

        self._report_fake(student, "W3")  # 4 distinct teachers > 3
        student.refresh_from_db()
        self.assertFalse(student.is_active)

        sanction = AccountSanction.objects.get(user=student, active=True)
        self.assertEqual(sanction.kind, "ban")
        self.assertEqual(sanction.source, "auto_fake_leads_weekly")
        self.assertIsNone(sanction.created_by)
        item = self._fake_item(student)
        self.assertTrue(item.payload["auto_banned"])
        self.assertEqual(item.priority, 1)

    def test_ban_kills_active_sessions(self):
        student = make_user(role=UserRole.STUDENT)
        UserSession.start(student)
        self.assertTrue(UserSession.objects.filter(user=student, is_active=True).exists())

        for i in range(4):
            self._report_fake(student, f"K{i}")

        student.refresh_from_db()
        self.assertFalse(student.is_active)
        self.assertFalse(
            UserSession.objects.filter(user=student, is_active=True).exists()
        )

    @override_settings(
        FAKE_LEAD_AUTOBAN_WEEKLY=1, FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS=3
    )
    def test_floor_blocks_a_ban_from_a_couple_of_teachers(self):
        """Threshold met at 2 teachers, but the 3-teacher floor stops it."""
        student = make_user(role=UserRole.STUDENT)
        self._report_fake(student, "F1")
        self._report_fake(student, "F2")
        student.refresh_from_db()
        self.assertTrue(student.is_active)
        # third distinct teacher clears the floor -> ban
        self._report_fake(student, "F3")
        student.refresh_from_db()
        self.assertFalse(student.is_active)

    def test_ban_is_idempotent(self):
        student = make_user(role=UserRole.STUDENT)
        for i in range(6):
            self._report_fake(student, f"I{i}")
        self.assertEqual(
            AccountSanction.objects.filter(user=student).count(), 1
        )

    def test_changing_a_verdict_away_from_fake_lowers_the_count(self):
        student = make_user(role=UserRole.STUDENT)
        r1 = self._report_fake(student, "C1")
        self._report_fake(student, "C2")
        self.assertEqual(self._fake_item(student).payload["distinct_teachers_all"], 2)

        LeadQualityService.rate(
            teacher=r1.teacher, lead=r1.lead, verdict="genuine"
        )
        # the item summary/counts refresh via _reassess only for fake; re-read live
        stats = LeadQualityService.fake_report_stats(student)
        self.assertEqual(stats["distinct_teachers_all"], 1)


class SanctionApiTests(_Mixin, APITestCase):
    def _superadmin(self):
        sa = make_user(role=UserRole.SUPERADMIN)
        login(self.client, sa)
        return sa

    def test_superadmin_can_ban_a_student(self):
        self._superadmin()
        student = make_user(role=UserRole.STUDENT)
        r = self.client.post(
            "/api/v1/ops/sanctions/",
            {"user_id": str(student.id), "kind": "ban", "reason": "spam"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        student.refresh_from_db()
        self.assertFalse(student.is_active)
        self.assertTrue(
            AccountSanction.objects.filter(
                user=student, active=True, source="manual"
            ).exists()
        )

    def test_non_superadmin_cannot_use_the_sanction_api(self):
        login(self.client, make_user(role=UserRole.ADMIN))
        student = make_user(role=UserRole.STUDENT)
        r = self.client.post(
            "/api/v1/ops/sanctions/",
            {"user_id": str(student.id), "kind": "ban"},
            format="json",
        )
        self.assertEqual(r.status_code, 403, r.content)
        student.refresh_from_db()
        self.assertTrue(student.is_active)

    def test_staff_accounts_cannot_be_sanctioned(self):
        self._superadmin()
        target = make_user(role=UserRole.ADMIN)
        r = self.client.post(
            "/api/v1/ops/sanctions/",
            {"user_id": str(target.id), "kind": "ban"},
            format="json",
        )
        self.assertEqual(r.status_code, 400, r.content)

    def test_lift_reactivates_the_account(self):
        self._superadmin()
        student = make_user(role=UserRole.STUDENT)
        sanction = SanctionService.apply(student, reason="test")
        r = self.client.post(
            f"/api/v1/ops/sanctions/{sanction.id}/lift/",
            {"reason": "cleared"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        student.refresh_from_db()
        self.assertTrue(student.is_active)
        sanction.refresh_from_db()
        self.assertFalse(sanction.active)

    @override_settings(**_SMALL)
    def test_fake_lead_feed_and_dashboard_reflect_a_banned_account(self):
        self._superadmin()
        student = make_user(role=UserRole.STUDENT)
        for i in range(4):
            self._report_fake(student, f"D{i}")
        student.refresh_from_db()
        self.assertFalse(student.is_active)

        feed = self.client.get("/api/v1/ops/fake-lead-reports/").json()["data"]
        self.assertEqual(feed["count"], 1)
        row = feed["results"][0]
        self.assertEqual(row["student_id"], str(student.id))
        self.assertTrue(row["auto_banned"])
        self.assertFalse(row["account_active"])
        self.assertEqual(row["distinct_teachers_7d"], 4)

        dash = self.client.get("/api/v1/dashboard/").json()["data"]
        self.assertEqual(len(dash["fake_lead_alerts"]), 1)
        self.assertEqual(dash["fake_lead_alerts"][0]["student_id"], str(student.id))


class TeacherRatingSurfaceTests(_Mixin, APITestCase):
    def test_pending_ratings_endpoint_lists_unrated_unlocked_leads(self):
        student = make_user(role=UserRole.STUDENT)
        profile = self.make_teacher("Rater", plan=self.free_plan)
        login(self.client, profile.teacher.user)

        req1 = self.make_requirement(student=student)
        lead1 = Lead.objects.create(student_requirement=req1, teacher_profile=profile)
        unlock_lead_contact(profile.teacher, lead1)
        req2 = self.make_requirement(student=student)
        lead2 = Lead.objects.create(student_requirement=req2, teacher_profile=profile)
        unlock_lead_contact(profile.teacher, lead2)

        r = self.client.get("/api/v1/leads/pending-ratings/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["data"]["count"], 2)

        LeadQualityService.rate(
            teacher=profile.teacher, lead=lead1, verdict="genuine"
        )
        r = self.client.get("/api/v1/leads/pending-ratings/")
        self.assertEqual(r.json()["data"]["count"], 1)
        self.assertEqual(r.json()["data"]["results"][0]["id"], str(lead2.id))

    def test_teacher_dashboard_carries_the_pending_count(self):
        student = make_user(role=UserRole.STUDENT)
        profile = self.make_teacher("Dash", plan=self.free_plan)
        login(self.client, profile.teacher.user)
        req = self.make_requirement(student=student)
        lead = Lead.objects.create(student_requirement=req, teacher_profile=profile)
        unlock_lead_contact(profile.teacher, lead)

        d = self.client.get("/api/v1/dashboard/").json()["data"]
        self.assertEqual(d["pending_rating_count"], 1)

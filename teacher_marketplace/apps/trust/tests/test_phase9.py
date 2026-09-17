"""
Phase 9 - risk engine + anomaly alerts + ops review queue.

Run: python manage.py test apps.trust.tests.test_phase9 --settings=config.settings.test
"""

from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.trust.models import (
    ManualReviewItem,
    ManualReviewKind,
    ManualReviewStatus,
    RiskSignalKind,
    RiskState,
)
from apps.trust.services.anomaly_service import AnomalyService
from apps.trust.services.risk_service import RiskService
from apps.trust.services.trust_service import TrustService

AUTO = override_settings(TRUST_ENABLE_RISK_AUTO_ACTIONS=True)
ANOM = override_settings(TRUST_ENABLE_ANOMALY_ALERTS=True)


class RiskEngineTests(TestCase):
    def test_thresholds_move_state(self):
        u = make_user()
        RiskService.add_signal(u, kind=RiskSignalKind.ANOMALY, weight=15)
        self.assertEqual(u.trust_profile.risk_state, RiskState.NORMAL)  # 15 < 20
        RiskService.add_signal(u, kind=RiskSignalKind.DUPLICATE_ACCOUNT, weight=10)
        u.trust_profile.refresh_from_db()
        self.assertEqual(u.trust_profile.risk_state, RiskState.LIMITED)  # 25
        RiskService.add_signal(u, kind=RiskSignalKind.PAYMENT_RISK, weight=40)
        u.trust_profile.refresh_from_db()
        self.assertEqual(u.trust_profile.risk_state, RiskState.REVIEW)  # 65

    def test_review_state_opens_escalation_item_and_clears_below(self):
        u = make_user()
        RiskService.add_signal(u, kind=RiskSignalKind.LEAD_QUALITY, weight=55)
        item = ManualReviewItem.objects.filter(
            kind=ManualReviewKind.RISK_ESCALATION, dedupe_key=f"risk:{u.id}"
        ).first()
        self.assertIsNotNone(item)
        self.assertEqual(item.status, ManualReviewStatus.OPEN)

        # deactivate the signal -> recompute drops the state -> item resolved
        from apps.trust.models import RiskSignal

        RiskSignal.objects.filter(user=u).update(active=False)
        RiskService.recompute(u)
        item.refresh_from_db()
        self.assertEqual(item.status, ManualReviewStatus.RESOLVED)

    def test_is_suspended_needs_flag_and_state(self):
        u = make_user()
        RiskService.add_signal(u, kind=RiskSignalKind.PAYMENT_RISK, weight=90)
        u.trust_profile.refresh_from_db()
        self.assertEqual(u.trust_profile.risk_state, RiskState.SUSPENDED)
        self.assertFalse(RiskService.is_suspended(u))  # flag off
        with AUTO:
            self.assertTrue(RiskService.is_suspended(u))

    def test_dedupe_now_contributes_a_risk_signal(self):
        from apps.trust.models import IdentitySignatureKind
        from apps.trust.services.dedupe_service import DedupeService

        a = make_user()
        b = make_user()
        for u in (a, b):  # both "use" the same phone number
            DedupeService.record_signature(
                u, kind=IdentitySignatureKind.PHONE, raw_value="911111111111"
            )
        DedupeService.scan(b)
        from apps.trust.models import RiskSignal

        self.assertTrue(
            RiskSignal.objects.filter(
                user=b, kind=RiskSignalKind.DUPLICATE_ACCOUNT
            ).exists()
        )


class SuspendedGateTests(APITestCase):
    @AUTO
    def test_suspended_student_cannot_post_requirement(self):
        student = make_user(role=UserRole.STUDENT)
        RiskService.add_signal(student, kind=RiskSignalKind.LEAD_QUALITY, weight=95)
        login(self.client, student)
        r = self.client.post(
            "/api/v1/student-requirements/",
            {
                "subject": "Mathematics",
                "preferred_languages": ["English"],
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
            },
            format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_suspended_is_noop_when_flag_off(self):
        student = make_user(role=UserRole.STUDENT)
        RiskService.add_signal(student, kind=RiskSignalKind.LEAD_QUALITY, weight=95)
        self.assertFalse(RiskService.is_suspended(student))


class AnomalyTests(TestCase):
    def _req(self, ip, ua="Mozilla/5.0 test"):
        from django.test import RequestFactory

        rf = RequestFactory()
        r = rf.get("/", HTTP_USER_AGENT=ua)
        r.META["REMOTE_ADDR"] = ip
        return r

    def test_noop_when_flag_off(self):
        u = make_user()
        AnomalyService.on_login(u, self._req("203.0.113.4"))
        self.assertEqual(u.trust_profile.risk_state, RiskState.NORMAL)

    @ANOM
    def test_new_country_login_flags(self):
        u = make_user()
        # first login establishes IN
        AnomalyService.on_login(u, self._req("10.0.0.1"))
        u.trust_profile.refresh_from_db()
        self.assertEqual(u.trust_profile.known_countries, ["IN"])
        self.assertFalse(
            ManualReviewItem.objects.filter(kind=ManualReviewKind.ANOMALY).exists()
        )
        # then a login from SG -> anomaly
        AnomalyService.on_login(u, self._req("203.0.113.9"))
        from apps.trust.models import RiskSignal

        self.assertTrue(
            RiskSignal.objects.filter(user=u, kind=RiskSignalKind.ANOMALY).exists()
        )
        self.assertTrue(
            ManualReviewItem.objects.filter(kind=ManualReviewKind.ANOMALY).exists()
        )

    @ANOM
    def test_refund_spike_flags(self):
        u = make_user(role=UserRole.TEACHER)
        for _ in range(2):
            AnomalyService.note_refund(u)
        from apps.trust.models import RiskSignal

        self.assertFalse(
            RiskSignal.objects.filter(user=u, kind=RiskSignalKind.ANOMALY).exists()
        )
        AnomalyService.note_refund(u)  # 3rd
        self.assertTrue(
            RiskSignal.objects.filter(user=u, kind=RiskSignalKind.ANOMALY).exists()
        )


class OpsReviewQueueTests(APITestCase):
    def _superadmin(self):
        return make_user(role=UserRole.SUPERADMIN)

    def test_queue_lists_items_and_resolves(self):
        subject = make_user(role=UserRole.TEACHER)
        item = TrustService.open_review_item(
            kind=ManualReviewKind.CONTENT_FLAG,
            summary="test content flag",
            subject_user=subject,
            dedupe_key="t:1",
            priority=2,
        )
        sa = self._superadmin()
        login(self.client, sa)

        r = self.client.get("/api/v1/ops/review-queue/")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()["data"]
        results = body["results"] if isinstance(body, dict) else body
        self.assertTrue(any(str(item.id) == it["id"] for it in results))

        r = self.client.post(
            f"/api/v1/ops/review-queue/{item.id}/assign/", {}, format="json"
        )
        self.assertEqual(r.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.assignee_id, sa.id)
        self.assertEqual(item.status, ManualReviewStatus.IN_REVIEW)

        r = self.client.post(
            f"/api/v1/ops/review-queue/{item.id}/resolve/",
            {"resolution": "handled"},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.status, ManualReviewStatus.RESOLVED)

    def test_queue_is_superadmin_only(self):
        TrustService.open_review_item(
            kind=ManualReviewKind.ANOMALY, summary="x", dedupe_key="t:2"
        )
        login(self.client, make_user(role=UserRole.TEACHER))
        self.assertEqual(self.client.get("/api/v1/ops/review-queue/").status_code, 403)

    def test_risk_endpoint(self):
        risky = make_user(role=UserRole.TEACHER)
        RiskService.add_signal(risky, kind=RiskSignalKind.PAYMENT_RISK, weight=60)
        login(self.client, self._superadmin())
        r = self.client.get("/api/v1/ops/risk/")
        self.assertEqual(r.status_code, 200)
        emails = [x["email"] for x in r.json()["data"]["results"]]
        self.assertIn(risky.email, emails)

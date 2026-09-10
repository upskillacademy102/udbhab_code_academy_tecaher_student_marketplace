"""
Suspension-appeal flow (plan Section 5 residual risk).

Run: python manage.py test apps.trust.tests.test_suspension_appeal --settings=config.settings.test
"""

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.api_permissions import is_allowed
from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.trust.models import (
    ManualReviewItem,
    ManualReviewKind,
    RiskSignal,
    RiskSignalKind,
    SuspensionAppeal,
    SuspensionAppealStatus,
)
from apps.trust.services.appeal_service import AppealService
from apps.trust.services.risk_service import RiskService
from apps.trust.services.trust_service import TrustService

APPEALS_ON = {
    "TRUST_ENABLE_RISK_AUTO_ACTIONS": True,
    "TRUST_ENABLE_SUSPENSION_APPEALS": True,
}

_STATUS = "/api/v1/appeals/suspension/"
_WITHDRAW = "/api/v1/appeals/suspension/withdraw/"


def _suspend(user):
    RiskService.add_signal(user, kind=RiskSignalKind.LEAD_QUALITY, weight=95)


# ======================================================================
# Registry
# ======================================================================
class AppealRegistryTests(APITestCase):
    def test_routes_registered_for_every_authed_role(self):
        for role in (UserRole.STUDENT, UserRole.TEACHER, UserRole.ADMIN):
            self.assertTrue(is_allowed(role, "GET", "appeals:suspension"), role)
            self.assertTrue(is_allowed(role, "POST", "appeals:suspension"), role)
            self.assertTrue(
                is_allowed(role, "POST", "appeals:suspension-withdraw"), role
            )
        self.assertFalse(is_allowed(UserRole.STUDENT, "DELETE", "appeals:suspension"))


# ======================================================================
# Flag OFF - the default everywhere
# ======================================================================
class AppealsDisabledTests(APITestCase):
    def test_status_reports_disabled_and_not_suspended(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)  # signal exists, but auto-actions are OFF -> not suspended
        login(self.client, user)

        d = self.client.get(_STATUS).json()["data"]
        self.assertFalse(d["suspended"])
        self.assertFalse(d["appeals_enabled"])
        self.assertFalse(d["can_appeal"])
        self.assertIsNone(d["appeal"])

    def test_submit_is_rejected_when_feature_off(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)
        login(self.client, user)
        r = self.client.post(_STATUS, {"message": "a" * 40}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(SuspensionAppeal.objects.exists())

    def test_web_pages_not_redirected_when_feature_off(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)
        login(self.client, user)
        self.assertEqual(self.client.get("/student/").status_code, 200)


# ======================================================================
# Flag ON
# ======================================================================
@override_settings(**APPEALS_ON)
class AppealsEnabledTests(APITestCase):
    def test_not_suspended_user_cannot_appeal(self):
        user = make_user(role=UserRole.STUDENT)
        login(self.client, user)

        d = self.client.get(_STATUS).json()["data"]
        self.assertFalse(d["suspended"])
        self.assertTrue(d["appeals_enabled"])
        self.assertFalse(d["can_appeal"])

        r = self.client.post(_STATUS, {"message": "b" * 40}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_suspended_user_files_appeal_opens_review_item(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)
        login(self.client, user)

        d = self.client.get(_STATUS).json()["data"]
        self.assertTrue(d["suspended"] and d["can_appeal"])

        r = self.client.post(
            _STATUS, {"message": "I did nothing wrong, please re-check."}, format="json"
        )
        self.assertEqual(r.status_code, 201, r.content)

        appeal = SuspensionAppeal.objects.get(user=user)
        self.assertEqual(appeal.status, SuspensionAppealStatus.PENDING)
        self.assertEqual(appeal.risk_state_at_submit, "suspended")

        item = ManualReviewItem.objects.get(
            kind=ManualReviewKind.SUSPENSION_APPEAL, subject_user=user
        )
        self.assertEqual(appeal.review_item_id, item.id)

        # can_appeal drops while one is open
        d = self.client.get(_STATUS).json()["data"]
        self.assertFalse(d["can_appeal"])
        self.assertEqual(d["appeal"]["status"], "pending")

    def test_second_appeal_while_one_open_conflicts(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)
        login(self.client, user)
        self.client.post(_STATUS, {"message": "first appeal message"}, format="json")
        r = self.client.post(
            _STATUS, {"message": "second appeal message"}, format="json"
        )
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(SuspensionAppeal.objects.filter(user=user).count(), 1)

    def test_withdraw_closes_appeal_and_review_item(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)
        login(self.client, user)
        self.client.post(
            _STATUS, {"message": "please withdraw this later"}, format="json"
        )

        r = self.client.post(_WITHDRAW, {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        appeal = SuspensionAppeal.objects.get(user=user)
        self.assertEqual(appeal.status, SuspensionAppealStatus.WITHDRAWN)
        appeal.review_item.refresh_from_db()
        self.assertEqual(appeal.review_item.status, "dismissed")

        # a fresh appeal is allowed again
        d = self.client.get(_STATUS).json()["data"]
        self.assertTrue(d["can_appeal"])

    def test_ops_resolving_the_item_grants_and_lifts_suspension(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)
        self.assertTrue(RiskService.is_suspended(user))

        appeal = AppealService.submit(user, message="genuine student, mistaken flag")
        superadmin = make_user(role=UserRole.SUPERADMIN)
        TrustService.resolve_review_item(
            appeal.review_item, by=superadmin, resolution="Verified - cleared."
        )

        appeal.refresh_from_db()
        self.assertEqual(appeal.status, SuspensionAppealStatus.GRANTED)
        self.assertEqual(appeal.decided_by_id, superadmin.id)
        self.assertFalse(RiskSignal.objects.filter(user=user, active=True).exists())
        self.assertFalse(RiskService.is_suspended(user))

    def test_ops_dismissing_the_item_denies_and_keeps_suspension(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)
        appeal = AppealService.submit(user, message="let me back in immediately")
        superadmin = make_user(role=UserRole.SUPERADMIN)
        TrustService.resolve_review_item(
            appeal.review_item,
            by=superadmin,
            resolution="Confirmed abuse.",
            dismiss=True,
        )

        appeal.refresh_from_db()
        self.assertEqual(appeal.status, SuspensionAppealStatus.DENIED)
        self.assertEqual(appeal.decision_note, "Confirmed abuse.")
        self.assertTrue(RiskService.is_suspended(user))

    def test_ops_review_queue_endpoint_grants_appeal(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)
        appeal = AppealService.submit(user, message="please review my account again")

        superadmin = make_user(role=UserRole.SUPERADMIN)
        login(self.client, superadmin)
        r = self.client.post(
            f"/api/v1/ops/review-queue/{appeal.review_item_id}/resolve/",
            {"resolution": "cleared"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        appeal.refresh_from_db()
        self.assertEqual(appeal.status, SuspensionAppealStatus.GRANTED)
        self.assertFalse(RiskService.is_suspended(user))


# ======================================================================
# Web page + redirect
# ======================================================================
@override_settings(**APPEALS_ON)
class SuspendedPageTests(APITestCase):
    def test_suspended_user_is_redirected_from_app_pages(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)
        login(self.client, user)

        resp = self.client.get("/student/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/suspended/")

    def test_suspended_page_itself_renders_without_looping(self):
        user = make_user(role=UserRole.STUDENT)
        _suspend(user)
        login(self.client, user)
        resp = self.client.get("/suspended/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("under review", resp.content.decode().lower())

    def test_healthy_user_not_redirected(self):
        user = make_user(role=UserRole.STUDENT)
        login(self.client, user)
        self.assertEqual(self.client.get("/student/").status_code, 200)

    def test_suspended_page_requires_login(self):
        resp = self.client.get("/suspended/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

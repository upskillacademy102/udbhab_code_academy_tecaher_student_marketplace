"""
Support admin's onboarding-call flow: the Support-only queue, "accept and go
live", the teacher-side snapshot that exposes the room once live, and the
video_interview-only / accepted-by-me guard on the per-item verdict.

Run: python manage.py test apps.teacher_profile.tests.test_onboarding_call_accept \
     --settings=config.settings.test
"""

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_named_admin, make_user
from apps.teacher_profile.models import TeacherProfile
from apps.teachers.models import Teacher
from apps.trust.models import OnboardingCallRequest
from apps.trust.services.verification_service import VerificationService

LIST_URL = "/api/v1/admin/onboarding-calls/"


def _client_for(test, user):
    c = test.client_class()
    login(c, user)
    return c


class _CallFixture(APITestCase):
    def setUp(self):
        self.tuser = make_user(role=UserRole.TEACHER)
        self.teacher = Teacher.objects.create(user=self.tuser, experience_years=2)
        TeacherProfile.objects.create(teacher=self.teacher)
        VerificationService.submit_reviewed_item(
            self.teacher, "video_interview", payload={}
        )
        self.call = OnboardingCallRequest.objects.get(item__teacher=self.teacher)
        self.accept_url = f"{LIST_URL}{self.teacher.id}/accept/"
        self.item_url = (
            f"/api/v1/admin/teacher-profiles/{self.teacher.id}"
            "/verification-items/video_interview/"
        )
        self.support = make_named_admin(department="Support")


class QueueScopeTests(_CallFixture):
    def test_support_admin_can_list(self):
        r = _client_for(self, self.support).get(LIST_URL)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()["data"]), 1)

    def test_other_departments_and_departmentless_admins_cannot_list(self):
        for admin in (
            make_named_admin(department="Verification", email="v@x.test"),
            make_named_admin(department="Finance", email="f@x.test"),
            make_user(role=UserRole.ADMIN, email="plain@x.test"),
        ):
            with self.subTest(admin=admin.email):
                r = _client_for(self, admin).get(LIST_URL)
                self.assertEqual(r.status_code, 403, r.content)


class AcceptTests(_CallFixture):
    def test_support_admin_accepts_and_call_goes_live(self):
        r = _client_for(self, self.support).post(self.accept_url, {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()["data"]
        self.assertIsNotNone(data["call_started_at"])
        self.assertEqual(data["room_name"], f"tm-onboarding-{self.call.id}")
        self.call.refresh_from_db()
        self.assertEqual(self.call.assigned_admin, self.support)
        self.assertTrue(self.call.is_live)

    def test_room_is_withheld_before_accept(self):
        r = _client_for(self, self.support).get(LIST_URL)
        row = r.json()["data"][0]
        self.assertIsNone(row["call_started_at"])
        self.assertIsNone(row["room_name"])

    def test_accepting_twice_by_same_admin_is_idempotent(self):
        c = _client_for(self, self.support)
        c.post(self.accept_url, {}, format="json")
        first = OnboardingCallRequest.objects.get(pk=self.call.pk).call_started_at
        r = c.post(self.accept_url, {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(
            OnboardingCallRequest.objects.get(pk=self.call.pk).call_started_at, first
        )

    def test_second_admin_cannot_take_a_live_call(self):
        _client_for(self, self.support).post(self.accept_url, {}, format="json")
        other = make_named_admin(
            department="Support", first_name="Other", last_name="Person", email="o@x.test"
        )
        r = _client_for(self, other).post(self.accept_url, {}, format="json")
        self.assertEqual(r.status_code, 409, r.content)
        self.call.refresh_from_db()
        self.assertEqual(self.call.assigned_admin, self.support)

    def test_already_decided_call_cannot_be_accepted(self):
        self.call.item.status = "verified"
        self.call.item.save(update_fields=["status"])
        r = _client_for(self, self.support).post(self.accept_url, {}, format="json")
        self.assertEqual(r.status_code, 409, r.content)

    def test_no_request_is_404(self):
        other = Teacher.objects.create(
            user=make_user(role=UserRole.TEACHER, email="nocall@x.test"),
            experience_years=1,
        )
        r = _client_for(self, self.support).post(
            f"{LIST_URL}{other.id}/accept/", {}, format="json"
        )
        self.assertEqual(r.status_code, 404, r.content)

    def test_non_support_roles_cannot_accept(self):
        for user in (
            make_named_admin(department="Verification", email="v2@x.test"),
            make_named_admin(department="Finance", email="f2@x.test"),
            make_user(role=UserRole.ADMIN, email="plain2@x.test"),
            make_user(role=UserRole.TEACHER, email="t2@x.test"),
            make_user(role=UserRole.STUDENT, email="s2@x.test"),
        ):
            with self.subTest(user=user.email):
                r = _client_for(self, user).post(self.accept_url, {}, format="json")
                self.assertEqual(r.status_code, 403, r.content)
        self.call.refresh_from_db()
        self.assertFalse(self.call.is_live)

    def test_superadmin_can_accept(self):
        sa = make_user(role=UserRole.SUPERADMIN)
        r = _client_for(self, sa).post(self.accept_url, {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)


class TeacherSnapshotTests(_CallFixture):
    def _call_block(self):
        snap = VerificationService.snapshot(self.teacher)
        row = next(i for i in snap["items"] if i["key"] == "video_interview")
        return row["call"]

    def test_teacher_sees_no_room_until_accepted(self):
        block = self._call_block()
        self.assertIsNone(block["call_started_at"])
        self.assertIsNone(block["room_name"])

    def test_teacher_sees_the_room_once_live(self):
        _client_for(self, self.support).post(self.accept_url, {}, format="json")
        block = self._call_block()
        self.assertIsNotNone(block["call_started_at"])
        self.assertEqual(block["room_name"], f"tm-onboarding-{self.call.id}")


class ApprovalGuardTests(_CallFixture):
    def _decide(self, client, status, key="video_interview"):
        url = (
            f"/api/v1/admin/teacher-profiles/{self.teacher.id}"
            f"/verification-items/{key}/"
        )
        return client.post(url, {"status": status}, format="json")

    def test_accepting_admin_can_approve(self):
        c = _client_for(self, self.support)
        c.post(self.accept_url, {}, format="json")
        r = self._decide(c, "verified")
        self.assertEqual(r.status_code, 200, r.content)
        self.call.item.refresh_from_db()
        self.assertEqual(self.call.item.status, "verified")

    def test_accepting_admin_can_reject(self):
        c = _client_for(self, self.support)
        c.post(self.accept_url, {}, format="json")
        r = self._decide(c, "rejected")
        self.assertEqual(r.status_code, 200, r.content)
        self.call.item.refresh_from_db()
        self.assertEqual(self.call.item.status, "rejected")

    def test_approving_only_touches_video_interview(self):
        c = _client_for(self, self.support)
        c.post(self.accept_url, {}, format="json")
        self._decide(c, "verified")
        others = self.teacher.verification_items.filter(
            key__in=["gov_id", "selfie_liveness", "address_proof", "bank_penny_drop"]
        )
        self.assertTrue(others.exists())
        self.assertFalse(others.filter(status="verified").exists())

    def test_support_admin_who_did_not_accept_cannot_decide(self):
        r = self._decide(_client_for(self, self.support), "verified")
        self.assertEqual(r.status_code, 403, r.content)
        self.call.item.refresh_from_db()
        self.assertNotEqual(self.call.item.status, "verified")

    def test_a_different_support_admin_cannot_decide_someone_elses_call(self):
        _client_for(self, self.support).post(self.accept_url, {}, format="json")
        other = make_named_admin(
            department="Support", first_name="Other", last_name="Person", email="o2@x.test"
        )
        r = self._decide(_client_for(self, other), "verified")
        self.assertEqual(r.status_code, 403, r.content)

    def test_support_admin_cannot_decide_any_other_item(self):
        c = _client_for(self, self.support)
        c.post(self.accept_url, {}, format="json")
        for key in ("gov_id", "selfie_liveness", "address_proof", "bank_penny_drop"):
            with self.subTest(key=key):
                r = self._decide(c, "verified", key=key)
                self.assertEqual(r.status_code, 403, r.content)

    def test_support_admin_cannot_set_overall_verification_status(self):
        c = _client_for(self, self.support)
        c.post(self.accept_url, {}, format="json")
        r = c.post(
            f"/api/v1/admin/teacher-profiles/{self.teacher.id}/verification/",
            {"status": "verified"},
            format="json",
        )
        self.assertEqual(r.status_code, 403, r.content)

    def test_verification_department_admin_is_unaffected(self):
        verifier = make_named_admin(department="Verification", email="ver@x.test")
        c = _client_for(self, verifier)
        for key in ("video_interview", "gov_id"):
            with self.subTest(key=key):
                r = self._decide(c, "verified", key=key)
                self.assertEqual(r.status_code, 200, r.content)

"""
Direct-offer flow: a student picks one specific teacher directly
("Learn with this teacher" on that teacher's own profile), bypassing
the general subscription/distance matching pool entirely.

Run: python manage.py test apps.student_requirement.tests.test_direct_offer \
     --settings=config.settings.test
"""

from datetime import time

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.languages.models import Language
from apps.lead_engine.models import Lead, LeadUnlockHistory
from apps.matching.models import AssignmentStatus, LeadAssignment
from apps.student_requirement.models import RequirementStatus, StudentRequirement
from apps.subjects.models import Subject
from apps.teacher_profile.models import (
    TeacherProfile,
    TeacherWeeklyAvailability,
    TeachingMode,
    VerificationStatus,
)
from apps.teachers.models import Teacher

DIRECT_OFFER = "/api/v1/student-requirements/direct-offer/"
IST = "Asia/Kolkata"


class DirectOfferTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.math = Subject.objects.create(name="Mathematics")
        cls.physics = Subject.objects.create(name="Physics")
        cls.english = Language.objects.get_or_create(
            name="English", defaults={"code": "en"}
        )[0]
        cls.bengali = Language.objects.get_or_create(
            name="Bengali", defaults={"code": "bn"}
        )[0]

    def _make_teacher(self, name="Ramesh"):
        user = make_user(
            role=UserRole.TEACHER,
            email=f"{name.lower()}@teacher.test",
            first_name=name,
            last_name="T",
        )
        teacher = Teacher.objects.create(
            user=user,
            experience_years=5,
            profile_photo="teachers/profile_photos/test.jpg",
        )
        profile = TeacherProfile.objects.create(
            teacher=teacher,
            teaching_mode=TeachingMode.ONLINE,
            rating="4.50",
            verification_status=VerificationStatus.VERIFIED,
        )
        profile.subjects.set([self.math])
        profile.languages.set([self.english])
        TeacherWeeklyAvailability.objects.create(
            teacher_profile=profile,
            day_of_week=1,
            start_time=time(18, 0),
            end_time=time(20, 0),
            timezone=IST,
            is_active=True,
        )
        return teacher, profile

    def setUp(self):
        self.teacher, self.teacher_profile = self._make_teacher()
        self.student = make_user(role=UserRole.STUDENT)
        login(self.client, self.student)

    def _payload(self, **overrides):
        body = {
            "offer_teacher_id": str(self.teacher.id),
            "subject_id": str(self.math.id),
            "language_ids": [str(self.english.id)],
            "no_language_preference": False,
            "teaching_mode": "online",
            "day_of_week": 1,
            "start_time": "18:30",
            "end_time": "19:30",
            "timezone": IST,
            "class_duration_minutes": 60,
        }
        body.update(overrides)
        return body

    def _switch_to(self, user):
        self.client.post("/api/v1/auth/logout/", {}, format="json")
        login(self.client, user)

    # ---- happy path ------------------------------------------------------
    def test_creates_single_lead_and_never_expiring_assignment(self):
        resp = self.client.post(DIRECT_OFFER, self._payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)

        requirement = StudentRequirement.objects.get(
            id=resp.json()["data"]["requirement_id"]
        )
        self.assertEqual(requirement.offer_teacher_id, self.teacher.id)
        self.assertEqual(
            Lead.objects.filter(student_requirement=requirement).count(), 1
        )

        assignment = LeadAssignment.objects.get(lead__student_requirement=requirement)
        self.assertTrue(assignment.is_direct)
        self.assertTrue(assignment.never_expires)
        self.assertEqual(assignment.status, AssignmentStatus.ASSIGNED)
        self.assertEqual(assignment.teacher_id, self.teacher.id)

    # ---- server-side re-validation, never trust the client -------------
    def test_offscope_subject_rejected(self):
        resp = self.client.post(
            DIRECT_OFFER, self._payload(subject_id=str(self.physics.id)), format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertFalse(
            StudentRequirement.objects.filter(offer_teacher=self.teacher).exists()
        )

    def test_offscope_language_rejected(self):
        resp = self.client.post(
            DIRECT_OFFER,
            self._payload(language_ids=[str(self.bengali.id)]),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_offscope_time_rejected(self):
        resp = self.client.post(
            DIRECT_OFFER,
            self._payload(start_time="09:00", end_time="10:00"),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_offscope_teaching_mode_rejected(self):
        # Teacher is ONLINE-only in setUp.
        resp = self.client.post(
            DIRECT_OFFER, self._payload(teaching_mode="offline"), format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_offer_teacher_not_settable_via_normal_requirement_create(self):
        resp = self.client.post(
            "/api/v1/student-requirements/",
            {
                "subject": "Mathematics",
                "preferred_languages": ["English"],
                "teaching_mode": "online",
                "class_duration_minutes": 60,
                "offer_teacher": str(self.teacher.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        requirement = StudentRequirement.objects.get(id=resp.json()["data"]["id"])
        self.assertIsNone(requirement.offer_teacher_id)

    # ---- unlock/review/reject reuse the SAME machinery as any lead -----
    def test_unlock_reuses_normal_quota_flow_and_appears_only_in_offers(self):
        resp = self.client.post(DIRECT_OFFER, self._payload(), format="json")
        lead_id = resp.json()["data"]["lead_id"]

        self._switch_to(self.teacher.user)

        offers = self.client.get("/api/v1/leads/offers/")
        self.assertEqual(len(offers.json()["data"]), 1)
        self.assertEqual(offers.json()["data"][0]["id"], lead_id)

        # Never shows up in the ordinary Leads list - Offers only.
        leads = self.client.get("/api/v1/leads/")
        self.assertEqual(leads.json()["data"], [])

        unlock = self.client.post(
            "/api/v1/leads/unlock/", {"lead_id": lead_id}, format="json"
        )
        self.assertEqual(unlock.status_code, 200, unlock.content)
        self.assertTrue(unlock.json()["data"]["is_free_unlock"])
        self.assertEqual(
            LeadUnlockHistory.objects.filter(teacher=self.teacher).count(), 1
        )

        # Still must review it, exactly like any other unlocked lead.
        pending = self.client.get("/api/v1/leads/pending-ratings/")
        self.assertEqual(pending.json()["data"]["count"], 1)

    def test_reject_leaves_requirement_open_with_no_broadcast(self):
        resp = self.client.post(DIRECT_OFFER, self._payload(), format="json")
        lead_id = resp.json()["data"]["lead_id"]
        requirement_id = resp.json()["data"]["requirement_id"]

        self._switch_to(self.teacher.user)
        reject = self.client.post(f"/api/v1/leads/{lead_id}/reject/", {}, format="json")
        self.assertEqual(reject.status_code, 200, reject.content)

        requirement = StudentRequirement.objects.get(id=requirement_id)
        self.assertEqual(requirement.status, RequirementStatus.OPEN)
        # No general-pool broadcast happened - still exactly the one Lead.
        self.assertEqual(
            Lead.objects.filter(student_requirement=requirement).count(), 1
        )

    def test_cannot_reject_after_unlocking(self):
        resp = self.client.post(DIRECT_OFFER, self._payload(), format="json")
        lead_id = resp.json()["data"]["lead_id"]

        self._switch_to(self.teacher.user)
        self.client.post("/api/v1/leads/unlock/", {"lead_id": lead_id}, format="json")
        reject = self.client.post(f"/api/v1/leads/{lead_id}/reject/", {}, format="json")
        self.assertEqual(reject.status_code, 400)

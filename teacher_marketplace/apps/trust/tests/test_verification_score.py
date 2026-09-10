"""
Teacher verification checklist -> progress score -> badge, plus the
auto-upgrade of marketplace verification_status when the floor is met.

Run: python manage.py test apps.trust.tests.test_verification_score \
     --settings=config.settings.test
"""

from decimal import Decimal

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_user
from apps.subjects.models import Subject
from apps.teacher_profile.models import (
    DayOfWeek,
    TeacherProfile,
    TeacherWeeklyAvailability,
    TeachingMode,
    VerificationStatus,
)
from apps.teachers.models import Teacher
from apps.trust.models import TeacherVerificationItemStatus, TeacherVerificationKey
from apps.trust.services.verification_service import VerificationService

S = TeacherVerificationItemStatus
K = TeacherVerificationKey


class VerificationScoreTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.subject = Subject.objects.create(name="Physics")

    def _teacher(self, **user_kw):
        user = make_user(role=UserRole.TEACHER, **user_kw)
        return Teacher.objects.create(user=user)

    def _score(self, teacher) -> Decimal:
        return VerificationService.recompute(teacher).verification_score

    def _status(self, teacher, key) -> str:
        return teacher.verification_items.get(key=key).status

    def test_empty_teacher_scores_zero(self):
        t = self._teacher()
        self.assertEqual(self._score(t), Decimal("0.000"))
        self.assertEqual(t.verification_items.count(), 10)
        self.assertTrue(all(i.status == S.PENDING for i in t.verification_items.all()))

    def test_verified_contacts_move_the_score(self):
        t = self._teacher()
        t.user.is_email_verified = True
        t.user.is_mobile_verified = True
        t.user.save(update_fields=["is_email_verified", "is_mobile_verified"])
        # email 10 + mobile 15 out of 100
        self.assertEqual(self._score(t), Decimal("0.250"))
        self.assertEqual(self._status(t, K.EMAIL_VERIFIED), S.VERIFIED)

    def test_reaching_the_floor_auto_verifies_the_marketplace_profile(self):
        t = self._teacher()
        t.bio = "10 years teaching physics."
        t.experience_years = 10
        t.qualification_level = "masters"
        t.save(update_fields=["bio", "experience_years", "qualification_level"])
        t.user.is_email_verified = t.user.is_mobile_verified = True
        t.user.save(update_fields=["is_email_verified", "is_mobile_verified"])

        mp = TeacherProfile.objects.create(
            teacher=t,
            teaching_mode=TeachingMode.BOTH,
            headline="Physics tutor",
            verification_status=VerificationStatus.PENDING,
        )
        mp.subjects.set([self.subject])
        TeacherWeeklyAvailability.objects.create(
            teacher_profile=mp,
            day_of_week=DayOfWeek.MONDAY,
            start_time="18:00",
            end_time="20:00",
            timezone="Asia/Kolkata",
        )

        score = self._score(t)
        # floor = 15 + 10 + 10 + 10 + 15 = 60
        self.assertEqual(score, Decimal("0.600"))
        mp.refresh_from_db()
        self.assertEqual(mp.verification_status, VerificationStatus.VERIFIED)

    def test_full_verification_awards_the_badge(self):
        t = self._teacher()
        t.bio, t.experience_years, t.qualification_level = "bio", 5, "bachelors"
        t.save(update_fields=["bio", "experience_years", "qualification_level"])
        t.user.is_email_verified = t.user.is_mobile_verified = True
        t.user.save(update_fields=["is_email_verified", "is_mobile_verified"])
        mp = TeacherProfile.objects.create(teacher=t, teaching_mode=TeachingMode.ONLINE)
        mp.subjects.set([self.subject])
        TeacherWeeklyAvailability.objects.create(
            teacher_profile=mp,
            day_of_week=1,
            start_time="09:00",
            end_time="10:00",
            timezone="UTC",
        )
        for key in (K.GOV_ID, K.SELFIE_LIVENESS, K.ADDRESS_PROOF, K.VIDEO_INTERVIEW):
            VerificationService.set_reviewed_item(t, key, status=S.VERIFIED)

        profile = VerificationService.recompute(t)
        self.assertEqual(profile.verification_score, Decimal("1.000"))
        self.assertTrue(profile.is_fully_verified)

    def test_rejecting_a_reviewed_item_lowers_the_score(self):
        t = self._teacher()
        VerificationService.set_reviewed_item(t, K.GOV_ID, status=S.VERIFIED)
        self.assertEqual(self._score(t), Decimal("0.200"))
        VerificationService.set_reviewed_item(t, K.GOV_ID, status=S.REJECTED)
        self.assertEqual(self._score(t), Decimal("0.000"))

    def test_recompute_never_downgrades_an_admin_verified_status(self):
        t = self._teacher()
        mp = TeacherProfile.objects.create(
            teacher=t, verification_status=VerificationStatus.VERIFIED
        )
        VerificationService.recompute(t)  # floor NOT met
        mp.refresh_from_db()
        self.assertEqual(mp.verification_status, VerificationStatus.VERIFIED)

    def test_recompute_does_not_upgrade_a_rejected_status(self):
        t = self._teacher()
        t.bio, t.experience_years, t.qualification_level = "b", 1, "diploma"
        t.save(update_fields=["bio", "experience_years", "qualification_level"])
        t.user.is_email_verified = t.user.is_mobile_verified = True
        t.user.save(update_fields=["is_email_verified", "is_mobile_verified"])
        mp = TeacherProfile.objects.create(
            teacher=t, verification_status=VerificationStatus.REJECTED
        )
        mp.subjects.set([self.subject])
        TeacherWeeklyAvailability.objects.create(
            teacher_profile=mp,
            day_of_week=1,
            start_time="09:00",
            end_time="10:00",
            timezone="UTC",
        )
        VerificationService.recompute(t)
        mp.refresh_from_db()
        self.assertEqual(mp.verification_status, VerificationStatus.REJECTED)

    def test_set_reviewed_item_rejects_auto_keys(self):
        from apps.core.exceptions.custom_exceptions import ValidationException

        t = self._teacher()
        with self.assertRaises(ValidationException):
            VerificationService.set_reviewed_item(
                t, K.EMAIL_VERIFIED, status=S.VERIFIED
            )

    def test_snapshot_shape(self):
        t = self._teacher()
        snap = VerificationService.snapshot(t)
        self.assertEqual(len(snap["items"]), 10)
        self.assertIn("progress_percent", snap)
        self.assertFalse(snap["floor_met"])

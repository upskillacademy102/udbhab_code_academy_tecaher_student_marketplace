"""
Verification-score recompute triggers: OTP verify, the nightly task, the
management command.

Run: python manage.py test apps.trust.tests.test_verification_triggers \
     --settings=config.settings.test
"""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_user
from apps.subjects.models import Subject
from apps.teacher_profile.models import TeacherProfile
from apps.teachers.models import Teacher
from apps.trust.models import TeacherVerificationKey
from apps.trust.services.otp_service import OTPService
from apps.trust.tasks import recompute_teacher_verification_scores

K = TeacherVerificationKey


class TriggerTests(TestCase):
    def _teacher(self):
        user = make_user(role=UserRole.TEACHER)
        return Teacher.objects.create(user=user)

    def test_verifying_email_via_otp_recomputes_a_teacher_score(self):
        t = self._teacher()
        self.assertEqual(t.user.trust_profile.verification_score, Decimal("0.000"))

        ch = OTPService.issue(t.user, channel="email")
        # confirm with the right code by reaching into the issued challenge
        from apps.trust.services.otp_service import _hash

        ch.code_hash = _hash("654321")
        ch.save(update_fields=["code_hash"])
        OTPService.verify(t.user, channel="email", code="654321")

        t.user.trust_profile.refresh_from_db()
        self.assertEqual(
            t.user.trust_profile.verification_score, Decimal("0.100")
        )  # email = 10/100
        self.assertEqual(
            t.verification_items.get(key=K.EMAIL_VERIFIED).status, "verified"
        )

    def test_nightly_task_recomputes_all_teachers(self):
        subject = Subject.objects.create(name="Chess")
        teachers = [self._teacher() for _ in range(3)]
        for t in teachers:
            t.bio, t.experience_years, t.qualification_level = "b", 3, "diploma"
            t.profile_photo = "teachers/profile_photos/test.jpg"
            t.save(update_fields=["bio", "experience_years", "qualification_level", "profile_photo"])
            t.user.is_email_verified = t.user.is_mobile_verified = True
            t.user.save(update_fields=["is_email_verified", "is_mobile_verified"])
            mp = TeacherProfile.objects.create(teacher=t)
            mp.subjects.set([subject])

        result = recompute_teacher_verification_scores()
        self.assertGreaterEqual(result["recomputed"], 3)
        for t in teachers:
            t.user.trust_profile.refresh_from_db()
            # profile_basics 15 + email 10 + mobile 15 + subjects 10 = 50
            self.assertEqual(t.user.trust_profile.verification_score, Decimal("0.500"))

    def test_management_command_runs(self):
        self._teacher()
        out = StringIO()
        call_command("recompute_verification_scores", stdout=out)
        self.assertIn("Recomputed", out.getvalue())

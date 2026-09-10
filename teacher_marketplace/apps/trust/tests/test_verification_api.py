"""
Teacher verification endpoints + the admin per-item verdict.

Run: python manage.py test apps.trust.tests.test_verification_api \
     --settings=config.settings.test
"""

import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.teacher_profile.models import TeacherProfile
from apps.teachers.models import Teacher
from apps.trust.models import ManualReviewItem, ManualReviewKind, TeacherVerificationEvidence
from apps.trust.services.verification_service import VerificationService

ME = "/api/v1/teachers/profile/verification/"


def _photo(name="photo.png", color="blue"):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


class TeacherVerificationApiTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.TEACHER)
        self.teacher = Teacher.objects.create(user=self.user, experience_years=5)
        TeacherProfile.objects.create(teacher=self.teacher)
        login(self.client, self.user)

    def test_get_snapshot(self):
        r = self.client.get(ME)
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()["data"]
        self.assertEqual(len(data["items"]), 10)
        self.assertIn("progress_percent", data)
        self.assertFalse(data["is_fully_verified"])

    def test_submit_gov_id_goes_to_manual_review(self):
        r = self.client.post(
            f"{ME}gov_id/submit/",
            {
                "full_name": "Ada Lovelace",
                "front": _photo("front.png"),
                "back": _photo("back.png"),
            },
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.content)
        item = self.teacher.verification_items.get(key="gov_id")
        self.assertEqual(item.status, "submitted")
        self.assertEqual(item.evidence_files.count(), 2)
        self.assertTrue(
            ManualReviewItem.objects.filter(
                kind=ManualReviewKind.TEACHER_VERIFICATION, subject_user=self.user
            ).exists()
        )

    def test_submit_gov_id_without_photos_is_400(self):
        r = self.client.post(
            f"{ME}gov_id/submit/", {"full_name": "Ada Lovelace"}, format="multipart"
        )
        self.assertEqual(r.status_code, 400, r.content)

    def test_submit_gov_id_with_only_one_side_is_400(self):
        r = self.client.post(
            f"{ME}gov_id/submit/", {"front": _photo()}, format="multipart"
        )
        self.assertEqual(r.status_code, 400, r.content)

    def test_submit_address_proof_with_photo(self):
        r = self.client.post(
            f"{ME}address_proof/submit/", {"document": _photo()}, format="multipart"
        )
        self.assertEqual(r.status_code, 200, r.content)
        item = self.teacher.verification_items.get(key="address_proof")
        self.assertEqual(item.status, "submitted")
        self.assertEqual(item.evidence_files.count(), 1)

    def test_submit_address_proof_without_photo_is_400(self):
        r = self.client.post(f"{ME}address_proof/submit/", {}, format="multipart")
        self.assertEqual(r.status_code, 400, r.content)

    def test_submit_selfie_liveness_requires_all_five_poses(self):
        r = self.client.post(
            f"{ME}selfie_liveness/submit/",
            {"center": _photo(), "left": _photo()},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400, r.content)

    def test_submit_selfie_liveness_with_all_five_poses(self):
        r = self.client.post(
            f"{ME}selfie_liveness/submit/",
            {
                "center": _photo("c.png"),
                "left": _photo("l.png"),
                "right": _photo("r.png"),
                "up": _photo("u.png"),
                "down": _photo("d.png"),
            },
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.content)
        item = self.teacher.verification_items.get(key="selfie_liveness")
        self.assertEqual(item.evidence_files.count(), 5)
        # a resubmission replaces the old evidence rather than piling up
        r2 = self.client.post(
            f"{ME}selfie_liveness/submit/",
            {
                "center": _photo("c2.png"),
                "left": _photo("l2.png"),
                "right": _photo("r2.png"),
                "up": _photo("u2.png"),
                "down": _photo("d2.png"),
            },
            format="multipart",
        )
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(
            TeacherVerificationEvidence.objects.filter(item=item).count(), 5
        )

    def test_submit_non_image_payload_is_rejected(self):
        html = SimpleUploadedFile(
            "x.png", b"<html><script>alert(1)</script></html>", content_type="image/png"
        )
        r = self.client.post(
            f"{ME}address_proof/submit/", {"document": html}, format="multipart"
        )
        self.assertEqual(r.status_code, 400, r.content)

    def test_video_interview_request_opens_review_item(self):
        r = self.client.post(f"{ME}video_interview/submit/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        item = self.teacher.verification_items.get(key="video_interview")
        self.assertEqual(item.status, "submitted")
        self.assertTrue(
            ManualReviewItem.objects.filter(
                kind=ManualReviewKind.TEACHER_VERIFICATION,
                subject_user=self.user,
                dedupe_key=f"tv:{self.teacher.id}:video_interview",
            ).exists()
        )

    def test_video_interview_request_is_idempotent(self):
        self.client.post(f"{ME}video_interview/submit/", {}, format="json")
        r = self.client.post(f"{ME}video_interview/submit/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(
            ManualReviewItem.objects.filter(
                kind=ManualReviewKind.TEACHER_VERIFICATION,
                subject_user=self.user,
                dedupe_key=f"tv:{self.teacher.id}:video_interview",
            ).count(),
            1,
        )

    def test_student_cannot_access(self):
        c = self.client_class()
        login(c, make_user(role=UserRole.STUDENT))
        self.assertEqual(c.get(ME).status_code, 403)


class AdminVerdictTests(APITestCase):
    def setUp(self):
        self.tuser = make_user(role=UserRole.TEACHER)
        self.teacher = Teacher.objects.create(user=self.tuser, experience_years=3)
        TeacherProfile.objects.create(teacher=self.teacher)
        # teacher submits -> lands in manual review
        VerificationService.submit_reviewed_item(
            self.teacher, "gov_id", payload={"full_name": "X", "document_ref": "d"}
        )
        self.admin = make_user(role=UserRole.ADMIN)
        login(self.client, self.admin)
        self.url = f"/api/v1/admin/teacher-profiles/{self.teacher.id}/verification-items/gov_id/"

    def test_admin_verifies_an_item(self):
        r = self.client.post(
            self.url, {"status": "verified", "notes": "looks good"}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.content)
        item = self.teacher.verification_items.get(key="gov_id")
        self.assertEqual(item.status, "verified")
        self.assertEqual(item.reviewed_by, self.admin)
        self.tuser.trust_profile.refresh_from_db()
        self.assertEqual(self.tuser.trust_profile.verification_score, Decimal("0.200"))
        # the linked review-queue item is resolved
        self.assertFalse(item.review_item.is_open)

    def test_admin_rejects_an_item(self):
        r = self.client.post(self.url, {"status": "rejected"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(
            self.teacher.verification_items.get(key="gov_id").status, "rejected"
        )

    def test_bad_status_is_400(self):
        r = self.client.post(self.url, {"status": "banana"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_non_admin_cannot(self):
        c = self.client_class()
        login(c, make_user(role=UserRole.TEACHER))
        self.assertEqual(
            c.post(self.url, {"status": "verified"}, format="json").status_code, 403
        )


class IdentityCheckEitherOrTests(APITestCase):
    """Selfie/liveness (10) and the video call (5) are either/or: passing
    either one earns their combined 15/100, not just its own weight."""

    def setUp(self):
        self.tuser = make_user(role=UserRole.TEACHER)
        self.teacher = Teacher.objects.create(user=self.tuser, experience_years=3)
        TeacherProfile.objects.create(teacher=self.teacher)
        self.admin = make_user(role=UserRole.ADMIN)

    def _verify(self, key):
        return self.client.post(
            f"/api/v1/admin/teacher-profiles/{self.teacher.id}/verification-items/{key}/",
            {"status": "verified"},
            format="json",
        )

    def test_video_interview_alone_earns_the_combined_weight(self):
        VerificationService.submit_reviewed_item(
            self.teacher, "video_interview", payload={}
        )
        login(self.client, self.admin)
        r = self._verify("video_interview")
        self.assertEqual(r.status_code, 200, r.content)
        self.tuser.trust_profile.refresh_from_db()
        self.assertEqual(self.tuser.trust_profile.verification_score, Decimal("0.150"))
        # selfie_liveness itself is untouched - still pending, not faked
        self.assertEqual(
            self.teacher.verification_items.get(key="selfie_liveness").status,
            "pending",
        )

    def test_selfie_alone_earns_the_combined_weight(self):
        VerificationService.submit_reviewed_item(
            self.teacher, "selfie_liveness", payload={"selfie_ref": "s"}
        )
        login(self.client, self.admin)
        r = self._verify("selfie_liveness")
        self.assertEqual(r.status_code, 200, r.content)
        self.tuser.trust_profile.refresh_from_db()
        self.assertEqual(self.tuser.trust_profile.verification_score, Decimal("0.150"))

    def test_both_verified_does_not_double_count(self):
        VerificationService.submit_reviewed_item(
            self.teacher, "selfie_liveness", payload={"selfie_ref": "s"}
        )
        VerificationService.submit_reviewed_item(
            self.teacher, "video_interview", payload={}
        )
        login(self.client, self.admin)
        self._verify("selfie_liveness")
        r = self._verify("video_interview")
        self.assertEqual(r.status_code, 200, r.content)
        self.tuser.trust_profile.refresh_from_db()
        self.assertEqual(self.tuser.trust_profile.verification_score, Decimal("0.150"))

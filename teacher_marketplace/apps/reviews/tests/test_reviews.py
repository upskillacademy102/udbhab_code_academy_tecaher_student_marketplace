"""
Phase 8c - reviews + integrity + rating recompute.

Run: python manage.py test apps.reviews --settings=config.settings.test
"""

from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.core.exceptions.custom_exceptions import (
    PermissionDeniedException,
    ValidationException,
)
from apps.lead_engine.models import Lead, LeadUnlockHistory
from apps.lead_engine.tests.test_lead_pipeline import PipelineFixtureMixin
from apps.reviews.models import Review, ReviewStatus
from apps.reviews.services import ReviewIntegrityService
from apps.teacher_profile.models import TeacherProfile

ON = override_settings(TRUST_ENABLE_REVIEW_SYSTEM=True)


class _Mixin(PipelineFixtureMixin):
    def _link(self, student, teacher_profile):
        """Record the LeadUnlockHistory that lets `student` review this teacher."""
        req = self.make_requirement(student=student)
        lead = Lead.objects.create(
            student_requirement=req, teacher_profile=teacher_profile
        )
        LeadUnlockHistory.objects.create(
            teacher=teacher_profile.teacher,
            lead=lead,
            is_free_unlock=True,
            tokens_deducted=0,
        )
        Lead.objects.filter(pk=lead.pk).update(contact_unlocked=True)
        return lead

    def _linked(self, *, teacher_name="Ana"):
        """A fresh student + teacher connected by an unlocked lead."""
        student = make_user(role=UserRole.STUDENT)
        profile = self.make_teacher(teacher_name, plan=self.free_plan)
        lead = self._link(student, profile)
        return student, profile.teacher, lead


class ReviewServiceTests(_Mixin, TestCase):
    def test_disabled_by_default(self):
        student, teacher, _ = self._linked()
        with self.assertRaises(PermissionDeniedException):
            ReviewIntegrityService.create_review(
                author=student, teacher=teacher, rating=5
            )

    @ON
    def test_review_requires_a_prior_lead(self):
        student = make_user(role=UserRole.STUDENT)
        teacher = self.make_teacher("NoLink", plan=self.free_plan).teacher
        with self.assertRaises(ValidationException):
            ReviewIntegrityService.create_review(
                author=student, teacher=teacher, rating=5
            )

    @ON
    def test_cannot_review_self(self):
        _s, teacher, _ = self._linked()
        with self.assertRaises(ValidationException):
            ReviewIntegrityService.create_review(
                author=teacher.user, teacher=teacher, rating=5
            )

    @ON
    def test_happy_path_and_rating_recompute(self):
        student, teacher, _lead = self._linked()
        r = ReviewIntegrityService.create_review(
            author=student, teacher=teacher, rating=4, text="Helpful and punctual."
        )
        self.assertEqual(r.status, ReviewStatus.PUBLISHED)
        prof = TeacherProfile.objects.get(teacher=teacher)
        self.assertEqual(prof.rating, Decimal("4.00"))

        # a second linked student reviews the SAME teacher
        s3 = make_user(role=UserRole.STUDENT)
        self._link(s3, teacher.marketplace_profile)
        ReviewIntegrityService.create_review(author=s3, teacher=teacher, rating=2)
        prof.refresh_from_db()
        self.assertEqual(prof.rating, Decimal("3.00"))  # (4 + 2) / 2

    @ON
    def test_one_review_per_lead(self):
        student, teacher, _lead = self._linked()
        ReviewIntegrityService.create_review(author=student, teacher=teacher, rating=5)
        with self.assertRaises(ValidationException):
            ReviewIntegrityService.create_review(
                author=student, teacher=teacher, rating=1
            )

    @ON
    @override_settings(TRUST_ENABLE_CONTACT_LEAKAGE_SCAN=True)
    def test_leaky_review_text_is_flagged_not_published(self):
        student, teacher, _lead = self._linked()
        r = ReviewIntegrityService.create_review(
            author=student,
            teacher=teacher,
            rating=5,
            text="great, contact me on 9876543210",
        )
        self.assertEqual(r.status, ReviewStatus.FLAGGED)
        prof = TeacherProfile.objects.get(teacher=teacher)
        self.assertEqual(prof.rating, Decimal("0.00"))  # flagged review not counted

    @ON
    def test_rating_ring_by_fingerprint_flags(self):
        profile = self.make_teacher("Ring", plan=self.free_plan)
        teacher = profile.teacher
        for _ in range(3):
            s = make_user(role=UserRole.STUDENT)
            self._link(s, profile)
            r = ReviewIntegrityService.create_review(
                author=s, teacher=teacher, rating=5, fingerprint="same-device-hash"
            )
        # the 3rd from the same fingerprint trips the ring detector
        self.assertEqual(r.status, ReviewStatus.FLAGGED)


class ReviewApiTests(_Mixin, APITestCase):
    def test_endpoints_404_when_disabled(self):
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        self.assertEqual(self.client.get("/api/v1/reviews/").status_code, 404)

    @ON
    def test_student_creates_review_via_api(self):
        student, teacher, _lead = self._linked()
        login(self.client, student)
        r = self.client.post(
            "/api/v1/reviews/",
            {"teacher_id": str(teacher.id), "rating": 5, "text": "Excellent."},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(Review.objects.filter(author=student, teacher=teacher).exists())

    @ON
    def test_teacher_cannot_post_review(self):
        _s, teacher, _ = self._linked()
        login(self.client, teacher.user)
        r = self.client.post(
            "/api/v1/reviews/",
            {"teacher_id": str(teacher.id), "rating": 5},
            format="json",
        )
        self.assertEqual(r.status_code, 403)

    @ON
    def test_public_teacher_reviews_list(self):
        student, teacher, _lead = self._linked()
        ReviewIntegrityService.create_review(author=student, teacher=teacher, rating=4)
        login(self.client, make_user(role=UserRole.STUDENT))
        r = self.client.get(f"/api/v1/teachers/{teacher.id}/reviews/")
        self.assertEqual(r.status_code, 200)
        body = r.json()["data"]
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["average_rating"], "4.00")

    @ON
    def test_author_withdraws_review(self):
        student, teacher, _lead = self._linked()
        rv = ReviewIntegrityService.create_review(
            author=student, teacher=teacher, rating=5
        )
        login(self.client, student)
        r = self.client.delete(f"/api/v1/reviews/{rv.id}/")
        self.assertIn(r.status_code, (200, 204))
        self.assertFalse(Review.objects.filter(id=rv.id).exists())
        TeacherProfile.objects.get(teacher=teacher).refresh_from_db()

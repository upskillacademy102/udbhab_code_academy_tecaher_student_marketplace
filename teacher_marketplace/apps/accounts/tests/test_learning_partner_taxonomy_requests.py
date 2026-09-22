"""
Phase LP-3: Super Admin review of Learning Partner taxonomy requests.

  GET  /api/v1/auth/staff/taxonomy-requests/               (super admin)
  POST /api/v1/auth/staff/taxonomy-requests/{id}/approve/   (super admin)
  POST /api/v1/auth/staff/taxonomy-requests/{id}/deny/      (super admin)

Submission itself (POST /api/v1/lp/taxonomy-requests/) is a Learning
Partner's own endpoint - covered in apps.learning_partner.tests.test_views.

Run: python manage.py test apps.accounts.tests.test_learning_partner_taxonomy_requests \
     --settings=config.settings.test
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_learning_partner_admin, make_user
from apps.languages.models import Language
from apps.subjects.models import Subject
from apps.trust.models import LearningPartnerTaxonomyRequest, TaxonomyRequestStatus

LIST_URL = "/api/v1/auth/staff/taxonomy-requests/"


def _approve_url(req_id):
    return f"{LIST_URL}{req_id}/approve/"


def _deny_url(req_id):
    return f"{LIST_URL}{req_id}/deny/"


class TaxonomyRequestReviewTests(APITestCase):
    def setUp(self):
        self.superadmin = make_user(role=UserRole.SUPERADMIN, email="root-tax@example.com")
        self.lp = make_learning_partner_admin("TaxPartner")
        login(self.client, self.superadmin)

    def test_list_shows_pending_requests(self):
        req = LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp, kind="subject", name="Robotics"
        )
        r = self.client.get(LIST_URL, {"status": "pending"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in r.data["data"]}
        self.assertIn(str(req.id), ids)

    def test_approve_subject_creates_scoped_subject(self):
        req = LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp, kind="subject", name="Robotics"
        )
        r = self.client.post(_approve_url(req.id), {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        req.refresh_from_db()
        self.assertEqual(req.status, TaxonomyRequestStatus.APPROVED)
        self.assertIsNotNone(req.created_subject)
        self.assertEqual(req.created_subject.name, "Robotics")
        self.assertEqual(req.created_subject.learning_partner_id, self.lp.id)

    def test_approve_language_creates_scoped_language_with_derived_code(self):
        req = LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp, kind="language", name="Konkani"
        )
        r = self.client.post(_approve_url(req.id), {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        req.refresh_from_db()
        self.assertIsNotNone(req.created_language)
        self.assertEqual(req.created_language.name, "Konkani")
        self.assertEqual(req.created_language.learning_partner_id, self.lp.id)
        self.assertTrue(req.created_language.code)

    def test_approve_reuses_existing_matching_row_instead_of_erroring(self):
        # Simulates two overlapping requests for the same name both ending
        # up pending, then both approved - the second must not IntegrityError.
        existing = Subject.objects.create(name="Chess Strategy", learning_partner=self.lp)
        req = LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp, kind="subject", name="Chess Strategy"
        )
        r = self.client.post(_approve_url(req.id), {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        req.refresh_from_db()
        self.assertEqual(req.created_subject_id, existing.id)
        self.assertEqual(Subject.objects.filter(name="Chess Strategy").count(), 1)

    def test_approved_subject_is_scoped_not_platform_wide(self):
        req = LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp, kind="subject", name="Advanced Origami"
        )
        self.client.post(_approve_url(req.id), {}, format="json")
        self.assertIsNone(
            Subject.objects.filter(name="Advanced Origami", learning_partner__isnull=True).first()
        )

    def test_deny_sets_status_and_reason(self):
        req = LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp, kind="subject", name="Bad Idea Subject"
        )
        r = self.client.post(_deny_url(req.id), {"reason": "Too niche."}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        req.refresh_from_db()
        self.assertEqual(req.status, TaxonomyRequestStatus.DENIED)
        self.assertEqual(req.deny_reason, "Too niche.")
        self.assertIsNone(req.created_subject)

    def test_cannot_decide_an_already_decided_request(self):
        req = LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp,
            kind="subject",
            name="Already Done",
            status=TaxonomyRequestStatus.APPROVED,
        )
        r = self.client.post(_approve_url(req.id), {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_request_404s(self):
        r = self.client.post(
            _approve_url("00000000-0000-0000-0000-000000000000"), {}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class TaxonomyRequestReviewPermissionTests(APITestCase):
    def setUp(self):
        self.lp = make_learning_partner_admin("TaxPermPartner")
        self.req = LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp, kind="subject", name="Permission Test Subject"
        )

    def test_plain_admin_forbidden(self):
        login(self.client, make_user(role=UserRole.ADMIN))
        self.assertEqual(self.client.get(LIST_URL).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(_approve_url(self.req.id), {}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_student_forbidden(self):
        login(self.client, make_user(role=UserRole.STUDENT))
        self.assertEqual(self.client.get(LIST_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_rejected(self):
        self.assertEqual(self.client.get(LIST_URL).status_code, status.HTTP_401_UNAUTHORIZED)

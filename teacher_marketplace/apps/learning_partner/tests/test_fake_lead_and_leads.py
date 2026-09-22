"""
Phase LP-4: a Learning Partner's fake-lead reports/endorsement, leads
browser, and audit log - all scoped to their own referred students/
teachers only.

  GET  /api/v1/lp/fake-lead-reports/
  POST /api/v1/lp/fake-lead-reports/{student_id}/endorse/
  GET  /api/v1/lp/students-lead-quality/
  GET  /api/v1/lp/teacher-lead-reviews/
  GET  /api/v1/lp/audit/

The service-layer arithmetic for endorsement weighting is covered in
apps.trust.tests.test_learning_partner_endorsement; this file is about the
API-level business rules (ownership, "must already have an open report",
one endorsement each) and the isolation guarantee.

Run: python manage.py test apps.learning_partner.tests.test_fake_lead_and_leads \
     --settings=config.settings.test
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, login_lp, make_learning_partner_admin, make_user
from apps.lead_engine.models import Lead
from apps.lead_engine.tests.test_lead_pipeline import PipelineFixtureMixin
from apps.lead_engine.unlock_service import unlock_lead_contact
from apps.ops.models import AuditCategory
from apps.ops.services import AuditService
from apps.trust.models import FakeLeadEndorsement
from apps.trust.services.lead_quality_service import LeadQualityService

FAKE_LEAD_REPORTS_URL = "/api/v1/lp/fake-lead-reports/"
STUDENTS_LEAD_QUALITY_URL = "/api/v1/lp/students-lead-quality/"
TEACHER_LEAD_REVIEWS_URL = "/api/v1/lp/teacher-lead-reviews/"
AUDIT_URL = "/api/v1/lp/audit/"


def _endorse_url(student_id):
    return f"{FAKE_LEAD_REPORTS_URL}{student_id}/endorse/"


class _Mixin(PipelineFixtureMixin):
    def _report_fake(self, student, teacher_name, *, note=""):
        req = self.make_requirement(student=student)
        profile = self.make_teacher(teacher_name, plan=self.free_plan)
        lead = Lead.objects.create(student_requirement=req, teacher_profile=profile)
        unlock_lead_contact(profile.teacher, lead)
        return LeadQualityService.rate(
            teacher=profile.teacher, lead=lead, verdict="fake", note=note
        )


class LPFakeLeadReportsTests(_Mixin, APITestCase):
    def setUp(self):
        self.lp_a = make_learning_partner_admin("FLRPartnerA")
        self.lp_b = make_learning_partner_admin("FLRPartnerB")
        self.student_a = make_user(role=UserRole.STUDENT, learning_partner=self.lp_a)
        self.student_b = make_user(role=UserRole.STUDENT, learning_partner=self.lp_b)
        self.student_none = make_user(role=UserRole.STUDENT)

    def test_scoped_to_own_students_only(self):
        self._report_fake(self.student_a, "T1")
        self._report_fake(self.student_b, "T2")
        self._report_fake(self.student_none, "T3")

        login_lp(self.client, self.lp_a)
        r = self.client.get(FAKE_LEAD_REPORTS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = {row["student_id"] for row in r.data["data"]["results"]}
        self.assertEqual(ids, {str(self.student_a.id)})

    def test_already_endorsed_flag(self):
        self._report_fake(self.student_a, "T1")
        login_lp(self.client, self.lp_a)

        r = self.client.get(FAKE_LEAD_REPORTS_URL)
        self.assertFalse(r.data["data"]["results"][0]["already_endorsed"])

        self.client.post(_endorse_url(self.student_a.id), {}, format="json")
        r = self.client.get(FAKE_LEAD_REPORTS_URL)
        self.assertTrue(r.data["data"]["results"][0]["already_endorsed"])


class LPEndorseFakeReportTests(_Mixin, APITestCase):
    def setUp(self):
        self.lp_a = make_learning_partner_admin("EndorseApiPartnerA")
        self.lp_b = make_learning_partner_admin("EndorseApiPartnerB")
        self.student_a = make_user(role=UserRole.STUDENT, learning_partner=self.lp_a)
        self.student_none = make_user(role=UserRole.STUDENT)

    def test_endorse_success(self):
        self._report_fake(self.student_a, "T1")
        login_lp(self.client, self.lp_a)
        r = self.client.post(_endorse_url(self.student_a.id), {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        self.assertTrue(
            FakeLeadEndorsement.objects.filter(
                student=self.student_a, learning_partner=self.lp_a
            ).exists()
        )

    def test_cannot_endorse_without_an_open_report(self):
        login_lp(self.client, self.lp_a)
        r = self.client.post(_endorse_url(self.student_a.id), {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_endorse_twice(self):
        self._report_fake(self.student_a, "T1")
        login_lp(self.client, self.lp_a)
        self.client.post(_endorse_url(self.student_a.id), {}, format="json")
        r = self.client.post(_endorse_url(self.student_a.id), {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            FakeLeadEndorsement.objects.filter(student=self.student_a).count(), 1
        )

    def test_cannot_endorse_another_partners_student(self):
        self._report_fake(self.student_a, "T1")
        login_lp(self.client, self.lp_b)
        r = self.client.post(_endorse_url(self.student_a.id), {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_endorse_a_partnerless_student(self):
        self._report_fake(self.student_none, "T1")
        login_lp(self.client, self.lp_a)
        r = self.client.post(_endorse_url(self.student_none.id), {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_endorsement_actually_raises_the_weighted_count(self):
        self._report_fake(self.student_a, "T1")
        login_lp(self.client, self.lp_a)
        self.client.post(_endorse_url(self.student_a.id), {}, format="json")
        stats = LeadQualityService.fake_report_stats(self.student_a)
        self.assertEqual(stats["distinct_teachers_all"], 1 + 5)


class LPStudentLeadQualityAndTeacherReviewsTests(_Mixin, APITestCase):
    def setUp(self):
        self.lp_a = make_learning_partner_admin("LeadsPartnerA")
        self.lp_b = make_learning_partner_admin("LeadsPartnerB")
        self.student_a = make_user(role=UserRole.STUDENT, learning_partner=self.lp_a)
        self.student_b = make_user(role=UserRole.STUDENT, learning_partner=self.lp_b)

    def test_student_aggregate_scoped_to_own_students(self):
        self._report_fake(self.student_a, "T1")
        self._report_fake(self.student_b, "T2")

        login_lp(self.client, self.lp_a)
        r = self.client.get(STUDENTS_LEAD_QUALITY_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = {row["student_id"] for row in r.data["data"]["results"]}
        self.assertEqual(ids, {str(self.student_a.id)})

    def test_student_id_detail_for_own_student_works(self):
        self._report_fake(self.student_a, "T1", note="own student")
        login_lp(self.client, self.lp_a)
        r = self.client.get(STUDENTS_LEAD_QUALITY_URL, {"student_id": str(self.student_a.id)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["count"], 1)

    def test_student_id_detail_for_another_partners_student_404s(self):
        self._report_fake(self.student_b, "T1")
        login_lp(self.client, self.lp_a)
        r = self.client.get(STUDENTS_LEAD_QUALITY_URL, {"student_id": str(self.student_b.id)})
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_teacher_reviews_scoped_by_student_not_by_teacher(self):
        # Same (unrelated-to-either-partner) teacher rates both students -
        # scoping must follow the STUDENT's partner link, not the teacher's.
        req_a = self.make_requirement(student=self.student_a)
        req_b = self.make_requirement(student=self.student_b)
        profile = self.make_teacher("SharedTeacher", plan=self.free_plan)
        lead_a = Lead.objects.create(student_requirement=req_a, teacher_profile=profile)
        lead_b = Lead.objects.create(student_requirement=req_b, teacher_profile=profile)
        unlock_lead_contact(profile.teacher, lead_a)
        unlock_lead_contact(profile.teacher, lead_b)
        LeadQualityService.rate(teacher=profile.teacher, lead=lead_a, verdict="genuine")
        LeadQualityService.rate(teacher=profile.teacher, lead=lead_b, verdict="genuine")

        login_lp(self.client, self.lp_a)
        r = self.client.get(TEACHER_LEAD_REVIEWS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        student_ids = {row["student_id"] for row in r.data["data"]["results"]}
        self.assertEqual(student_ids, {str(self.student_a.id)})


class LPAuditViewTests(APITestCase):
    def setUp(self):
        self.lp = make_learning_partner_admin("AuditPartner")
        self.own_student = make_user(role=UserRole.STUDENT, learning_partner=self.lp)
        self.unrelated_student = make_user(role=UserRole.STUDENT)

    def test_scoped_to_rows_targeting_own_referred_users(self):
        AuditService.record(
            category=AuditCategory.USER,
            action="test.own_student_action",
            target=self.own_student,
            message="targets own student",
        )
        AuditService.record(
            category=AuditCategory.USER,
            action="test.unrelated_student_action",
            target=self.unrelated_student,
            message="targets unrelated student",
        )

        login_lp(self.client, self.lp)
        r = self.client.get(AUDIT_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        actions = {row["action"] for row in r.data["data"]}
        self.assertIn("test.own_student_action", actions)
        self.assertNotIn("test.unrelated_student_action", actions)


class LPFakeLeadPermissionTests(_Mixin, APITestCase):
    def setUp(self):
        self.lp = make_learning_partner_admin("PermFLRPartner")
        self.student = make_user(role=UserRole.STUDENT, learning_partner=self.lp)

    def test_plain_admin_forbidden(self):
        login(self.client, make_user(role=UserRole.ADMIN, email="plain-flr@example.com"))
        for url in (FAKE_LEAD_REPORTS_URL, STUDENTS_LEAD_QUALITY_URL, TEACHER_LEAD_REVIEWS_URL, AUDIT_URL):
            self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN, url)

    def test_student_forbidden(self):
        login(self.client, make_user(role=UserRole.STUDENT, email="reg-flr@example.com"))
        self.assertEqual(
            self.client.get(FAKE_LEAD_REPORTS_URL).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_superadmin_forbidden_too(self):
        login(self.client, make_user(role=UserRole.SUPERADMIN, email="sa-flr@example.com"))
        self.assertEqual(
            self.client.get(FAKE_LEAD_REPORTS_URL).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_unauthenticated_rejected(self):
        for url in (FAKE_LEAD_REPORTS_URL, STUDENTS_LEAD_QUALITY_URL, TEACHER_LEAD_REVIEWS_URL, AUDIT_URL):
            self.assertEqual(self.client.get(url).status_code, status.HTTP_401_UNAUTHORIZED, url)

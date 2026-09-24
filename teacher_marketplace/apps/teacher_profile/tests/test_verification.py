"""
Admin/Super-Admin teacher verification, and its effect on student search.

Run:  python manage.py test apps.teacher_profile --settings=config.settings.test
"""

from decimal import Decimal

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_named_admin, make_user
from apps.subjects.models import Subject
from apps.teacher_profile.models import TeacherProfile, TeachingMode, VerificationStatus
from apps.teachers.models import Teacher


class TeacherVerificationTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.karate = Subject.objects.create(name="Karate")

    def _make_teacher_profile(self, email, *, verified=False):
        user = make_user(role=UserRole.TEACHER, email=email, first_name="Kata")
        teacher = Teacher.objects.create(user=user, experience_years=5)
        profile = TeacherProfile.objects.create(
            teacher=teacher,
            teaching_mode=TeachingMode.BOTH,
            rating=Decimal("4.00"),
            verification_status=(
                VerificationStatus.VERIFIED if verified else VerificationStatus.PENDING
            ),
        )
        profile.subjects.set([self.karate])
        return profile

    def _search_karate(self, student):
        c = self.client_class()
        login(c, student)
        return c.get("/api/v1/search/teachers/", {"subject": "Karate"})

    def test_pending_teacher_is_hidden_from_student_search(self):
        self._make_teacher_profile("pending@k.test")
        student = make_user(role=UserRole.STUDENT)
        resp = self._search_karate(student)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], [])

    def test_admin_verify_makes_teacher_appear_in_search(self):
        profile = self._make_teacher_profile("tv@k.test")
        student = make_user(role=UserRole.STUDENT)
        # POST .../verification/ is Verification-department only (apps.
        # accounts.api_permissions.DEPARTMENT_ROUTE_SCOPE).
        admin = make_named_admin(department="Verification", email="adm@k.test")

        c = self.client_class()
        self.assertEqual(login(c, admin).status_code, 200)
        r = c.post(
            f"/api/v1/admin/teacher-profiles/{profile.teacher_id}/verification/",
            {"status": "verified"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        profile.refresh_from_db()
        self.assertEqual(profile.verification_status, VerificationStatus.VERIFIED)

        resp = self._search_karate(student)
        self.assertEqual(len(resp.json()["data"]), 1)

    def test_reject_removes_teacher_from_search(self):
        profile = self._make_teacher_profile("rej@k.test", verified=True)
        admin = make_named_admin(department="Verification", email="adm2@k.test")
        student = make_user(role=UserRole.STUDENT)

        c = self.client_class()
        login(c, admin)
        c.post(
            f"/api/v1/admin/teacher-profiles/{profile.teacher_id}/verification/",
            {"status": "rejected"},
            format="json",
        )
        self.assertEqual(self._search_karate(student).json()["data"], [])

    def test_student_cannot_verify_a_teacher(self):
        profile = self._make_teacher_profile("s@k.test")
        student = make_user(role=UserRole.STUDENT)
        c = self.client_class()
        login(c, student)
        r = c.post(
            f"/api/v1/admin/teacher-profiles/{profile.teacher_id}/verification/",
            {"status": "verified"},
            format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_teacher_cannot_verify_themselves(self):
        profile = self._make_teacher_profile("self@k.test")
        c = self.client_class()
        login(c, profile.teacher.user)
        r = c.post(
            f"/api/v1/admin/teacher-profiles/{profile.teacher_id}/verification/",
            {"status": "verified"},
            format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_invalid_status_is_rejected(self):
        profile = self._make_teacher_profile("bad@k.test")
        admin = make_named_admin(department="Verification", email="adm3@k.test")
        c = self.client_class()
        login(c, admin)
        r = c.post(
            f"/api/v1/admin/teacher-profiles/{profile.teacher_id}/verification/",
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_admin_list_filters_by_status(self):
        self._make_teacher_profile("p1@k.test")
        self._make_teacher_profile("v1@k.test", verified=True)
        admin = make_user(role=UserRole.ADMIN, email="adm4@k.test")
        c = self.client_class()
        login(c, admin)

        pending = c.get(
            "/api/v1/admin/teacher-profiles/", {"verification_status": "pending"}
        )
        self.assertEqual(pending.status_code, 200)
        self.assertTrue(
            all(x["verification_status"] == "pending" for x in pending.json()["data"])
        )
        self.assertGreaterEqual(len(pending.json()["data"]), 1)

    def test_admin_detail_includes_verification_checklist(self):
        profile = self._make_teacher_profile("checklist@k.test")
        admin = make_user(role=UserRole.ADMIN, email="adm6@k.test")
        c = self.client_class()
        login(c, admin)
        r = c.get(f"/api/v1/admin/teacher-profiles/{profile.teacher_id}/")
        self.assertEqual(r.status_code, 200, r.content)
        items = r.json()["data"]["verification_items"]
        self.assertEqual(len(items), 10)
        gov_id = next(i for i in items if i["key"] == "gov_id")
        self.assertIn("evidence", gov_id)
        self.assertEqual(gov_id["evidence"], [])

    def test_verification_for_teacher_without_profile_404s(self):
        user = make_user(role=UserRole.TEACHER, email="np@k.test")
        teacher = Teacher.objects.create(user=user)
        admin = make_named_admin(department="Verification", email="adm5@k.test")
        c = self.client_class()
        login(c, admin)
        r = c.post(
            f"/api/v1/admin/teacher-profiles/{teacher.id}/verification/",
            {"status": "verified"},
            format="json",
        )
        self.assertEqual(r.status_code, 404)

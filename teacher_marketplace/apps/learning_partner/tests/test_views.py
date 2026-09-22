"""
Phase LP-2: the Learning Partner dashboard API.

  GET /api/v1/lp/dashboard/
  GET /api/v1/lp/students/, /students/{id}/
  GET /api/v1/lp/teachers/, /teachers/{id}/

The one property every test here ultimately protects: a Learning Partner
can see their OWN referred students/teachers and nothing else - not
another partner's, not a platform user with no partner at all, and no
plain admin (or superadmin) can reach this data via these endpoints either.

Phase LP-3 additionally covers:
  GET/POST /api/v1/lp/taxonomy-requests/

Run: python manage.py test apps.learning_partner.tests.test_views \
     --settings=config.settings.test
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import AdminDepartment, User, UserRole
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_user
from apps.trust.models import LearningPartnerTaxonomyRequest, TaxonomyRequestStatus

DASHBOARD_URL = "/api/v1/lp/dashboard/"
STUDENTS_URL = "/api/v1/lp/students/"
TEACHERS_URL = "/api/v1/lp/teachers/"
TAXONOMY_REQUESTS_URL = "/api/v1/lp/taxonomy-requests/"


def _login_lp(client, lp_admin):
    """
    A Learning Partner is a new-flow admin (admin_account_name set) - it
    signs in via /staff/login-admin/ (account name + password), not the
    shared login() helper, which routes role=admin through the OLD
    /auth/admin/login/ approval flow that explicitly rejects any account
    with admin_account_name set (see AdminLoginView.post). Same pattern
    apps.accounts.tests.test_staff_dashboards/test_staff_login already use.
    """
    r = client.post(
        "/api/v1/auth/staff/login-admin/",
        {"account_name": lp_admin.admin_account_name, "password": TEST_PASSWORD},
        format="json",
    )
    assert r.status_code == 200, r.content
    return r


def _lp_admin(name, mobile):
    dept, _ = AdminDepartment.objects.get_or_create(
        name="Learning Partner", defaults={"is_learning_partner": True}
    )
    if not dept.is_learning_partner:
        dept.is_learning_partner = True
        dept.save(update_fields=["is_learning_partner"])
    return User.objects.create_user(
        password=TEST_PASSWORD,
        email=f"{name.lower()}@example.com",
        mobile=mobile,
        first_name=name,
        last_name="",
        role=UserRole.ADMIN,
        admin_department=dept,
        admin_account_name=f"{name}@LearningPartner",
    )


class LearningPartnerIsolationTests(APITestCase):
    """The core isolation guarantee, checked from every angle."""

    def setUp(self):
        self.lp_a = _lp_admin("LearnAcademy", "919300000001")
        self.lp_b = _lp_admin("BrightMinds", "919300000002")

        self.student_a = make_user(
            role=UserRole.STUDENT, email="student-a@example.com", learning_partner=self.lp_a
        )
        self.teacher_a = make_user(
            role=UserRole.TEACHER, email="teacher-a@example.com", learning_partner=self.lp_a
        )
        self.student_b = make_user(
            role=UserRole.STUDENT, email="student-b@example.com", learning_partner=self.lp_b
        )
        self.student_none = make_user(role=UserRole.STUDENT, email="student-none@example.com")

    def test_dashboard_counts_are_scoped_to_the_caller(self):
        _login_lp(self.client, self.lp_a)
        r = self.client.get(DASHBOARD_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["organization_name"], "LearnAcademy")
        self.assertEqual(r.data["data"]["students_count"], 1)
        self.assertEqual(r.data["data"]["teachers_count"], 1)

        self.client.logout()
        _login_lp(self.client, self.lp_b)
        r = self.client.get(DASHBOARD_URL)
        self.assertEqual(r.data["data"]["students_count"], 1)
        self.assertEqual(r.data["data"]["teachers_count"], 0)

    def test_student_list_only_shows_own_referred_students(self):
        _login_lp(self.client, self.lp_a)
        r = self.client.get(STUDENTS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in r.data["data"]}
        self.assertEqual(emails, {"student-a@example.com"})

    def test_teacher_list_only_shows_own_referred_teachers(self):
        _login_lp(self.client, self.lp_a)
        r = self.client.get(TEACHERS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in r.data["data"]}
        self.assertEqual(emails, {"teacher-a@example.com"})

    def test_cannot_view_another_partners_student_by_id(self):
        _login_lp(self.client, self.lp_a)
        r = self.client.get(f"{STUDENTS_URL}{self.student_b.id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_view_a_partnerless_students_detail(self):
        _login_lp(self.client, self.lp_a)
        r = self.client.get(f"{STUDENTS_URL}{self.student_none.id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_view_a_teacher_via_the_student_endpoint(self):
        # student_a's own teacher, but through the wrong (students) endpoint.
        _login_lp(self.client, self.lp_a)
        r = self.client.get(f"{STUDENTS_URL}{self.teacher_a.id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_can_view_own_students_detail(self):
        _login_lp(self.client, self.lp_a)
        r = self.client.get(f"{STUDENTS_URL}{self.student_a.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["email"], "student-a@example.com")


class LearningPartnerPermissionTests(APITestCase):
    def setUp(self):
        self.lp = _lp_admin("LearnAcademy2", "919300000010")

    def test_unauthenticated_rejected(self):
        for url in (DASHBOARD_URL, STUDENTS_URL, TEACHERS_URL):
            r = self.client.get(url)
            self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED, url)

    def test_plain_admin_forbidden(self):
        plain_admin = make_user(role=UserRole.ADMIN, email="plain@example.com")
        login(self.client, plain_admin)
        for url in (DASHBOARD_URL, STUDENTS_URL, TEACHERS_URL):
            r = self.client.get(url)
            self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, url)

    def test_student_forbidden(self):
        student = make_user(role=UserRole.STUDENT, email="reg-student@example.com")
        login(self.client, student)
        r = self.client.get(DASHBOARD_URL)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_teacher_forbidden(self):
        teacher = make_user(role=UserRole.TEACHER, email="reg-teacher@example.com")
        login(self.client, teacher)
        r = self.client.get(DASHBOARD_URL)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_superadmin_forbidden_too(self):
        # Deliberate: these endpoints require literally
        # is_learning_partner_admin, which a superadmin never is - the
        # object-level check runs even though the central role gate
        # bypasses everything for superadmin.
        superadmin = make_user(role=UserRole.SUPERADMIN, email="sa-lp@example.com")
        login(self.client, superadmin)
        r = self.client.get(DASHBOARD_URL)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_learning_partner_itself_is_allowed(self):
        _login_lp(self.client, self.lp)
        r = self.client.get(DASHBOARD_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class LearningPartnerTaxonomyRequestTests(APITestCase):
    """
    A Learning Partner's own subject/language requests - submission and
    listing. Approval/denial is the Super Admin's side, covered in
    apps.accounts.tests.test_learning_partner_taxonomy_requests.
    """

    def setUp(self):
        self.lp_a = _lp_admin("TaxReqPartnerA", "919300000020")
        self.lp_b = _lp_admin("TaxReqPartnerB", "919300000021")

    def test_submit_creates_pending_request(self):
        _login_lp(self.client, self.lp_a)
        r = self.client.post(
            TAXONOMY_REQUESTS_URL,
            {"kind": "subject", "name": "Robotics", "note": "Popular ask from parents."},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        req = LearningPartnerTaxonomyRequest.objects.get(id=r.data["data"]["id"])
        self.assertEqual(req.learning_partner_id, self.lp_a.id)
        self.assertEqual(req.status, TaxonomyRequestStatus.PENDING)
        self.assertEqual(req.name, "Robotics")

    def test_list_shows_only_this_partners_own_requests(self):
        LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp_a, kind="subject", name="A's Subject"
        )
        LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp_b, kind="subject", name="B's Subject"
        )
        _login_lp(self.client, self.lp_a)
        r = self.client.get(TAXONOMY_REQUESTS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        names = {row["name"] for row in r.data["data"]}
        self.assertEqual(names, {"A's Subject"})

    def test_kind_filter(self):
        LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp_a, kind="subject", name="Filter Subject"
        )
        LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=self.lp_a, kind="language", name="Filter Language"
        )
        _login_lp(self.client, self.lp_a)
        r = self.client.get(TAXONOMY_REQUESTS_URL, {"kind": "language"})
        names = {row["name"] for row in r.data["data"]}
        self.assertEqual(names, {"Filter Language"})

    def test_duplicate_pending_request_rejected(self):
        _login_lp(self.client, self.lp_a)
        self.client.post(
            TAXONOMY_REQUESTS_URL, {"kind": "subject", "name": "Robotics"}, format="json"
        )
        r = self.client.post(
            TAXONOMY_REQUESTS_URL, {"kind": "subject", "name": "robotics"}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            LearningPartnerTaxonomyRequest.objects.filter(
                learning_partner=self.lp_a, name__iexact="robotics"
            ).count(),
            1,
        )

    def test_another_partner_can_request_the_same_name(self):
        _login_lp(self.client, self.lp_a)
        self.client.post(
            TAXONOMY_REQUESTS_URL, {"kind": "subject", "name": "Robotics"}, format="json"
        )
        self.client.logout()
        _login_lp(self.client, self.lp_b)
        r = self.client.post(
            TAXONOMY_REQUESTS_URL, {"kind": "subject", "name": "Robotics"}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)

    def test_invalid_name_rejected(self):
        _login_lp(self.client, self.lp_a)
        r = self.client.post(
            TAXONOMY_REQUESTS_URL, {"kind": "subject", "name": "!!!"}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_plain_admin_forbidden(self):
        plain_admin = make_user(role=UserRole.ADMIN, email="plain-tax@example.com")
        login(self.client, plain_admin)
        r = self.client.get(TAXONOMY_REQUESTS_URL)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_rejected(self):
        r = self.client.get(TAXONOMY_REQUESTS_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

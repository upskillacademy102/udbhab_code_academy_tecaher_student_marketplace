"""
Phase LP-1: Learning Partner data model + signup flow.

  POST /api/v1/auth/become-learning-partner/     (public)
  GET  /api/v1/auth/learning-partners/           (public)
  POST /api/v1/auth/register/                    learning_partner_id (optional)

Learning Partner is its own role (UserRole.LEARNING_PARTNER), not a
department - approving a request reuses the existing admin-account
request/approval/naming pipeline (apps.accounts.services.admin_account_naming),
which for a Learning Partner request creates the user with no department at
all (see AdminAccountRequestDecisionView - there is nothing to pick).

Run: python manage.py test apps.accounts.tests.test_learning_partner \
     --settings=config.settings.test
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import (
    AdminAccountRequest,
    AdminAccountRequestStatus,
    AdminDepartment,
    User,
    UserRole,
)
from apps.accounts.services.admin_account_naming import build_admin_account_name
from apps.accounts.tests.helpers import (
    TEST_PASSWORD,
    login,
    make_learning_partner_admin,
    make_user,
)

BECOME_LP_URL = "/api/v1/auth/become-learning-partner/"
LP_LIST_URL = "/api/v1/auth/learning-partners/"
DECISION_LIST_URL = "/api/v1/auth/staff/admin-account-requests/"
REGISTER_URL = "/api/v1/auth/register/"


def _lp_payload(**over):
    defaults = dict(
        organization_name="Learn Academy",
        email="learnacademy@example.com",
        mobile="919200000001",
        password=TEST_PASSWORD,
        password_confirm=TEST_PASSWORD,
    )
    defaults.update(over)
    return defaults


class BuildAdminAccountNameOrganizationTests(APITestCase):
    def test_organization_name_used_verbatim_as_one_token_stream(self):
        self.assertEqual(
            build_admin_account_name(
                "", "", None, organization_name="Learn Academy"
            ),
            "LearnAcademy@LearningPartner",
        )

    def test_single_word_organization_name(self):
        self.assertEqual(
            build_admin_account_name("", "", None, organization_name="Byjus"),
            "Byjus@LearningPartner",
        )

    def test_organization_name_takes_priority_over_first_last(self):
        # Should never happen in practice (a request has either
        # organization_name OR first/last, never both) - confirms the
        # branch really is organization_name-first, not silently ignored.
        self.assertEqual(
            build_admin_account_name(
                "Should", "Ignore", None, organization_name="Learn Academy"
            ),
            "LearnAcademy@LearningPartner",
        )


class BecomeLearningPartnerSubmitTests(APITestCase):
    def test_submit_creates_pending_request_with_organization_name(self):
        r = self.client.post(BECOME_LP_URL, _lp_payload(), format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        req = AdminAccountRequest.objects.get(email="learnacademy@example.com")
        self.assertEqual(req.status, AdminAccountRequestStatus.PENDING)
        self.assertEqual(req.organization_name, "Learn Academy")
        self.assertEqual(req.first_name, "")
        self.assertEqual(req.last_name, "")
        self.assertFalse(
            User.all_objects.filter(email__iexact="learnacademy@example.com").exists()
        )

    def test_password_mismatch_rejected(self):
        r = self.client.post(
            BECOME_LP_URL,
            _lp_payload(password_confirm="Different1!"),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_organization_name_rejected(self):
        r = self.client.post(
            BECOME_LP_URL, _lp_payload(organization_name="!!!"), format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_email_against_existing_user_rejected(self):
        existing = make_user(email="taken-lp@example.com")
        r = self.client.post(
            BECOME_LP_URL, _lp_payload(email=existing.email, mobile="919200000002"), format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_mobile_against_pending_request_rejected(self):
        self.client.post(
            BECOME_LP_URL,
            _lp_payload(email="lp-a@example.com", mobile="919200000003"),
            format="json",
        )
        r = self.client.post(
            BECOME_LP_URL,
            _lp_payload(email="lp-b@example.com", mobile="919200000003"),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class LearningPartnerApprovalTests(APITestCase):
    """
    Replaces the old ApprovalDepartmentTypeEnforcementTests (which asserted
    a "Learning Partner request into the wrong department" 400 - that
    scenario is now structurally impossible: a Learning Partner request has
    no department dimension at all, so there's nothing to mismatch).
    """

    def setUp(self):
        self.superadmin = make_user(role=UserRole.SUPERADMIN, email="root-lp@example.com")
        login(self.client, self.superadmin)
        self.finance = AdminDepartment.objects.get_or_create(name="Finance")[0]

    def _submit_lp(self, **over):
        self.client.logout()
        r = self.client.post(BECOME_LP_URL, _lp_payload(**over), format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        login(self.client, self.superadmin)
        return AdminAccountRequest.objects.get(id=r.data["data"]["id"])

    def _submit_normal(self, **over):
        from apps.accounts.tests.test_admin_account_requests import CREATE_URL, _payload

        self.client.logout()
        r = self.client.post(CREATE_URL, _payload(**over), format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        login(self.client, self.superadmin)
        return AdminAccountRequest.objects.get(id=r.data["data"]["id"])

    def test_lp_request_approved_with_no_department_id_succeeds(self):
        req = self._submit_lp(email="ok-lp@example.com", mobile="919200000010")
        r = self.client.post(f"{DECISION_LIST_URL}{req.id}/approve/", {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        req.refresh_from_db()
        self.assertEqual(req.created_user.role, UserRole.LEARNING_PARTNER)
        self.assertEqual(req.created_user.admin_account_name, "LearnAcademy@LearningPartner")
        self.assertIsNone(req.created_user.admin_department)
        self.assertEqual(req.created_user.first_name, "Learn Academy")
        self.assertIsNone(req.department)

    def test_lp_request_approved_ignores_a_stray_department_id(self):
        # A department_id sent alongside an LP request is simply not read -
        # there is nothing for it to mean here.
        req = self._submit_lp(email="lp-with-dept-id@example.com", mobile="919200000011")
        r = self.client.post(
            f"{DECISION_LIST_URL}{req.id}/approve/",
            {"department_id": str(self.finance.id)},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        req.refresh_from_db()
        self.assertIsNone(req.created_user.admin_department)

    def test_normal_request_approved_without_department_id_rejected(self):
        req = self._submit_normal(email="normal-no-dept@example.com", mobile="919200000012")
        r = self.client.post(f"{DECISION_LIST_URL}{req.id}/approve/", {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        self.assertEqual(req.status, AdminAccountRequestStatus.PENDING)
        self.assertIsNone(req.created_user)

    def test_normal_request_approved_into_normal_department_still_works(self):
        # Regression check: the Learning Partner split must not affect the
        # pre-existing, unrelated regular admin-account flow.
        req = self._submit_normal(email="normal-ok@example.com", mobile="919200000013")
        r = self.client.post(
            f"{DECISION_LIST_URL}{req.id}/approve/",
            {"department_id": str(self.finance.id)},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        req.refresh_from_db()
        self.assertEqual(req.created_user.role, UserRole.ADMIN)


class LearningPartnerListViewTests(APITestCase):
    def setUp(self):
        self.other_department, _ = AdminDepartment.objects.get_or_create(name="Support")

    def test_lists_only_active_learning_partner_admins(self):
        active_lp = make_learning_partner_admin("LearnAcademy", mobile="919200000020")
        make_learning_partner_admin("InactiveOrg", mobile="919200000021", is_active=False)
        # A plain admin (any department) must never appear here.
        User.objects.create_user(
            password=TEST_PASSWORD,
            email="plainadmin@example.com",
            mobile="919200000022",
            first_name="Plain",
            last_name="Admin",
            role=UserRole.ADMIN,
            admin_department=self.other_department,
            admin_account_name="PlainAdmin@Support",
        )

        r = self.client.get(LP_LIST_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        names = {row["name"] for row in r.data["data"]}
        self.assertEqual(names, {"LearnAcademy"})
        self.assertEqual(r.data["data"][0]["id"], str(active_lp.id))

    def test_no_auth_required(self):
        r = self.client.get(LP_LIST_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class RegisterLearningPartnerIdTests(APITestCase):
    def setUp(self):
        self.lp_admin = make_learning_partner_admin(
            "Learn Academy", mobile="919200000030", email="lpforregister@example.com"
        )

    def _student_payload(self, **over):
        defaults = dict(
            first_name="New",
            last_name="Student",
            email="newstudent@example.com",
            mobile="919200000031",
            role="student",
            password=TEST_PASSWORD,
            password_confirm=TEST_PASSWORD,
        )
        defaults.update(over)
        return defaults

    def test_register_with_valid_learning_partner_id_sets_it(self):
        r = self.client.post(
            REGISTER_URL,
            self._student_payload(learning_partner_id=str(self.lp_admin.id)),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        user = User.objects.get(email="newstudent@example.com")
        self.assertEqual(user.learning_partner_id, self.lp_admin.id)

    def test_register_with_no_learning_partner_id_is_unaffected(self):
        r = self.client.post(
            REGISTER_URL,
            self._student_payload(email="nopartner@example.com", mobile="919200000032"),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        user = User.objects.get(email="nopartner@example.com")
        self.assertIsNone(user.learning_partner_id)

    def test_register_with_explicit_null_learning_partner_id_is_unaffected(self):
        r = self.client.post(
            REGISTER_URL,
            self._student_payload(
                email="nullpartner@example.com", mobile="919200000033", learning_partner_id=None
            ),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        user = User.objects.get(email="nullpartner@example.com")
        self.assertIsNone(user.learning_partner_id)

    def test_register_with_unknown_learning_partner_id_rejected(self):
        r = self.client.post(
            REGISTER_URL,
            self._student_payload(
                email="badpartner@example.com",
                mobile="919200000034",
                learning_partner_id="00000000-0000-0000-0000-000000000000",
            ),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_with_a_plain_admins_id_rejected(self):
        plain_admin = make_user(role=UserRole.ADMIN, email="plain-admin-2@example.com")
        r = self.client.post(
            REGISTER_URL,
            self._student_payload(
                email="triedplain@example.com",
                mobile="919200000035",
                learning_partner_id=str(plain_admin.id),
            ),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_with_inactive_learning_partner_id_rejected(self):
        self.lp_admin.is_active = False
        self.lp_admin.save(update_fields=["is_active"])
        r = self.client.post(
            REGISTER_URL,
            self._student_payload(
                email="triedinactive@example.com",
                mobile="919200000036",
                learning_partner_id=str(self.lp_admin.id),
            ),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_teacher_registration_also_accepts_learning_partner_id(self):
        r = self.client.post(
            REGISTER_URL,
            dict(
                first_name="New",
                last_name="Teacher",
                email="newteacher@example.com",
                mobile="919200000037",
                role="teacher",
                password=TEST_PASSWORD,
                password_confirm=TEST_PASSWORD,
                learning_partner_id=str(self.lp_admin.id),
            ),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        user = User.objects.get(email="newteacher@example.com")
        self.assertEqual(user.learning_partner_id, self.lp_admin.id)

"""
Self-service "become an Admin" requests and Department CRUD:

  POST /api/v1/auth/staff/create-admin-account/                  (public)
  GET  /api/v1/auth/staff/admin-account-requests/                 (super admin)
  POST /api/v1/auth/staff/admin-account-requests/{id}/approve/    (super admin)
  POST /api/v1/auth/staff/admin-account-requests/{id}/deny/       (super admin)
  GET/POST             /api/v1/auth/staff/departments/            (super admin)
  GET/PUT/PATCH/DELETE /api/v1/auth/staff/departments/{id}/       (super admin)

Run: python manage.py test apps.accounts.tests.test_admin_account_requests \
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
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_user

CREATE_URL = "/api/v1/auth/staff/create-admin-account/"
LIST_URL = "/api/v1/auth/staff/admin-account-requests/"


def _payload(**over):
    defaults = dict(
        first_name="Priya",
        last_name="Sharma",
        email="priya.request@example.com",
        mobile="919100000001",
        password=TEST_PASSWORD,
        password_confirm=TEST_PASSWORD,
    )
    defaults.update(over)
    return defaults


class AdminAccountRequestSubmitTests(APITestCase):
    def test_submit_creates_pending_request_no_user_yet(self):
        r = self.client.post(CREATE_URL, _payload(), format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        req = AdminAccountRequest.objects.get(email="priya.request@example.com")
        self.assertEqual(req.status, AdminAccountRequestStatus.PENDING)
        self.assertFalse(
            User.all_objects.filter(email__iexact="priya.request@example.com").exists()
        )
        # Plaintext password never stored anywhere on the request.
        self.assertNotEqual(req.password_hash, TEST_PASSWORD)

    def test_password_mismatch_rejected(self):
        r = self.client.post(
            CREATE_URL,
            _payload(email="mismatch@example.com", mobile="919100000002", password_confirm="Different1!"),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_weak_password_rejected(self):
        r = self.client.post(
            CREATE_URL,
            _payload(email="weak@example.com", mobile="919100000003", password="weak", password_confirm="weak"),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_email_against_existing_user_rejected(self):
        existing = make_user(email="taken@example.com")
        r = self.client.post(
            CREATE_URL, _payload(email=existing.email, mobile="919100000004"), format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_email_against_pending_request_rejected(self):
        self.client.post(
            CREATE_URL, _payload(email="dupe@example.com", mobile="919100000005"), format="json"
        )
        r = self.client.post(
            CREATE_URL, _payload(email="dupe@example.com", mobile="919100000006"), format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_mobile_against_existing_user_rejected(self):
        existing = make_user(email="other@example.com", mobile="919100000007")
        r = self.client.post(
            CREATE_URL,
            _payload(email="freshmail@example.com", mobile=existing.mobile),
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_mobile_against_pending_request_rejected(self):
        self.client.post(
            CREATE_URL, _payload(email="a@example.com", mobile="919100000008"), format="json"
        )
        r = self.client.post(
            CREATE_URL, _payload(email="b@example.com", mobile="919100000008"), format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_email_taken_by_a_denied_request_can_be_resubmitted(self):
        # A denied request must not permanently block the email - only a
        # still-pending one does.
        self.client.post(
            CREATE_URL, _payload(email="retry@example.com", mobile="919100000009"), format="json"
        )
        AdminAccountRequest.objects.filter(email="retry@example.com").update(
            status=AdminAccountRequestStatus.DENIED
        )
        r = self.client.post(
            CREATE_URL, _payload(email="retry@example.com", mobile="919100000010"), format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)


class AdminAccountRequestReviewPermissionTests(APITestCase):
    def test_anonymous_cannot_list(self):
        r = self.client.get(LIST_URL)
        self.assertIn(r.status_code, (401, 403))

    def test_non_superadmin_cannot_list(self):
        for role in (UserRole.STUDENT, UserRole.TEACHER, UserRole.ADMIN):
            u = make_user(role=role, email=f"nope-list-{role}@example.com")
            login(self.client, u)
            r = self.client.get(LIST_URL)
            self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
            self.client.logout()

    def test_non_superadmin_cannot_approve_or_deny(self):
        self.client.post(
            CREATE_URL, _payload(email="target@example.com", mobile="919100000011"), format="json"
        )
        req = AdminAccountRequest.objects.get(email="target@example.com")
        admin = make_user(role=UserRole.ADMIN, email="actor-admin@example.com")
        login(self.client, admin)
        r = self.client.post(f"{LIST_URL}{req.id}/approve/", {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class AdminAccountRequestDecisionTests(APITestCase):
    def setUp(self):
        self.superadmin = make_user(role=UserRole.SUPERADMIN, email="root@example.com")
        login(self.client, self.superadmin)
        self.department, _ = AdminDepartment.objects.get_or_create(name="Finance")

    def _submit(self, **over):
        self.client.logout()
        r = self.client.post(CREATE_URL, _payload(**over), format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        login(self.client, self.superadmin)
        return AdminAccountRequest.objects.get(id=r.data["data"]["id"])

    def test_list_shows_pending_by_default(self):
        self._submit(email="listed@example.com", mobile="919100000012")
        r = self.client.get(LIST_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        emails = [row["email"] for row in r.data["data"]]
        self.assertIn("listed@example.com", emails)

    def test_approve_requires_department_id(self):
        req = self._submit(email="needsdept@example.com", mobile="919100000013")
        r = self.client.post(f"{LIST_URL}{req.id}/approve/", {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        self.assertEqual(req.status, AdminAccountRequestStatus.PENDING)

    def test_approve_with_invalid_department_id_rejected(self):
        req = self._submit(email="baddept@example.com", mobile="919100000014")
        r = self.client.post(
            f"{LIST_URL}{req.id}/approve/",
            {"department_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_approve_creates_admin_with_generated_name(self):
        req = self._submit(
            first_name="Raju", last_name="Das", email="raju.approve@example.com", mobile="919100000015"
        )
        r = self.client.post(
            f"{LIST_URL}{req.id}/approve/",
            {"department_id": str(self.department.id)},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        req.refresh_from_db()
        self.assertEqual(req.status, AdminAccountRequestStatus.APPROVED)
        self.assertIsNotNone(req.created_user)
        user = req.created_user
        self.assertEqual(user.role, UserRole.ADMIN)
        self.assertEqual(user.admin_account_name, "RajuDas@Finance")
        self.assertEqual(user.admin_department_id, self.department.id)
        # The requester's own chosen password signs them in afterward.
        self.assertTrue(user.check_password(TEST_PASSWORD))

    def test_approve_is_one_action_no_partial_state_on_missing_department(self):
        """
        The "no way around it" requirement: a rejected approve() (missing
        department) must leave no User and the request untouched - there is
        no partial "approved but no department" state to exploit.
        """
        req = self._submit(email="atomic@example.com", mobile="919100000016")
        self.client.post(f"{LIST_URL}{req.id}/approve/", {}, format="json")
        req.refresh_from_db()
        self.assertIsNone(req.created_user)
        self.assertEqual(req.status, AdminAccountRequestStatus.PENDING)

    def test_cannot_approve_already_decided_request(self):
        req = self._submit(email="twice@example.com", mobile="919100000017")
        self.client.post(
            f"{LIST_URL}{req.id}/approve/", {"department_id": str(self.department.id)}, format="json"
        )
        r = self.client.post(
            f"{LIST_URL}{req.id}/approve/", {"department_id": str(self.department.id)}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deny_sets_status_and_reason_no_user_created(self):
        req = self._submit(email="denyme@example.com", mobile="919100000018")
        r = self.client.post(
            f"{LIST_URL}{req.id}/deny/", {"reason": "Could not verify identity."}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        req.refresh_from_db()
        self.assertEqual(req.status, AdminAccountRequestStatus.DENIED)
        self.assertEqual(req.deny_reason, "Could not verify identity.")
        self.assertIsNone(req.created_user)

    def test_second_approval_same_name_and_department_gets_numeric_suffix(self):
        req1 = self._submit(
            first_name="Amit", last_name="Roy", email="amit1@example.com", mobile="919100000019"
        )
        req2 = self._submit(
            first_name="Amit", last_name="Roy", email="amit2@example.com", mobile="919100000020"
        )
        self.client.post(
            f"{LIST_URL}{req1.id}/approve/", {"department_id": str(self.department.id)}, format="json"
        )
        self.client.post(
            f"{LIST_URL}{req2.id}/approve/", {"department_id": str(self.department.id)}, format="json"
        )
        req1.refresh_from_db()
        req2.refresh_from_db()
        self.assertEqual(req1.created_user.admin_account_name, "AmitRoy@Finance")
        self.assertEqual(req2.created_user.admin_account_name, "AmitRoy2@Finance")

    def test_double_approval_race_fails_clean_not_a_500(self):
        """
        Regression: the view's own status check (test_cannot_approve_
        already_decided_request above) only protects the SEQUENTIAL case,
        because it re-queries the request fresh each time. Two requests
        that both read status=PENDING before either commits (two open
        tabs, both clicking Approve at once) used to both sail past that
        check and race on User.email's unique constraint - the second one
        raising a raw, unhandled IntegrityError instead of a clean 400.
        Calling the service directly with the SAME pre-fetched object
        (instead of going through the view's fresh re-fetch) reproduces
        that race deterministically, without needing real threads.
        """
        from apps.accounts.services.admin_account_naming import approve_and_create_admin
        from apps.core.exceptions.custom_exceptions import ValidationException

        req = self._submit(email="racecondition@example.com", mobile="919100000021")
        approve_and_create_admin(req, department=self.department, reviewed_by=None)

        with self.assertRaises(ValidationException):
            approve_and_create_admin(req, department=self.department, reviewed_by=None)

        # Exactly one admin account was created for this request - not two,
        # and not a crash.
        self.assertEqual(User.objects.filter(email="racecondition@example.com").count(), 1)


class AdminDepartmentCRUDTests(APITestCase):
    def setUp(self):
        self.superadmin = make_user(role=UserRole.SUPERADMIN, email="deptroot@example.com")
        login(self.client, self.superadmin)

    def test_non_superadmin_cannot_manage_departments(self):
        self.client.logout()
        admin = make_user(role=UserRole.ADMIN, email="deptadmin@example.com")
        login(self.client, admin)
        r = self.client.get("/api/v1/auth/staff/departments/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_list_update_department(self):
        r = self.client.post(
            "/api/v1/auth/staff/departments/", {"name": "Compliance"}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        dept_id = r.data["data"]["id"]
        self.assertEqual(r.data["data"]["slug"], "compliance")

        r = self.client.get("/api/v1/auth/staff/departments/")
        names = [d["name"] for d in r.data["data"]]
        self.assertIn("Compliance", names)

        r = self.client.patch(
            f"/api/v1/auth/staff/departments/{dept_id}/", {"is_active": False}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(r.data["data"]["is_active"])

    def test_duplicate_department_name_rejected(self):
        AdminDepartment.objects.get_or_create(name="Finance")
        r = self.client.post(
            "/api/v1/auth/staff/departments/", {"name": "finance"}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_delete_department_with_active_admin(self):
        department, _ = AdminDepartment.objects.get_or_create(name="Support")
        make_user(
            role=UserRole.ADMIN,
            email="supportadmin@example.com",
            admin_account_name="SupportOne@Support",
            admin_department=department,
        )
        r = self.client.delete(f"/api/v1/auth/staff/departments/{department.id}/")
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)

    def test_can_delete_department_with_no_active_admins(self):
        department, _ = AdminDepartment.objects.get_or_create(name="Marketing")
        r = self.client.delete(f"/api/v1/auth/staff/departments/{department.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

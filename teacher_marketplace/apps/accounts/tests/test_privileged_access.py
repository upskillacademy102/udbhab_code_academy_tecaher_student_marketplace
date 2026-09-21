"""
User management, Super-Admin impersonation, and the admin-login
approval flow.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import ImpersonationSession, UserRole, UserSession
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_user
from apps.ops.models import AuditLog

FORBIDDEN = status.HTTP_403_FORBIDDEN
UNAUTH = status.HTTP_401_UNAUTHORIZED
OK = status.HTTP_200_OK


def as_role(test, role):
    u = make_user(role)
    c = test.client_class()
    login(c, u)
    return u, c


class AdminLoginFlowTests(APITestCase):
    def test_admin_cannot_use_standard_login(self):
        admin = make_user(UserRole.ADMIN)
        r = self.client.post(
            "/api/v1/auth/login/",
            {"email": admin.email, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pending_request_then_super_admin_approves(self):
        admin = make_user(UserRole.ADMIN)
        sa = make_user(UserRole.SUPERADMIN)

        r = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": admin.email, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        req_id = r.data["data"]["request_id"]
        token = r.data["data"]["poll_token"]

        # not approved yet
        poll = self.client.get(
            f"/api/v1/auth/admin/login/{req_id}/status/?token={token}"
        )
        self.assertEqual(poll.data["data"]["status"], "pending")

        # wrong poll token -> 404
        self.assertEqual(
            self.client.get(
                f"/api/v1/auth/admin/login/{req_id}/status/?token=nope"
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

        # super admin approves
        sac = self.client_class()
        login(sac, sa)
        ap = sac.post(f"/api/v1/auth/admin/login-requests/{req_id}/approve/")
        self.assertEqual(ap.status_code, OK)

        # admin polls -> gets a session
        done = self.client.get(
            f"/api/v1/auth/admin/login/{req_id}/status/?token={token}"
        )
        self.assertEqual(done.status_code, OK)
        self.assertIn("access", done.data["data"])
        self.assertTrue(UserSession.objects.filter(user=admin, is_active=True).exists())

        # second poll -> already consumed
        again = self.client.get(
            f"/api/v1/auth/admin/login/{req_id}/status/?token={token}"
        )
        self.assertEqual(again.data["data"]["status"], "consumed")

    def test_non_super_admin_cannot_approve(self):
        admin = make_user(UserRole.ADMIN)
        r = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": admin.email, "password": TEST_PASSWORD},
            format="json",
        )
        req_id = r.data["data"]["request_id"]
        _, tc = as_role(self, UserRole.TEACHER)
        self.assertEqual(
            tc.post(f"/api/v1/auth/admin/login-requests/{req_id}/approve/").status_code,
            FORBIDDEN,
        )

    def test_denied_request_never_issues_session(self):
        admin = make_user(UserRole.ADMIN)
        sa = make_user(UserRole.SUPERADMIN)
        r = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": admin.email, "password": TEST_PASSWORD},
            format="json",
        )
        req_id, token = r.data["data"]["request_id"], r.data["data"]["poll_token"]
        sac = self.client_class()
        login(sac, sa)
        sac.post(f"/api/v1/auth/admin/login-requests/{req_id}/deny/")
        poll = self.client.get(
            f"/api/v1/auth/admin/login/{req_id}/status/?token={token}"
        )
        self.assertEqual(poll.data["data"]["status"], "denied")
        self.assertFalse(
            UserSession.objects.filter(user=admin, is_active=True).exists()
        )

    def test_super_admin_login_is_direct(self):
        sa = make_user(UserRole.SUPERADMIN)
        r = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": sa.email, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(r.status_code, OK)
        self.assertIn("access", r.data["data"])


class UserManagementTests(APITestCase):
    def test_admin_can_read_but_not_write_users(self):
        _, ac = as_role(self, UserRole.ADMIN)
        make_user(UserRole.STUDENT)
        self.assertEqual(ac.get("/api/v1/admin/users/").status_code, OK)
        r = ac.post(
            "/api/v1/admin/users/",
            {
                "email": "n@e.test",
                "mobile": "919111111111",
                "first_name": "N",
                "last_name": "E",
                "role": "student",
                "password": TEST_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_super_admin_creates_and_deactivates(self):
        _, sc = as_role(self, UserRole.SUPERADMIN)
        r = sc.post(
            "/api/v1/admin/users/",
            {
                "email": "new.teacher@e.test",
                "mobile": "919222222222",
                "first_name": "New",
                "last_name": "T",
                "role": "teacher",
                "password": TEST_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        uid = r.data["data"]["id"]

        # deactivate kills their session
        target_client = self.client_class()
        from apps.accounts.models import User

        login(target_client, User.objects.get(id=uid))
        self.assertEqual(
            sc.post(f"/api/v1/admin/users/{uid}/deactivate/").status_code, OK
        )
        self.assertFalse(
            UserSession.objects.filter(user_id=uid, is_active=True).exists()
        )

    def test_cannot_demote_last_super_admin(self):
        sa = make_user(UserRole.SUPERADMIN)
        sc = self.client_class()
        login(sc, sa)
        r = sc.patch(f"/api/v1/admin/users/{sa.id}/", {"role": "admin"}, format="json")
        self.assertIn(r.status_code, (status.HTTP_400_BAD_REQUEST, FORBIDDEN))

    def test_plain_user_cannot_touch_user_admin_api(self):
        _, tc = as_role(self, UserRole.TEACHER)
        self.assertEqual(tc.get("/api/v1/admin/users/").status_code, FORBIDDEN)


class SuperAdminSuspendPromoteRevokeTests(APITestCase):
    """
    Super Admin's authority over every non-super-admin account: suspend
    (deactivate) a teacher or student, revoke an Admin's role back to
    teacher/student, and suspend an Admin account outright. All through the
    existing `/api/v1/admin/users/{id}/` PATCH + activate/deactivate
    endpoints - superadmin-only per apps.accounts.api_permissions (only
    GET is granted to plain Admin there).

    Promoting someone TO Admin via this PATCH endpoint is intentionally
    NOT available, even to Super Admin - see
    `test_promoting_to_admin_via_patch_is_blocked` below. The only path to
    role=admin is the admin-account request/approval flow (see
    test_admin_account_requests.py), which also assigns a department and
    generates the admin_account_name login identifier.
    """

    def setUp(self):
        _, self.sc = as_role(self, UserRole.SUPERADMIN)

    def _deactivate(self, target):
        return self.sc.post(f"/api/v1/admin/users/{target.id}/deactivate/")

    def _activate(self, target):
        return self.sc.post(f"/api/v1/admin/users/{target.id}/activate/")

    def _set_role(self, target, role):
        return self.sc.patch(
            f"/api/v1/admin/users/{target.id}/", {"role": role}, format="json"
        )

    def test_suspends_a_teacher_and_a_student(self):
        for role in (UserRole.TEACHER, UserRole.STUDENT):
            target = make_user(role, email=f"suspend-{role}@x.test")
            target_client = self.client_class()
            login(target_client, target)

            r = self._deactivate(target)
            self.assertEqual(r.status_code, OK, r.content)
            target.refresh_from_db()
            self.assertFalse(target.is_active)
            self.assertFalse(
                UserSession.objects.filter(user=target, is_active=True).exists()
            )
            # suspended -> the standard login rejects them
            self.assertNotEqual(
                self.client_class()
                .post(
                    "/api/v1/auth/login/",
                    {"email": target.email, "password": TEST_PASSWORD},
                    format="json",
                )
                .status_code,
                OK,
            )

    def test_reactivates_a_suspended_account(self):
        target = make_user(UserRole.TEACHER, email="reactivate@x.test")
        self._deactivate(target)
        r = self._activate(target)
        self.assertEqual(r.status_code, OK, r.content)
        target.refresh_from_db()
        self.assertTrue(target.is_active)

    def test_promoting_to_admin_via_patch_is_blocked(self):
        for role in (UserRole.STUDENT, UserRole.TEACHER):
            target = make_user(role, email=f"promote-{role}@x.test")
            r = self._set_role(target, "admin")
            self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
            target.refresh_from_db()
            # role is unchanged - the request/approval flow is the only path.
            self.assertEqual(target.role, role)

    def test_revokes_admin_status(self):
        admin = make_user(UserRole.ADMIN, email="revoke@x.test")
        r = self._set_role(admin, "teacher")
        self.assertEqual(r.status_code, OK, r.content)
        admin.refresh_from_db()
        self.assertEqual(admin.role, UserRole.TEACHER)

        ex_admin_client = self.client_class()
        login(ex_admin_client, admin)
        self.assertEqual(
            ex_admin_client.get("/api/v1/admin/users/").status_code, FORBIDDEN
        )

    def test_suspends_an_admin(self):
        admin = make_user(UserRole.ADMIN, email="suspend-admin@x.test")
        admin_client = self.client_class()
        login(admin_client, admin)

        r = self._deactivate(admin)
        self.assertEqual(r.status_code, OK, r.content)
        admin.refresh_from_db()
        self.assertFalse(admin.is_active)
        self.assertFalse(
            UserSession.objects.filter(user=admin, is_active=True).exists()
        )

    def test_plain_admin_cannot_suspend_promote_or_revoke(self):
        _, ac = as_role(self, UserRole.ADMIN)
        student = make_user(UserRole.STUDENT, email="untouchable@x.test")
        other_admin = make_user(UserRole.ADMIN, email="peer-admin@x.test")

        self.assertEqual(
            ac.post(f"/api/v1/admin/users/{student.id}/deactivate/").status_code,
            FORBIDDEN,
        )
        self.assertEqual(
            ac.patch(
                f"/api/v1/admin/users/{student.id}/", {"role": "admin"}, format="json"
            ).status_code,
            FORBIDDEN,
        )
        self.assertEqual(
            ac.post(f"/api/v1/admin/users/{other_admin.id}/deactivate/").status_code,
            FORBIDDEN,
        )

    def test_suspend_and_role_change_are_audit_logged(self):
        target = make_user(UserRole.TEACHER, email="audited@x.test")
        self._deactivate(target)
        self._activate(target)
        # Promotion to admin is blocked (see test_promoting_to_admin_via_patch_is_blocked
        # above) - exercise "role changed" via a still-allowed transition instead:
        # demoting an existing admin back to teacher.
        admin = make_user(UserRole.ADMIN, email="audited-admin@x.test")
        self._set_role(admin, "teacher")
        actions = set(
            AuditLog.objects.filter(
                target_id__in=[str(target.id), str(admin.id)]
            ).values_list("action", flat=True)
        )
        self.assertIn("user.deactivated", actions)
        self.assertIn("user.activated", actions)
        self.assertIn("user.role_changed", actions)


class ImpersonationTests(APITestCase):
    def setUp(self):
        self.sa = make_user(UserRole.SUPERADMIN)
        self.student = make_user(UserRole.STUDENT)
        self.client_sa = self.client_class()
        login(self.client_sa, self.sa)

    def _impersonate(self, target):
        return self.client_sa.post(
            f"/api/v1/admin/users/{target.id}/impersonate/",
            {"reason": "t"},
            format="json",
        )

    def test_impersonate_then_act_then_return(self):
        r = self._impersonate(self.student)
        self.assertEqual(r.status_code, OK)
        # /auth/me/ now reports impersonation
        me = self.client_sa.get("/api/v1/auth/me/")
        self.assertEqual(me.data["data"]["user"]["role"], "student")
        self.assertEqual(me.data["data"]["impersonated_by"]["email"], self.sa.email)
        # can act as the student
        self.assertEqual(
            self.client_sa.get("/api/v1/student-requirements/").status_code, OK
        )
        # cannot reach teacher-only routes
        self.assertEqual(self.client_sa.get("/api/v1/leads/").status_code, FORBIDDEN)
        # student's own real session is untouched
        self.assertFalse(
            UserSession.objects.filter(user=self.student, is_active=True).exists()
        )
        # return
        back = self.client_sa.post("/api/v1/auth/stop-impersonation/")
        self.assertEqual(back.status_code, OK)
        self.assertEqual(
            self.client_sa.get("/api/v1/auth/me/").data["data"]["user"]["role"],
            "superadmin",
        )

    def test_cannot_impersonate_another_super_admin(self):
        other_sa = make_user(UserRole.SUPERADMIN)
        self.assertEqual(self._impersonate(other_sa).status_code, FORBIDDEN)

    def test_admin_cannot_impersonate(self):
        _, ac = as_role(self, UserRole.ADMIN)
        self.assertEqual(
            ac.post(
                f"/api/v1/admin/users/{self.student.id}/impersonate/", {}, format="json"
            ).status_code,
            FORBIDDEN,
        )

    def test_impersonation_expiry_rejects_token(self):
        self._impersonate(self.student)
        # force-expire
        ImpersonationSession.objects.filter(
            target_user=self.student, is_active=True
        ).update(expires_at="2000-01-01T00:00:00Z")
        self.assertEqual(self.client_sa.get("/api/v1/auth/me/").status_code, UNAUTH)

    def test_stop_without_impersonating_is_400(self):
        self.assertEqual(
            self.client_sa.post("/api/v1/auth/stop-impersonation/").status_code,
            status.HTTP_400_BAD_REQUEST,
        )


class AuditTrailTests(APITestCase):
    def test_privileged_actions_are_logged(self):
        sa = make_user(UserRole.SUPERADMIN)
        student = make_user(UserRole.STUDENT)
        sc = self.client_class()
        login(sc, sa)
        sc.post(f"/api/v1/admin/users/{student.id}/impersonate/", {}, format="json")
        self.assertTrue(
            AuditLog.objects.filter(
                action="impersonation.start", target_id=str(student.id)
            ).exists()
        )

    def test_ops_endpoints_super_admin_only(self):
        _, ac = as_role(self, UserRole.ADMIN)
        for ep in (
            "/api/v1/ops/health/",
            "/api/v1/ops/events/",
            "/api/v1/ops/overview/",
        ):
            self.assertEqual(ac.get(ep).status_code, FORBIDDEN, ep)
        _, sc = as_role(self, UserRole.SUPERADMIN)
        self.assertEqual(sc.get("/api/v1/ops/health/").status_code, OK)

    def test_ops_health_does_not_hang_when_broker_is_down(self):
        """
        Regression: OpsHealthView called celery_app.control.ping() whose
        `timeout` only bounds the reply wait, not the broker connection -
        a down Redis made /ops/health/ block ~4s. It must now fail fast
        via a short TCP pre-check.
        """
        import time as _time

        from django.test import override_settings

        _, sc = as_role(self, UserRole.SUPERADMIN)
        # A routable-but-dead address (TEST-NET-1, RFC 5737).
        with override_settings(CELERY_BROKER_URL="redis://192.0.2.1:6379/0"):
            t0 = _time.perf_counter()
            resp = sc.get("/api/v1/ops/health/")
            elapsed = _time.perf_counter() - t0

        self.assertEqual(resp.status_code, OK)
        self.assertLess(elapsed, 2.0, "health check hung on a down broker")
        self.assertEqual(
            resp.json()["data"]["checks"]["celery"]["status"], "unreachable"
        )
        # celery being down is best-effort - it must not flip overall health.
        self.assertEqual(resp.json()["data"]["overall"], "ok")

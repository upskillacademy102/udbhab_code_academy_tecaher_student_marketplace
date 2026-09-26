"""
Department-scoped admin authority (apps.accounts.api_permissions.
DEPARTMENT_ROUTE_SCOPE / DEPARTMENT_CAPABILITY_LABELS), plus the
department-reassignment endpoint that makes department a manageable
authority boundary rather than a fixed-at-approval-time label.

Run: python manage.py test apps.accounts.tests.test_department_authority \
     --settings=config.settings.test
"""

from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.api_permissions import (
    DEPARTMENT_ROUTE_SCOPE,
    DEPT_CONTENT_MODERATION,
    DEPT_FINANCE,
    DEPT_MARKETING,
    DEPT_SUPPORT,
    DEPT_VERIFICATION,
    FINANCE_DENIED_ROUTES,
    SUPPORT_DENIED_ROUTES,
    is_allowed,
)
from apps.accounts.models import AdminDepartment, UserRole
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_named_admin, make_user

OK = status.HTTP_200_OK
CREATED = status.HTTP_201_CREATED
FORBIDDEN = status.HTTP_403_FORBIDDEN


#: make_named_admin(department=...)'s string path does
#: AdminDepartment.objects.get_or_create(name=...) - it needs the seeded
#: display name (apps/accounts/migrations/0006_seed_admin_departments.py),
#: not the slug constants DEPT_* are keyed by, or it would create a
#: *second*, differently-cased department whose auto-derived slug collides
#: with the real one's (AdminDepartment.slug is unique).
_DEPARTMENT_NAME = {
    DEPT_FINANCE: "Finance",
    DEPT_SUPPORT: "Support",
    DEPT_VERIFICATION: "Verification",
    DEPT_CONTENT_MODERATION: "Content Moderation",
    DEPT_MARKETING: "Marketing",
}


def _admin_client(test, department_slug):
    admin = make_named_admin(department=_DEPARTMENT_NAME[department_slug])
    c = test.client_class()
    login(c, admin)
    return admin, c


# ==========================================================
# Pure unit coverage of is_allowed() - every row of the matrix, no DB.
# ==========================================================
class DepartmentScopeUnitTests(APITestCase):
    def test_matching_department_allowed(self):
        for (route, method), depts in DEPARTMENT_ROUTE_SCOPE.items():
            for dept in depts:
                self.assertTrue(
                    is_allowed(UserRole.ADMIN, method, route, department_slug=dept),
                    f"{dept} should be allowed on {method} {route}",
                )

    def test_mismatched_department_denied(self):
        for (route, method), depts in DEPARTMENT_ROUTE_SCOPE.items():
            other = "some-other-department"
            self.assertNotIn(other, depts)
            self.assertFalse(
                is_allowed(UserRole.ADMIN, method, route, department_slug=other),
            )

    def test_admin_with_no_department_denied_on_scoped_routes(self):
        for (route, method) in DEPARTMENT_ROUTE_SCOPE:
            self.assertFalse(
                is_allowed(UserRole.ADMIN, method, route, department_slug=None)
            )

    def test_superadmin_always_allowed_regardless_of_department_scope(self):
        for (route, method) in DEPARTMENT_ROUTE_SCOPE:
            self.assertTrue(
                is_allowed(UserRole.SUPERADMIN, method, route, department_slug=None)
            )

    def test_unscoped_admin_route_unaffected_by_department(self):
        # matching:eligible-search GET is granted to admin (via
        # _STUDENT_ADMIN) and never appears in DEPARTMENT_ROUTE_SCOPE -
        # department must not restrict it, for any department including
        # Finance.
        self.assertNotIn(("matching:eligible-search", "GET"), DEPARTMENT_ROUTE_SCOPE)
        self.assertTrue(
            is_allowed(
                UserRole.ADMIN, "GET", "matching:eligible-search", department_slug=None
            )
        )
        self.assertTrue(
            is_allowed(
                UserRole.ADMIN,
                "GET",
                "matching:eligible-search",
                department_slug=DEPT_FINANCE,
            )
        )

    def test_admin_users_list_now_denied_to_finance_only(self):
        # admin_users:list GET is granted to _ADMIN and deliberately never
        # enters DEPARTMENT_ROUTE_SCOPE (that's an allow-list; "every
        # department except Finance" can't be expressed there without also
        # denying a departmentless admin - see FINANCE_DENIED_ROUTES's own
        # docstring). It's denied to Finance specifically via that separate
        # denylist instead - every other department, and no department at
        # all, is unaffected.
        self.assertNotIn(("admin_users:list", "GET"), DEPARTMENT_ROUTE_SCOPE)
        self.assertIn(("admin_users:list", "GET"), FINANCE_DENIED_ROUTES)
        self.assertFalse(
            is_allowed(
                UserRole.ADMIN, "GET", "admin_users:list", department_slug=DEPT_FINANCE
            )
        )
        self.assertTrue(
            is_allowed(
                UserRole.ADMIN, "GET", "admin_users:list", department_slug=DEPT_SUPPORT
            )
        )

    def test_departmentless_admin_unaffected_by_finance_denylist(self):
        # The regression this denylist design specifically avoids: a plain
        # admin with NO department (every legacy pre-department-system
        # admin, and any admin/seed script that never assigned one) must
        # keep exactly today's access to every route in FINANCE_DENIED_
        # ROUTES - only department=finance loses it.
        for route, method in FINANCE_DENIED_ROUTES:
            self.assertTrue(
                is_allowed(UserRole.ADMIN, method, route, department_slug=None),
                f"departmentless admin should still reach {method} {route}",
            )

    def test_departmentless_admin_unaffected_by_support_denylist(self):
        # Same invariant as above, for SUPPORT_DENIED_ROUTES - only
        # department=support loses this access.
        for route, method in SUPPORT_DENIED_ROUTES:
            self.assertTrue(
                is_allowed(UserRole.ADMIN, method, route, department_slug=None),
                f"departmentless admin should still reach {method} {route}",
            )

    def test_finance_can_still_read_commerce_catalog_support_cannot(self):
        # The one deliberate difference between the two denylists: Finance
        # keeps read access to the commerce catalog ("they need to see
        # current prices to request a change" - see _RULES's own comment
        # above), Support has no reason to and loses it. (Most of the rest
        # of SUPPORT_DENIED_ROUTES - reference data, matching config, full
        # profile views - is independently denied to Finance too, via its
        # own FINANCE_DENIED_ROUTES, so isn't a useful contrast here.)
        for route in (
            "token-packages:token-package-list-create",
            "subscriptions:plan-list-create",
            "lead-unlock-pricing:pricing-list-create",
        ):
            self.assertTrue(
                is_allowed(UserRole.ADMIN, "GET", route, department_slug=DEPT_FINANCE),
                f"Finance admin should still read {route}",
            )
            self.assertFalse(
                is_allowed(UserRole.ADMIN, "GET", route, department_slug=DEPT_SUPPORT),
                f"Support admin should not read {route}",
            )

    def test_read_methods_stay_baseline_on_partially_scoped_routes(self):
        # token-packages GET is granted to _TEACHER_ADMIN and is NOT in
        # DEPARTMENT_ROUTE_SCOPE (only the write methods are) - a
        # non-Finance, non-Support admin must still be able to read the
        # catalog. (Support also loses this GET, but via SUPPORT_DENIED_
        # ROUTES, not DEPARTMENT_ROUTE_SCOPE - see SupportReadRestrictionTests
        # below - so Verification stands in as the unaffected department here.)
        self.assertNotIn(
            ("token-packages:token-package-list-create", "GET"),
            DEPARTMENT_ROUTE_SCOPE,
        )
        self.assertTrue(
            is_allowed(
                UserRole.ADMIN,
                "GET",
                "token-packages:token-package-list-create",
                department_slug=DEPT_VERIFICATION,
            )
        )
        self.assertFalse(
            is_allowed(
                UserRole.ADMIN,
                "POST",
                "token-packages:token-package-list-create",
                department_slug=DEPT_VERIFICATION,
            )
        )


# ==========================================================
# Finance: pricing writes removed from every admin department (Finance
# included) as of 2026-09-24 - apps.finance's request/approve flow
# replaces direct writes (see apps.finance.tests for that flow's own
# coverage). Only Super Admin can still write the catalog directly.
# ==========================================================
class FinanceScopeTests(APITestCase):
    def test_finance_admin_cannot_directly_create_token_package(self):
        _, c = _admin_client(self, DEPT_FINANCE)
        r = c.post(
            "/api/v1/token-packages/",
            {"name": "Starter", "token_count": 10, "price": "199.00"},
            format="json",
        )
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_other_department_admin_cannot_create_token_package(self):
        _, c = _admin_client(self, DEPT_SUPPORT)
        r = c.post(
            "/api/v1/token-packages/",
            {"name": "Starter", "token_count": 10, "price": "199.00"},
            format="json",
        )
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_any_admin_can_still_read_token_packages(self):
        # Support also lost this read (SUPPORT_DENIED_ROUTES, added
        # 2026-09-25) - Verification stands in as the unaffected department.
        _, c = _admin_client(self, DEPT_VERIFICATION)
        r = c.get("/api/v1/token-packages/")
        self.assertEqual(r.status_code, OK)

    def test_superadmin_can_create_token_package(self):
        sa = make_user(role=UserRole.SUPERADMIN)
        c = self.client_class()
        login(c, sa)
        r = c.post(
            "/api/v1/token-packages/",
            {"name": "Starter", "token_count": 10, "price": "199.00"},
            format="json",
        )
        self.assertEqual(r.status_code, CREATED, r.content)


# ==========================================================
# Finance: a representative sample of the routes hidden from Finance only
# (apps.accounts.api_permissions.FINANCE_DENIED_ROUTES) - Finance denied,
# every other department (sampled via Verification, which neither denylist
# touches) unaffected, and a departmentless admin (no AdminDepartment at
# all - every legacy pre-department-system account) also unaffected.
# ==========================================================
class FinanceReadRestrictionTests(APITestCase):
    # (admin_onboarding_calls:list isn't sampled here any more: it became
    # Support-only via DEPARTMENT_ROUTE_SCOPE, so it's no longer a route the
    # other departments keep - see test_onboarding_call_accept for its
    # coverage.)
    _SAMPLE = [
        ("/api/v1/admin/users/", "GET"),
        ("/api/v1/students/", "GET"),
        ("/api/v1/admin/support-tickets/", "GET"),
        ("/api/v1/subjects/", "GET"),
        ("/api/v1/location/countries/", "GET"),
        ("/api/v1/matching/pincode-locations/", "GET"),
    ]

    def test_finance_admin_denied_on_hidden_routes(self):
        _, c = _admin_client(self, DEPT_FINANCE)
        for path, method in self._SAMPLE:
            with self.subTest(path=path, method=method):
                r = getattr(c, method.lower())(path)
                self.assertEqual(r.status_code, FORBIDDEN, f"{method} {path}: {r.content}")

    def test_verification_admin_unaffected_on_same_routes(self):
        _, c = _admin_client(self, DEPT_VERIFICATION)
        for path, method in self._SAMPLE:
            with self.subTest(path=path, method=method):
                r = getattr(c, method.lower())(path)
                self.assertNotEqual(
                    r.status_code, FORBIDDEN, f"{method} {path}: {r.content}"
                )

    def test_departmentless_admin_unaffected_on_same_routes(self):
        c = self.client_class()
        login(c, make_user(role=UserRole.ADMIN))
        for path, method in self._SAMPLE:
            with self.subTest(path=path, method=method):
                r = getattr(c, method.lower())(path)
                self.assertNotEqual(
                    r.status_code, FORBIDDEN, f"{method} {path}: {r.content}"
                )


# ==========================================================
# Support: a representative sample of the routes hidden from Support only
# (apps.accounts.api_permissions.SUPPORT_DENIED_ROUTES) - Support denied,
# Finance (sampled as the "other" department - already narrowly scoped
# itself, so a meaningful contrast) unaffected on the routes Finance keeps,
# and a departmentless admin also unaffected.
# ==========================================================
class SupportReadRestrictionTests(APITestCase):
    _SAMPLE = [
        ("/api/v1/students/", "GET"),
        ("/api/v1/teachers/", "GET"),
        ("/api/v1/admin/teacher-profiles/", "GET"),
        ("/api/v1/subjects/", "GET"),
        ("/api/v1/languages/", "GET"),
        ("/api/v1/grade-levels/", "GET"),
        ("/api/v1/location/countries/", "GET"),
        ("/api/v1/matching/pincode-locations/", "GET"),
        ("/api/v1/matching/subject-aliases/", "GET"),
        ("/api/v1/matching/config/", "GET"),
    ]
    # Commerce-catalog reads are the one route family Finance keeps and
    # Support does not - see test_finance_can_still_read_commerce_catalog_
    # support_cannot above for that specific contrast.
    _COMMERCE_SAMPLE = [
        ("/api/v1/token-packages/", "GET"),
        ("/api/v1/subscriptions/plans/", "GET"),
        ("/api/v1/lead-unlock-pricing/", "GET"),
    ]

    def test_support_admin_denied_on_hidden_routes(self):
        _, c = _admin_client(self, DEPT_SUPPORT)
        for path, method in self._SAMPLE + self._COMMERCE_SAMPLE:
            with self.subTest(path=path, method=method):
                r = getattr(c, method.lower())(path)
                self.assertEqual(r.status_code, FORBIDDEN, f"{method} {path}: {r.content}")

    def test_finance_admin_unaffected_on_same_routes(self):
        # Finance is independently denied the _SAMPLE routes too (via its
        # own denylist) - only the commerce-catalog reads are a meaningful
        # contrast here.
        _, c = _admin_client(self, DEPT_FINANCE)
        for path, method in self._COMMERCE_SAMPLE:
            with self.subTest(path=path, method=method):
                r = getattr(c, method.lower())(path)
                self.assertNotEqual(
                    r.status_code, FORBIDDEN, f"{method} {path}: {r.content}"
                )

    def test_departmentless_admin_unaffected_on_same_routes(self):
        c = self.client_class()
        login(c, make_user(role=UserRole.ADMIN))
        for path, method in self._SAMPLE + self._COMMERCE_SAMPLE:
            with self.subTest(path=path, method=method):
                r = getattr(c, method.lower())(path)
                self.assertNotEqual(
                    r.status_code, FORBIDDEN, f"{method} {path}: {r.content}"
                )

    def test_support_admin_keeps_admin_users_and_onboarding_calls_and_support_tickets(self):
        # Not in SUPPORT_DENIED_ROUTES - Support's People/Calls screens
        # (Phases 1/3/4) depend on these staying reachable.
        _, c = _admin_client(self, DEPT_SUPPORT)
        for path in (
            "/api/v1/admin/users/",
            "/api/v1/admin/onboarding-calls/",
            "/api/v1/admin/support-tickets/",
        ):
            with self.subTest(path=path):
                r = c.get(path)
                self.assertNotEqual(r.status_code, FORBIDDEN, f"GET {path}: {r.content}")


# ==========================================================
# Verification: teacher-verification decisions narrowed to Verification.
# ==========================================================
class VerificationScopeTests(APITestCase):
    def _teacher_profile(self):
        from apps.subjects.models import Subject
        from apps.teacher_profile.models import TeacherProfile, TeachingMode, VerificationStatus
        from apps.teachers.models import Teacher

        Subject.objects.get_or_create(name="Karate")
        user = make_user(role=UserRole.TEACHER, first_name="Kata")
        teacher = Teacher.objects.create(user=user, experience_years=5)
        return TeacherProfile.objects.create(
            teacher=teacher,
            teaching_mode=TeachingMode.ONLINE,
            rating=Decimal("4.00"),
            verification_status=VerificationStatus.PENDING,
        )

    def test_verification_admin_can_set_status(self):
        profile = self._teacher_profile()
        _, c = _admin_client(self, DEPT_VERIFICATION)
        r = c.post(
            f"/api/v1/admin/teacher-profiles/{profile.teacher_id}/verification/",
            {"status": "verified"},
            format="json",
        )
        self.assertEqual(r.status_code, OK, r.content)

    def test_other_department_admin_cannot_set_status(self):
        profile = self._teacher_profile()
        _, c = _admin_client(self, DEPT_FINANCE)
        r = c.post(
            f"/api/v1/admin/teacher-profiles/{profile.teacher_id}/verification/",
            {"status": "verified"},
            format="json",
        )
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_finance_admin_cannot_list_teacher_profiles(self):
        # Finance lost this read (apps.finance replaces it with its own,
        # money-only screens) - every other department still has it, see
        # test_other_admin_can_still_list_teacher_profiles below.
        _, c = _admin_client(self, DEPT_FINANCE)
        r = c.get("/api/v1/admin/teacher-profiles/")
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_support_admin_also_cannot_list_teacher_profiles(self):
        # Support lost this read too (SUPPORT_DENIED_ROUTES) - Support uses
        # the trimmed admin_users:list endpoint for contact info instead.
        _, c = _admin_client(self, DEPT_SUPPORT)
        r = c.get("/api/v1/admin/teacher-profiles/")
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_other_admin_can_still_list_teacher_profiles(self):
        _, c = _admin_client(self, DEPT_MARKETING)
        r = c.get("/api/v1/admin/teacher-profiles/")
        self.assertEqual(r.status_code, OK)


# ==========================================================
# Support: resolving a ticket narrowed to Support (assignment check
# unchanged on top - a Support admin not assigned still 403s).
# ==========================================================
class SupportScopeTests(APITestCase):
    def _ticket(self, *, assign=None):
        from apps.support.models import SupportTicket

        reporter = make_user(role=UserRole.STUDENT)
        ticket = SupportTicket.objects.create(
            reporter=reporter, subject="Broken thing", description="It's broken."
        )
        if assign is not None:
            ticket.assigned_admins.add(assign)
        return ticket

    def test_assigned_support_admin_can_resolve(self):
        admin, c = _admin_client(self, DEPT_SUPPORT)
        ticket = self._ticket(assign=admin)
        r = c.post(f"/api/v1/admin/support-tickets/{ticket.id}/resolve/", {}, format="json")
        self.assertEqual(r.status_code, OK, r.content)

    def test_assigned_wrong_department_admin_cannot_resolve(self):
        admin, c = _admin_client(self, DEPT_FINANCE)
        ticket = self._ticket(assign=admin)
        r = c.post(f"/api/v1/admin/support-tickets/{ticket.id}/resolve/", {}, format="json")
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_unassigned_support_admin_still_cannot_resolve(self):
        # Department scoping is additive, not a replacement for the
        # existing per-ticket assignment check.
        _, c = _admin_client(self, DEPT_SUPPORT)
        ticket = self._ticket(assign=None)
        r = c.post(f"/api/v1/admin/support-tickets/{ticket.id}/resolve/", {}, format="json")
        self.assertEqual(r.status_code, FORBIDDEN)


# ==========================================================
# Content Moderation: new grant, narrowed further by object-level checks
# a route-name grant alone can't express.
# ==========================================================
class ContentModerationScopeTests(APITestCase):
    def _review_item(self, kind):
        from apps.trust.models import ManualReviewItem

        subject = make_user(role=UserRole.STUDENT)
        return ManualReviewItem.objects.create(
            kind=kind, subject_user=subject, summary="test item"
        )

    def test_content_moderation_admin_can_view_fake_lead_reports(self):
        _, c = _admin_client(self, DEPT_CONTENT_MODERATION)
        r = c.get("/api/v1/ops/fake-lead-reports/")
        self.assertEqual(r.status_code, OK)

    def test_marketing_admin_cannot_view_fake_lead_reports(self):
        _, c = _admin_client(self, DEPT_MARKETING)
        r = c.get("/api/v1/ops/fake-lead-reports/")
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_content_moderation_admin_can_resolve_fake_lead_item(self):
        from apps.trust.models import ManualReviewKind

        item = self._review_item(ManualReviewKind.FAKE_LEAD_REPORT)
        _, c = _admin_client(self, DEPT_CONTENT_MODERATION)
        r = c.post(f"/api/v1/ops/review-queue/{item.id}/resolve/", {"dismiss": True}, format="json")
        self.assertEqual(r.status_code, OK, r.content)

    def test_content_moderation_admin_cannot_resolve_non_fake_lead_item(self):
        from apps.trust.models import ManualReviewKind

        item = self._review_item(ManualReviewKind.TEACHER_VERIFICATION)
        _, c = _admin_client(self, DEPT_CONTENT_MODERATION)
        r = c.post(f"/api/v1/ops/review-queue/{item.id}/resolve/", {"dismiss": True}, format="json")
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_content_moderation_admin_can_ban_and_it_is_tagged(self):
        from apps.trust.models import AccountSanctionSource

        target = make_user(role=UserRole.STUDENT)
        _, c = _admin_client(self, DEPT_CONTENT_MODERATION)
        r = c.post(
            "/api/v1/ops/sanctions/", {"user_id": str(target.id), "kind": "ban"}, format="json"
        )
        self.assertEqual(r.status_code, CREATED, r.content)
        self.assertEqual(
            r.data["data"]["source"], AccountSanctionSource.MANUAL_CONTENT_MODERATION
        )

    def test_content_moderation_admin_cannot_list_all_sanctions(self):
        # GET is unlisted for the ops:sanctions route -> Super Admin only,
        # even though POST is now open to this department.
        _, c = _admin_client(self, DEPT_CONTENT_MODERATION)
        r = c.get("/api/v1/ops/sanctions/")
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_content_moderation_admin_can_lift_own_sourced_sanction(self):
        from apps.trust.models import AccountSanctionSource
        from apps.trust.services.sanction_service import SanctionService

        target = make_user(role=UserRole.STUDENT)
        sanction = SanctionService.apply(
            target, source=AccountSanctionSource.MANUAL_CONTENT_MODERATION
        )
        _, c = _admin_client(self, DEPT_CONTENT_MODERATION)
        r = c.post(f"/api/v1/ops/sanctions/{sanction.id}/lift/", {}, format="json")
        self.assertEqual(r.status_code, OK, r.content)

    def test_content_moderation_admin_cannot_lift_superadmin_sourced_sanction(self):
        from apps.trust.models import AccountSanctionSource
        from apps.trust.services.sanction_service import SanctionService

        target = make_user(role=UserRole.STUDENT)
        sanction = SanctionService.apply(target, source=AccountSanctionSource.MANUAL)
        _, c = _admin_client(self, DEPT_CONTENT_MODERATION)
        r = c.post(f"/api/v1/ops/sanctions/{sanction.id}/lift/", {}, format="json")
        self.assertEqual(r.status_code, FORBIDDEN)


# ==========================================================
# Marketing: read-only lead-quality visibility, new grant.
# ==========================================================
class MarketingScopeTests(APITestCase):
    def test_marketing_admin_can_view_lead_quality(self):
        _, c = _admin_client(self, DEPT_MARKETING)
        self.assertEqual(c.get("/api/v1/ops/students-lead-quality/").status_code, OK)
        self.assertEqual(c.get("/api/v1/ops/teacher-lead-reviews/").status_code, OK)

    def test_content_moderation_admin_cannot_view_lead_quality(self):
        _, c = _admin_client(self, DEPT_CONTENT_MODERATION)
        self.assertEqual(c.get("/api/v1/ops/students-lead-quality/").status_code, FORBIDDEN)


# ==========================================================
# Reassigning an existing admin's department (Super Admin only).
# ==========================================================
class DepartmentReassignmentTests(APITestCase):
    def test_superadmin_can_reassign(self):
        admin = make_named_admin(department=_DEPARTMENT_NAME[DEPT_SUPPORT])
        finance = AdminDepartment.objects.get_or_create(name="Finance")[0]
        sa = make_user(role=UserRole.SUPERADMIN)
        c = self.client_class()
        login(c, sa)
        r = c.patch(
            f"/api/v1/admin/users/{admin.id}/",
            {"admin_department_id": str(finance.id)},
            format="json",
        )
        self.assertEqual(r.status_code, OK, r.content)
        admin.refresh_from_db()
        self.assertEqual(admin.admin_department_id, finance.id)

    def test_plain_admin_cannot_reassign(self):
        admin = make_named_admin(department=_DEPARTMENT_NAME[DEPT_SUPPORT])
        finance = AdminDepartment.objects.get_or_create(name="Finance")[0]
        _, c = _admin_client(self, DEPT_FINANCE)
        r = c.patch(
            f"/api/v1/admin/users/{admin.id}/",
            {"admin_department_id": str(finance.id)},
            format="json",
        )
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_cannot_reassign_department_of_a_non_admin(self):
        teacher = make_user(role=UserRole.TEACHER)
        finance = AdminDepartment.objects.get_or_create(name="Finance")[0]
        sa = make_user(role=UserRole.SUPERADMIN)
        c = self.client_class()
        login(c, sa)
        r = c.patch(
            f"/api/v1/admin/users/{teacher.id}/",
            {"admin_department_id": str(finance.id)},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)

    def test_cannot_reassign_to_inactive_department(self):
        admin = make_named_admin(department=_DEPARTMENT_NAME[DEPT_SUPPORT])
        inactive = AdminDepartment.objects.create(name="Retired Dept", is_active=False)
        sa = make_user(role=UserRole.SUPERADMIN)
        c = self.client_class()
        login(c, sa)
        r = c.patch(
            f"/api/v1/admin/users/{admin.id}/",
            {"admin_department_id": str(inactive.id)},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)

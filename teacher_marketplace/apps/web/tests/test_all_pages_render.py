"""
Every server-rendered page, for every role, must render without a 500.

WHY THIS EXISTS (2026-09-09): templates/web/partials/_unlock_allowance.html
used ``{% icon %}`` but never ``{% load web_extras %}``. ``{% load %}`` is not
inherited through ``{% include %}`` (or ``{% extends %}``), so the tag was an
unknown block tag and *every* page that included the partial - the teacher
leads list and lead detail - raised TemplateSyntaxError at render time.
Nothing caught it: it is a render-time error, so ``manage.py check`` and the
app booting are both clean, and no existing test rendered those two pages.

This test walks apps.web.urls, logs in as each role, and GETs every page that
role can reach (a throwaway UUID stands in for ``<uuid:id>`` detail routes -
the page factory renders the shell and never looks the object up). A missing
``{% load %}``, a renamed include, a bad ``{% url %}``, a NoReverseMatch or any
unhandled view error surfaces here as a 500 with the offending path named.

Run: python manage.py test apps.web.tests.test_all_pages_render \
     --settings=config.settings.test
"""

from django.test import Client, TestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_named_admin, make_user
from apps.web import urls as web_urls

# staff/admin/finance/ routes need a Finance-department admin, not just any
# admin (department_slugs={"finance"} guard, apps/web/urls.py) - excluded
# from the generic ADMIN-role sweep below and covered by their own test,
# test_finance_pages_render_only_for_finance_department, mirroring how
# test_learning_partner_pages_render_only_for_a_learning_partner covers
# /staff/learning-partner/.
_FINANCE_PREFIX = "/staff/admin/finance/"

# Same story for /staff/admin/support/ (department_slugs={"support"}) - covered
# by test_support_pages_render_only_for_support_department.
_SUPPORT_PREFIX = "/staff/admin/support/"

# A syntactically valid UUID that matches nothing. Detail pages render their
# shell regardless; the browser fetches the real record from the API.
DUMMY_UUID = "11111111-1111-1111-1111-111111111111"

# URL-prefix -> the role whose nav and guard own that page. staff/admin/ and
# staff/superadmin/ are the new React-owned dashboards (Phase 3+) - a
# distinct prefix from the legacy admin-portal/ and super-admin/ templates,
# which keep working by direct URL even though ROLE_HOME no longer points at
# them (apps/web/guards.py).
_PREFIX_ROLE = (
    ("student/", UserRole.STUDENT),
    ("teacher/", UserRole.TEACHER),
    ("admin-portal/", UserRole.ADMIN),
    ("staff/admin/", UserRole.ADMIN),
    ("super-admin/", UserRole.SUPERADMIN),
    ("staff/superadmin/", UserRole.SUPERADMIN),
)

# Public pages: (path, needs_login). /suspended/ is behind login_required_web
# but has no role guard - any signed-in user renders it.
_PUBLIC = (
    ("/", False),
    ("/login/", False),
    ("/register/", False),
    ("/login/staff/", False),
    ("/suspended/", True),
    ("/learning-partner/", False),
    ("/learning-partner/login/", False),
)


def _iter_routes():
    """(name, path) for every route in apps.web.urls, id-routes filled in."""
    for pattern in web_urls.urlpatterns:
        route = str(pattern.pattern)
        path = "/" + route.replace("<uuid:id>", DUMMY_UUID)
        yield pattern.name, path


def _role_for_path(path):
    for prefix, role in _PREFIX_ROLE:
        if path.startswith("/" + prefix):
            return role
    return None


def _login_lp(client, lp_user):
    """
    A Learning Partner signs in with its admin_account_name at its own
    dedicated endpoint, /staff/login-learning-partner/ - not the shared
    login() helper (routes role=admin through the OLD /auth/admin/login/
    flow) and not /staff/login-admin/ either, which now rejects a Learning
    Partner account name outright (see StaffAdminLoginView).
    """
    resp = client.post(
        "/api/v1/auth/staff/login-learning-partner/",
        {"account_name": lp_user.admin_account_name, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.content
    return resp


def _fresh_client():
    # raise_request_exception=False so a broken page comes back as a 500
    # response we can collect, instead of aborting the whole sweep on the
    # first failure - the point is to report every broken page at once.
    return Client(raise_request_exception=False, enforce_csrf_checks=False)


class AllPagesRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {
            UserRole.STUDENT: make_user(role=UserRole.STUDENT, email="s@render.test"),
            UserRole.TEACHER: make_user(role=UserRole.TEACHER, email="t@render.test"),
            UserRole.ADMIN: make_user(role=UserRole.ADMIN, email="a@render.test"),
            UserRole.SUPERADMIN: make_user(
                role=UserRole.SUPERADMIN, email="sa@render.test"
            ),
        }
        cls.lp_user = make_user(
            role=UserRole.LEARNING_PARTNER,
            email="lp@render.test",
            admin_account_name="RenderTest@LearningPartner",
        )
        cls.finance_admin = make_named_admin(department="Finance")
        cls.support_admin = make_named_admin(department="Support")

    def _client_for(self, role):
        client = _fresh_client()
        resp = login(client, self.users[role])
        self.assertIn(
            resp.status_code, (200, 202), f"login failed for {role}: {resp.status_code}"
        )
        return client

    def test_public_pages_render(self):
        anon = _fresh_client()
        member = self._client_for(UserRole.STUDENT)
        failures = []
        for path, needs_login in _PUBLIC:
            client = member if needs_login else anon
            resp = client.get(path)
            if resp.status_code >= 500:
                failures.append(f"{path} -> {resp.status_code}")
        self.assertFalse(failures, "public pages 500ing:\n" + "\n".join(failures))

    def test_every_role_page_renders_for_its_own_role(self):
        by_role = {}
        for name, path in _iter_routes():
            if path.startswith(_FINANCE_PREFIX):
                continue  # covered by test_finance_pages_render_only_for_finance_department
            if path.startswith(_SUPPORT_PREFIX):
                continue  # covered by test_support_pages_render_only_for_support_department
            role = _role_for_path(path)
            if role is not None:
                by_role.setdefault(role, []).append((name, path))

        # Sanity: the sweep actually found the four role areas.
        self.assertEqual(set(by_role), {r for _, r in _PREFIX_ROLE})

        failures = []
        for role, routes in by_role.items():
            client = self._client_for(role)
            for name, path in routes:
                resp = client.get(path)
                if resp.status_code != 200:
                    failures.append(
                        f"[{role}] {name or '(unnamed)'} {path} -> {resp.status_code}"
                    )
        self.assertFalse(
            failures,
            "pages not rendering 200 for their own role:\n" + "\n".join(failures),
        )

    def test_superadmin_can_render_every_page(self):
        """
        Super Admin is implicitly allowed on every role_required() route, so a
        broken template anywhere also shows up here - under the Super Admin
        nav, which is the branch of nav_for() the per-role pass never exercises
        for the student / teacher / admin areas.
        """
        client = self._client_for(UserRole.SUPERADMIN)
        failures = []
        for name, path in _iter_routes():
            if _role_for_path(path) is None:
                continue  # public pages handled separately
            resp = client.get(path)
            if resp.status_code >= 500:
                failures.append(f"{name or '(unnamed)'} {path} -> {resp.status_code}")
        self.assertFalse(
            failures,
            "pages 500ing under the Super Admin session:\n" + "\n".join(failures),
        )

    def test_every_nav_link_resolves_to_a_registered_route(self):
        """
        apps.web.nav.nav_for() is hand-maintained separately from
        apps.web.urls - nothing enforces that a URL typed into a NavItem
        actually matches a registered path. This walks every nav item for
        every role and resolves its url through Django's own URL resolver,
        so a typo'd or stale nav link (pointing at a renamed/removed page)
        fails here instead of silently 404ing for a real user who clicks it.
        """
        from django.urls import Resolver404, resolve

        from apps.web.nav import nav_for

        failures = []
        for role in ("student", "teacher", "admin", "superadmin", "learning_partner"):
            for section in nav_for(role):
                for item in section["items"]:
                    url = item.get("url")
                    if not url:
                        continue
                    try:
                        resolve(url)
                    except Resolver404:
                        failures.append(f"[{role}] {item['label']!r} -> {url}")
        self.assertFalse(
            failures, "nav items pointing at unregistered URLs:\n" + "\n".join(failures)
        )

    def test_learning_partner_pages_render_only_for_a_learning_partner(self):
        """
        /staff/learning-partner/* is guarded by learning_partner_required,
        not plain role_required("admin") - a real Learning Partner admin
        must get every page, and a PLAIN admin (same role, ordinary
        department) must be cleanly refused rather than shown a shell whose
        data calls all 403 underneath it.
        """
        lp_routes = [
            (name, path) for name, path in _iter_routes() if path.startswith("/staff/learning-partner/")
        ]
        self.assertTrue(lp_routes, "no /staff/learning-partner/ routes were registered")

        lp_client = _fresh_client()
        _login_lp(lp_client, self.lp_user)
        failures = [
            f"{name or '(unnamed)'} {path} -> {r.status_code}"
            for name, path in lp_routes
            if (r := lp_client.get(path)).status_code != 200
        ]
        self.assertFalse(failures, "Learning Partner pages not rendering 200:\n" + "\n".join(failures))

        plain_admin_client = self._client_for(UserRole.ADMIN)
        failures = [
            f"{name or '(unnamed)'} {path} -> {r.status_code}"
            for name, path in lp_routes
            if (r := plain_admin_client.get(path)).status_code != 403
        ]
        self.assertFalse(
            failures,
            "Learning Partner pages not refused (403) for a plain admin:\n" + "\n".join(failures),
        )

    def test_finance_pages_render_only_for_finance_department(self):
        """
        /staff/admin/finance/* is guarded by role_required(..., department_
        slugs={"finance"}) - a Finance-department admin must get every page,
        and a plain admin (same role, ordinary department) must be cleanly
        refused. Mirrors test_learning_partner_pages_render_only_for_a_
        learning_partner above.
        """
        finance_routes = [
            (name, path) for name, path in _iter_routes() if path.startswith(_FINANCE_PREFIX)
        ]
        self.assertTrue(finance_routes, "no /staff/admin/finance/ routes were registered")

        finance_client = _fresh_client()
        resp = login(finance_client, self.finance_admin)
        self.assertIn(resp.status_code, (200, 202), f"login failed for finance admin: {resp.status_code}")
        failures = [
            f"{name or '(unnamed)'} {path} -> {r.status_code}"
            for name, path in finance_routes
            if (r := finance_client.get(path)).status_code != 200
        ]
        self.assertFalse(failures, "Finance pages not rendering 200:\n" + "\n".join(failures))

        plain_admin_client = self._client_for(UserRole.ADMIN)
        failures = [
            f"{name or '(unnamed)'} {path} -> {r.status_code}"
            for name, path in finance_routes
            if (r := plain_admin_client.get(path)).status_code != 403
        ]
        self.assertFalse(
            failures,
            "Finance pages not refused (403) for a plain admin:\n" + "\n".join(failures),
        )

    def test_support_pages_render_only_for_support_department(self):
        """
        /staff/admin/support/* is guarded by role_required(..., department_
        slugs={"support"}) - a Support-department admin must get every page,
        and a plain admin or a Finance admin must be cleanly refused.
        Mirrors test_finance_pages_render_only_for_finance_department above.
        """
        support_routes = [
            (name, path) for name, path in _iter_routes() if path.startswith(_SUPPORT_PREFIX)
        ]
        self.assertTrue(support_routes, "no /staff/admin/support/ routes were registered")

        support_client = _fresh_client()
        resp = login(support_client, self.support_admin)
        self.assertIn(resp.status_code, (200, 202), f"login failed for support admin: {resp.status_code}")
        failures = [
            f"{name or '(unnamed)'} {path} -> {r.status_code}"
            for name, path in support_routes
            if (r := support_client.get(path)).status_code != 200
        ]
        self.assertFalse(failures, "Support pages not rendering 200:\n" + "\n".join(failures))

        other_clients = {"plain admin": self._client_for(UserRole.ADMIN)}
        finance_client = _fresh_client()
        login(finance_client, self.finance_admin)
        other_clients["finance admin"] = finance_client
        for who, client in other_clients.items():
            failures = [
                f"{name or '(unnamed)'} {path} -> {r.status_code}"
                for name, path in support_routes
                if (r := client.get(path)).status_code != 403
            ]
            self.assertFalse(
                failures,
                f"Support pages not refused (403) for a {who}:\n" + "\n".join(failures),
            )

    def test_support_nav_is_narrow_and_every_link_resolves(self):
        """
        A Support admin gets its own sidebar (not the generic admin one): it
        must contain the Support screens, none of the removed sections, and
        every link in it must resolve to a registered page.
        """
        from django.urls import Resolver404, resolve

        from apps.web.nav import nav_for

        sections = nav_for("admin", self.support_admin)
        labels = {item["label"] for s in sections for item in s["items"]}
        self.assertTrue(
            {"Students", "Teachers", "Learning Partners", "Onboarding Calls", "Bug Calls", "Circulate a Message"}
            <= labels,
            labels,
        )
        removed = {
            "Users", "Bugs Reported", "Subjects", "Languages", "Grade Levels", "Locations",
            "Token Packages", "Subscription Plans", "Lead Pricing", "Config",
            "Subject Aliases", "Language Aliases", "Pincode Locations",
        }
        self.assertFalse(removed & labels, removed & labels)

        failures = []
        for s in sections:
            for item in s["items"]:
                try:
                    resolve(item["url"])
                except Resolver404:
                    failures.append(f"{item['label']!r} -> {item['url']}")
        self.assertFalse(failures, "Support nav items pointing at unregistered URLs:\n" + "\n".join(failures))

    def test_support_admin_lands_on_the_support_dashboard(self):
        from apps.web.guards import home_url_for

        self.assertEqual(home_url_for(self.support_admin), "/staff/admin/support/")
        # a departmentless admin keeps the generic admin dashboard
        self.assertEqual(home_url_for(self.users[UserRole.ADMIN]), "/staff/admin/")

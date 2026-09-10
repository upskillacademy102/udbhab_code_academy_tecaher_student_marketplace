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
from apps.accounts.tests.helpers import login, make_user
from apps.web import urls as web_urls

# A syntactically valid UUID that matches nothing. Detail pages render their
# shell regardless; the browser fetches the real record from the API.
DUMMY_UUID = "11111111-1111-1111-1111-111111111111"

# URL-prefix -> the role whose nav and guard own that page.
_PREFIX_ROLE = (
    ("student/", UserRole.STUDENT),
    ("teacher/", UserRole.TEACHER),
    ("admin-portal/", UserRole.ADMIN),
    ("super-admin/", UserRole.SUPERADMIN),
)

# Public pages: (path, needs_login). /suspended/ is behind login_required_web
# but has no role guard - any signed-in user renders it.
_PUBLIC = (
    ("/", False),
    ("/login/", False),
    ("/register/", False),
    ("/login/staff/", False),
    ("/suspended/", True),
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

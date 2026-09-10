"""
Security response headers must be present on every response - web pages,
API JSON, and error responses alike.

Run: python manage.py test apps.core.tests.test_security_headers \
     --settings=config.settings.test
"""

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from rest_framework.test import APITestCase

from apps.core.middleware.security_headers import (
    DEFAULT_CONTENT_SECURITY_POLICY,
    SecurityHeadersMiddleware,
)


class SecurityHeadersOnLiveResponsesTests(APITestCase):
    def _assert_hardened(self, response):
        csp = response.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri 'self'", csp)
        pp = response.headers.get("Permissions-Policy", "")
        self.assertIn("geolocation=()", pp)
        self.assertIn("microphone=()", pp)
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(
            response.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin"
        )

    def test_web_page_is_hardened(self):
        self._assert_hardened(self.client.get("/login/"))

    def test_api_success_is_hardened(self):
        self._assert_hardened(self.client.get("/api/v1/subjects/"))

    def test_api_auth_error_is_hardened(self):
        r = self.client.get("/api/v1/students/me/")  # 401 - no creds
        self.assertEqual(r.status_code, 401)
        self._assert_hardened(r)

    def test_404_is_hardened(self):
        self._assert_hardened(self.client.get("/this-path-does-not-exist/"))


class SecurityHeadersMiddlewareUnitTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def _run(self, settings_over=None):
        with self.settings(**(settings_over or {})):
            mw = SecurityHeadersMiddleware(lambda req: HttpResponse("ok"))
            return mw(self.rf.get("/"))

    def test_default_policy_applied(self):
        resp = self._run()
        self.assertEqual(
            resp.headers["Content-Security-Policy"], DEFAULT_CONTENT_SECURITY_POLICY
        )

    def test_custom_policy_overrides_default(self):
        resp = self._run({"CONTENT_SECURITY_POLICY": "default-src 'none'"})
        self.assertEqual(resp.headers["Content-Security-Policy"], "default-src 'none'")

    def test_report_only_mode_switches_header_name(self):
        resp = self._run({"CONTENT_SECURITY_POLICY_REPORT_ONLY": True})
        self.assertIn("Content-Security-Policy-Report-Only", resp.headers)
        self.assertNotIn("Content-Security-Policy", resp.headers)

    def test_does_not_clobber_an_explicit_downstream_csp(self):
        def view(req):
            r = HttpResponse("ok")
            r["Content-Security-Policy"] = "default-src 'self' example.com"
            return r

        mw = SecurityHeadersMiddleware(view)
        resp = mw(self.rf.get("/"))
        self.assertEqual(
            resp.headers["Content-Security-Policy"], "default-src 'self' example.com"
        )

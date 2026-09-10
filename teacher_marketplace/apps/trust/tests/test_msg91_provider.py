"""
MSG91SMSProvider - real-SMS adapter for OTP delivery. All HTTP calls are
mocked; no real network request is ever made from the test suite.

Run: python manage.py test apps.trust.tests.test_msg91_provider --settings=config.settings.test
"""

from unittest.mock import patch

import requests
from django.test import SimpleTestCase, override_settings

from apps.trust.providers.msg91 import MSG91SMSProvider, _to_msg91_mobile


class _Resp:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class MobileNumberNormalizationTests(SimpleTestCase):
    def test_bare_ten_digit_gets_india_code(self):
        self.assertEqual(_to_msg91_mobile("9876543210"), "919876543210")

    def test_leading_zero_stripped_and_india_code_added(self):
        self.assertEqual(_to_msg91_mobile("09876543210"), "919876543210")

    def test_plus_and_spaces_stripped(self):
        self.assertEqual(_to_msg91_mobile("+91 98765 43210"), "919876543210")

    def test_already_prefixed_left_alone(self):
        self.assertEqual(_to_msg91_mobile("919876543210"), "919876543210")


@override_settings(MSG91_AUTH_KEY="test-key", MSG91_TEMPLATE_ID="test-template")
class MSG91SendTests(SimpleTestCase):
    def test_not_configured_fails_without_calling_out(self):
        with override_settings(MSG91_AUTH_KEY="", MSG91_TEMPLATE_ID=""):
            with patch("apps.trust.providers.msg91.requests.post") as post:
                r = MSG91SMSProvider().send(to="9876543210", body="Your code is 123456")
        self.assertFalse(r.ok)
        post.assert_not_called()

    def test_success_extracts_code_and_normalizes_number(self):
        with patch("apps.trust.providers.msg91.requests.post") as post:
            post.return_value = _Resp({"type": "success", "request_id": "abc123"})
            r = MSG91SMSProvider().send(to="9876543210", body="Your code is 654321. Expires soon.")

        self.assertTrue(r.ok)
        self.assertEqual(r.reference, "abc123")
        _, kwargs = post.call_args
        self.assertEqual(kwargs["params"]["otp"], "654321")
        self.assertEqual(kwargs["params"]["mobile"], "919876543210")
        self.assertEqual(kwargs["params"]["authkey"], "test-key")
        self.assertEqual(kwargs["params"]["template_id"], "test-template")

    def test_vendor_error_response_is_a_clean_failure(self):
        with patch("apps.trust.providers.msg91.requests.post") as post:
            post.return_value = _Resp({"type": "error", "message": "invalid mobile number"})
            r = MSG91SMSProvider().send(to="9876543210", body="Your code is 111111")
        self.assertFalse(r.ok)
        self.assertIn("invalid mobile number", r.detail)

    def test_network_failure_is_a_clean_failure_not_an_exception(self):
        with patch(
            "apps.trust.providers.msg91.requests.post",
            side_effect=requests.ConnectionError("boom"),
        ):
            r = MSG91SMSProvider().send(to="9876543210", body="Your code is 111111")
        self.assertFalse(r.ok)

    def test_no_extractable_code_fails_without_calling_out(self):
        with patch("apps.trust.providers.msg91.requests.post") as post:
            r = MSG91SMSProvider().send(to="9876543210", body="no digits here")
        self.assertFalse(r.ok)
        post.assert_not_called()

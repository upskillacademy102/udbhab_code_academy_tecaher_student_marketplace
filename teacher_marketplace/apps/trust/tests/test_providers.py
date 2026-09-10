"""
Provider factory + dev-adapter behaviour.

Run: python manage.py test apps.trust.tests.test_providers --settings=config.settings.test
"""

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from apps.trust.providers import get_provider
from apps.trust.providers.base import (
    CaptchaProvider,
    ContentClassifierProvider,
    IDVerificationProvider,
    LivenessProvider,
    PennyDropProvider,
    PhoneReachabilityProvider,
    SMSProvider,
)
from apps.trust.providers.msg91 import MSG91SMSProvider
from apps.trust.providers.stub import FAIL_SENTINEL

_KIND_BASECLASS = {
    "sms": SMSProvider,
    "id": IDVerificationProvider,
    "liveness": LivenessProvider,
    "phone_reachability": PhoneReachabilityProvider,
    "penny_drop": PennyDropProvider,
    "captcha": CaptchaProvider,
    "content_classifier": ContentClassifierProvider,
}


class ProviderFactoryTests(SimpleTestCase):
    def test_every_kind_resolves_to_its_baseclass(self):
        for kind, base in _KIND_BASECLASS.items():
            self.assertIsInstance(get_provider(kind), base, kind)

    def test_unknown_kind_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            get_provider("nope")

    @override_settings(TRUST_SMS_PROVIDER="doesnotexist")
    def test_unknown_provider_name_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            get_provider("sms")

    @override_settings(TRUST_SMS_PROVIDER="msg91")
    def test_msg91_resolves_when_selected(self):
        self.assertIsInstance(get_provider("sms"), MSG91SMSProvider)


class DevAdapterBehaviourTests(SimpleTestCase):
    def test_console_sms_reports_success(self):
        r = get_provider("sms").send(to="919812345678", body="Your code is 123456")
        self.assertTrue(r.ok)

    def test_stub_phone_reachability_success_and_forced_failure(self):
        p = get_provider("phone_reachability")
        self.assertTrue(p.check(number="919812345678").ok)
        self.assertFalse(p.check(number=FAIL_SENTINEL).ok)

    def test_stub_captcha_success_and_forced_failure(self):
        p = get_provider("captcha")
        self.assertTrue(p.verify(token="solved").ok)
        self.assertFalse(p.verify(token="").ok)
        self.assertFalse(p.verify(token=FAIL_SENTINEL).ok)

    def test_manual_providers_ask_for_review(self):
        self.assertTrue(
            get_provider("id").verify(full_name="Ada Lovelace").needs_manual_review
        )
        self.assertTrue(
            get_provider("liveness").check(selfie_ref="x").needs_manual_review
        )
        self.assertTrue(
            get_provider("penny_drop")
            .verify(account_number="1", ifsc="X", expected_name="Y")
            .needs_manual_review
        )

    def test_regex_classifier_flags_contact_leakage(self):
        p = get_provider("content_classifier")
        self.assertTrue(p.classify(text="Great tutor, very patient.").ok)

        bad = p.classify(text="call me on 98765 43210 or pay me on GPay")
        self.assertFalse(bad.ok)
        self.assertIn("phone_number", bad.metadata["categories"])
        self.assertIn("payment_solicitation", bad.metadata["categories"])

    def test_regex_classifier_flags_upi_and_urls(self):
        p = get_provider("content_classifier")
        r = p.classify(text="my upi is john@okhdfcbank visit http://example.com/pay")
        self.assertFalse(r.ok)
        self.assertIn("upi_vpa", r.metadata["categories"])
        self.assertIn("external_url", r.metadata["categories"])

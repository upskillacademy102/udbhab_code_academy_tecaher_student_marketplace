"""
Duplicate-account detection.

Run: python manage.py test apps.trust.tests.test_dedupe --settings=config.settings.test
"""

from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import TEST_PASSWORD, login, make_user
from apps.trust.models import (
    DuplicateSignal,
    IdentitySignatureKind,
    ManualReviewItem,
    ManualReviewKind,
)
from apps.trust.services.dedupe_service import DedupeService
from apps.trust.services.trust_service import TrustService

REGISTER = "/api/v1/auth/register/"
UNLOCK = "/api/v1/leads/unlock/"


class NormalizationTests(TestCase):
    def test_phone_variants_collapse(self):
        n = DedupeService.normalize_phone
        self.assertEqual(n("+91 98765 43210"), n("09876543210"))
        self.assertEqual(n("919876543210"), n("9876543210"))

    def test_gmail_dot_plus_canonicalisation(self):
        n = DedupeService.normalize_email
        self.assertEqual(n("john.doe@gmail.com"), n("johndoe+spam@gmail.com"))
        self.assertEqual(n("J.O.H.N@googlemail.com"), "john@gmail.com")
        # non-gmail keeps dots
        self.assertNotEqual(n("a.b@outlook.com"), n("ab@outlook.com"))


class ScanTests(TestCase):
    def test_shared_phone_opens_a_signal_and_review_item(self):
        a = make_user(role=UserRole.STUDENT, email="a@x.test", mobile="919876543210")
        b = make_user(role=UserRole.TEACHER, email="b@x.test", mobile="09876543210")

        DedupeService.record_signature(
            a, kind=IdentitySignatureKind.PHONE, raw_value=a.mobile
        )
        DedupeService.record_signature(
            b, kind=IdentitySignatureKind.PHONE, raw_value=b.mobile
        )

        signals = DedupeService.scan(b)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].matched_user, a)
        self.assertTrue(
            ManualReviewItem.objects.filter(
                kind=ManualReviewKind.DUPLICATE_ACCOUNT, subject_user=b
            ).exists()
        )

    def test_no_collision_no_signal(self):
        a = make_user(role=UserRole.STUDENT, email="a@x.test", mobile="911111111111")
        b = make_user(role=UserRole.STUDENT, email="b@x.test", mobile="922222222222")
        DedupeService.record_signature(
            a, kind=IdentitySignatureKind.PHONE, raw_value=a.mobile
        )
        DedupeService.record_signature(
            b, kind=IdentitySignatureKind.PHONE, raw_value=b.mobile
        )
        self.assertEqual(DedupeService.scan(b), [])

    def test_device_collision(self):
        rf = RequestFactory()
        req = rf.post("/x", HTTP_USER_AGENT="same-agent", HTTP_ACCEPT="text/html")
        a = make_user(role=UserRole.STUDENT, email="a@x.test")
        b = make_user(role=UserRole.STUDENT, email="b@x.test")
        DedupeService.record_and_scan_device(a, request=req)
        signals = DedupeService.record_and_scan_device(b, request=req)
        self.assertTrue(any(s.kind == IdentitySignatureKind.DEVICE for s in signals))

    def test_scan_is_idempotent(self):
        a = make_user(email="a@x.test", mobile="919876543210")
        b = make_user(email="b@x.test", mobile="09876543210")
        for u in (a, b):
            DedupeService.record_signature(
                u, kind=IdentitySignatureKind.PHONE, raw_value=u.mobile
            )
        DedupeService.scan(b)
        DedupeService.scan(b)
        self.assertEqual(DuplicateSignal.objects.filter(user=b).count(), 1)


class BlockingTests(TestCase):
    def setUp(self):
        self.a = make_user(email="a@x.test", mobile="919876543210")
        self.b = make_user(email="b@x.test", mobile="09876543210")
        for u in (self.a, self.b):
            DedupeService.record_signature(
                u, kind=IdentitySignatureKind.PHONE, raw_value=u.mobile
            )
        DedupeService.scan(self.b)

    def test_blocking_off_by_default(self):
        self.assertFalse(DedupeService.is_blocked(self.b))

    @override_settings(TRUST_ENABLE_DEDUP_BLOCKING=True)
    def test_blocking_on(self):
        self.assertTrue(DedupeService.is_blocked(self.b))
        self.assertFalse(DedupeService.is_blocked(make_user(email="clean@x.test")))

    @override_settings(TRUST_ENABLE_DEDUP_BLOCKING=True)
    def test_resolving_the_review_item_unblocks(self):
        item = ManualReviewItem.objects.get(
            kind=ManualReviewKind.DUPLICATE_ACCOUNT, subject_user=self.b
        )
        TrustService.resolve_review_item(item, resolution="Verified different people.")
        self.assertFalse(DedupeService.is_blocked(self.b))


class GateTests(APITestCase):
    def setUp(self):
        self.a = make_user(
            role=UserRole.TEACHER, email="a@x.test", mobile="919876543210"
        )
        self.b = make_user(
            role=UserRole.TEACHER, email="b@x.test", mobile="09876543210"
        )
        for u in (self.a, self.b):
            DedupeService.record_signature(
                u, kind=IdentitySignatureKind.PHONE, raw_value=u.mobile
            )
        DedupeService.scan(self.b)

    def test_gate_off_by_default(self):
        login(self.client, self.b)
        self.assertNotEqual(
            self.client.post(UNLOCK, {}, format="json").status_code, 403
        )

    @override_settings(TRUST_ENABLE_DEDUP_BLOCKING=True)
    def test_gate_on_blocks_flagged_account(self):
        login(self.client, self.b)
        self.assertEqual(self.client.post(UNLOCK, {}, format="json").status_code, 403)

    @override_settings(TRUST_ENABLE_DEDUP_BLOCKING=True)
    def test_gate_on_allows_clean_account(self):
        clean = make_user(role=UserRole.TEACHER, email="clean@x.test")
        login(self.client, clean)
        self.assertNotEqual(
            self.client.post(UNLOCK, {}, format="json").status_code, 403
        )


class RegisterIntegrationTests(APITestCase):
    def test_registering_a_phone_variant_flags_the_new_account(self):
        first = make_user(
            role=UserRole.STUDENT, email="first@x.test", mobile="919876543210"
        )
        DedupeService.record_signature(
            first, kind=IdentitySignatureKind.PHONE, raw_value=first.mobile
        )
        payload = {
            "email": "second@x.test",
            "mobile": "09876543210",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
            "role": "student",
            "first_name": "Sec",
            "last_name": "Ond",
        }
        r = self.client.post(REGISTER, payload, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(
            ManualReviewItem.objects.filter(
                kind=ManualReviewKind.DUPLICATE_ACCOUNT,
                subject_user__email="second@x.test",
            ).exists()
        )

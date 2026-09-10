"""
TrustProfile auto-creation + TrustService basics.

Run: python manage.py test apps.trust.tests.test_trust_profile --settings=config.settings.test
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_user
from apps.trust.models import (
    ManualReviewKind,
    ManualReviewStatus,
    RiskState,
    TrustProfile,
)
from apps.trust.services.trust_service import TrustService


class TrustProfileLifecycleTests(TestCase):
    def test_profile_is_auto_created_for_every_new_user(self):
        u = make_user(role=UserRole.STUDENT)
        self.assertTrue(TrustProfile.objects.filter(user=u).exists())
        p = u.trust_profile
        self.assertEqual(p.verification_score, Decimal("0.000"))
        self.assertEqual(p.risk_state, RiskState.NORMAL)
        self.assertFalse(p.is_fully_verified)
        self.assertEqual(p.lead_quality_score, Decimal("1.000"))

    def test_get_or_create_is_idempotent(self):
        u = make_user(role=UserRole.TEACHER)
        a = TrustService.get_or_create_profile(u)
        b = TrustService.get_or_create_profile(u)
        self.assertEqual(a.pk, b.pk)

    def test_recompute_stamps_only(self):
        u = make_user()
        p = TrustService.recompute_verification_score(u)
        self.assertIsNotNone(p.verification_recomputed_at)
        p = TrustService.recompute_risk(u)
        self.assertIsNotNone(p.risk_recomputed_at)

    def test_score_range_check_constraint(self):
        u = make_user()
        p = u.trust_profile
        p.verification_score = Decimal("1.500")
        with self.assertRaises(IntegrityError), transaction.atomic():
            p.save(update_fields=["verification_score"])


class ManualReviewQueueTests(TestCase):
    def test_open_and_dedupe(self):
        u = make_user()
        a = TrustService.open_review_item(
            kind=ManualReviewKind.DUPLICATE_ACCOUNT,
            summary="Shares a phone with 2 other accounts",
            subject_user=u,
            dedupe_key=f"dupe:{u.id}",
        )
        b = TrustService.open_review_item(
            kind=ManualReviewKind.DUPLICATE_ACCOUNT,
            summary="Shares a phone with 3 other accounts",
            subject_user=u,
            dedupe_key=f"dupe:{u.id}",
        )
        self.assertEqual(a.pk, b.pk)  # deduped, not a second row

    def test_resolve(self):
        u = make_user()
        admin = make_user(role=UserRole.ADMIN)
        item = TrustService.open_review_item(
            kind=ManualReviewKind.CONTENT_FLAG,
            summary="Phone number in bio",
            subject_user=u,
        )
        TrustService.resolve_review_item(item, by=admin, resolution="Edited out.")
        item.refresh_from_db()
        self.assertEqual(item.status, ManualReviewStatus.RESOLVED)
        self.assertEqual(item.resolved_by, admin)
        self.assertIsNotNone(item.resolved_at)

    def test_dedupe_only_applies_while_open(self):
        u = make_user()
        first = TrustService.open_review_item(
            kind=ManualReviewKind.LEAD_QUALITY,
            summary="fake lead",
            subject_user=u,
            dedupe_key="lq:1",
        )
        TrustService.resolve_review_item(first, resolution="handled")
        second = TrustService.open_review_item(
            kind=ManualReviewKind.LEAD_QUALITY,
            summary="fake lead again",
            subject_user=u,
            dedupe_key="lq:1",
        )
        self.assertNotEqual(
            first.pk, second.pk
        )  # previous one resolved -> new row allowed

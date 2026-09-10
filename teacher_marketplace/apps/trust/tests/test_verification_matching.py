"""
Phase 5d: the verification FLOOR (who can receive leads) and the
verification-score RANKING BIAS - both feature-flagged, both no-ops by
default.

Run: python manage.py test apps.trust.tests.test_verification_matching \
     --settings=config.settings.test
"""

from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.lead_engine.tests.test_lead_pipeline import PipelineFixtureMixin
from apps.matching.services.lead_distribution_service import LeadDistributionService
from apps.teacher_profile.models import VerificationStatus


def _set_score(profile, value):
    tp = profile.teacher.user.trust_profile
    tp.verification_score = Decimal(value)
    tp.save(update_fields=["verification_score"])


def _make_floor_ready(mixin, name, **kw):
    p = mixin.make_teacher(name, verified=False, **kw)  # verification_status = PENDING
    t = p.teacher
    t.bio = "Experienced tutor."
    t.qualification_level = "bachelors"
    t.save(update_fields=["bio", "qualification_level"])
    t.user.is_email_verified = t.user.is_mobile_verified = True
    t.user.save(update_fields=["is_email_verified", "is_mobile_verified"])
    return p


def _eligible_ids(requirement):
    return [
        e["teacher_profile"].id
        for e in LeadDistributionService._get_eligible_teachers_with_scores(requirement)
    ]


class FloorOffTests(PipelineFixtureMixin, TestCase):
    """Default: only verification_status == VERIFIED teachers get leads."""

    def test_pending_teacher_with_the_field_floor_still_excluded(self):
        verified = self.make_teacher("Vera", verified=True)
        pending = _make_floor_ready(self, "Pam")
        ids = _eligible_ids(self.make_requirement())
        self.assertIn(verified.id, ids)
        self.assertNotIn(pending.id, ids)


@override_settings(TRUST_TEACHER_FLOOR_FOR_LEADS=True)
class FloorOnTests(PipelineFixtureMixin, TestCase):
    def test_floor_ready_pending_teacher_becomes_eligible(self):
        p = _make_floor_ready(self, "Anita")
        self.assertIn(p.id, _eligible_ids(self.make_requirement()))

    def test_teacher_missing_the_floor_is_excluded(self):
        p = self.make_teacher("Bea", verified=False)  # no verified contacts, no bio
        self.assertNotIn(p.id, _eligible_ids(self.make_requirement()))

    def test_rejected_teacher_excluded_even_when_floor_ready(self):
        p = _make_floor_ready(self, "Rhea")
        p.verification_status = VerificationStatus.REJECTED
        p.save(update_fields=["verification_status"])
        self.assertNotIn(p.id, _eligible_ids(self.make_requirement()))

    def test_admin_verified_teacher_with_unverified_contact_is_excluded(self):
        # Floor ON is strict: an old manual VERIFIED without verified contacts
        # no longer qualifies (this is the documented activation caveat).
        p = self.make_teacher("Old", verified=True)  # VERIFIED but contacts unverified
        self.assertNotIn(p.id, _eligible_ids(self.make_requirement()))


@override_settings(TRUST_VERIFICATION_SCORE_AFFECTS_RANKING=True)
class RankingBiasOnTests(PipelineFixtureMixin, TestCase):
    def test_more_verified_teacher_is_offered_first_within_a_tier(self):
        low = self.make_teacher("Low", rating="4.00", plan=self.free_plan)
        high = self.make_teacher("High", rating="4.00", plan=self.free_plan)
        _set_score(low, "0.200")
        _set_score(high, "0.900")

        eligible = LeadDistributionService._get_eligible_teachers_with_scores(
            self.make_requirement()
        )
        plan_map = LeadDistributionService._plans_for(eligible)
        tiers = LeadDistributionService._group_by_tier(eligible, plan_map)
        first_group = tiers[next(iter(tiers))]
        self.assertEqual(first_group[0]["teacher_profile"].id, high.id)


class RankingBiasOffTests(PipelineFixtureMixin, TestCase):
    def test_score_does_not_reorder_when_flag_off(self):
        # Same rating; without the bias the deterministic tiebreak (experience,
        # then created_at) decides - NOT the verification score.
        a = self.make_teacher("Aaa", rating="4.00", experience=9, plan=self.free_plan)
        b = self.make_teacher("Bbb", rating="4.00", experience=3, plan=self.free_plan)
        _set_score(a, "0.100")
        _set_score(b, "0.950")  # b is more verified but the flag is off

        eligible = LeadDistributionService._get_eligible_teachers_with_scores(
            self.make_requirement()
        )
        plan_map = LeadDistributionService._plans_for(eligible)
        tiers = LeadDistributionService._group_by_tier(eligible, plan_map)
        first_group = tiers[next(iter(tiers))]
        self.assertEqual(
            first_group[0]["teacher_profile"].id, a.id
        )  # more experience wins


@override_settings(
    TRUST_TEACHER_FLOOR_FOR_LEADS=True, TRUST_VERIFICATION_SCORE_AFFECTS_RANKING=True
)
class SearchIntegrationTests(PipelineFixtureMixin, APITestCase):
    def test_search_uses_the_floor_and_the_bias(self):
        floor_ready = _make_floor_ready(self, "Fiona")
        _set_score(floor_ready, "0.300")
        fully = _make_floor_ready(self, "Grace")
        _set_score(fully, "1.000")
        self.make_teacher("Nadia", verified=True)  # unverified contacts: below floor

        login(self.client, make_user(role=UserRole.STUDENT))
        r = self.client.get("/api/v1/search/teachers/", {"subject": "Mathematics"})
        self.assertEqual(r.status_code, 200, r.content)
        blob = str(r.json()["data"])
        self.assertIn("Fiona", blob)
        self.assertIn("Grace", blob)
        self.assertNotIn("Nadia", blob)  # excluded by the floor

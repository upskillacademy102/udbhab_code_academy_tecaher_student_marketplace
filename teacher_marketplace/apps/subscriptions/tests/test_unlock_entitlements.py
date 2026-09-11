"""
Regression tests for the unlock-allowance model (approved 2026-09-09).

Covers the rules that replaced the variable-cost token economy while
settings.TOKEN_SYSTEM_ENABLED is False:

  * a plan's allowance is a rolling 30-day cycle, not a calendar month, and
    it shares one clock with the subscription's billing window;
  * unused allowance does not carry over, but usage carries forward across
    an early resubscribe so a cancel/resubscribe cannot mint a second
    allowance inside one cycle;
  * every lead costs exactly one unlock regardless of its category;
  * purchased top-ups grant volume only - never search priority - and are
    sold to, and spendable only on, paid plans;
  * a corroborated fake lead refunds the teacher even when the unlock came
    out of the plan allowance rather than the purchased balance.

Run: python manage.py test apps.subscriptions.tests.test_unlock_entitlements \
     --settings=config.settings.test
"""

from datetime import timedelta

from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.lead_engine.models import Lead, LeadUnlockHistory
from apps.lead_engine.tests.test_lead_pipeline import PipelineFixtureMixin
from apps.lead_engine.unlock_service import (
    UnlockAllowanceExhausted,
    get_unlock_token_cost,
    unlock_lead_contact,
)
from apps.matching.services.token_priority_service import TokenPriorityService
from apps.payments.models import TokenPackage
from apps.subscriptions.models import MonthlyLeadQuota
from apps.subscriptions.services import LeadQuotaService, SubscriptionService
from apps.wallet.services import WalletService

CYCLE = timedelta(days=settings.LEAD_UNLOCK_CYCLE_DAYS)


class AllowancePeriodTests(PipelineFixtureMixin, APITestCase):
    """The 30-day cycle, its anchor, and how periods chain."""

    def setUp(self):
        self.profile = self.make_teacher("Priya", plan=self.pro_plan)
        self.teacher = self.profile.teacher

    def test_period_is_thirty_days_not_a_calendar_month(self):
        start, end = LeadQuotaService.resolve_period(self.teacher)
        self.assertEqual(end - start, CYCLE)

    def test_period_is_anchored_to_the_subscription_not_the_month(self):
        subscription = SubscriptionService.get_active_subscription(self.teacher)
        start, _end = LeadQuotaService.resolve_period(self.teacher)
        self.assertEqual(start, subscription.start_date)
        # Emphatically not the first of the calendar month.
        self.assertNotEqual((start.day, start.hour), (1, 0))

    def test_allowance_resets_once_the_cycle_elapses(self):
        quota = LeadQuotaService.get_or_create_current_quota(self.teacher)
        quota.used_free_leads = quota.total_free_leads
        quota.save(update_fields=["used_free_leads"])
        self.assertFalse(LeadQuotaService.has_free_leads_remaining(self.teacher))

        # Backdate the whole period so "now" sits after it.
        MonthlyLeadQuota.objects.filter(pk=quota.pk).update(
            period_start=quota.period_start - CYCLE,
            period_end=quota.period_end - CYCLE,
        )
        self.assertTrue(LeadQuotaService.has_free_leads_remaining(self.teacher))
        fresh = LeadQuotaService.get_or_create_current_quota(self.teacher)
        self.assertEqual(fresh.used_free_leads, 0)
        self.assertEqual(fresh.total_free_leads, self.pro_plan.free_leads)

    def test_periods_chain_from_the_anchor_not_from_when_you_log_back_in(self):
        """
        A teacher who ignores the platform for months comes back to a window
        still aligned with their original anchor, so billing and allowance
        never drift apart.
        """
        quota = LeadQuotaService.get_or_create_current_quota(self.teacher)
        anchor_start = quota.period_start
        MonthlyLeadQuota.objects.filter(pk=quota.pk).update(
            period_start=anchor_start - 3 * CYCLE,
            period_end=anchor_start - 2 * CYCLE,
        )

        start, end = LeadQuotaService.resolve_period(self.teacher)
        self.assertEqual(end - start, CYCLE)
        # Still a whole number of cycles away from the original anchor.
        offset = start - (anchor_start - 3 * CYCLE)
        self.assertEqual(offset % CYCLE, timedelta(0))


class ResubscribeFarmingTests(PipelineFixtureMixin, APITestCase):
    """
    The rule that stops subscribe -> spend -> cancel -> resubscribe minting a
    second allowance inside one cycle.
    """

    def setUp(self):
        self.profile = self.make_teacher("Rahul", plan=None)
        self.teacher = self.profile.teacher

    def _spend(self, n):
        quota = LeadQuotaService.get_or_create_current_quota(self.teacher)
        quota.used_free_leads = n
        quota.save(update_fields=["used_free_leads"])

    def test_resubscribing_mid_cycle_carries_usage_forward(self):
        SubscriptionService.subscribe(self.teacher, self.elite_plan)
        self._spend(self.elite_plan.free_leads)  # burn all 40

        # Cancel and immediately resubscribe - the classic farming attempt.
        SubscriptionService.subscribe(self.teacher, self.elite_plan)

        quota = LeadQuotaService.get_or_create_current_quota(self.teacher)
        self.assertEqual(quota.total_free_leads, self.elite_plan.free_leads)
        self.assertEqual(quota.used_free_leads, self.elite_plan.free_leads)
        self.assertEqual(quota.remaining_free_leads, 0)

    def test_renewal_after_the_cycle_elapses_starts_clean(self):
        SubscriptionService.subscribe(self.teacher, self.pro_plan)
        self._spend(self.pro_plan.free_leads)

        # Age the period out, then renew - this is paying again, not farming.
        MonthlyLeadQuota.objects.filter(teacher=self.teacher).update(
            period_start=timezone.now() - 2 * CYCLE,
            period_end=timezone.now() - CYCLE,
        )
        SubscriptionService.subscribe(self.teacher, self.pro_plan)

        quota = LeadQuotaService.get_or_create_current_quota(self.teacher)
        self.assertEqual(quota.used_free_leads, 0)
        self.assertEqual(quota.remaining_free_leads, self.pro_plan.free_leads)

    def test_upgrade_mid_cycle_raises_the_allowance_and_keeps_usage(self):
        SubscriptionService.subscribe(self.teacher, self.pro_plan)
        self._spend(3)
        SubscriptionService.subscribe(self.teacher, self.elite_plan)

        quota = LeadQuotaService.get_or_create_current_quota(self.teacher)
        self.assertEqual(quota.total_free_leads, self.elite_plan.free_leads)
        self.assertEqual(quota.used_free_leads, 3)
        self.assertEqual(quota.remaining_free_leads, self.elite_plan.free_leads - 3)

    def test_downgrade_does_not_hand_unlocks_back(self):
        SubscriptionService.subscribe(self.teacher, self.elite_plan)
        self._spend(self.elite_plan.free_leads)
        SubscriptionService.subscribe(self.teacher, self.pro_plan)

        quota = LeadQuotaService.get_or_create_current_quota(self.teacher)
        self.assertEqual(quota.remaining_free_leads, 0)

    def test_subscribing_credits_no_bonus_tokens(self):
        """
        The former signup bonus is folded into the recurring allowance, so a
        subscribe must not also credit the wallet - that would pay it twice.
        """
        self.pro_plan.bonus_tokens = 20  # even if a plan row still carries one
        self.pro_plan.save(update_fields=["bonus_tokens"])

        SubscriptionService.subscribe(self.teacher, self.pro_plan)
        self.assertEqual(WalletService.get_balance(self.teacher), 0)


class FixedUnlockCostTests(PipelineFixtureMixin, APITestCase):
    """Every lead is worth exactly one unlock, whatever its category."""

    def test_cost_is_one_regardless_of_student_class(self):
        profile = self.make_teacher("Sana", plan=self.pro_plan)
        # Categories that priced differently under the token economy: school
        # tuition, competitive exams, corporate. All worth 1 unlock now.
        # (A blank student_class is rejected by a CHECK constraint, so the
        # tier-inference fallback is not reachable through a saved row.)
        for student_class in ("Grade 6", "JEE Aspirant", "Corporate professional"):
            req = self.make_requirement(student=make_user(role=UserRole.STUDENT))
            req.student_class = student_class
            req.save(update_fields=["student_class"])
            lead = Lead.objects.create(
                student_requirement=req, teacher_profile=profile
            )
            self.assertEqual(
                get_unlock_token_cost(lead),
                1,
                f"{student_class!r} should still cost exactly 1 unlock",
            )

    @override_settings(TOKEN_SYSTEM_ENABLED=True)
    def test_token_mode_still_prices_by_category(self):
        """The dormant path must stay intact so re-enabling is a flag flip."""
        profile = self.make_teacher("Tara", plan=self.pro_plan)
        req = self.make_requirement(student=make_user(role=UserRole.STUDENT))
        req.student_class = "JEE Aspirant"
        req.save(update_fields=["student_class"])
        lead = Lead.objects.create(student_requirement=req, teacher_profile=profile)
        self.assertGreater(get_unlock_token_cost(lead), 1)


class TopUpsGrantVolumeNotPriorityTests(PipelineFixtureMixin, APITestCase):
    def test_token_priority_is_neutralised(self):
        profile = self.make_teacher("Uma", plan=self.elite_plan, tokens=500)
        self.assertEqual(TokenPriorityService.get_token_balance(profile.teacher), 0)

    @override_settings(TOKEN_SYSTEM_ENABLED=True)
    def test_token_priority_returns_again_in_token_mode(self):
        profile = self.make_teacher("Vik", plan=self.elite_plan, tokens=500)
        self.assertEqual(TokenPriorityService.get_token_balance(profile.teacher), 500)


class TopUpPurchaseTests(PipelineFixtureMixin, APITestCase):
    """
    Every plan can buy extra unlocks, Free included. Packs sell capacity;
    only the subscription sells priority.
    """

    def setUp(self):
        self.pack = TokenPackage.objects.get(name="5 extra unlocks")

    def _order_as(self, profile):
        login(self.client, profile.teacher.user)
        return self.client.post(
            "/api/v1/payments/create-order/",
            {"token_package_id": str(self.pack.id)},
            format="json",
        )

    def test_free_teacher_can_buy(self):
        resp = self._order_as(self.make_teacher("Free1", plan=None))
        # Razorpay is unconfigured in tests, so reaching the provider (503) is
        # how "the gate let this through" shows up. What matters is that it is
        # not the TOPUP_REQUIRES_PAID_PLAN 400.
        self.assertNotEqual(resp.status_code, 400, resp.content)

    def test_paid_teacher_can_buy(self):
        resp = self._order_as(self.make_teacher("Paid1", plan=self.pro_plan))
        self.assertNotEqual(resp.status_code, 400, resp.content)

    def test_catalogue_is_purchasable_for_a_free_teacher(self):
        login(self.client, self.make_teacher("Free2", plan=None).teacher.user)
        rows = self.client.get("/api/v1/token-packages/").json()["data"]
        rows = rows["results"] if isinstance(rows, dict) else rows
        self.assertTrue(rows)
        self.assertTrue(all(r["can_purchase"] is True for r in rows))

    @override_settings(TOPUP_ELIGIBLE_PLANS=["Professional", "Elite"])
    def test_the_paid_only_fence_can_be_restored_by_settings_alone(self):
        """
        Re-gating top-ups must stay a settings change, not a code change - so
        the fence and its error code are kept even though nothing trips them
        in the current configuration.
        """
        resp = self._order_as(self.make_teacher("Free3", plan=None))
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["error"]["code"], "TOPUP_REQUIRES_PAID_PLAN")

    def test_buying_unlocks_never_buys_priority(self):
        """
        A Free teacher loaded with purchased unlocks still sits in the Free
        tier of the distribution cascade - capacity, never priority.
        """
        from apps.matching.services.subscription_priority_service import (
            SubscriptionPriorityService,
        )

        loaded = self.make_teacher("Loaded", plan=None, tokens=500)
        broke = self.make_teacher("Broke", plan=None)
        self.assertEqual(
            SubscriptionPriorityService.get_priority_rank(loaded.teacher),
            SubscriptionPriorityService.get_priority_rank(broke.teacher),
        )
        # And a paid teacher still outranks both.
        paid = self.make_teacher("Paid2", plan=self.elite_plan)
        self.assertLess(
            SubscriptionPriorityService.get_priority_rank(paid.teacher),
            SubscriptionPriorityService.get_priority_rank(loaded.teacher),
        )

    def test_plan_allowances_advertise_their_bonus_split(self):
        self.assertEqual((self.free_plan.free_leads, self.free_plan.bonus_leads), (4, 0))
        self.assertEqual((self.pro_plan.free_leads, self.pro_plan.bonus_leads), (10, 2))
        self.assertEqual((self.elite_plan.free_leads, self.elite_plan.bonus_leads), (40, 5))
        # base + bonus == total; the bonus is a slice, never an addition.
        for plan in (self.free_plan, self.pro_plan, self.elite_plan):
            self.assertEqual(plan.base_leads + plan.bonus_leads, plan.free_leads)

    def test_seeded_packs_are_gst_inclusive_at_the_advertised_price(self):
        single = TokenPackage.objects.get(name="1 extra unlock")
        self.assertEqual(single.token_count, 1)
        self.assertEqual(str(single.final_price), "15.00")
        # Repriced to Rs.60 by payments/0008. Unlike Rs.49, Rs.60 lands
        # exactly on a two-decimal base (50.85 * 1.18 = 60.0030 -> 60.00),
        # so there is no paisa-under fudge here.
        self.assertEqual(self.pack.token_count, 5)
        self.assertEqual(str(self.pack.final_price), "60.00")

    def test_every_plan_including_free_may_buy_top_ups(self):
        """
        Packs sell CAPACITY to everyone; the subscription sells PRIORITY.

        The priority half is covered by the cascade test above - this one
        pins the eligibility half, which the UI reads via
        TokenPackageSerializer.can_purchase.
        """
        from apps.payments.views import teacher_can_buy_topups

        free = self.make_teacher("FreeBuyer", plan=self.free_plan)
        paid = self.make_teacher("PaidBuyer", plan=self.elite_plan)

        self.assertTrue(teacher_can_buy_topups(free.teacher))
        self.assertTrue(teacher_can_buy_topups(paid.teacher))


class AllowanceClawbackTests(PipelineFixtureMixin, APITestCase):
    """
    The bug this model surfaced: _clawback used to filter on
    is_free_unlock=False AND tokens_deducted > 0. Under the allowance model
    almost every unlock is an allowance unlock (True / 0), so that filter
    matched nothing and the gate silently refunded nobody.
    """

    @override_settings(
        TRUST_ENABLE_LEAD_QUALITY_CLAWBACK=True, TRUST_LEAD_QUALITY_CORROBORATION=2
    )
    def test_corroborated_fakes_refund_an_allowance_unlock(self):
        from apps.trust.models import LeadQualityVerdict
        from apps.trust.services.lead_quality_service import LeadQualityService

        student = make_user(role=UserRole.STUDENT)
        req = self.make_requirement(student=student)

        teachers = []
        for name in ("Wanda", "Xena"):
            profile = self.make_teacher(name, plan=self.pro_plan)
            lead = Lead.objects.create(
                student_requirement=req, teacher_profile=profile
            )
            result = unlock_lead_contact(profile.teacher, lead)
            # Came out of the plan allowance, so it cost zero tokens...
            self.assertTrue(result.is_free_unlock)
            self.assertEqual(result.tokens_deducted, 0)
            self.assertEqual(WalletService.get_balance(profile.teacher), 0)
            teachers.append((profile.teacher, lead))

        for teacher, lead in teachers:
            LeadQualityService.rate(
                teacher=teacher, lead=lead, verdict=LeadQualityVerdict.FAKE
            )

        # ...and is still refunded, into the never-expiring purchased bucket.
        for teacher, _lead in teachers:
            self.assertEqual(
                WalletService.get_balance(teacher),
                1,
                "an allowance unlock on a corroborated fake lead must refund",
            )

    @override_settings(
        TRUST_ENABLE_LEAD_QUALITY_CLAWBACK=True, TRUST_LEAD_QUALITY_CORROBORATION=2
    )
    def test_a_single_complaint_refunds_nobody(self):
        """Corroboration is what stops a teacher self-serving a refund."""
        from apps.trust.models import LeadQualityVerdict
        from apps.trust.services.lead_quality_service import LeadQualityService

        student = make_user(role=UserRole.STUDENT)
        req = self.make_requirement(student=student)
        profile = self.make_teacher("Yash", plan=self.pro_plan)
        lead = Lead.objects.create(student_requirement=req, teacher_profile=profile)
        unlock_lead_contact(profile.teacher, lead)

        LeadQualityService.rate(
            teacher=profile.teacher, lead=lead, verdict=LeadQualityVerdict.FAKE
        )
        self.assertEqual(WalletService.get_balance(profile.teacher), 0)


class SpendOrderTests(PipelineFixtureMixin, APITestCase):
    """Allowance burns before the purchased balance - it is the bucket that expires."""

    def test_allowance_is_spent_before_purchased_unlocks(self):
        profile = self.make_teacher("Zoya", plan=self.pro_plan, tokens=10)
        teacher = profile.teacher

        req = self.make_requirement(student=make_user(role=UserRole.STUDENT))
        lead = Lead.objects.create(student_requirement=req, teacher_profile=profile)
        result = unlock_lead_contact(teacher, lead)

        self.assertTrue(result.is_free_unlock)
        self.assertEqual(WalletService.get_balance(teacher), 10)  # untouched
        self.assertEqual(
            LeadQuotaService.get_or_create_current_quota(teacher).used_free_leads, 1
        )

    def test_purchased_balance_takes_over_once_the_allowance_is_gone(self):
        profile = self.make_teacher("Amir", plan=self.pro_plan, tokens=10)
        teacher = profile.teacher
        quota = LeadQuotaService.get_or_create_current_quota(teacher)
        quota.used_free_leads = quota.total_free_leads
        quota.save(update_fields=["used_free_leads"])

        req = self.make_requirement(student=make_user(role=UserRole.STUDENT))
        lead = Lead.objects.create(student_requirement=req, teacher_profile=profile)
        result = unlock_lead_contact(teacher, lead)

        self.assertFalse(result.is_free_unlock)
        self.assertEqual(result.tokens_deducted, 1)
        self.assertEqual(WalletService.get_balance(teacher), 9)
        self.assertEqual(
            LeadUnlockHistory.objects.filter(teacher=teacher).count(), 1
        )

    def test_exhausted_teacher_is_told_when_the_allowance_resets(self):
        profile = self.make_teacher("Bela", plan=self.pro_plan)
        teacher = profile.teacher
        quota = LeadQuotaService.get_or_create_current_quota(teacher)
        quota.used_free_leads = quota.total_free_leads
        quota.save(update_fields=["used_free_leads"])

        req = self.make_requirement(student=make_user(role=UserRole.STUDENT))
        lead = Lead.objects.create(student_requirement=req, teacher_profile=profile)

        with self.assertRaises(UnlockAllowanceExhausted) as ctx:
            unlock_lead_contact(teacher, lead)
        message = str(ctx.exception.detail)
        self.assertIn("resets", message)
        self.assertIn(str(self.pro_plan.free_leads), message)
        lead.refresh_from_db()
        self.assertFalse(lead.contact_unlocked)

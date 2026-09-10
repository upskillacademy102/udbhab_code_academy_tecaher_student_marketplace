"""
Subscription service layer for the Teacher Marketplace Platform.

SubscriptionService handles the subscribe/renew workflow: creating
a new TeacherSubscription row (never mutating an old one, per the
model's history-via-append-only design), expiring any previous
active subscription, and crediting bonus_tokens via WalletService
if the plan grants any.

LeadQuotaService handles the allowance side: resolving the teacher's
current entitlement period, lazily creating its MonthlyLeadQuota row,
and the decrement the unlock workflow performs. Kept in this app (not
lead_engine) since allowance tracking is fundamentally subscription
data, even though lead_engine's unlock workflow is the primary caller.

ONE CLOCK (2026-09-09): a period is a rolling
settings.LEAD_UNLOCK_CYCLE_DAYS (30) days, not a calendar month, and a
subscription's billing window is the same window. See
LeadQuotaService.resolve_period for how the anchor is chosen and
SubscriptionService.subscribe for the plan-change rules that stop a
teacher minting a fresh allowance by resubscribing.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.subscriptions.models import (
    MonthlyLeadQuota,
    PlanStatus,
    SubscriptionPlan,
    SubscriptionStatus,
    TeacherSubscription,
)
from apps.wallet.services import WalletService

logger = logging.getLogger("apps.subscriptions")


class SubscriptionService:

    @staticmethod
    @transaction.atomic
    def subscribe(teacher, plan: SubscriptionPlan, payment=None) -> TeacherSubscription:
        """
        Subscribes a teacher to the given plan, starting now.

        Expires any currently-active subscription first (a teacher has
        exactly one active subscription at a time), creates the new
        TeacherSubscription row, and opens a fresh entitlement period
        carrying the new plan's allowance.

        BILLING AND ALLOWANCE SHARE ONE WINDOW: end_date is
        start_date + LEAD_UNLOCK_CYCLE_DAYS (30 days), not a calendar
        month, and the MonthlyLeadQuota row opened here uses exactly the
        same bounds - so a renewal and an allowance reset can never drift
        apart.

        USAGE CARRIES ACROSS AN EARLY RESUBSCRIBE. Subscribing while the
        previous period is still running (an upgrade, or a cancel-and-
        resubscribe) starts a fresh 30-day window at the new plan's
        allowance but carries the usage already spent forward. Without
        that carry, a teacher could subscribe to Elite, spend all 40
        unlocks, cancel, resubscribe and mint another 40 inside the same
        month. Once the previous period has genuinely elapsed, usage
        resets to zero - that is an ordinary renewal, not farming.

        bonus_tokens is skipped entirely while TOKEN_SYSTEM_ENABLED is
        False: the signup bonus that used to arrive as wallet tokens is
        now folded into the plan's recurring monthly allowance
        (Professional 8+2 = 10, Elite 35+5 = 40).
        """
        if plan.status != PlanStatus.ACTIVE:
            raise ValidationException(
                detail="This subscription plan is not currently available."
            )

        # Expire any existing active subscription for this teacher.
        TeacherSubscription.objects.filter(
            teacher=teacher, status=SubscriptionStatus.ACTIVE
        ).update(status=SubscriptionStatus.CANCELLED)

        start_date = timezone.now()
        end_date = start_date + timedelta(days=settings.LEAD_UNLOCK_CYCLE_DAYS)

        subscription = TeacherSubscription.objects.create(
            teacher=teacher,
            plan=plan,
            status=SubscriptionStatus.ACTIVE,
            start_date=start_date,
            end_date=end_date,
            payment=payment,
        )

        if plan.bonus_tokens > 0 and settings.TOKEN_SYSTEM_ENABLED:
            WalletService.credit(
                teacher=teacher,
                amount=plan.bonus_tokens,
                description=f"Bonus tokens - {plan.name} subscription",
                reference_id=str(subscription.id),
            )

        # Open the new period on exactly the subscription's window,
        # carrying forward any allowance already spent in a period that
        # has not yet elapsed.
        LeadQuotaService.open_period(
            teacher,
            plan=plan,
            period_start=start_date,
            period_end=end_date,
        )

        logger.info(
            "Teacher %s subscribed to plan %s (allowance=%d, period %s -> %s)",
            teacher.user.email,
            plan.name,
            plan.free_leads,
            start_date.date(),
            end_date.date(),
        )
        from apps.notifications.services import NotificationService

        # Best-effort: a notification/email failure must never break an
        # otherwise-successful subscription activation.
        try:
            NotificationService.subscription_activated(subscription)
        except Exception:  # noqa: BLE001
            logger.exception(
                "subscription_activated notification failed for %s (subscription still active)",
                teacher.user.email,
            )
        return subscription

    @staticmethod
    def renew(teacher) -> TeacherSubscription:
        """
        Renews a teacher's current plan for another month - creates
        a fresh TeacherSubscription row on the SAME plan they're
        already on. Raises if the teacher has no subscription to
        renew (they should call subscribe() for a first-time
        subscription instead).
        """
        current = SubscriptionService.get_active_subscription(teacher)
        if current is None:
            raise ValidationException(
                detail="No active subscription to renew. Subscribe to a plan first."
            )
        return SubscriptionService.subscribe(teacher, current.plan)

    @staticmethod
    def get_active_subscription(teacher):
        """
        Returns the teacher's current ACTIVE TeacherSubscription, or
        None if they have none (e.g. never subscribed, or their
        last subscription expired without renewal).
        """
        return (
            TeacherSubscription.objects.filter(
                teacher=teacher, status=SubscriptionStatus.ACTIVE
            )
            .select_related("plan")
            .order_by("-created_at")
            .first()
        )

    @staticmethod
    def get_effective_plan(teacher) -> SubscriptionPlan:
        """
        Returns the plan that should apply to this teacher right
        now: their active subscription's plan if they have one and
        it hasn't passed end_date, otherwise falls back to the
        platform's Free plan. Every teacher effectively has SOME
        plan at all times - there's no "no plan" state from the
        unlock workflow's perspective.
        """
        subscription = SubscriptionService.get_active_subscription(teacher)
        if subscription is not None and subscription.is_active_now:
            return subscription.plan

        return SubscriptionService._free_plan_or_raise()

    @staticmethod
    def _free_plan_or_raise() -> SubscriptionPlan:
        free_plan = SubscriptionPlan.objects.filter(name__iexact="Free").first()
        if free_plan is None:
            raise ValidationException(
                detail="No Free plan is configured. Contact platform support."
            )
        return free_plan

    @staticmethod
    def get_effective_plans(teachers) -> dict:
        """
        Batch form of get_effective_plan: resolve the effective plan for
        many teachers in a FIXED number of queries (one for the active
        subscriptions, at most one for the Free fallback), instead of
        2 queries per teacher.

        Args:
            teachers: an iterable of Teacher instances or teacher ids.

        Returns:
            {teacher_id: SubscriptionPlan} covering every id passed in.
        """
        teacher_ids = [getattr(t, "id", t) for t in teachers]
        if not teacher_ids:
            return {}

        active_by_teacher = {}
        rows = (
            TeacherSubscription.objects.filter(
                teacher_id__in=teacher_ids,
                status=SubscriptionStatus.ACTIVE,
                end_date__gt=timezone.now(),
            )
            .select_related("plan")
            .order_by("teacher_id", "-created_at")
        )
        for sub in rows:
            # first row per teacher wins (newest, thanks to the ordering)
            active_by_teacher.setdefault(sub.teacher_id, sub.plan)

        free_plan = None
        result = {}
        for tid in teacher_ids:
            plan = active_by_teacher.get(tid)
            if plan is None:
                if free_plan is None:
                    free_plan = SubscriptionService._free_plan_or_raise()
                plan = free_plan
            result[tid] = plan
        return result


class LeadQuotaService:
    """
    Owns the teacher's plan allowance: which entitlement period we are in,
    how much of it is spent, and the decrement the unlock workflow performs.

    Purchased top-up unlocks are NOT tracked here - they live in the
    teacher's Wallet because they never expire while this allowance resets
    every LEAD_UNLOCK_CYCLE_DAYS. apps.lead_engine.unlock_service spends
    this allowance first and the purchased balance second.
    """

    @staticmethod
    def _cycle() -> timedelta:
        return timedelta(days=settings.LEAD_UNLOCK_CYCLE_DAYS)

    @staticmethod
    def _latest_row(teacher) -> MonthlyLeadQuota:
        return (
            MonthlyLeadQuota.objects.filter(teacher=teacher)
            .order_by("-period_start")
            .first()
        )

    @staticmethod
    def resolve_period(teacher) -> tuple:
        """
        Returns (period_start, period_end) for the entitlement window that
        contains right now.

        Periods CHAIN off the teacher's original anchor rather than
        restarting from whenever they next happen to load a page: after a
        window elapses, the next one begins at the previous period_end plus
        however many whole cycles have passed since. A teacher who ignores
        the platform for three months therefore comes back to a window whose
        boundaries still line up with their subscription's, not one anchored
        to the moment they logged back in.

        With no history at all the anchor is the active subscription's
        start_date, falling back to the teacher's own created_at - a stable
        per-teacher value either way, so the reset date never depends on
        when the row first happened to be touched.
        """
        now = timezone.now()
        cycle = LeadQuotaService._cycle()

        latest = LeadQuotaService._latest_row(teacher)
        if latest is not None:
            if latest.period_start <= now < latest.period_end:
                return latest.period_start, latest.period_end
            if latest.period_start > now:
                # Future-dated row (backdated fixture, or clock skew between
                # app servers). Its own window is still the authority.
                return latest.period_start, latest.period_end
            elapsed = (now - latest.period_end) // cycle
            start = latest.period_end + (elapsed * cycle)
            return start, start + cycle

        subscription = SubscriptionService.get_active_subscription(teacher)
        if subscription is not None:
            anchor = subscription.start_date
        else:
            anchor = getattr(teacher, "created_at", None) or now
        if anchor > now:
            anchor = now

        elapsed = (now - anchor) // cycle
        start = anchor + (elapsed * cycle)
        return start, start + cycle

    @staticmethod
    @transaction.atomic
    def open_period(
        teacher, *, plan: SubscriptionPlan, period_start, period_end
    ) -> MonthlyLeadQuota:
        """
        Opens an entitlement period on an explicit window at `plan`'s
        allowance. Called by SubscriptionService.subscribe so the billing
        window and the allowance window are literally the same dates.

        Usage already spent inside a period that has NOT yet elapsed carries
        forward into the new row - this is what stops subscribe / spend /
        cancel / resubscribe minting a second allowance inside one cycle.
        Once the old period has genuinely run out, nothing carries and the
        teacher starts clean, which is an ordinary renewal.

        Carried usage is deliberately not clamped to the new allowance: a
        teacher who spent 40 on Elite and drops to Professional's 10 sits at
        zero remaining, rather than being handed unlocks back for
        downgrading.
        """
        now = timezone.now()
        previous = LeadQuotaService._latest_row(teacher)
        carried_used = (
            previous.used_free_leads
            if previous is not None and previous.period_end > now
            else 0
        )

        quota, _created = MonthlyLeadQuota.objects.update_or_create(
            teacher=teacher,
            period_start=period_start,
            defaults={
                "period_end": period_end,
                "total_free_leads": plan.free_leads,
                "used_free_leads": carried_used,
            },
        )
        if carried_used:
            logger.info(
                "Teacher %s changed plan mid-period - carried %d used unlock(s) forward.",
                teacher.user.email,
                carried_used,
            )
        return quota

    @staticmethod
    def get_or_create_current_quota(
        teacher, plan: SubscriptionPlan = None, force_refresh: bool = False
    ) -> MonthlyLeadQuota:
        """
        Returns the MonthlyLeadQuota row for the period containing now,
        creating it (snapshotting total_free_leads from the teacher's
        effective plan) if it does not exist yet.

        force_refresh=True re-snapshots the allowance onto an existing row -
        used where a teacher's effective plan may have changed without
        going through subscribe(), e.g. an admin editing plan.free_leads.
        Usage is never touched here; only a new period resets it.
        """
        period_start, period_end = LeadQuotaService.resolve_period(teacher)
        effective_plan = plan or SubscriptionService.get_effective_plan(teacher)

        quota, created = MonthlyLeadQuota.objects.get_or_create(
            teacher=teacher,
            period_start=period_start,
            defaults={
                "period_end": period_end,
                "total_free_leads": effective_plan.free_leads,
            },
        )

        if (
            force_refresh
            and not created
            and quota.total_free_leads != effective_plan.free_leads
        ):
            quota.total_free_leads = effective_plan.free_leads
            quota.save(update_fields=["total_free_leads"])

        return quota

    @staticmethod
    @transaction.atomic
    def consume_free_lead(teacher) -> MonthlyLeadQuota:
        """
        Spends one unlock from this period's plan allowance.

        Uses select_for_update for the same race-condition reasoning as
        WalletService: two simultaneous unlock requests must not both
        succeed in consuming the last unlock of the period.

        Raises ValidationException if the allowance is already spent - the
        CALLER (apps.lead_engine.unlock_service) checks
        has_free_leads_remaining() first and falls through to the purchased
        balance instead; this exception is a safety net, not the primary
        control flow.
        """
        quota = LeadQuotaService.get_or_create_current_quota(teacher)
        quota = MonthlyLeadQuota.objects.select_for_update().get(id=quota.id)

        if quota.used_free_leads >= quota.total_free_leads:
            raise ValidationException(
                detail="Your plan's unlocks for this period are already used up."
            )

        quota.used_free_leads += 1
        quota.save(update_fields=["used_free_leads"])
        return quota

    @staticmethod
    def has_free_leads_remaining(teacher) -> bool:
        """Non-mutating check, used by the unlock workflow before charging."""
        quota = LeadQuotaService.get_or_create_current_quota(teacher)
        return quota.has_free_leads_remaining

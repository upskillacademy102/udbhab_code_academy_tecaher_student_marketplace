"""
Subscription models for the Teacher Marketplace Platform.

Covers:
    - SubscriptionPlan: admin-configured membership tiers (Free,
      Professional, Elite), each granting a monthly free-lead
      allowance plus other perks (priority rank, featured listing,
      lead multiplier, bonus tokens).
    - TeacherSubscription: links a Teacher to their current (and
      historical) SubscriptionPlan, satisfying the spec's
      "Subscription Model" + "Subscription History" requirement -
      history is achieved by keeping every past TeacherSubscription
      row rather than overwriting one row per teacher.
    - MonthlyLeadQuota: one row per (teacher, month), tracking how
      many of that month's free leads have been used - this is
      what apps.lead_engine's unlock workflow (built next) checks
      in STEP 1 of the spec's Lead Unlock Logic.
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import validate_taxonomy_name

# Sane ceilings for admin-configured plan numbers.
MAX_PLAN_PRICE = Decimal("1000000.00")
MAX_FREE_LEADS = 100_000
MAX_PRIORITY_RANK = 1_000
MAX_LEAD_MULTIPLIER = Decimal("10.00")
MAX_BONUS_TOKENS = 1_000_000


class PlanStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    INACTIVE = "inactive", _("Inactive")


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    EXPIRED = "expired", _("Expired")
    CANCELLED = "cancelled", _("Cancelled")


class SubscriptionPlan(BaseModel):
    """
    An admin-configured membership tier. Every field here matches
    the spec's explicit list: Plan Name, Monthly Price, Free Leads,
    Priority Rank, Featured Listing, Lead Multiplier, Bonus Tokens,
    Status.
    """

    name = models.CharField(
        _("plan name"),
        max_length=100,
        unique=True,
        validators=[validate_taxonomy_name],
        help_text=_("e.g. 'Free', 'Professional', 'Elite'."),
    )
    monthly_price = models.DecimalField(
        _("monthly price"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_PLAN_PRICE),
        ],
    )
    free_leads = models.PositiveIntegerField(
        _("unlock allowance per cycle"),
        default=0,
        validators=[MaxValueValidator(MAX_FREE_LEADS)],
        help_text=_(
            "TOTAL contact unlocks this plan grants per 30-day cycle - base plus "
            "bonus. This is the single number the unlock workflow spends against; "
            "bonus_leads only records how it is composed for display."
        ),
    )
    bonus_leads = models.PositiveIntegerField(
        _("bonus unlocks per cycle"),
        default=0,
        validators=[MaxValueValidator(MAX_FREE_LEADS)],
        help_text=_(
            "How many of free_leads are advertised as a bonus, e.g. Professional "
            "is '8 + 2 bonus' = 10. Display only - it is already counted inside "
            "free_leads and must never be added on top, or the teacher would be "
            "granted the bonus twice."
        ),
    )
    priority_rank = models.PositiveIntegerField(
        _("priority rank"),
        default=0,
        validators=[MaxValueValidator(MAX_PRIORITY_RANK)],
        help_text=_(
            "Higher rank = higher priority in search/listing ordering. "
            "Phase 3 note: this field is stored and available for "
            "apps.search to consume as a ranking signal, but wiring it "
            "into search's actual ordering logic is left as a follow-up "
            "- see the note in this app's admin.py."
        ),
    )
    is_featured_listing = models.BooleanField(
        _("featured listing"),
        default=False,
        help_text=_(
            "Whether teachers on this plan get featured/highlighted placement."
        ),
    )
    lead_multiplier = models.DecimalField(
        _("lead multiplier"),
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_LEAD_MULTIPLIER),
        ],
        help_text=_(
            "Multiplier applied to how many leads this teacher is matched "
            "with, relative to baseline (e.g. 1.5 = 50% more lead "
            "visibility). Phase 3 note: stored as configurable plan data; "
            "actual application inside lead_engine's matching algorithm "
            "is intentionally out of scope for Phase 3's synchronous, "
            "simple matching pass - flagged here rather than silently "
            "implemented as a hidden behavior change to Phase 2's engine."
        ),
    )
    bonus_tokens = models.PositiveIntegerField(
        _("bonus tokens on subscribe"),
        default=0,
        validators=[MaxValueValidator(MAX_BONUS_TOKENS)],
        help_text=_(
            "One-time bonus tokens credited to the wallet when a teacher subscribes to this plan."
        ),
    )
    compare_at_price = models.DecimalField(
        _("compare-at price"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_PLAN_PRICE),
        ],
        help_text=_(
            "Optional 'was' price shown struck through next to monthly_price to "
            "advertise a discount (e.g. compare_at_price=199.00 with "
            "monthly_price=99.00 displays '₹199 → ₹99, 50% off'). "
            "Null when this plan isn't being shown as discounted."
        ),
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=PlanStatus.choices,
        default=PlanStatus.ACTIVE,
        db_index=True,
    )

    class Meta:
        verbose_name = _("Subscription Plan")
        verbose_name_plural = _("Subscription Plans")
        ordering = ["monthly_price"]
        constraints = [
            models.CheckConstraint(
                name="subscription_plan_name_not_blank",
                check=~models.Q(name__regex=r"^\s*$"),
            ),
            models.CheckConstraint(
                name="subscription_plan_sane_ranges",
                check=(
                    models.Q(monthly_price__gte=Decimal("0.00"))
                    & models.Q(monthly_price__lte=MAX_PLAN_PRICE)
                    & models.Q(free_leads__lte=MAX_FREE_LEADS)
                    & models.Q(bonus_leads__lte=models.F("free_leads"))
                    & models.Q(priority_rank__lte=MAX_PRIORITY_RANK)
                    & models.Q(lead_multiplier__gte=Decimal("0.00"))
                    & models.Q(lead_multiplier__lte=MAX_LEAD_MULTIPLIER)
                    & models.Q(bonus_tokens__lte=MAX_BONUS_TOKENS)
                ),
            ),
            models.CheckConstraint(
                name="subscription_plan_compare_at_price_is_a_real_discount",
                check=(
                    models.Q(compare_at_price__isnull=True)
                    | models.Q(compare_at_price__gt=models.F("monthly_price"))
                ),
            ),
        ]

    def __str__(self):
        return f"{self.name} (₹{self.monthly_price}/mo, {self.free_leads} unlocks)"

    @property
    def base_leads(self) -> int:
        """
        The allowance excluding the advertised bonus - the "8" in "8 + 2".
        Derived, never stored, so free_leads stays the one number the unlock
        workflow spends against and the two can't drift.
        """
        return max(self.free_leads - self.bonus_leads, 0)

    @property
    def discount_percent(self) -> int | None:
        """Rounded % off, for display next to the struck-through
        compare_at_price - None when this plan isn't shown as discounted."""
        if not self.compare_at_price or self.compare_at_price <= self.monthly_price:
            return None
        off = (self.compare_at_price - self.monthly_price) / self.compare_at_price
        return round(off * 100)


class TeacherSubscription(BaseModel):
    """
    Links a Teacher to a SubscriptionPlan for a specific period.
    Every subscribe/renew action creates a NEW row (never mutates
    an old one in place) - this is what gives "Subscription
    History" for free: querying all TeacherSubscription rows for a
    teacher, ordered by created_at, is the full history.

    Exactly one row per teacher should have status=ACTIVE at a time
    (enforced at the service layer, not a database constraint,
    since a teacher legitimately has zero ACTIVE rows before their
    first subscription).
    """

    teacher = models.ForeignKey(
        "teachers.Teacher",
        related_name="subscriptions",
        on_delete=models.CASCADE,
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        related_name="subscriptions",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
        db_index=True,
    )
    start_date = models.DateTimeField(_("start date"), default=timezone.now)
    end_date = models.DateTimeField(
        _("end date"),
        help_text=_(
            "When this subscription period ends (start_date + 1 month, typically)."
        ),
    )
    payment = models.ForeignKey(
        "payments.Payment",
        related_name="subscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_(
            "The Payment that funded this subscription, if it was a paid "
            "plan. Null for the Free plan or admin-granted subscriptions."
        ),
    )

    class Meta:
        verbose_name = _("Teacher Subscription")
        verbose_name_plural = _("Teacher Subscriptions")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["teacher", "status"]),
            models.Index(fields=["status", "end_date"]),
        ]

    def __str__(self):
        return f"{self.teacher.user.get_full_name()} - {self.plan.name} ({self.status})"

    @property
    def is_active_now(self) -> bool:
        return (
            self.status == SubscriptionStatus.ACTIVE and self.end_date > timezone.now()
        )


class MonthlyLeadQuota(BaseModel):
    """
    One row per (teacher, entitlement period), tracking how much of that
    period's plan allowance the teacher has spent.

    PERIOD, NOT CALENDAR MONTH: the window is a rolling
    ``settings.LEAD_UNLOCK_CYCLE_DAYS`` (30) days anchored to
    ``period_start``, deliberately NOT the first-of-the-month keying this
    model originally used. The anchor is the teacher's active
    TeacherSubscription.start_date, so the billing period and the
    allowance period are the SAME clock - a renewal and a reset can never
    drift apart (a calendar month is 28-31 days, so the two would
    otherwise separate by ~5 days a year and produce "my subscription
    renewed but my unlocks didn't" support tickets).

    "free" in these field names means "included in the teacher's plan",
    not "costs nothing" - a Professional teacher paid Rs.99 for their 10.
    Unlocks bought as top-up packs are NOT tracked here: they live in the
    teacher's Wallet, because they never expire and this row resets.
    See apps.lead_engine.unlock_service for how the two buckets are spent.
    """

    teacher = models.ForeignKey(
        "teachers.Teacher",
        related_name="monthly_lead_quotas",
        on_delete=models.CASCADE,
    )
    period_start = models.DateTimeField(
        _("period start"),
        help_text=_(
            "When this entitlement period opened. Anchored to the teacher's "
            "active subscription start_date so billing and allowance share "
            "one clock."
        ),
    )
    period_end = models.DateTimeField(
        _("period end"),
        help_text=_(
            "When this period closes and the allowance resets. "
            "period_start + LEAD_UNLOCK_CYCLE_DAYS."
        ),
    )
    total_free_leads = models.PositiveIntegerField(
        _("allowance this period"),
        help_text=_(
            "Snapshot of the teacher's plan.free_leads for this period. Raised "
            "in place on a mid-period upgrade (usage carries forward); only a "
            "new period resets usage to zero."
        ),
    )
    used_free_leads = models.PositiveIntegerField(
        _("allowance used"),
        default=0,
    )

    class Meta:
        verbose_name = _("Lead Unlock Allowance")
        verbose_name_plural = _("Lead Unlock Allowances")
        ordering = ["-period_start"]
        indexes = [
            models.Index(
                fields=["teacher", "period_end"], name="sub_quota_teacher_period_idx"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "period_start"],
                name="unique_quota_per_teacher_per_period",
            ),
            models.CheckConstraint(
                name="quota_period_ends_after_it_starts",
                check=models.Q(period_end__gt=models.F("period_start")),
            ),
        ]

    def __str__(self):
        return (
            f"{self.teacher.user.get_full_name()} - "
            f"{self.period_start:%d %b %Y} to {self.period_end:%d %b %Y}"
        )

    @property
    def remaining_free_leads(self) -> int:
        return max(self.total_free_leads - self.used_free_leads, 0)

    @property
    def has_free_leads_remaining(self) -> bool:
        return self.remaining_free_leads > 0

    @property
    def is_current(self) -> bool:
        """Whether this row is the period we are actually inside right now."""
        return self.period_start <= timezone.now() < self.period_end

    @property
    def days_until_reset(self) -> int:
        """
        Whole days left before the allowance resets, floored at 0. Drives the
        "resets in N days" line on the teacher's leads screen.
        """
        remaining = self.period_end - timezone.now()
        return max(remaining.days, 0)

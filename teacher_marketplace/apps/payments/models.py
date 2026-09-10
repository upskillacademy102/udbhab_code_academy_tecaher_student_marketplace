"""
Payment models for the Teacher Marketplace Platform.

Covers:
    - TokenPackage: admin-configured bundles teachers can purchase
      (e.g. "Starter - 100 tokens - Rs. 499").
    - Payment: one row per Razorpay order/payment attempt, tracking
      its lifecycle (pending -> success/failed/refunded).
    - PaymentWebhook: raw log of every webhook event Razorpay sends,
      kept for audit/debugging even after being processed - webhook
      payloads are the authoritative source of truth for what
      Razorpay actually reported, independent of how our own
      Payment.status interpretation of that event turned out.

On successful payment (per spec): "Credit Teacher Wallet, Create
Wallet Transaction" - that side effect is implemented in
apps.payments.services (next relevant file), never here in the
model layer.
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import validate_taxonomy_name

# Sane ceilings - anything above these is a data-entry error.
MAX_TOKEN_COUNT = 1_000_000
MAX_TOKEN_PRICE = Decimal("1000000.00")
MAX_PERCENTAGE = Decimal("100.00")
MAX_SORT_ORDER = 100_000


class PaymentStatus(models.TextChoices):
    """
    Matches the spec's exact list: Success, Failed, Pending, Refunded.
    """

    PENDING = "pending", _("Pending")
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")
    REFUNDED = "refunded", _("Refunded")


class PaymentType(models.TextChoices):
    TOKEN_PURCHASE = "token_purchase", _("Token Purchase")
    SUBSCRIPTION = "subscription", _("Subscription")


class TokenPackage(BaseModel):
    """
    An admin-configured, purchasable bundle of tokens. Teachers
    browse these via GET /api/v1/token-packages/ and purchase one
    via the payments flow.
    """

    name = models.CharField(
        _("package name"),
        max_length=100,
        unique=True,
        validators=[validate_taxonomy_name],
        help_text=_("e.g. 'Starter', 'Professional', 'Enterprise'."),
    )
    token_count = models.PositiveIntegerField(
        _("token count"),
        validators=[MinValueValidator(1), MaxValueValidator(MAX_TOKEN_COUNT)],
        help_text=_("Number of tokens credited to the wallet on successful purchase."),
    )
    price = models.DecimalField(
        _("price"),
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_TOKEN_PRICE),
        ],
        help_text=_("Base price before GST, in the platform's base currency."),
    )
    gst_percentage = models.DecimalField(
        _("GST percentage"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("18.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_PERCENTAGE),
        ],
        help_text=_("GST rate applied to price, e.g. 18.00 for 18%."),
    )
    discount_percentage = models.DecimalField(
        _("discount percentage"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_PERCENTAGE),
        ],
        help_text=_("Optional promotional discount applied to price before GST."),
    )
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        db_index=True,
        help_text=_(
            "Inactive packages are hidden from purchase but preserved for historical orders."
        ),
    )
    sort_order = models.PositiveIntegerField(
        _("sort order"),
        default=0,
        validators=[MaxValueValidator(MAX_SORT_ORDER)],
        help_text=_("Lower numbers appear first in package listings."),
    )

    class Meta:
        verbose_name = _("Token Package")
        verbose_name_plural = _("Token Packages")
        ordering = ["sort_order", "price"]
        constraints = [
            models.CheckConstraint(
                name="token_package_name_not_blank",
                check=~models.Q(name__regex=r"^\s*$"),
            ),
            models.CheckConstraint(
                name="token_package_sane_ranges",
                check=(
                    models.Q(token_count__gte=1)
                    & models.Q(token_count__lte=MAX_TOKEN_COUNT)
                    & models.Q(price__gte=Decimal("0.00"))
                    & models.Q(price__lte=MAX_TOKEN_PRICE)
                    & models.Q(gst_percentage__gte=Decimal("0.00"))
                    & models.Q(gst_percentage__lte=MAX_PERCENTAGE)
                    & models.Q(discount_percentage__gte=Decimal("0.00"))
                    & models.Q(discount_percentage__lte=MAX_PERCENTAGE)
                ),
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.token_count} tokens)"

    @property
    def discounted_price(self) -> Decimal:
        """Price after discount_percentage is applied, before GST."""
        discount_amount = self.price * (self.discount_percentage / Decimal("100"))
        return (self.price - discount_amount).quantize(Decimal("0.01"))

    @property
    def gst_amount(self) -> Decimal:
        """GST computed on the discounted price."""
        return (
            self.discounted_price * (self.gst_percentage / Decimal("100"))
        ).quantize(Decimal("0.01"))

    @property
    def final_price(self) -> Decimal:
        """
        The actual amount charged to the teacher: discounted price
        plus GST. This is what gets sent to Razorpay as the order
        amount.
        """
        return (self.discounted_price + self.gst_amount).quantize(Decimal("0.01"))


class Payment(BaseModel):
    """
    One row per payment attempt for a TokenPackage purchase.
    Created in PENDING status when a Razorpay order is created,
    transitions to SUCCESS/FAILED once verified (via the Verify
    Payment API or the Webhook API - whichever confirms first).
    """

    teacher = models.ForeignKey(
        "teachers.Teacher",
        related_name="payments",
        on_delete=models.CASCADE,
        help_text=_("The Teacher making this payment. Students never make payments."),
    )
    payment_type = models.CharField(
        _("payment type"),
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.TOKEN_PURCHASE,
        db_index=True,
    )
    token_package = models.ForeignKey(
        TokenPackage,
        related_name="payments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=_("Set when payment_type=TOKEN_PURCHASE."),
    )
    subscription_plan = models.ForeignKey(
        "subscriptions.SubscriptionPlan",
        related_name="payments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=_("Set when payment_type=SUBSCRIPTION."),
    )
    razorpay_order_id = models.CharField(
        _("Razorpay order id"),
        max_length=100,
        unique=True,
        db_index=True,
    )
    razorpay_payment_id = models.CharField(
        _("Razorpay payment id"),
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
        help_text=_(
            "Populated once Razorpay confirms the payment (not present at order-creation time)."
        ),
    )
    razorpay_signature = models.CharField(
        _("Razorpay signature"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_(
            "The signature submitted for verification - stored for audit purposes."
        ),
    )
    amount = models.DecimalField(
        _("amount"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_(
            "The exact amount charged (TokenPackage.final_price at time of purchase)."
        ),
    )
    token_count = models.PositiveIntegerField(
        _("token count"),
        null=True,
        blank=True,
        help_text=_(
            "Snapshot of TokenPackage.token_count at time of purchase - "
            "only set when payment_type=TOKEN_PURCHASE."
        ),
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    failure_reason = models.CharField(
        _("failure reason"),
        max_length=255,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["teacher", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(
                        payment_type="token_purchase",
                        token_package__isnull=False,
                        subscription_plan__isnull=True,
                    )
                    | models.Q(
                        payment_type="subscription",
                        subscription_plan__isnull=False,
                        token_package__isnull=True,
                    )
                ),
                name="payment_type_matches_target",
            ),
        ]

    def __str__(self):
        return f"Payment {self.razorpay_order_id} - {self.teacher.user.get_full_name()} ({self.status})"


class PaymentWebhook(BaseModel):
    """
    Raw log of every webhook event received from Razorpay, kept
    permanently for audit/debugging - this is intentionally an
    append-only event log, separate from Payment's interpreted
    state, so the exact payload Razorpay sent is always
    reconstructable even if our own processing logic had a bug.
    """

    payment = models.ForeignKey(
        Payment,
        related_name="webhook_events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("The Payment this webhook relates to, if it could be matched."),
    )
    event_type = models.CharField(
        _("event type"),
        max_length=100,
        db_index=True,
        help_text=_("Razorpay event name, e.g. 'payment.captured', 'payment.failed'."),
    )
    razorpay_event_id = models.CharField(
        _("Razorpay event id"),
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_(
            "Used to detect and ignore duplicate webhook deliveries (Razorpay may retry)."
        ),
    )
    payload = models.JSONField(
        _("payload"),
        help_text=_("The full raw webhook payload as received, for audit/debugging."),
    )
    is_processed = models.BooleanField(
        _("is processed"),
        default=False,
        db_index=True,
    )
    processing_error = models.TextField(
        _("processing error"),
        null=True,
        blank=True,
        help_text=_(
            "Populated if processing this webhook raised an error, for debugging."
        ),
    )

    class Meta:
        verbose_name = _("Payment Webhook")
        verbose_name_plural = _("Payment Webhooks")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} ({self.razorpay_event_id})"


class PaymentInstrumentKind(models.TextChoices):
    CARD = "card", _("Card")
    UPI = "upi", _("UPI")
    WALLET = "wallet", _("Wallet")
    NETBANKING = "netbanking", _("Netbanking")
    OTHER = "other", _("Other")


class PaymentInstrumentSignature(BaseModel):
    """
    A hashed fingerprint of the payment instrument a teacher used (UPI VPA,
    card fingerprint, wallet handle). Never stores the raw value. Phase 7c
    (``apps.payments.risk.PaymentRiskService``) uses these to spot one
    instrument funding many different accounts - a classic payment-fraud
    / multi-accounting signal.
    """

    teacher = models.ForeignKey(
        "teachers.Teacher",
        related_name="payment_instruments",
        on_delete=models.CASCADE,
    )
    kind = models.CharField(
        max_length=12, choices=PaymentInstrumentKind.choices, db_index=True
    )
    value_hash = models.CharField(max_length=64, db_index=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Payment instrument signature")
        verbose_name_plural = _("Payment instrument signatures")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "kind", "value_hash"],
                name="payment_instrument_unique_per_teacher",
            ),
        ]
        indexes = [
            models.Index(fields=["kind", "value_hash"]),
        ]

    def __str__(self):
        return f"{self.kind}:{self.value_hash[:12]} ({self.teacher_id})"


class DisputeKind(models.TextChoices):
    CHARGEBACK = "chargeback", _("Chargeback / dispute")
    REFUND = "refund", _("Refund")


class DisputeStatus(models.TextChoices):
    OPEN = "open", _("Open")
    UNDER_REVIEW = "under_review", _("Under review")
    WON = "won", _("Won (in our favour)")
    LOST = "lost", _("Lost (charge reversed)")
    CANCELLED = "cancelled", _("Cancelled")


class PaymentDispute(BaseModel):
    """
    A chargeback / dispute / refund raised against a Payment. Recorded from
    the Razorpay webhook. When ``TRUST_ENABLE_PAYMENT_RISK_CHECKS`` is on,
    the tokens the disputed payment credited are frozen via a
    ``wallet.WalletHold`` until the dispute resolves:
      - won  -> hold released (tokens usable again)
      - lost -> hold settled as a debit (tokens clawed back)
    """

    payment = models.ForeignKey(
        Payment, related_name="disputes", on_delete=models.CASCADE
    )
    kind = models.CharField(max_length=12, choices=DisputeKind.choices, db_index=True)
    external_ref = models.CharField(
        max_length=100,
        unique=True,
        help_text=_("Razorpay dispute id or refund id - dedupes webhook retries."),
    )
    status = models.CharField(
        max_length=16,
        choices=DisputeStatus.choices,
        default=DisputeStatus.OPEN,
        db_index=True,
    )
    amount = models.DecimalField(
        _("disputed amount"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    tokens_frozen = models.PositiveIntegerField(default=0)
    reason_code = models.CharField(max_length=120, blank=True)
    wallet_hold = models.ForeignKey(
        "wallet.WalletHold",
        related_name="disputes",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    review_item = models.ForeignKey(
        "trust.ManualReviewItem",
        related_name="payment_disputes",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    raw_event = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Payment dispute")
        verbose_name_plural = _("Payment disputes")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.kind} {self.external_ref} ({self.status})"


class ReconciliationRun(BaseModel):
    """
    One nightly payment-reconciliation pass (Phase 7f). Compares our
    Payment / WalletTransaction ledger against Razorpay's settlement view
    and records any drift for ops.
    """

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    payments_checked = models.PositiveIntegerField(default=0)
    discrepancies = models.PositiveIntegerField(default=0)
    ok = models.BooleanField(default=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("Reconciliation run")
        verbose_name_plural = _("Reconciliation runs")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Reconciliation {self.created_at:%Y-%m-%d} ({self.discrepancies} drift)"

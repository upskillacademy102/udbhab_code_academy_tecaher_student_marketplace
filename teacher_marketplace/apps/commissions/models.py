"""
Learning Partner commission + payout models.

BUSINESS RULE: whenever a teacher who is attributed to a Learning
Partner (User.learning_partner, see apps.accounts.models) makes a
successful purchase (token package OR subscription), that partner
earns 2/3 of the pre-GST base price and the business keeps the rest
(1/3 of the base price, plus all GST). A teacher with no partner
generates zero partner commission - the business keeps the full
charged amount, same as before this app existed. See
apps.commissions.services.CommissionService for the actual split
arithmetic and apps.payments.services for where it is invoked.

Mirrors apps.wallet's structural rule one level up: "No direct
modification of LearningPartnerWallet.balance. All balance updates
must create a LearningPartnerWalletTransaction." The only sanctioned
writer of balances/ledger rows is
apps.commissions.services.LearningPartnerWalletService.
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel


class CommissionStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    REVERSED = "reversed", _("Reversed")


class Commission(BaseModel):
    """
    One immutable row per successful Payment (both token_purchase and
    subscription), recording how that payment's money was split between
    the referring Learning Partner (if any) and the business. Created
    inside the same atomic block that marks the Payment successful
    (apps.payments.services.PaymentService._credit_successful_payment) -
    see CommissionService.credit_for_payment.

    The OneToOne on `payment` is the idempotency guard: a given Payment
    can only ever produce one Commission row, even if the crediting path
    races (verify-API vs webhook) or retries.
    """

    payment = models.OneToOneField(
        "payments.Payment",
        related_name="commission",
        on_delete=models.CASCADE,
    )
    teacher = models.ForeignKey(
        "teachers.Teacher",
        related_name="commissions",
        on_delete=models.CASCADE,
        help_text=_("Denormalized from payment.teacher for cheap reporting queries."),
    )
    learning_partner = models.ForeignKey(
        "accounts.User",
        verbose_name=_("learning partner"),
        related_name="partner_commissions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role": "learning_partner"},
        help_text=_(
            "The Learning Partner this commission was earned by - a snapshot of "
            "teacher.user.learning_partner at the moment the payment succeeded. "
            "Null when the teacher was not attributed to any partner, in which "
            "case the business kept the full amount and partner_share is 0."
        ),
    )
    payment_type = models.CharField(
        _("payment type"),
        max_length=20,
        db_index=True,
        help_text=_("Denormalized copy of Payment.payment_type, for filtering."),
    )
    base_amount = models.DecimalField(
        _("base amount"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_(
            "The pre-GST amount the 2/3 - 1/3 split is computed from "
            "(Payment.base_amount, snapshotted at order-creation time)."
        ),
    )
    partner_share = models.DecimalField(
        _("partner share"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("round(base_amount * 2/3, 2). Zero when learning_partner is null."),
    )
    business_share = models.DecimalField(
        _("business share"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_(
            "payment.amount - partner_share. Always includes the full GST "
            "amount (GST is never split with a partner) plus, when there is "
            "a partner, 1/3 of the base price - or the full charged amount "
            "when there is no partner."
        ),
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=CommissionStatus.choices,
        default=CommissionStatus.ACTIVE,
        db_index=True,
    )
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = _("Commission")
        verbose_name_plural = _("Commissions")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["learning_partner", "status"]),
            models.Index(fields=["teacher", "status"]),
        ]

    def __str__(self):
        partner = self.learning_partner.first_name if self.learning_partner else "none"
        return f"Commission {self.payment_id} - partner={partner} ({self.status})"


class LearningPartnerWallet(BaseModel):
    """
    A Learning Partner's commission wallet. One-to-one with a
    role=learning_partner User (never a plain admin, teacher, or
    student). `balance` is a plain field for cheap reads, but - exactly
    like apps.wallet.Wallet - must only ever change via
    LearningPartnerWalletService.
    """

    learning_partner = models.OneToOneField(
        "accounts.User",
        verbose_name=_("learning partner"),
        related_name="commission_wallet",
        on_delete=models.CASCADE,
        limit_choices_to={"role": "learning_partner"},
    )
    balance = models.DecimalField(
        _("balance"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_(
            "Current commission balance in rupees. NEVER set this directly - "
            "always go through LearningPartnerWalletService.credit()/debit(). "
            "May go negative after a reversal clawing back an already-paid-out "
            "commission - a real accounting state, not a bug."
        ),
    )

    class Meta:
        verbose_name = _("Learning Partner Wallet")
        verbose_name_plural = _("Learning Partner Wallets")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Wallet: {self.learning_partner.first_name} (Rs.{self.balance})"


class LPTransactionType(models.TextChoices):
    CREDIT = "credit", _("Credit")
    DEBIT = "debit", _("Debit")
    REVERSAL = "reversal", _("Reversal")


class LearningPartnerWalletTransaction(BaseModel):
    """
    Immutable audit record of a single LearningPartnerWallet balance
    change - a commission credit, a payout debit, or a reversal clawback.
    Append-only, mirroring apps.wallet.WalletTransaction exactly.
    """

    wallet = models.ForeignKey(
        LearningPartnerWallet,
        related_name="transactions",
        on_delete=models.CASCADE,
    )
    transaction_type = models.CharField(
        _("transaction type"),
        max_length=10,
        choices=LPTransactionType.choices,
        db_index=True,
    )
    amount = models.DecimalField(
        _("amount"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text=_("Rupee amount involved in this transaction (always positive)."),
    )
    balance_after = models.DecimalField(
        _("balance after"), max_digits=12, decimal_places=2
    )
    reference_id = models.CharField(
        _("reference id"),
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text=_(
            "A Commission id (credit/reversal) or PayoutRequest id (debit) - "
            "not a foreign key since the reference type varies."
        ),
    )
    description = models.CharField(_("description"), max_length=255)

    class Meta:
        verbose_name = _("Learning Partner Wallet Transaction")
        verbose_name_plural = _("Learning Partner Wallet Transactions")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "transaction_type"]),
            models.Index(fields=["wallet", "created_at"]),
            models.Index(fields=["reference_id"]),
        ]

    def __str__(self):
        return f"{self.get_transaction_type_display()} Rs.{self.amount} - {self.wallet}"


class LearningPartnerBankAccount(BaseModel):
    """
    A Learning Partner's saved payout bank details. One-to-one - a
    partner has exactly one active bank account on file at a time;
    saving again overwrites it. PayoutRequest snapshots these fields at
    request time, so a later edit here never rewrites payout history.
    """

    learning_partner = models.OneToOneField(
        "accounts.User",
        verbose_name=_("learning partner"),
        related_name="bank_account",
        on_delete=models.CASCADE,
        limit_choices_to={"role": "learning_partner"},
    )
    account_holder_name = models.CharField(max_length=150)
    account_number = models.CharField(max_length=34)
    ifsc_code = models.CharField(max_length=11)
    bank_name = models.CharField(max_length=150)

    class Meta:
        verbose_name = _("Learning Partner Bank Account")
        verbose_name_plural = _("Learning Partner Bank Accounts")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.bank_name} - {self.account_holder_name} ({self.learning_partner.first_name})"


class PayoutStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    PAID = "paid", _("Paid")


class PayoutRequest(BaseModel):
    """
    A Learning Partner's request to withdraw part of their commission
    wallet balance. Actual money movement happens outside this system
    (a real bank transfer, done by Finance/Super Admin) - this model
    just tracks the request lifecycle and, once PAID, holds the bank
    reference (UTR) as proof.

    The wallet is only ever debited at mark_paid() time (see
    PayoutService), not at request time - a PENDING or REJECTED request
    never touches the balance, so "available balance" for a new request
    is balance minus the sum of the partner's own PENDING+APPROVED
    requests (see LearningPartnerWalletService.available_balance).
    """

    learning_partner = models.ForeignKey(
        "accounts.User",
        verbose_name=_("learning partner"),
        related_name="payout_requests",
        on_delete=models.CASCADE,
        limit_choices_to={"role": "learning_partner"},
    )
    amount = models.DecimalField(
        _("amount"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("1.00"))],
    )
    # Bank detail snapshot at request time (see class docstring).
    account_holder_name = models.CharField(max_length=150)
    account_number = models.CharField(max_length=34)
    ifsc_code = models.CharField(max_length=11)
    bank_name = models.CharField(max_length=150)

    status = models.CharField(
        _("status"),
        max_length=10,
        choices=PayoutStatus.choices,
        default=PayoutStatus.PENDING,
        db_index=True,
    )
    decided_by = models.ForeignKey(
        "accounts.User",
        related_name="payout_decisions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("The Admin/Super Admin who approved or rejected this request."),
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.CharField(max_length=500, null=True, blank=True)
    payout_reference = models.CharField(
        _("payout reference"),
        max_length=100,
        null=True,
        blank=True,
        help_text=_("Bank transfer UTR / reference number, filled in at mark-paid time."),
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Payout Request")
        verbose_name_plural = _("Payout Requests")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["learning_partner", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"Payout {self.amount} - {self.learning_partner.first_name} ({self.status})"

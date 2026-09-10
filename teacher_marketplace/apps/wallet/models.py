"""
Wallet models for the Teacher Marketplace Platform.

BUSINESS RULE (enforced structurally, not just by convention):
"No direct modification of Wallet Balance. All Wallet updates must
create a WalletTransaction." This means Wallet.balance must NEVER
be set directly from a view or serializer - the only sanctioned
path is apps.wallet.services.WalletService (next file), which
wraps every balance change in a database transaction alongside
creating the corresponding WalletTransaction row atomically.

Every Teacher owns exactly one Wallet (OneToOneField). Students
never have a Wallet - there is no code path anywhere in this app
that creates one for a Student, and the service layer will
explicitly reject attempts to do so.
"""

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel


class TransactionType(models.TextChoices):
    CREDIT = "credit", _("Credit")
    DEBIT = "debit", _("Debit")
    REFUND = "refund", _("Refund")


class TransactionStatus(models.TextChoices):
    """
    Nearly all transactions complete synchronously and immediately
    (Phase 3 has no async task queue), so SUCCESS is the default
    for most rows. PENDING/FAILED exist for payment-triggered
    credits where the payment itself may not have completed yet -
    see apps.payments for how those states are actually used.
    """

    PENDING = "pending", _("Pending")
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")


class Wallet(BaseModel):
    """
    A Teacher's token wallet. One-to-one with Phase 1's Teacher
    model (not User directly), consistent with how TeacherProfile
    extends Teacher in Phase 2.

    `balance` is a plain field for query/display purposes (so
    "check current balance" is a cheap read, not a SUM() over every
    transaction ever made), but it must only ever be changed via
    WalletService - see module docstring.
    """

    teacher = models.OneToOneField(
        "teachers.Teacher",
        related_name="wallet",
        on_delete=models.CASCADE,
        help_text=_("The Teacher who owns this wallet. Students never have a wallet."),
    )
    balance = models.PositiveIntegerField(
        _("balance"),
        default=0,
        validators=[MinValueValidator(0)],
        help_text=_(
            "Current token balance. NEVER set this directly - always go "
            "through WalletService.credit()/debit()/refund()."
        ),
    )

    class Meta:
        verbose_name = _("Wallet")
        verbose_name_plural = _("Wallets")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Wallet: {self.teacher.user.get_full_name()} ({self.balance} tokens)"


class WalletTransaction(BaseModel):
    """
    Immutable audit record of a single wallet balance change.
    Every credit, debit, or refund creates exactly one row here -
    this table is the source of truth for "Transaction History" and
    the audit trail your spec requires ("Every Wallet transaction
    must be auditable").

    Rows are never updated or hard-deleted after creation (aside
    from status transitioning PENDING -> SUCCESS/FAILED for
    payment-linked credits) - this is an append-only ledger.
    """

    wallet = models.ForeignKey(
        Wallet,
        related_name="transactions",
        on_delete=models.CASCADE,
    )
    transaction_type = models.CharField(
        _("transaction type"),
        max_length=10,
        choices=TransactionType.choices,
        db_index=True,
    )
    amount = models.PositiveIntegerField(
        _("amount"),
        validators=[MinValueValidator(1)],
        help_text=_("Number of tokens involved in this transaction (always positive)."),
    )
    balance_after = models.PositiveIntegerField(
        _("balance after"),
        help_text=_(
            "The wallet's balance immediately after this transaction was applied."
        ),
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=TransactionStatus.choices,
        default=TransactionStatus.SUCCESS,
        db_index=True,
    )
    reference_id = models.CharField(
        _("reference id"),
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text=_(
            "External or internal reference this transaction relates to, "
            "e.g. a Payment id, a Lead id (unlock debit), or a refund "
            "reason code. Not a foreign key since the reference type "
            "varies by transaction_type."
        ),
    )
    description = models.CharField(
        _("description"),
        max_length=255,
        help_text=_(
            "Human-readable summary, e.g. 'Token package purchase - Professional'."
        ),
    )

    class Meta:
        verbose_name = _("Wallet Transaction")
        verbose_name_plural = _("Wallet Transactions")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "transaction_type"]),
            models.Index(fields=["wallet", "created_at"]),
            models.Index(fields=["reference_id"]),
        ]

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.amount} - {self.wallet}"


class WalletHold(BaseModel):
    """
    A freeze on part of a wallet's balance. The balance figure is left
    untouched (it stays a PositiveIntegerField), but *spendable* balance is
    ``balance - sum(active holds)`` - WalletService.debit() and
    has_sufficient_balance() both enforce that, so held tokens cannot be
    spent on lead unlocks while the hold stands.

    Placed by apps.payments (Phase 7d) when a payment behind a wallet
    credit is disputed / charged back. Resolved by releasing the hold
    (dispute won) or settling it as a debit (dispute lost).
    """

    wallet = models.ForeignKey(Wallet, related_name="holds", on_delete=models.CASCADE)
    amount = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    reason = models.CharField(max_length=255)
    payment = models.ForeignKey(
        "payments.Payment",
        related_name="wallet_holds",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    active = models.BooleanField(default=True, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("Wallet hold")
        verbose_name_plural = _("Wallet holds")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "active"]),
        ]

    def __str__(self):
        state = "active" if self.active else "released"
        return f"Hold {self.amount} ({state}) - {self.wallet}"

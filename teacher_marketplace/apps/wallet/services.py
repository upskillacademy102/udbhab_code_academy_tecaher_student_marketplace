"""
Wallet service layer for the Teacher Marketplace Platform.

STRUCTURAL ENFORCEMENT of the business rule "No direct modification
of Wallet Balance. All Wallet updates must create a
WalletTransaction": every method here wraps a Wallet.balance change
and the corresponding WalletTransaction.objects.create() call in a
single atomic transaction.select_for_update() block. No other
module in this project should ever call wallet.save() after
mutating wallet.balance directly - always go through this service.

Uses select_for_update() (row-level database locking) rather than a
plain read-modify-write, because wallet balance is exactly the kind
of value where a race condition has real financial consequences:
two concurrent "unlock a lead" requests both reading balance=10,
both deciding they can afford a 10-token unlock, both debiting,
would incorrectly leave the wallet at -10 without locking. Postgres
row locks make the second request wait for the first to fully
commit before it reads the (now-updated) balance.
"""

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.wallet.models import (
    TransactionStatus,
    TransactionType,
    Wallet,
    WalletHold,
    WalletTransaction,
)


class InsufficientBalanceError(ValidationException):
    """
    Raised when a debit is attempted that would take the wallet
    balance below zero. Extends the project's own ValidationException
    (not a bare Exception) so it flows through the standard DRF
    exception handler and produces a consistent 400 API error
    automatically, without the caller needing to catch and re-wrap it.
    """

    default_detail = "Insufficient wallet balance."
    error_code = "INSUFFICIENT_BALANCE"


class WalletService:
    """
    All wallet balance mutations go through this class's static
    methods. Never instantiated - purely a namespace for related
    operations (consistent with how similarly stateless logic is
    typically organized in this project's service layer).
    """

    @staticmethod
    def get_or_create_wallet(teacher) -> Wallet:
        """
        Returns the given Teacher's Wallet, creating one (with a
        zero balance) if it doesn't exist yet. This is the only
        place a Wallet is ever created - typically called lazily
        the first time a teacher interacts with any wallet-related
        endpoint, rather than eagerly at Teacher-creation time in
        Phase 1 (keeping apps.teachers fully decoupled from
        apps.wallet, per this project's app-boundary conventions).
        """
        wallet, _created = Wallet.objects.get_or_create(teacher=teacher)
        return wallet

    @staticmethod
    @transaction.atomic
    def credit(
        teacher,
        amount: int,
        description: str,
        reference_id: str = None,
        status: str = TransactionStatus.SUCCESS,
    ) -> WalletTransaction:
        """
        Increases the teacher's wallet balance by `amount` tokens
        and records a CREDIT transaction. Used for: token package
        purchases (via apps.payments), refunds are handled by
        refund() below instead (kept distinct so transaction_type
        correctly reflects intent, even though the balance math is
        identical).
        """
        if amount <= 0:
            raise ValidationException(detail="Credit amount must be positive.")

        wallet = Wallet.objects.select_for_update().get(teacher=teacher)
        wallet.balance = wallet.balance + amount
        wallet.save(update_fields=["balance"])

        return WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=TransactionType.CREDIT,
            amount=amount,
            balance_after=wallet.balance,
            status=status,
            reference_id=reference_id,
            description=description,
        )

    @staticmethod
    @transaction.atomic
    def debit(
        teacher,
        amount: int,
        description: str,
        reference_id: str = None,
    ) -> WalletTransaction:
        """
        Decreases the teacher's wallet balance by `amount` tokens
        and records a DEBIT transaction. Raises
        InsufficientBalanceError if the wallet doesn't have enough
        tokens - callers (e.g. lead_engine's unlock service) MUST
        check balance via has_sufficient_balance() first if they
        need to branch on insufficient-balance as a normal flow
        (not an exception) - see apps.lead_engine.unlock_service
        for exactly this pattern.
        """
        if amount <= 0:
            raise ValidationException(detail="Debit amount must be positive.")

        wallet = Wallet.objects.select_for_update().get(teacher=teacher)

        held = WalletService._active_hold_total(wallet)
        spendable = wallet.balance - held
        if spendable < amount:
            raise InsufficientBalanceError(
                detail=(
                    f"Insufficient wallet balance. Required: {amount}, "
                    f"available: {max(spendable, 0)}"
                    + (f" ({held} tokens are frozen)." if held else ".")
                )
            )

        wallet.balance = wallet.balance - amount
        wallet.save(update_fields=["balance"])

        return WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=TransactionType.DEBIT,
            amount=amount,
            balance_after=wallet.balance,
            status=TransactionStatus.SUCCESS,
            reference_id=reference_id,
            description=description,
        )

    @staticmethod
    @transaction.atomic
    def refund(
        teacher,
        amount: int,
        description: str,
        reference_id: str = None,
    ) -> WalletTransaction:
        """
        Increases the teacher's wallet balance by `amount` tokens as
        a REFUND (distinct transaction_type from CREDIT, even though
        the balance arithmetic is identical) - e.g. an Admin
        reversing a mistaken token deduction. Per the spec's
        permissions ("Admin: Refund Tokens"), the calling view must
        itself enforce that only Admin/SuperAdmin can trigger this -
        this service method does not check the caller's role, since
        service-layer methods are role-agnostic by design (the same
        pattern as every other service in this project); permission
        enforcement belongs in the view/permission class layer.
        """
        if amount <= 0:
            raise ValidationException(detail="Refund amount must be positive.")

        wallet = Wallet.objects.select_for_update().get(teacher=teacher)
        wallet.balance = wallet.balance + amount
        wallet.save(update_fields=["balance"])

        return WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=TransactionType.REFUND,
            amount=amount,
            balance_after=wallet.balance,
            status=TransactionStatus.SUCCESS,
            reference_id=reference_id,
            description=description,
        )

    @staticmethod
    def has_sufficient_balance(teacher, amount: int) -> bool:
        """
        Non-mutating check of *spendable* balance (raw balance minus any
        active WalletHolds), used by callers (e.g. the lead unlock
        workflow) that branch on "can this teacher afford this" BEFORE
        attempting a debit. Does not lock the row - advisory only; debit()
        re-checks atomically under lock.
        """
        wallet = WalletService.get_or_create_wallet(teacher)
        return (wallet.balance - WalletService._active_hold_total(wallet)) >= amount

    @staticmethod
    def get_balance(teacher) -> int:
        """Convenience read - returns the teacher's current raw balance."""
        wallet = WalletService.get_or_create_wallet(teacher)
        return wallet.balance

    @staticmethod
    def _active_hold_total(wallet: Wallet) -> int:
        return (
            WalletHold.objects.filter(wallet=wallet, active=True).aggregate(
                s=Sum("amount")
            )["s"]
            or 0
        )

    @staticmethod
    def available_balance(teacher) -> int:
        """Raw balance minus the sum of active holds, floored at 0."""
        wallet = WalletService.get_or_create_wallet(teacher)
        return max(wallet.balance - WalletService._active_hold_total(wallet), 0)

    @staticmethod
    @transaction.atomic
    def place_hold(teacher, amount: int, reason: str, payment=None) -> WalletHold:
        """
        Freeze `amount` tokens of the teacher's wallet. The balance figure
        is unchanged; spendable balance drops. `amount` is clamped so a
        hold never exceeds the current raw balance (you cannot freeze
        tokens that aren't there - the rest is recorded in `reason`).
        """
        if amount <= 0:
            raise ValidationException(detail="Hold amount must be positive.")
        wallet = Wallet.objects.select_for_update().get(teacher=teacher)
        effective = min(int(amount), wallet.balance)
        if effective <= 0:
            raise ValidationException(
                detail="Nothing to hold - the wallet balance is already zero."
            )
        note = reason
        if effective < amount:
            note = f"{reason} (requested {amount}, only {effective} available)"
        return WalletHold.objects.create(
            wallet=wallet, amount=effective, reason=note[:255], payment=payment
        )

    @staticmethod
    @transaction.atomic
    def release_hold(hold: WalletHold, *, resolution: str = "") -> WalletHold:
        """Lift a hold - the frozen tokens become spendable again."""
        hold = WalletHold.objects.select_for_update().get(pk=hold.pk)
        if not hold.active:
            return hold
        hold.active = False
        hold.released_at = timezone.now()
        hold.resolution = (resolution or "Hold released.")[:255]
        hold.save(update_fields=["active", "released_at", "resolution", "updated_at"])
        return hold

    @staticmethod
    @transaction.atomic
    def settle_hold_as_debit(
        hold: WalletHold, *, description: str, reference_id: str = None
    ) -> WalletHold:
        """
        Convert a hold into a real deduction (dispute lost / chargeback
        upheld). Debits up to the held amount, capped at the current
        balance; any shortfall is recorded on the hold's resolution.
        """
        hold = WalletHold.objects.select_for_update().get(pk=hold.pk)
        if not hold.active:
            return hold
        wallet = Wallet.objects.select_for_update().get(pk=hold.wallet_id)
        to_debit = min(hold.amount, wallet.balance)
        if to_debit > 0:
            wallet.balance = wallet.balance - to_debit
            wallet.save(update_fields=["balance"])
            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type=TransactionType.DEBIT,
                amount=to_debit,
                balance_after=wallet.balance,
                status=TransactionStatus.SUCCESS,
                reference_id=reference_id,
                description=description[:255],
            )
        shortfall = hold.amount - to_debit
        hold.active = False
        hold.released_at = timezone.now()
        hold.resolution = (
            f"Settled as debit of {to_debit} token(s)."
            + (f" Shortfall of {shortfall} (already spent)." if shortfall else "")
        )[:255]
        hold.save(update_fields=["active", "released_at", "resolution", "updated_at"])
        return hold

"""
Service layer for Learning Partner commissions and payouts.

STRUCTURAL ENFORCEMENT (mirrors apps.wallet.services exactly, one level
up): every LearningPartnerWallet.balance change happens inside
LearningPartnerWalletService, atomically alongside the
LearningPartnerWalletTransaction row that explains it. No other module
should ever call wallet.save() after mutating wallet.balance directly.

Entry points other apps call:
    CommissionService.credit_for_payment(payment)
        - apps.payments.services.PaymentService._credit_successful_payment
    CommissionService.reverse_for_payment(payment, reason=...)
        - apps.payments.disputes.DisputeService (refund opened / chargeback lost)
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.commissions.models import (
    Commission,
    CommissionStatus,
    LearningPartnerWallet,
    LearningPartnerWalletTransaction,
    LPTransactionType,
    PayoutRequest,
    PayoutStatus,
)
from apps.core.exceptions.custom_exceptions import ValidationException

# Partner gets 2/3 of the pre-GST base price; the business keeps the
# remaining 1/3 of the base price plus all GST. See Commission.business_share.
_PARTNER_FRACTION = Decimal("2") / Decimal("3")
_CENTS = Decimal("0.01")


class InsufficientCommissionBalanceError(ValidationException):
    default_detail = "Insufficient available commission balance."
    error_code = "INSUFFICIENT_COMMISSION_BALANCE"


def _round_currency(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


class CommissionService:
    """
    Computes and records the partner/business split for a successful
    Payment, and reverses it if the underlying money later comes back
    (refund or lost chargeback). Never instantiated - a namespace for
    related static operations, consistent with WalletService.
    """

    @staticmethod
    @transaction.atomic
    def credit_for_payment(payment) -> Commission:
        """
        Idempotent: if a Commission already exists for this payment
        (verify-API and webhook both reaching SUCCESS, or a webhook
        retry), returns the existing row without crediting twice.
        """
        existing = Commission.objects.filter(payment=payment).first()
        if existing is not None:
            return existing

        base_amount = payment.base_amount
        if base_amount is None:
            # Defensive fallback for any pre-existing Payment row created
            # before this app existed (base_amount is nullable for exactly
            # this reason) - treat the full charged amount as the base
            # rather than crediting nothing.
            base_amount = payment.amount

        learning_partner = payment.teacher.user.learning_partner
        if learning_partner is not None and not learning_partner.is_learning_partner_admin:
            # Defence in depth - User.learning_partner already limits its
            # queryset to role=learning_partner, but a stale/edited row is
            # cheap to guard against here too.
            learning_partner = None

        partner_share = (
            _round_currency(base_amount * _PARTNER_FRACTION)
            if learning_partner is not None
            else Decimal("0.00")
        )
        business_share = payment.amount - partner_share

        commission = Commission.objects.create(
            payment=payment,
            teacher=payment.teacher,
            learning_partner=learning_partner,
            payment_type=payment.payment_type,
            base_amount=base_amount,
            partner_share=partner_share,
            business_share=business_share,
        )

        if learning_partner is not None and partner_share > 0:
            LearningPartnerWalletService.credit(
                learning_partner,
                amount=partner_share,
                description=(
                    f"Commission - {payment.teacher.user.get_full_name()}'s "
                    f"{payment.get_payment_type_display()} purchase"
                ),
                reference_id=str(commission.id),
            )

        return commission

    @staticmethod
    @transaction.atomic
    def reverse_for_payment(payment, *, reason: str) -> Commission | None:
        """
        Claws back a previously-credited commission when the payment
        behind it is refunded or a chargeback against it is lost.
        Idempotent - a Commission can only be reversed once. Safe no-op
        if no Commission row exists at all (e.g. a payment that failed
        before ever succeeding).
        """
        commission = (
            Commission.objects.select_for_update()
            .filter(payment=payment)
            .first()
        )
        if commission is None or commission.status == CommissionStatus.REVERSED:
            return commission

        commission.status = CommissionStatus.REVERSED
        commission.reversed_at = timezone.now()
        commission.reversal_reason = reason[:255]
        commission.save(
            update_fields=["status", "reversed_at", "reversal_reason", "updated_at"]
        )

        if commission.learning_partner_id and commission.partner_share > 0:
            LearningPartnerWalletService.debit(
                commission.learning_partner,
                amount=commission.partner_share,
                description=f"Commission reversed - {reason}"[:255],
                reference_id=str(commission.id),
                allow_negative=True,
            )

        return commission


class LearningPartnerWalletService:
    """All LearningPartnerWallet balance mutations go through here."""

    @staticmethod
    def get_or_create_wallet(learning_partner) -> LearningPartnerWallet:
        wallet, _created = LearningPartnerWallet.objects.get_or_create(
            learning_partner=learning_partner
        )
        return wallet

    @staticmethod
    @transaction.atomic
    def credit(
        learning_partner, *, amount: Decimal, description: str, reference_id: str = None
    ) -> LearningPartnerWalletTransaction:
        if amount <= 0:
            raise ValidationException(detail="Credit amount must be positive.")

        LearningPartnerWalletService.get_or_create_wallet(learning_partner)
        wallet = LearningPartnerWallet.objects.select_for_update().get(
            learning_partner=learning_partner
        )
        wallet.balance = wallet.balance + amount
        wallet.save(update_fields=["balance", "updated_at"])

        return LearningPartnerWalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=LPTransactionType.CREDIT,
            amount=amount,
            balance_after=wallet.balance,
            reference_id=reference_id,
            description=description[:255],
        )

    @staticmethod
    @transaction.atomic
    def debit(
        learning_partner,
        *,
        amount: Decimal,
        description: str,
        reference_id: str = None,
        allow_negative: bool = False,
        transaction_type: str = LPTransactionType.DEBIT,
    ) -> LearningPartnerWalletTransaction:
        if amount <= 0:
            raise ValidationException(detail="Debit amount must be positive.")

        LearningPartnerWalletService.get_or_create_wallet(learning_partner)
        wallet = LearningPartnerWallet.objects.select_for_update().get(
            learning_partner=learning_partner
        )

        if not allow_negative and wallet.balance < amount:
            raise InsufficientCommissionBalanceError(
                detail=(
                    f"Insufficient commission balance. Required: {amount}, "
                    f"available: {wallet.balance}."
                )
            )

        wallet.balance = wallet.balance - amount
        wallet.save(update_fields=["balance", "updated_at"])

        return LearningPartnerWalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=transaction_type,
            amount=amount,
            balance_after=wallet.balance,
            reference_id=reference_id,
            description=description[:255],
        )

    @staticmethod
    def get_balance(learning_partner) -> Decimal:
        wallet = LearningPartnerWalletService.get_or_create_wallet(learning_partner)
        return wallet.balance

    @staticmethod
    def available_balance(learning_partner) -> Decimal:
        """
        Raw balance minus the partner's own PENDING+APPROVED payout
        requests (money already spoken for, not yet debited - debiting
        only happens at mark_paid time, see PayoutService). Floored at 0
        for display purposes; callers that need the raw signed balance
        should use get_balance() instead.
        """
        wallet = LearningPartnerWalletService.get_or_create_wallet(learning_partner)
        reserved = PayoutRequest.objects.filter(
            learning_partner=learning_partner,
            status__in=[PayoutStatus.PENDING, PayoutStatus.APPROVED],
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return max(wallet.balance - reserved, Decimal("0.00"))


class PayoutService:
    """Withdrawal request lifecycle: request -> decide -> mark_paid."""

    @staticmethod
    @transaction.atomic
    def request_payout(learning_partner, *, amount: Decimal) -> PayoutRequest:
        from apps.commissions.models import LearningPartnerBankAccount

        if amount <= 0:
            raise ValidationException(detail="Payout amount must be positive.")

        bank = LearningPartnerBankAccount.objects.filter(
            learning_partner=learning_partner
        ).first()
        if bank is None:
            raise ValidationException(
                detail="Save your bank account details before requesting a payout."
            )

        available = LearningPartnerWalletService.available_balance(learning_partner)
        if amount > available:
            raise InsufficientCommissionBalanceError(
                detail=(
                    f"Requested amount ({amount}) exceeds your available balance "
                    f"({available})."
                )
            )

        return PayoutRequest.objects.create(
            learning_partner=learning_partner,
            amount=amount,
            account_holder_name=bank.account_holder_name,
            account_number=bank.account_number,
            ifsc_code=bank.ifsc_code,
            bank_name=bank.bank_name,
        )

    @staticmethod
    @transaction.atomic
    def decide(payout_request: PayoutRequest, *, admin, approve: bool, notes: str = "") -> PayoutRequest:
        payout_request = PayoutRequest.objects.select_for_update().get(
            pk=payout_request.pk
        )
        if payout_request.status != PayoutStatus.PENDING:
            raise ValidationException(
                detail=f"This payout request is already {payout_request.status}."
            )

        payout_request.status = (
            PayoutStatus.APPROVED if approve else PayoutStatus.REJECTED
        )
        payout_request.decided_by = admin
        payout_request.decided_at = timezone.now()
        payout_request.admin_notes = (notes or "")[:500]
        payout_request.save(
            update_fields=[
                "status",
                "decided_by",
                "decided_at",
                "admin_notes",
                "updated_at",
            ]
        )
        return payout_request

    @staticmethod
    @transaction.atomic
    def mark_paid(
        payout_request: PayoutRequest, *, admin, payout_reference: str
    ) -> PayoutRequest:
        payout_request = PayoutRequest.objects.select_for_update().get(
            pk=payout_request.pk
        )
        if payout_request.status != PayoutStatus.APPROVED:
            raise ValidationException(
                detail="Only an approved payout request can be marked paid."
            )
        if not payout_reference or not payout_reference.strip():
            raise ValidationException(
                detail="A payout reference (bank UTR) is required to mark this paid."
            )

        LearningPartnerWalletService.debit(
            payout_request.learning_partner,
            amount=payout_request.amount,
            description=f"Payout {payout_request.id}",
            reference_id=str(payout_request.id),
            allow_negative=False,
        )

        payout_request.status = PayoutStatus.PAID
        payout_request.payout_reference = payout_reference.strip()[:100]
        payout_request.paid_at = timezone.now()
        if payout_request.decided_by_id is None:
            payout_request.decided_by = admin
            payout_request.decided_at = timezone.now()
        payout_request.save(
            update_fields=[
                "status",
                "payout_reference",
                "paid_at",
                "decided_by",
                "decided_at",
                "updated_at",
            ]
        )
        return payout_request

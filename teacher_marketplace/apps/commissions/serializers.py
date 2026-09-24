"""
Serializers for the commissions app.

Wallet/Commission serializers are read-only, same rationale as
apps.wallet.serializers: balances and ledger rows only ever change via
the service layer, never a client-supplied value. Bank account and
payout-request creation are the only writes exposed here.
"""

from decimal import Decimal

from rest_framework import serializers

from apps.commissions.models import (
    Commission,
    LearningPartnerBankAccount,
    LearningPartnerWallet,
    LearningPartnerWalletTransaction,
    PayoutRequest,
)


class LearningPartnerWalletSerializer(serializers.ModelSerializer):
    available_balance = serializers.SerializerMethodField()

    class Meta:
        model = LearningPartnerWallet
        fields = ("id", "balance", "available_balance", "created_at", "updated_at")
        read_only_fields = fields

    def get_available_balance(self, wallet):
        from apps.commissions.services import LearningPartnerWalletService

        return LearningPartnerWalletService.available_balance(wallet.learning_partner)


class LearningPartnerWalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningPartnerWalletTransaction
        fields = (
            "id",
            "transaction_type",
            "amount",
            "balance_after",
            "reference_id",
            "description",
            "created_at",
        )
        read_only_fields = fields


class CommissionEarningSerializer(serializers.ModelSerializer):
    """
    A Learning Partner's own view of a Commission row - which teacher's
    purchase it came from and how it was split, for transparency /
    self-verification of the 2/3 math.
    """

    teacher_name = serializers.CharField(
        source="teacher.user.get_full_name", read_only=True
    )
    teacher_email = serializers.CharField(source="teacher.user.email", read_only=True)

    class Meta:
        model = Commission
        fields = (
            "id",
            "teacher_name",
            "teacher_email",
            "payment_type",
            "base_amount",
            "partner_share",
            "status",
            "reversed_at",
            "created_at",
        )
        read_only_fields = fields


class LearningPartnerBankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningPartnerBankAccount
        fields = (
            "id",
            "account_holder_name",
            "account_number",
            "ifsc_code",
            "bank_name",
            "updated_at",
        )
        read_only_fields = ("id", "updated_at")

    def validate_account_number(self, value):
        value = value.strip()
        if not value.isalnum() or not (5 <= len(value) <= 34):
            raise serializers.ValidationError("Enter a valid account number.")
        return value

    def validate_ifsc_code(self, value):
        value = value.strip().upper()
        if len(value) != 11 or not value.isalnum():
            raise serializers.ValidationError("Enter a valid 11-character IFSC code.")
        return value


class PayoutRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutRequest
        fields = (
            "id",
            "amount",
            "account_holder_name",
            "account_number",
            "ifsc_code",
            "bank_name",
            "status",
            "admin_notes",
            "payout_reference",
            "decided_at",
            "paid_at",
            "created_at",
        )
        read_only_fields = fields


class PayoutRequestCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("1.00")
    )


class PayoutDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500)


class PayoutMarkPaidSerializer(serializers.Serializer):
    payout_reference = serializers.CharField(max_length=100)


class AdminPayoutRequestSerializer(serializers.ModelSerializer):
    """Admin-side view: includes who the partner is, not just their bank details."""

    learning_partner_name = serializers.CharField(
        source="learning_partner.first_name", read_only=True
    )
    learning_partner_email = serializers.CharField(
        source="learning_partner.email", read_only=True
    )
    decided_by_email = serializers.CharField(
        source="decided_by.email", read_only=True, default=None
    )

    class Meta:
        model = PayoutRequest
        fields = (
            "id",
            "learning_partner_name",
            "learning_partner_email",
            "amount",
            "account_holder_name",
            "account_number",
            "ifsc_code",
            "bank_name",
            "status",
            "admin_notes",
            "payout_reference",
            "decided_by_email",
            "decided_at",
            "paid_at",
            "created_at",
        )
        read_only_fields = fields

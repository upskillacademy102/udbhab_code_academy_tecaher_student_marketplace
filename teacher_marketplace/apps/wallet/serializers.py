"""
Serializers for the wallet app.

No write serializer exists here for Wallet or WalletTransaction -
per the business rule "No direct modification of Wallet Balance",
there is no API endpoint that accepts a client-supplied balance or
transaction. Both serializers are strictly read-only, reflecting
state that changes only via apps.wallet.services.WalletService,
called from apps.payments (credits) and apps.lead_engine (debits).
"""

from rest_framework import serializers

from apps.wallet.models import Wallet, WalletTransaction


class WalletTransactionSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a single wallet transaction, used
    for GET /api/v1/wallet/history/.
    """

    class Meta:
        model = WalletTransaction
        fields = (
            "id",
            "transaction_type",
            "amount",
            "balance_after",
            "status",
            "reference_id",
            "description",
            "created_at",
        )
        read_only_fields = fields


class WalletSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a Teacher's Wallet, used for
    GET /api/v1/wallet/. Does not nest the full transaction list
    (that's a separate, paginated endpoint - /wallet/history/) to
    keep this response lightweight for frequent balance checks
    (e.g. a dashboard widget polling balance).
    """

    class Meta:
        model = Wallet
        fields = ("id", "balance", "created_at", "updated_at")
        read_only_fields = fields

"""Serializers for the finance app."""

from decimal import Decimal

from rest_framework import serializers

from apps.finance.models import PricingChangeRequest, PricingTargetType


class PricingChangeRequestSerializer(serializers.ModelSerializer):
    requested_by_email = serializers.CharField(source="requested_by.email", read_only=True)
    decided_by_email = serializers.CharField(
        source="decided_by.email", read_only=True, default=None
    )
    target_name = serializers.SerializerMethodField()

    class Meta:
        model = PricingChangeRequest
        fields = (
            "id",
            "target_type",
            "target_name",
            "field_name",
            "current_value",
            "requested_value",
            "status",
            "requested_by_email",
            "note",
            "decided_by_email",
            "decided_at",
            "decision_note",
            "created_at",
        )
        read_only_fields = fields

    def get_target_name(self, obj):
        target = obj.target
        if target is None:
            return None
        # TokenPackage/SubscriptionPlan have `.name`; LeadUnlockPricing has
        # no name field, only `.tier` (a PricingTier choice) - fall back to
        # its display label so every target type gets a real label.
        name = getattr(target, "name", None)
        if name is not None:
            return name
        return target.get_tier_display() if hasattr(target, "get_tier_display") else str(target)


class PricingChangeRequestCreateSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(choices=PricingTargetType.choices)
    target_id = serializers.UUIDField()
    requested_value = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class PricingChangeDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)

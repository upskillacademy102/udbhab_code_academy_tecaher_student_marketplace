"""
Serializers for the subscriptions app.
"""

from rest_framework import serializers

from apps.subscriptions.models import (
    MonthlyLeadQuota,
    SubscriptionPlan,
    TeacherSubscription,
)


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """Read representation of a SubscriptionPlan."""

    discount_percent = serializers.IntegerField(read_only=True, allow_null=True)
    # free_leads is the TOTAL allowance; base_leads + bonus_leads is only how
    # that total is advertised ("8 + 2 bonus"). Never sum base and total.
    base_leads = serializers.IntegerField(read_only=True)

    class Meta:
        model = SubscriptionPlan
        fields = (
            "id",
            "name",
            "monthly_price",
            "compare_at_price",
            "discount_percent",
            "free_leads",
            "base_leads",
            "bonus_leads",
            "priority_rank",
            "is_featured_listing",
            "lead_multiplier",
            "bonus_tokens",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class SubscriptionPlanWriteSerializer(serializers.ModelSerializer):
    """Admin-only write representation for managing SubscriptionPlans."""

    class Meta:
        model = SubscriptionPlan
        fields = (
            "id",
            "name",
            "monthly_price",
            "compare_at_price",
            "free_leads",
            "bonus_leads",
            "priority_rank",
            "is_featured_listing",
            "lead_multiplier",
            "bonus_tokens",
            "status",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        # bonus_leads is a slice of free_leads, not an addition to it - the
        # DB CHECK enforces this too, but catching it here gives the admin a
        # field error instead of an IntegrityError.
        free_leads = attrs.get(
            "free_leads", getattr(self.instance, "free_leads", 0)
        )
        bonus_leads = attrs.get(
            "bonus_leads", getattr(self.instance, "bonus_leads", 0)
        )
        if bonus_leads > free_leads:
            raise serializers.ValidationError(
                {
                    "bonus_leads": (
                        "Bonus unlocks are counted inside the total allowance, "
                        "so they cannot exceed it."
                    )
                }
            )
        return attrs

    def validate_name(self, value):
        return value.strip() if isinstance(value, str) else value

    def validate_monthly_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Monthly price cannot be negative.")
        return value

    def validate_free_leads(self, value):
        if value < 0:
            raise serializers.ValidationError("Free leads cannot be negative.")
        return value

    def validate(self, attrs):
        compare_at = attrs.get(
            "compare_at_price",
            getattr(self.instance, "compare_at_price", None),
        )
        monthly = attrs.get(
            "monthly_price", getattr(self.instance, "monthly_price", None)
        )
        if compare_at is not None and monthly is not None and compare_at <= monthly:
            raise serializers.ValidationError(
                {
                    "compare_at_price": "The struck-through price must be higher "
                    "than the actual monthly price, or left blank."
                }
            )
        return attrs


class TeacherSubscriptionSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a single TeacherSubscription.
    Nests the plan's full details (not just its id) since a
    subscription record without knowing what the plan actually
    offered isn't very useful for display, and used both for the
    current-subscription endpoint and the history list.
    """

    plan = SubscriptionPlanSerializer(read_only=True)
    is_active_now = serializers.BooleanField(read_only=True)

    class Meta:
        model = TeacherSubscription
        fields = (
            "id",
            "plan",
            "status",
            "start_date",
            "end_date",
            "is_active_now",
            "created_at",
        )
        read_only_fields = fields


class MonthlyLeadQuotaSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a teacher's allowance for the entitlement
    period they are currently inside - used by the Teacher Dashboard
    (apps.analytics), the leads screen's allowance banner, and the
    standalone /subscriptions/quota/ endpoint.

    days_until_reset drives the "resets in N days" line the teacher sees;
    it is derived from period_end rather than stored.
    """

    remaining_free_leads = serializers.IntegerField(read_only=True)
    has_free_leads_remaining = serializers.BooleanField(read_only=True)
    days_until_reset = serializers.IntegerField(read_only=True)

    class Meta:
        model = MonthlyLeadQuota
        fields = (
            "id",
            "period_start",
            "period_end",
            "days_until_reset",
            "total_free_leads",
            "used_free_leads",
            "remaining_free_leads",
            "has_free_leads_remaining",
            "created_at",
        )
        read_only_fields = fields

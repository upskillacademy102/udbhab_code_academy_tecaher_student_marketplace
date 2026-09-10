from rest_framework import serializers

from apps.ops.models import AuditLog
from apps.trust.models import AccountSanction, ManualReviewItem


class ReviewQueueItemSerializer(serializers.ModelSerializer):
    subject_email = serializers.CharField(
        source="subject_user.email", read_only=True, default=""
    )
    assignee_email = serializers.CharField(
        source="assignee.email", read_only=True, default=""
    )
    subject_risk_state = serializers.SerializerMethodField()

    class Meta:
        model = ManualReviewItem
        fields = (
            "id",
            "kind",
            "status",
            "priority",
            "summary",
            "payload",
            "subject_user",
            "subject_email",
            "subject_risk_state",
            "assignee",
            "assignee_email",
            "resolution",
            "resolved_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_subject_risk_state(self, obj) -> str:
        tp = getattr(
            getattr(obj.subject_user, "trust_profile", None), "risk_state", None
        )
        return tp or ""


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = (
            "id",
            "created_at",
            "actor",
            "actor_email",
            "actor_role",
            "actor_name",
            "category",
            "action",
            "status",
            "target_type",
            "target_id",
            "target_repr",
            "message",
            "metadata",
            "ip_address",
            "user_agent",
        )
        read_only_fields = fields

    def get_actor_name(self, obj) -> str:
        if obj.actor:
            return obj.actor.get_full_name() or obj.actor.email
        return obj.actor_email or "system"


class AccountSanctionSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.get_full_name", read_only=True)
    user_role = serializers.CharField(source="user.role", read_only=True)
    user_active = serializers.BooleanField(source="user.is_active", read_only=True)
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True, default=""
    )
    lifted_by_email = serializers.CharField(
        source="lifted_by.email", read_only=True, default=""
    )
    is_automatic = serializers.BooleanField(read_only=True)

    class Meta:
        model = AccountSanction
        fields = (
            "id",
            "user",
            "user_email",
            "user_name",
            "user_role",
            "user_active",
            "kind",
            "source",
            "is_automatic",
            "reason",
            "created_by",
            "created_by_email",
            "review_item",
            "payload",
            "active",
            "lifted_at",
            "lifted_by_email",
            "lift_reason",
            "created_at",
        )
        read_only_fields = fields

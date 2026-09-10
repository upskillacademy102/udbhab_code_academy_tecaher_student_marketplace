from rest_framework import serializers

from apps.support.models import SupportTicket, SupportTicketAttachment


class SupportTicketAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicketAttachment
        fields = ("id", "file")
        read_only_fields = fields


class SupportTicketSerializer(serializers.ModelSerializer):
    """The reporter's own view of their ticket."""

    attachments = SupportTicketAttachmentSerializer(many=True, read_only=True)
    assigned_admin_names = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = (
            "id",
            "subject",
            "description",
            "contact_preference",
            "status",
            "assigned_admin_names",
            "resolution",
            "resolved_at",
            "attachments",
            "created_at",
        )
        read_only_fields = fields

    def get_assigned_admin_names(self, obj) -> list:
        return [a.get_full_name() or a.email for a in obj.assigned_admins.all()]


class AdminSupportTicketSerializer(SupportTicketSerializer):
    """The Admin/Super-Admin view - adds who reported it and their ids."""

    reporter_name = serializers.CharField(
        source="reporter.get_full_name", read_only=True
    )
    reporter_email = serializers.EmailField(source="reporter.email", read_only=True)
    reporter_role = serializers.CharField(source="reporter.role", read_only=True)
    assigned_admin_ids = serializers.PrimaryKeyRelatedField(
        source="assigned_admins", many=True, read_only=True
    )

    class Meta(SupportTicketSerializer.Meta):
        fields = SupportTicketSerializer.Meta.fields + (
            "reporter_name",
            "reporter_email",
            "reporter_role",
            "assigned_admin_ids",
        )
        read_only_fields = fields

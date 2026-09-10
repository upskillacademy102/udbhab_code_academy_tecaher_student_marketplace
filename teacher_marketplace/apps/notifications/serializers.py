"""
Serializers for the notifications app.

No write serializer for creating notifications - per
NotificationService's design, notifications are only ever created
via NotificationService.notify(), never through a direct client
POST. The only client-facing "write" action is marking a
notification as read, handled via a dedicated small serializer.
"""

from rest_framework import serializers

from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only representation of a Notification."""

    class Meta:
        model = Notification
        fields = (
            "id",
            "event",
            "title",
            "message",
            "reference_id",
            "is_read",
            "is_email_sent",
            "created_at",
        )
        read_only_fields = fields


class MarkNotificationReadSerializer(serializers.Serializer):
    """
    Validates the request body for marking one or more
    notifications as read. Accepts a list of ids so a frontend can
    mark several as read in one call (e.g. "mark all visible as
    read") without N separate requests.
    """

    notification_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=True,
        allow_empty=False,
    )

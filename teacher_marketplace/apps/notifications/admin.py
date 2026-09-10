"""
Django Admin configuration for the notifications app.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """
    Fully read-only admin for browsing notifications platform-wide -
    useful for support/debugging ("did this teacher actually get
    notified about X"). Created exclusively via
    apps.notifications.services.NotificationService.notify().
    """

    list_display = (
        "get_user_name",
        "event",
        "title",
        "is_read",
        "is_email_sent",
        "created_at",
    )
    list_filter = ("event", "is_read", "is_email_sent")
    search_fields = ("user__email", "user__first_name", "title", "message")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "user",
        "event",
        "title",
        "message",
        "reference_id",
        "is_read",
        "is_email_sent",
        "email_error",
        "created_at",
        "updated_at",
        "deleted_at",
    )

    @admin.display(description=_("User"), ordering="user__first_name")
    def get_user_name(self, obj):
        return obj.user.get_full_name()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related("user").get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

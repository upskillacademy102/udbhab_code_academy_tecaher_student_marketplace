"""Django admin for the support (Connect to Admin) app."""

from django.contrib import admin

from apps.support.models import SupportTicket, SupportTicketAttachment


class SupportTicketAttachmentInline(admin.TabularInline):
    model = SupportTicketAttachment
    extra = 0
    readonly_fields = ("file", "created_at")
    can_delete = False


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        "subject",
        "reporter",
        "status",
        "contact_preference",
        "created_at",
    )
    list_filter = ("status", "contact_preference")
    search_fields = ("subject", "description", "reporter__email")
    filter_horizontal = ("assigned_admins",)
    readonly_fields = ("id", "reporter", "review_item", "created_at", "updated_at")
    inlines = [SupportTicketAttachmentInline]

    def has_add_permission(self, request):
        return False

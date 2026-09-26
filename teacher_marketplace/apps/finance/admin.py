from django.contrib import admin

from apps.finance.models import PricingChangeRequest


@admin.register(PricingChangeRequest)
class PricingChangeRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "target_type",
        "field_name",
        "current_value",
        "requested_value",
        "status",
        "requested_by",
        "decided_by",
        "created_at",
    )
    list_filter = ("status", "target_type")
    search_fields = ("requested_by__email", "decided_by__email")
    readonly_fields = [f.name for f in PricingChangeRequest._meta.fields]

    def has_add_permission(self, request):
        return False

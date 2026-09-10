from django.contrib import admin

from apps.ops.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "actor_email",
        "actor_role",
        "category",
        "action",
        "status",
        "target_repr",
    )
    list_filter = ("category", "status", "actor_role", "created_at")
    search_fields = ("actor_email", "action", "target_repr", "message", "ip_address")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

"""Django Admin configuration for the grade_levels app."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.grade_levels.models import GradeLevel


@admin.register(GradeLevel)
class GradeLevelAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "is_active", "is_deleted", "created_at")
    list_filter = ("is_active", "is_deleted")
    search_fields = ("name",)
    ordering = ("sort_order", "name")
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")

    fieldsets = (
        (None, {"fields": ("id", "name", "sort_order")}),
        (_("Status"), {"fields": ("is_active",)}),
        (
            _("Soft Delete"),
            {"fields": ("is_deleted", "deleted_at"), "classes": ("collapse",)},
        ),
        (
            _("Timestamps"),
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def get_queryset(self, request):
        qs = self.model.all_objects.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

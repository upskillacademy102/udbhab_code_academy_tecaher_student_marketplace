"""
Django Admin configuration for the languages app.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.languages.models import Language


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    """
    Admin configuration for Language reference data.
    """

    list_display = (
        "name",
        "code",
        "is_active",
        "is_deleted",
        "created_at",
    )
    list_filter = ("is_active", "is_deleted")
    search_fields = ("name", "code")
    ordering = ("name",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")

    fieldsets = (
        (None, {"fields": ("id", "name", "code")}),
        (
            _("Status"),
            {"fields": ("is_active",)},
        ),
        (
            _("Soft Delete"),
            {
                "fields": ("is_deleted", "deleted_at"),
                "classes": ("collapse",),
            },
        ),
        (
            _("Timestamps"),
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """
        Uses all_objects (soft-delete-aware) so soft-deleted
        languages remain visible/restorable in Django Admin - same
        pattern established across every admin class so far.
        """
        qs = self.model.all_objects.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

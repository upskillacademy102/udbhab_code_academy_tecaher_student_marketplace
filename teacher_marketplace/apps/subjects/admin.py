"""
Django Admin configuration for the subjects app.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.subjects.models import Subject


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    """
    Admin configuration for Subject reference data. Uses
    prepopulated_fields so the slug auto-fills from the name field
    as an admin types, with the option to override manually before
    saving.
    """

    list_display = (
        "name",
        "slug",
        "is_active",
        "is_deleted",
        "created_at",
    )
    list_filter = ("is_active", "is_deleted")
    search_fields = ("name", "slug", "description")
    ordering = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")

    fieldsets = (
        (None, {"fields": ("id", "name", "slug")}),
        (
            _("Details"),
            {"fields": ("description", "icon", "is_active")},
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
        subjects remain visible/restorable in Django Admin - same
        pattern established in Phase 1's UserAdmin/StudentAdmin/
        TeacherAdmin.
        """
        qs = self.model.all_objects.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

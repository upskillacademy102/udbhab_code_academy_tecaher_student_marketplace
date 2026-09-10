"""
Django Admin configuration for the teachers app.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.teachers.models import Teacher


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    """
    Admin configuration for Teacher profiles. Uses select_related
    on the list queryset to avoid an N+1 query per row when
    displaying the related user's email/name in list_display.
    """

    list_display = (
        "get_user_email",
        "get_user_full_name",
        "qualification_level",
        "experience_years",
        "city",
        "state",
        "country",
        "is_deleted",
        "created_at",
    )
    list_filter = (
        "qualification_level",
        "city",
        "state",
        "country",
        "is_deleted",
    )
    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "city",
        "subjects_taught",
        "qualification_detail",
    )
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("user",)

    fieldsets = (
        (None, {"fields": ("id", "user")}),
        (
            _("Profile"),
            {
                "fields": (
                    "profile_photo",
                    "bio",
                    "experience_years",
                )
            },
        ),
        (
            _("Qualification"),
            {"fields": ("qualification_level", "qualification_detail")},
        ),
        (
            _("Subjects"),
            {"fields": ("subjects_taught",)},
        ),
        (
            _("Location"),
            {"fields": ("city", "state", "country")},
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

    @admin.display(description=_("Email"), ordering="user__email")
    def get_user_email(self, obj):
        return obj.user.email

    @admin.display(description=_("Full Name"), ordering="user__first_name")
    def get_user_full_name(self, obj):
        return obj.user.get_full_name()

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related("user").get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

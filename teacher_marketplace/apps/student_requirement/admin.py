"""
Django Admin configuration for the student_requirement app.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.student_requirement.models import (
    StudentRequirement,
    StudentRequirementLanguage,
    StudentScheduleException,
    StudentSchedulePreference,
)


class StudentRequirementLanguageInline(admin.TabularInline):
    """Read-heavy inline so the ranked list is visible on the requirement
    itself, same reasoning as pulling schedule preferences onto one screen."""

    model = StudentRequirementLanguage
    extra = 0
    fields = ("rank", "language")
    autocomplete_fields = ("language",)
    ordering = ("rank",)


@admin.register(StudentRequirement)
class StudentRequirementAdmin(admin.ModelAdmin):
    """
    Admin configuration for StudentRequirement. Surfaces the key
    matching-relevant fields (subject, mode, city, status) in the
    list view for quick operational review.
    """

    list_display = (
        "get_student_name",
        "subject",
        "student_class",
        "teaching_mode",
        "city",
        "budget_min",
        "budget_max",
        "status",
        "created_at",
    )
    list_filter = (
        "status",
        "teaching_mode",
        "subject",
        "no_language_preference",
        "city",
        "is_deleted",
    )
    search_fields = (
        "student__email",
        "student__first_name",
        "student__last_name",
        "subject__name",
        "description",
    )
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("student", "subject", "city")
    inlines = (StudentRequirementLanguageInline,)

    fieldsets = (
        (None, {"fields": ("id", "student", "subject", "student_class")}),
        (
            _("Preferences"),
            {
                "fields": (
                    "no_language_preference",
                    "teaching_mode",
                    "city",
                    "preferred_timing",
                )
            },
        ),
        (
            _("Budget"),
            {"fields": ("budget_min", "budget_max")},
        ),
        (
            _("Details"),
            {"fields": ("description", "status")},
        ),
        (
            _("Soft Delete"),
            {"fields": ("is_deleted", "deleted_at"), "classes": ("collapse",)},
        ),
        (
            _("Timestamps"),
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    @admin.display(description=_("Student"), ordering="student__first_name")
    def get_student_name(self, obj):
        return obj.student.get_full_name()

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "student", "subject", "city"
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


@admin.register(StudentSchedulePreference)
class StudentSchedulePreferenceAdmin(admin.ModelAdmin):
    """
    Read-heavy admin for student schedule preferences - satisfies
    "Admin should be able to view: Student Preferred Schedules."
    """

    list_display = (
        "get_student_name",
        "get_day_display",
        "start_time",
        "end_time",
        "timezone",
        "flexibility",
        "priority",
    )
    list_filter = ("day_of_week", "flexibility", "priority")
    search_fields = (
        "student_requirement__student__email",
        "student_requirement__student__first_name",
    )
    ordering = ("student_requirement", "day_of_week", "start_time")
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("student_requirement",)

    @admin.display(
        description=_("Student"), ordering="student_requirement__student__first_name"
    )
    def get_student_name(self, obj):
        return obj.student_requirement.student.get_full_name()

    @admin.display(description=_("Day"), ordering="day_of_week")
    def get_day_display(self, obj):
        return obj.get_day_of_week_display()

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "student_requirement", "student_requirement__student"
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


@admin.register(StudentScheduleException)
class StudentScheduleExceptionAdmin(admin.ModelAdmin):
    """Admin for one-off student schedule exceptions."""

    list_display = ("get_student_name", "date", "reason")
    list_filter = ("date",)
    search_fields = ("student_requirement__student__email", "reason")
    ordering = ("-date",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("student_requirement",)

    @admin.display(description=_("Student"))
    def get_student_name(self, obj):
        return obj.student_requirement.student.get_full_name()

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "student_requirement", "student_requirement__student"
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

"""
Django Admin configuration for the teacher_profile app.

This is where Admin-driven Teacher Verification (per the spec's
Admin Panel requirements) actually happens - an admin reviews a
TeacherProfile and changes verification_status from Pending to
Verified/Rejected here.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.teacher_profile.models import (
    TeacherAvailability,
    TeacherProfile,
    TeacherScheduleException,
    TeacherWeeklyAvailability,
)


class TeacherAvailabilityInline(admin.TabularInline):
    """
    Lets an admin view/manage a teacher's availability slots
    directly from their TeacherProfile detail page, rather than
    navigating to a separate list.
    """

    model = TeacherAvailability
    extra = 0
    fields = ("day_type", "time_slot")


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    """
    Admin configuration for TeacherProfile. list_display surfaces
    verification_status prominently since reviewing/verifying
    teachers is a primary admin workflow for this model.
    """

    list_display = (
        "get_teacher_name",
        "get_teacher_email",
        "headline",
        "teaching_mode",
        "hourly_rate",
        "rating",
        "verification_status",
        "is_deleted",
        "created_at",
    )
    list_filter = (
        "verification_status",
        "teaching_mode",
        "is_deleted",
        "subjects",
        "languages",
        "cities",
    )
    search_fields = (
        "teacher__user__email",
        "teacher__user__first_name",
        "teacher__user__last_name",
        "headline",
    )
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("teacher",)
    filter_horizontal = ("subjects", "languages", "cities")
    inlines = [TeacherAvailabilityInline]

    fieldsets = (
        (None, {"fields": ("id", "teacher", "headline")}),
        (
            _("Professional Details"),
            {
                "fields": (
                    "teaching_mode",
                    "hourly_rate",
                    "rating",
                )
            },
        ),
        (
            _("Verification"),
            {
                "fields": ("verification_status",),
                "description": _(
                    "Changing this to 'Verified' marks the teacher as "
                    "verified across the platform - this affects search "
                    "ranking and the 'Verified Teacher' filter."
                ),
            },
        ),
        (
            _("Taxonomy"),
            {"fields": ("subjects", "languages", "cities")},
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

    actions = [
        "mark_verified",
        "mark_rejected",
        "clear_moderation_hold",
        "hold_for_moderation",
    ]

    @admin.display(description=_("Teacher"), ordering="teacher__user__first_name")
    def get_teacher_name(self, obj):
        return obj.teacher.user.get_full_name()

    @admin.display(description=_("Email"), ordering="teacher__user__email")
    def get_teacher_email(self, obj):
        return obj.teacher.user.email

    @admin.action(description=_("Mark selected profiles as Verified"))
    def mark_verified(self, request, queryset):
        updated = queryset.update(verification_status="verified")
        self.message_user(request, f"{updated} teacher profile(s) marked as Verified.")

    @admin.action(description=_("Mark selected profiles as Rejected"))
    def mark_rejected(self, request, queryset):
        updated = queryset.update(verification_status="rejected")
        self.message_user(request, f"{updated} teacher profile(s) marked as Rejected.")

    @admin.action(description=_("Clear content-moderation hold (make visible again)"))
    def clear_moderation_hold(self, request, queryset):
        from apps.trust.models import ContentFlag, ContentFlagStatus
        from apps.trust.services.trust_service import TrustService

        n = 0
        for profile in queryset:
            profile.moderation_status = "clear"
            profile.save(update_fields=["moderation_status"])
            flags = ContentFlag.objects.filter(
                subject_user=profile.teacher.user,
                surface__startswith="teacher_profile.",
                status=ContentFlagStatus.OPEN,
            ).select_related("review_item")
            for flag in flags:
                flag.status = ContentFlagStatus.DISMISSED
                flag.save(update_fields=["status"])
                if flag.review_item and flag.review_item.status in (
                    "open",
                    "in_review",
                ):
                    TrustService.resolve_review_item(
                        flag.review_item,
                        by=request.user,
                        resolution="Cleared by admin.",
                        dismiss=True,
                    )
            n += 1
        self.message_user(request, f"Cleared moderation hold on {n} profile(s).")

    @admin.action(description=_("Hold selected profiles for content review"))
    def hold_for_moderation(self, request, queryset):
        updated = queryset.update(moderation_status="held")
        self.message_user(request, f"{updated} teacher profile(s) held for review.")

    def get_queryset(self, request):
        qs = (
            self.model.all_objects.select_related("teacher", "teacher__user")
            .prefetch_related("subjects", "languages", "cities")
            .get_queryset()
        )
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


@admin.register(TeacherAvailability)
class TeacherAvailabilityAdmin(admin.ModelAdmin):
    """
    Standalone admin for TeacherAvailability, in addition to the
    inline on TeacherProfileAdmin - useful for bulk-browsing/
    auditing availability data across all teachers at once, which
    the inline view doesn't support.
    """

    list_display = ("get_teacher_name", "day_type", "time_slot", "created_at")
    list_filter = ("day_type", "time_slot")
    search_fields = (
        "teacher_profile__teacher__user__email",
        "teacher_profile__teacher__user__first_name",
    )
    autocomplete_fields = ("teacher_profile",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")

    @admin.display(description=_("Teacher"))
    def get_teacher_name(self, obj):
        return obj.teacher_profile.teacher.user.get_full_name()

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "teacher_profile",
            "teacher_profile__teacher",
            "teacher_profile__teacher__user",
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


@admin.register(TeacherWeeklyAvailability)
class TeacherWeeklyAvailabilityAdmin(admin.ModelAdmin):
    """
    Read-heavy admin for the new structured availability model -
    satisfies "Admin should be able to view: Teacher Availability."
    Created/edited primarily via
    apps.teacher_profile.services.availability_service.AvailabilityService
    (which enforces overlap-prevention and cache invalidation), but
    left EDITABLE here (unlike the fully-locked audit-log admins
    elsewhere in this project) since an admin correcting a teacher's
    schedule directly is a legitimate support operation - overlap
    validation still applies via full_clean() on save through the
    admin form.
    """

    list_display = (
        "get_teacher_name",
        "get_day_display",
        "start_time",
        "end_time",
        "timezone",
        "is_active",
    )
    list_filter = ("day_of_week", "is_active", "timezone")
    search_fields = (
        "teacher_profile__teacher__user__email",
        "teacher_profile__teacher__user__first_name",
    )
    ordering = ("teacher_profile", "day_of_week", "start_time")
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("teacher_profile",)

    @admin.display(
        description=_("Teacher"), ordering="teacher_profile__teacher__user__first_name"
    )
    def get_teacher_name(self, obj):
        return obj.teacher_profile.teacher.user.get_full_name()

    @admin.display(description=_("Day"), ordering="day_of_week")
    def get_day_display(self, obj):
        return obj.get_day_of_week_display()

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "teacher_profile",
            "teacher_profile__teacher",
            "teacher_profile__teacher__user",
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


@admin.register(TeacherScheduleException)
class TeacherScheduleExceptionAdmin(admin.ModelAdmin):
    """Admin for one-off teacher schedule exceptions."""

    list_display = ("get_teacher_name", "exception_type", "date", "get_scope", "reason")
    list_filter = ("exception_type", "date")
    search_fields = ("teacher_profile__teacher__user__email", "reason")
    ordering = ("-date",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("teacher_profile",)

    @admin.display(description=_("Teacher"))
    def get_teacher_name(self, obj):
        return obj.teacher_profile.teacher.user.get_full_name()

    @admin.display(description=_("Scope"))
    def get_scope(self, obj):
        return "Full day" if obj.is_full_day else f"{obj.start_time}-{obj.end_time}"

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "teacher_profile",
            "teacher_profile__teacher",
            "teacher_profile__teacher__user",
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

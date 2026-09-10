"""
Django Admin configuration for the subscriptions app.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.subscriptions.models import (
    MonthlyLeadQuota,
    SubscriptionPlan,
    TeacherSubscription,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    """
    Admin configuration for SubscriptionPlan - where an operator
    configures the Free/Professional/Elite tiers per the spec.

    NOTE on priority_rank/lead_multiplier: these fields are stored
    and editable here, but (per the documented caveat in
    models.py) are not yet consumed by apps.search's ranking logic
    or apps.lead_engine's matching algorithm in Phase 3. Editing
    them here has no live effect on search/matching yet.
    """

    list_display = (
        "name",
        "monthly_price",
        "free_leads",
        "priority_rank",
        "is_featured_listing",
        "lead_multiplier",
        "bonus_tokens",
        "status",
    )
    list_filter = ("status", "is_featured_listing")
    search_fields = ("name",)
    ordering = ("monthly_price",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")

    fieldsets = (
        (None, {"fields": ("id", "name", "status")}),
        (
            _("Pricing & Leads"),
            {"fields": ("monthly_price", "free_leads", "bonus_tokens")},
        ),
        (
            _("Ranking & Visibility (not yet applied to search - see docstring)"),
            {"fields": ("priority_rank", "is_featured_listing", "lead_multiplier")},
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

    def get_queryset(self, request):
        qs = self.model.all_objects.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


@admin.register(TeacherSubscription)
class TeacherSubscriptionAdmin(admin.ModelAdmin):
    """
    Read-heavy admin for subscription records - subscriptions are
    only ever created via SubscriptionService, never manually, to
    guarantee bonus_tokens crediting and quota refresh always
    happen together with subscription creation.
    """

    list_display = (
        "get_teacher_name",
        "plan",
        "status",
        "start_date",
        "end_date",
        "get_is_active_now",
    )
    list_filter = ("status", "plan")
    search_fields = ("teacher__user__email", "teacher__user__first_name", "plan__name")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "teacher",
        "plan",
        "status",
        "start_date",
        "end_date",
        "payment",
        "created_at",
        "updated_at",
        "deleted_at",
    )

    @admin.display(description=_("Teacher"), ordering="teacher__user__first_name")
    def get_teacher_name(self, obj):
        return obj.teacher.user.get_full_name()

    @admin.display(description=_("Active Now"), boolean=True)
    def get_is_active_now(self, obj):
        return obj.is_active_now

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "teacher", "teacher__user", "plan", "payment"
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


@admin.register(MonthlyLeadQuota)
class MonthlyLeadQuotaAdmin(admin.ModelAdmin):
    """
    Read-heavy admin for allowance tracking - useful for
    support/debugging ("why can't this teacher unlock a lead this
    cycle"). used_free_leads is only ever incremented via
    LeadQuotaService.consume_free_lead, never edited directly here.

    Rows are keyed on a rolling entitlement period, not a calendar
    month, so a teacher accumulates one row per 30-day cycle.
    """

    list_display = (
        "get_teacher_name",
        "period_start",
        "period_end",
        "total_free_leads",
        "used_free_leads",
        "get_remaining",
    )
    list_filter = ("period_start",)
    search_fields = ("teacher__user__email", "teacher__user__first_name")
    ordering = ("-period_start",)
    readonly_fields = (
        "id",
        "teacher",
        "period_start",
        "period_end",
        "total_free_leads",
        "used_free_leads",
        "created_at",
        "updated_at",
        "deleted_at",
    )

    @admin.display(description=_("Teacher"), ordering="teacher__user__first_name")
    def get_teacher_name(self, obj):
        return obj.teacher.user.get_full_name()

    @admin.display(description=_("Remaining"))
    def get_remaining(self, obj):
        return obj.remaining_free_leads

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "teacher", "teacher__user"
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

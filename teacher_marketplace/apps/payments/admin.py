"""
Django Admin configuration for the payments app.
"""

from django.contrib import admin
from django.db.models import Count, Sum
from django.utils.translation import gettext_lazy as _

from apps.payments.models import (
    Payment,
    PaymentDispute,
    PaymentInstrumentSignature,
    PaymentStatus,
    PaymentWebhook,
    ReconciliationRun,
    TokenPackage,
)


@admin.register(TokenPackage)
class TokenPackageAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "token_count",
        "price",
        "gst_percentage",
        "discount_percentage",
        "get_final_price",
        "is_active",
        "sort_order",
    )
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("sort_order", "price")
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")

    fieldsets = (
        (None, {"fields": ("id", "name", "sort_order", "is_active")}),
        (
            _("Pricing"),
            {
                "fields": (
                    "token_count",
                    "price",
                    "gst_percentage",
                    "discount_percentage",
                )
            },
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

    @admin.display(description=_("Final Price"))
    def get_final_price(self, obj):
        return f"₹{obj.final_price}"

    def get_queryset(self, request):
        qs = self.model.all_objects.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


class PaymentWebhookInline(admin.TabularInline):
    """
    Shows the raw webhook events linked to a Payment directly on
    its admin detail page - useful for debugging a specific
    payment's lifecycle without cross-referencing the separate
    PaymentWebhook admin list.
    """

    model = PaymentWebhook
    extra = 0
    fields = (
        "event_type",
        "razorpay_event_id",
        "is_processed",
        "processing_error",
        "created_at",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    Read-heavy admin for Payment records - the "Payments" and
    contributor to "Revenue Reports" from the spec's Admin Panel
    requirements. Status/amounts are readonly since payment state
    should only ever change via PaymentService (verify/webhook
    flows), never a manual admin edit that could desync from
    Razorpay's actual record of what happened.
    """

    list_display = (
        "razorpay_order_id",
        "get_teacher_name",
        "token_package",
        "amount",
        "token_count",
        "status",
        "created_at",
    )
    list_filter = ("status", "token_package", "is_deleted")
    search_fields = (
        "razorpay_order_id",
        "razorpay_payment_id",
        "teacher__user__email",
        "teacher__user__first_name",
    )
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "teacher",
        "token_package",
        "razorpay_order_id",
        "razorpay_payment_id",
        "razorpay_signature",
        "amount",
        "token_count",
        "status",
        "failure_reason",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    autocomplete_fields = ()
    inlines = [PaymentWebhookInline]

    fieldsets = (
        (None, {"fields": ("id", "teacher", "token_package")}),
        (
            _("Razorpay Details"),
            {
                "fields": (
                    "razorpay_order_id",
                    "razorpay_payment_id",
                    "razorpay_signature",
                )
            },
        ),
        (
            _("Amount"),
            {"fields": ("amount", "token_count")},
        ),
        (
            _("Status"),
            {"fields": ("status", "failure_reason")},
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

    @admin.display(description=_("Teacher"), ordering="teacher__user__first_name")
    def get_teacher_name(self, obj):
        return obj.teacher.user.get_full_name()

    def has_add_permission(self, request):
        """Payments are only ever created via PaymentService.create_order."""
        return False

    def changelist_view(self, request, extra_context=None):
        """
        Adds a simple revenue summary (total successful payment
        amount, count) to the top of the Payment changelist - a
        lightweight contribution toward the spec's "Revenue Reports"
        admin requirement, without building a separate dedicated
        reporting page for Phase 3 (apps.analytics, built later
        this phase, covers the fuller dashboard API requirements).
        """
        extra_context = extra_context or {}
        successful = Payment.objects.filter(status=PaymentStatus.SUCCESS)
        summary = successful.aggregate(
            total_revenue=Sum("amount"), total_count=Count("id")
        )
        extra_context["revenue_summary"] = {
            "total_revenue": summary["total_revenue"] or 0,
            "total_count": summary["total_count"] or 0,
        }
        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "teacher", "teacher__user", "token_package"
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


@admin.register(PaymentWebhook)
class PaymentWebhookAdmin(admin.ModelAdmin):
    """
    Standalone, fully read-only admin for browsing ALL webhook
    events across every payment - useful for debugging Razorpay
    integration issues platform-wide.
    """

    list_display = (
        "event_type",
        "razorpay_event_id",
        "payment",
        "is_processed",
        "created_at",
    )
    list_filter = ("event_type", "is_processed")
    search_fields = ("razorpay_event_id", "payment__razorpay_order_id")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "payment",
        "event_type",
        "razorpay_event_id",
        "payload",
        "is_processed",
        "processing_error",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related("payment").get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


@admin.register(PaymentDispute)
class PaymentDisputeAdmin(admin.ModelAdmin):
    list_display = (
        "external_ref",
        "kind",
        "status",
        "amount",
        "tokens_frozen",
        "payment",
        "created_at",
    )
    list_filter = ("kind", "status")
    search_fields = (
        "external_ref",
        "payment__razorpay_order_id",
        "payment__teacher__user__email",
    )
    ordering = ("-created_at",)
    readonly_fields = tuple(f.name for f in PaymentDispute._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(PaymentInstrumentSignature)
class PaymentInstrumentSignatureAdmin(admin.ModelAdmin):
    list_display = ("kind", "value_hash", "teacher", "last_seen_at", "created_at")
    list_filter = ("kind",)
    search_fields = ("value_hash", "teacher__user__email")
    ordering = ("-created_at",)
    readonly_fields = tuple(f.name for f in PaymentInstrumentSignature._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ReconciliationRun)
class ReconciliationRunAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "window_start",
        "window_end",
        "payments_checked",
        "discrepancies",
        "ok",
    )
    list_filter = ("ok",)
    ordering = ("-created_at",)
    readonly_fields = tuple(f.name for f in ReconciliationRun._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

"""
Django Admin configuration for the wallet app.

IMPORTANT: Wallet.balance is READ-ONLY in this admin, even for
Superusers. This is a deliberate, hard enforcement of "No direct
modification of Wallet Balance" - even an Admin cannot edit balance
via a form field. The ONLY way an Admin can adjust a teacher's
balance is the "Refund tokens" action below, which goes through
WalletService.refund() and therefore always creates a proper
WalletTransaction audit row alongside the change.

Uses Django Admin's built-in ActionForm mechanism (action_form) to
collect the refund amount/reason inline on the standard action
confirmation bar - no custom admin template required.
"""

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.utils.translation import gettext_lazy as _

from apps.wallet.models import Wallet, WalletHold, WalletTransaction
from apps.wallet.services import WalletService


@admin.register(WalletHold)
class WalletHoldAdmin(admin.ModelAdmin):
    list_display = ("wallet", "amount", "active", "reason", "released_at", "created_at")
    list_filter = ("active",)
    search_fields = ("wallet__teacher__user__email", "reason")
    ordering = ("-created_at",)
    readonly_fields = tuple(f.name for f in WalletHold._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class WalletTransactionInline(admin.TabularInline):
    """
    Read-only inline showing a wallet's recent transactions
    directly on its admin detail page - useful for quickly auditing
    a specific teacher's activity without navigating to the
    separate WalletTransaction admin list.
    """

    model = WalletTransaction
    extra = 0
    fields = (
        "transaction_type",
        "amount",
        "balance_after",
        "status",
        "description",
        "created_at",
    )
    readonly_fields = fields
    can_delete = False
    ordering = ("-created_at",)
    max_num = 0

    def has_add_permission(self, request, obj=None):
        return False


class RefundActionForm(ActionForm):
    """
    Extends Django Admin's built-in ActionForm to add two extra
    fields (amount, reason) that render inline on the action bar
    at the top of the Wallet changelist, alongside the standard
    action dropdown - no separate confirmation page/template needed.
    """

    refund_amount = forms.IntegerField(
        required=False, min_value=1, label=_("Refund amount (tokens)")
    )
    refund_reason = forms.CharField(
        required=False,
        max_length=255,
        label=_("Refund reason"),
        initial="Admin-initiated refund",
    )


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("get_teacher_name", "get_teacher_email", "balance", "created_at")
    list_filter = ("is_deleted",)
    search_fields = (
        "teacher__user__email",
        "teacher__user__first_name",
        "teacher__user__last_name",
    )
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "teacher",
        "balance",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    inlines = [WalletTransactionInline]
    actions = ["refund_tokens"]
    action_form = RefundActionForm

    fieldsets = (
        (None, {"fields": ("id", "teacher", "balance")}),
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

    @admin.display(description=_("Email"), ordering="teacher__user__email")
    def get_teacher_email(self, obj):
        return obj.teacher.user.email

    def has_add_permission(self, request):
        """
        Wallets are created lazily by WalletService.get_or_create_wallet,
        never manually - disabling manual creation prevents an admin
        from creating a duplicate or orphaned Wallet outside that
        controlled path.
        """
        return False

    @admin.action(
        description=_("Refund tokens to selected wallet(s) (enter amount+reason above)")
    )
    def refund_tokens(self, request, queryset):
        """
        Admin action implementing the spec's "Admin: Refund Tokens"
        permission, using the amount/reason entered in the
        RefundActionForm fields shown on the changelist action bar.
        Applies the SAME amount/reason to every selected wallet -
        an admin refunding different amounts to different teachers
        should run this action separately per teacher.
        """
        amount = request.POST.get("refund_amount")
        reason = request.POST.get("refund_reason") or "Admin-initiated refund"

        if not amount or not str(amount).isdigit() or int(amount) <= 0:
            self.message_user(
                request,
                "Please enter a valid positive refund amount in the "
                "'Refund amount (tokens)' field before running this action.",
                level=messages.ERROR,
            )
            return

        amount = int(amount)
        refunded_count = 0
        for wallet in queryset:
            WalletService.refund(
                teacher=wallet.teacher,
                amount=amount,
                description=reason,
                reference_id=f"admin_refund_by_{request.user.email}",
            )
            refunded_count += 1

        self.message_user(
            request,
            f"Refunded {amount} tokens to {refunded_count} wallet(s).",
            level=messages.SUCCESS,
        )


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    """
    Standalone, fully read-only admin for browsing ALL wallet
    transactions across every teacher - the platform-wide audit
    view your spec's "Wallet Transactions" admin requirement calls
    for, complementing the per-wallet inline above.
    """

    list_display = (
        "get_teacher_name",
        "transaction_type",
        "amount",
        "balance_after",
        "status",
        "description",
        "created_at",
    )
    list_filter = ("transaction_type", "status", "is_deleted")
    search_fields = (
        "wallet__teacher__user__email",
        "wallet__teacher__user__first_name",
        "reference_id",
        "description",
    )
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "wallet",
        "transaction_type",
        "amount",
        "balance_after",
        "status",
        "reference_id",
        "description",
        "created_at",
        "updated_at",
        "deleted_at",
    )

    @admin.display(description=_("Teacher"))
    def get_teacher_name(self, obj):
        return obj.wallet.teacher.user.get_full_name()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        """
        Fully immutable - transactions are an append-only audit
        log. Not even status is editable here (payment webhook
        transitions handle PENDING -> SUCCESS/FAILED automatically
        in apps.payments, not via manual admin edits).
        """
        return False

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "wallet", "wallet__teacher", "wallet__teacher__user"
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

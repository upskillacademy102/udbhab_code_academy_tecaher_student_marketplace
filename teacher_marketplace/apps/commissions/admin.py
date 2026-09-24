from django.contrib import admin

from apps.commissions.models import (
    Commission,
    LearningPartnerBankAccount,
    LearningPartnerWallet,
    LearningPartnerWalletTransaction,
    PayoutRequest,
)


@admin.register(Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "teacher",
        "learning_partner",
        "payment_type",
        "base_amount",
        "partner_share",
        "business_share",
        "status",
        "created_at",
    )
    list_filter = ("status", "payment_type")
    search_fields = ("teacher__user__email", "learning_partner__email")
    readonly_fields = [f.name for f in Commission._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(LearningPartnerWallet)
class LearningPartnerWalletAdmin(admin.ModelAdmin):
    list_display = ("learning_partner", "balance", "updated_at")
    search_fields = ("learning_partner__email", "learning_partner__first_name")
    readonly_fields = ("balance",)


@admin.register(LearningPartnerWalletTransaction)
class LearningPartnerWalletTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "wallet",
        "transaction_type",
        "amount",
        "balance_after",
        "reference_id",
        "created_at",
    )
    list_filter = ("transaction_type",)
    readonly_fields = [f.name for f in LearningPartnerWalletTransaction._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(LearningPartnerBankAccount)
class LearningPartnerBankAccountAdmin(admin.ModelAdmin):
    list_display = ("learning_partner", "bank_name", "account_holder_name", "updated_at")
    search_fields = ("learning_partner__email", "account_holder_name")


@admin.register(PayoutRequest)
class PayoutRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "learning_partner",
        "amount",
        "status",
        "decided_by",
        "payout_reference",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("learning_partner__email", "payout_reference")

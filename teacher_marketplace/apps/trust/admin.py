"""Django Admin for the trust app."""

from django.contrib import admin

from apps.trust.models import (
    ContentFlag,
    DuplicateSignal,
    IdentitySignature,
    LeadQualityRating,
    ManualReviewItem,
    OTPChallenge,
    RequirementContactCheck,
    RiskSignal,
    SensitiveChangeRequest,
    SuspensionAppeal,
    TrustProfile,
    UserBlock,
    UserReport,
)


@admin.register(ContentFlag)
class ContentFlagAdmin(admin.ModelAdmin):
    list_display = ("surface", "subject_user", "status", "categories", "created_at")
    list_filter = ("status", "surface")
    search_fields = ("subject_user__email", "surface", "excerpt")
    readonly_fields = tuple(f.name for f in ContentFlag._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(UserReport)
class UserReportAdmin(admin.ModelAdmin):
    list_display = ("reporter", "reported", "reason", "status", "created_at")
    list_filter = ("reason", "status")
    search_fields = ("reporter__email", "reported__email", "detail")
    readonly_fields = tuple(f.name for f in UserReport._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(UserBlock)
class UserBlockAdmin(admin.ModelAdmin):
    list_display = ("blocker", "blocked", "created_at")
    search_fields = ("blocker__email", "blocked__email")
    readonly_fields = tuple(f.name for f in UserBlock._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(RiskSignal)
class RiskSignalAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "weight", "active", "detail", "created_at")
    list_filter = ("kind", "active")
    search_fields = ("user__email", "detail")
    readonly_fields = tuple(f.name for f in RiskSignal._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(LeadQualityRating)
class LeadQualityRatingAdmin(admin.ModelAdmin):
    list_display = ("teacher", "student", "verdict", "clawed_back", "created_at")
    list_filter = ("verdict", "clawed_back")
    search_fields = ("teacher__user__email", "student__email")
    readonly_fields = tuple(f.name for f in LeadQualityRating._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(RequirementContactCheck)
class RequirementContactCheckAdmin(admin.ModelAdmin):
    list_display = ("requirement", "reachable", "detail", "created_at")
    list_filter = ("reachable",)
    readonly_fields = tuple(f.name for f in RequirementContactCheck._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(IdentitySignature)
class IdentitySignatureAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "value_hash", "source", "created_at")
    list_filter = ("kind", "source")
    search_fields = ("user__email", "value_hash")
    readonly_fields = tuple(f.name for f in IdentitySignature._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DuplicateSignal)
class DuplicateSignalAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "matched_user",
        "kind",
        "resolved",
        "review_item",
        "created_at",
    )
    list_filter = ("kind", "resolved")
    search_fields = ("user__email", "matched_user__email")
    readonly_fields = (
        "user",
        "matched_user",
        "kind",
        "value_hash",
        "review_item",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(SensitiveChangeRequest)
class SensitiveChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "field", "state", "apply_after", "applied_at", "created_at")
    list_filter = ("field", "state")
    search_fields = ("user__email", "new_value")
    readonly_fields = tuple(f.name for f in SensitiveChangeRequest._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(OTPChallenge)
class OTPChallengeAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "channel",
        "purpose",
        "attempts",
        "consumed_at",
        "expires_at",
        "created_at",
    )
    list_filter = ("channel", "purpose")
    search_fields = ("user__email", "destination")
    readonly_fields = tuple(f.name for f in OTPChallenge._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TrustProfile)
class TrustProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "verification_score",
        "is_fully_verified",
        "risk_score",
        "risk_state",
        "lead_quality_score",
        "updated_at",
    )
    list_filter = ("risk_state", "is_fully_verified")
    search_fields = ("user__email", "user__first_name", "user__last_name")
    readonly_fields = (
        "id",
        "user",
        "verification_recomputed_at",
        "risk_recomputed_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        # Created automatically per user; never added by hand.
        return False


@admin.register(SuspensionAppeal)
class SuspensionAppealAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "status",
        "risk_state_at_submit",
        "risk_score_at_submit",
        "decided_by",
        "decided_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("user__email", "message", "decision_note", "contact_email")
    readonly_fields = tuple(f.name for f in SuspensionAppeal._meta.fields)
    list_select_related = ("user", "decided_by")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ManualReviewItem)
class ManualReviewItemAdmin(admin.ModelAdmin):
    list_display = (
        "kind",
        "summary",
        "subject_user",
        "status",
        "priority",
        "assignee",
        "created_at",
    )
    list_filter = ("kind", "status", "priority")
    search_fields = ("summary", "subject_user__email", "dedupe_key", "resolution")
    readonly_fields = (
        "id",
        "kind",
        "subject_user",
        "payload",
        "dedupe_key",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("assignee", "resolved_by")
    list_select_related = ("subject_user", "assignee")

    def has_add_permission(self, request):
        return False

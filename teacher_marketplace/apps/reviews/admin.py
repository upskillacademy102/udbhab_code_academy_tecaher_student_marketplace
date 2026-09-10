"""Admin for the reviews app."""

from django.contrib import admin

from apps.reviews.models import Review
from apps.reviews.services import ReviewIntegrityService


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        "teacher",
        "author",
        "rating",
        "status",
        "flag_reason",
        "created_at",
    )
    list_filter = ("status", "rating")
    search_fields = ("teacher__user__email", "author__email", "text")
    readonly_fields = (
        "id",
        "author",
        "teacher",
        "source_lead",
        "rating",
        "text",
        "author_fingerprint",
        "created_at",
        "updated_at",
    )
    actions = ["publish", "flag", "remove_reviews"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Publish selected reviews")
    def publish(self, request, queryset):
        for r in queryset:
            ReviewIntegrityService.set_status(r, "published")
        self.message_user(request, f"Published {queryset.count()} review(s).")

    @admin.action(description="Flag selected reviews")
    def flag(self, request, queryset):
        for r in queryset:
            ReviewIntegrityService.set_status(r, "flagged", reason="Flagged by admin.")
        self.message_user(request, f"Flagged {queryset.count()} review(s).")

    @admin.action(description="Remove selected reviews")
    def remove_reviews(self, request, queryset):
        for r in queryset:
            ReviewIntegrityService.set_status(r, "removed", reason="Removed by admin.")
        self.message_user(request, f"Removed {queryset.count()} review(s).")

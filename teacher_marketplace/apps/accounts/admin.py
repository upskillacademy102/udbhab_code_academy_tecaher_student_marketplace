"""
Django Admin configuration for the accounts app.

Django's built-in django.contrib.auth.admin.UserAdmin assumes the
default User model's fields (username, first_name, last_name,
email, is_staff, etc. in a specific fieldset layout). Since our
User model replaces username with email as the login field and
adds role/mobile/verification fields, we subclass Django's
UserAdmin and override its fieldsets/list display entirely rather
than trying to patch the default one.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    Custom admin for the User model. Subclasses Django's own
    UserAdmin (not admin.ModelAdmin directly) to retain its
    battle-tested password-change form, permission widgets, and
    add/change form behavior - only the fieldsets, list display,
    and ordering are customized for our email-based, role-based
    model.
    """

    # ----------------------------------------------------------
    # List view configuration
    # ----------------------------------------------------------
    list_display = (
        "email",
        "first_name",
        "last_name",
        "mobile",
        "role",
        "is_active",
        "is_staff",
        "is_email_verified",
        "is_mobile_verified",
        "created_at",
    )
    list_filter = (
        "role",
        "is_active",
        "is_staff",
        "is_superuser",
        "is_email_verified",
        "is_mobile_verified",
        "is_deleted",
    )
    search_fields = ("email", "first_name", "last_name", "mobile")
    ordering = ("-created_at",)

    # ----------------------------------------------------------
    # Detail / edit view configuration
    # ----------------------------------------------------------
    # Overrides DjangoUserAdmin.fieldsets entirely - the default
    # references `username`, which does not exist on our model.
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Personal Info"),
            {"fields": ("first_name", "last_name", "mobile")},
        ),
        (
            _("Role & Verification"),
            {
                "fields": (
                    "role",
                    "is_email_verified",
                    "is_mobile_verified",
                )
            },
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            _("Soft Delete"),
            {
                "fields": ("is_deleted", "deleted_at"),
                "classes": ("collapse",),
            },
        ),
        (
            _("Important Dates"),
            {
                "fields": ("last_login", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    # ----------------------------------------------------------
    # "Add user" form configuration (the simplified creation form
    # shown when adding a new user directly from Django Admin)
    # ----------------------------------------------------------
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "mobile",
                    "first_name",
                    "last_name",
                    "role",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    readonly_fields = ("created_at", "updated_at", "last_login", "deleted_at")

    def get_queryset(self, request):
        """
        Ensures Django Admin can see AND manage soft-deleted users
        too (e.g. to restore an accidentally deleted account),
        using the `all_objects` manager from SoftDeleteModel rather
        than the default `objects` manager which excludes them.
        """
        qs = self.model.all_objects.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

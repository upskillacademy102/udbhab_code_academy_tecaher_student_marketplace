"""
Django Admin configuration for the location app.

Uses TabularInline to let admins manage the hierarchy without
leaving the parent object's page - e.g. adding States directly
from a Country's admin detail view.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.location.models import City, Country, State


class StateInline(admin.TabularInline):
    """
    Lets an admin view/add States directly from a Country's detail
    page. extra=0 keeps the inline form clean (no empty placeholder
    rows) since country lists can have many states already.
    """

    model = State
    extra = 0
    fields = ("name", "code", "is_active")
    show_change_link = True


class CityInline(admin.TabularInline):
    """
    Lets an admin view/add Cities directly from a State's detail
    page.
    """

    model = City
    extra = 0
    fields = ("name", "is_active")
    show_change_link = True


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "is_deleted", "created_at")
    list_filter = ("is_active", "is_deleted")
    search_fields = ("name", "code")
    ordering = ("name",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    inlines = [StateInline]

    fieldsets = (
        (None, {"fields": ("id", "name", "code")}),
        (_("Status"), {"fields": ("is_active",)}),
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


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "country", "is_active", "is_deleted", "created_at")
    list_filter = ("is_active", "is_deleted", "country")
    search_fields = ("name", "code", "country__name")
    ordering = ("country__name", "name")
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("country",)
    inlines = [CityInline]

    fieldsets = (
        (None, {"fields": ("id", "country", "name", "code")}),
        (_("Status"), {"fields": ("is_active",)}),
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
        qs = self.model.all_objects.select_related("country").get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "state",
        "get_country",
        "is_active",
        "is_deleted",
        "created_at",
    )
    list_filter = ("is_active", "is_deleted", "state__country")
    search_fields = ("name", "state__name", "state__country__name")
    ordering = ("state__country__name", "state__name", "name")
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("state",)

    fieldsets = (
        (None, {"fields": ("id", "state", "name")}),
        (_("Status"), {"fields": ("is_active",)}),
        (
            _("Soft Delete"),
            {"fields": ("is_deleted", "deleted_at"), "classes": ("collapse",)},
        ),
        (
            _("Timestamps"),
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    @admin.display(description=_("Country"), ordering="state__country__name")
    def get_country(self, obj):
        return obj.state.country.name

    def get_queryset(self, request):
        qs = self.model.all_objects.select_related(
            "state", "state__country"
        ).get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

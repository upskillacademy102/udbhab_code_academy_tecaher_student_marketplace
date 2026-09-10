"""
Serializers for the location app.

Provides both simple per-level serializers (for admin CRUD and
straightforward list/detail use) and a flattened CitySerializer
that includes state and country names inline - useful for search
result displays and dropdowns where the full "City, State, Country"
context is needed without extra client-side requests.
"""

from rest_framework import serializers

from apps.location.models import City, Country, State


class CountrySerializer(serializers.ModelSerializer):
    """Full read/write representation of a Country."""

    class Meta:
        model = Country
        fields = ("id", "name", "code", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_name(self, value):
        value = value.strip() if isinstance(value, str) else value
        queryset = Country.all_objects.filter(name__iexact=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                "A country with this name already exists."
            )
        return value

    def validate_code(self, value):
        normalized = value.strip().upper() if isinstance(value, str) else value
        queryset = Country.all_objects.filter(code__iexact=normalized)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                "A country with this code already exists."
            )
        return normalized


class StateSerializer(serializers.ModelSerializer):
    """
    Full read/write representation of a State. Includes
    `country_name` as a read-only convenience field alongside the
    writable `country` FK id, so clients don't need a second lookup
    just to display which country a state belongs to.
    """

    country_name = serializers.CharField(source="country.name", read_only=True)

    class Meta:
        model = State
        fields = (
            "id",
            "country",
            "country_name",
            "name",
            "code",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        """
        Enforces the same (country, name) uniqueness as the model's
        UniqueConstraint, but at the serializer layer for a clean
        400 error instead of a raw IntegrityError. Object-level
        validation is required here (not a single-field validator)
        since the uniqueness check spans two fields together.
        """
        if "name" in attrs and isinstance(attrs["name"], str):
            attrs["name"] = attrs["name"].strip()
        if "code" in attrs and isinstance(attrs["code"], str):
            attrs["code"] = attrs["code"].strip() or None

        country = attrs.get("country", getattr(self.instance, "country", None))
        name = attrs.get("name", getattr(self.instance, "name", None))

        queryset = State.all_objects.filter(country=country, name__iexact=name)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                {"name": "A state with this name already exists in this country."}
            )
        return attrs


class CitySerializer(serializers.ModelSerializer):
    """
    Full read/write representation of a City. Flattens
    `state_name` and `country_name` as read-only convenience
    fields alongside the writable `state` FK id, so a search UI
    can render "Pune, Maharashtra, India" from a single City
    object without additional requests.
    """

    state_name = serializers.CharField(source="state.name", read_only=True)
    country_name = serializers.CharField(source="state.country.name", read_only=True)
    country_id = serializers.UUIDField(source="state.country.id", read_only=True)

    class Meta:
        model = City
        fields = (
            "id",
            "state",
            "state_name",
            "country_id",
            "country_name",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        """
        Enforces the same (state, name) uniqueness as the model's
        UniqueConstraint, mirroring StateSerializer.validate.
        """
        if "name" in attrs and isinstance(attrs["name"], str):
            attrs["name"] = attrs["name"].strip()

        state = attrs.get("state", getattr(self.instance, "state", None))
        name = attrs.get("name", getattr(self.instance, "name", None))

        queryset = City.all_objects.filter(state=state, name__iexact=name)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                {"name": "A city with this name already exists in this state."}
            )
        return attrs

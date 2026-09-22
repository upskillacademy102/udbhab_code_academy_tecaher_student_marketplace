"""
Serializers for the languages app.

Language is simple reference data - a single ModelSerializer
covers both read and write use cases, same reasoning as
apps/subjects/serializers.py.
"""

from rest_framework import serializers

from apps.languages.models import Language


class LanguageSerializer(serializers.ModelSerializer):
    """
    Full read/write representation of a Language.

    `learning_partner`/`learning_partner_name` are read-only - a language is
    scoped to a partner only via the Learning Partner taxonomy-request
    approval flow (apps.accounts.admin_api), never through this endpoint.
    """

    learning_partner_name = serializers.CharField(
        source="learning_partner.first_name", read_only=True, default=None
    )

    class Meta:
        model = Language
        fields = (
            "id",
            "name",
            "code",
            "is_active",
            "learning_partner",
            "learning_partner_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "learning_partner",
            "learning_partner_name",
            "created_at",
            "updated_at",
        )

    def validate_name(self, value):
        """
        Case-insensitive uniqueness check, scoped the same way the model's
        partial unique constraints are - see
        SubjectSerializer.validate_name's docstring for the full reasoning.
        """
        value = value.strip() if isinstance(value, str) else value
        scope_partner_id = (
            self.instance.learning_partner_id if self.instance is not None else None
        )
        queryset = Language.all_objects.filter(
            name__iexact=value, learning_partner_id=scope_partner_id
        )
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                "A language with this name already exists."
            )
        return value

    def validate_code(self, value):
        """
        Case-insensitive uniqueness check on `code`, mirroring
        validate_name (including the same partner-scoped comparison). The
        model's save() lowercases the code before persisting, but
        validation happens before save() is called, so we normalize here
        too for an accurate duplicate check against existing lowercase-
        stored codes.
        """
        normalized = value.strip().lower() if isinstance(value, str) else value
        scope_partner_id = (
            self.instance.learning_partner_id if self.instance is not None else None
        )
        queryset = Language.all_objects.filter(
            code__iexact=normalized, learning_partner_id=scope_partner_id
        )
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                "A language with this code already exists."
            )
        return normalized

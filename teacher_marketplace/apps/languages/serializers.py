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
    """

    class Meta:
        model = Language
        fields = (
            "id",
            "name",
            "code",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_name(self, value):
        """
        Case-insensitive uniqueness check, checked against
        soft-deleted rows too - same reasoning as
        SubjectSerializer.validate_name.
        """
        value = value.strip() if isinstance(value, str) else value
        queryset = Language.all_objects.filter(name__iexact=value)
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
        validate_name. The model's save() lowercases the code
        before persisting, but validation happens before save() is
        called, so we normalize here too for an accurate duplicate
        check against existing lowercase-stored codes.
        """
        normalized = value.strip().lower() if isinstance(value, str) else value
        queryset = Language.all_objects.filter(code__iexact=normalized)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                "A language with this code already exists."
            )
        return normalized

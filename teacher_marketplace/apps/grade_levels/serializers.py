"""
Serializers for the grade_levels app - simple reference data, same
reasoning as apps/subjects/serializers.py and apps/languages/serializers.py.
"""

from rest_framework import serializers

from apps.grade_levels.models import GradeLevel


class GradeLevelSerializer(serializers.ModelSerializer):
    """Full read/write representation of a GradeLevel."""

    class Meta:
        model = GradeLevel
        fields = ("id", "name", "sort_order", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_name(self, value):
        """Case-insensitive uniqueness check, checked against soft-deleted
        rows too - same reasoning as SubjectSerializer.validate_name."""
        value = value.strip() if isinstance(value, str) else value
        queryset = GradeLevel.all_objects.filter(name__iexact=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                "A grade level with this name already exists."
            )
        return value

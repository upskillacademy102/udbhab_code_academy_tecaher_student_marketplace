"""
Serializers for the subjects app.

Subject is simple reference data - a single ModelSerializer covers
both read and write use cases, unlike apps/students or apps/teachers
which needed separate read/write serializers to control embedding
and ownership of the related User.
"""

from rest_framework import serializers

from apps.subjects.models import Subject


class SubjectSerializer(serializers.ModelSerializer):
    """
    Full read/write representation of a Subject. `slug` is
    read-only in the API - it's derived server-side from `name`
    (see Subject.save()), so clients should never set it directly;
    this keeps slugs consistent and avoids clients supplying
    malformed or colliding slug values.
    """

    class Meta:
        model = Subject
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "icon",
            "is_active",
            "is_skill_based",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "slug", "created_at", "updated_at")

    def validate(self, attrs):
        # Optional free text -> NULL instead of "" / whitespace.
        for field in ("description", "icon"):
            if field in attrs and isinstance(attrs[field], str):
                attrs[field] = attrs[field].strip() or None
        return attrs

    def validate_name(self, value):
        """
        Case-insensitive uniqueness check. The model's `unique=True`
        on `name` already enforces this at the database level, but
        a plain database IntegrityError surfaces as an unfriendly
        500-style error if not caught at the serializer layer first
        - this raises a clean 400 with a clear message instead.
        Case-insensitive because "Mathematics" and "mathematics"
        should be treated as the same subject to prevent accidental
        near-duplicates in the taxonomy.
        """
        value = value.strip() if isinstance(value, str) else value
        queryset = Subject.all_objects.filter(name__iexact=value)

        # Exclude the current instance when updating (PATCH/PUT),
        # so re-saving a subject with its own unchanged name doesn't
        # incorrectly flag itself as a duplicate.
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "A subject with this name already exists."
            )
        return value

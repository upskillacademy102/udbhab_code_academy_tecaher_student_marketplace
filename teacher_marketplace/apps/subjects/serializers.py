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

    `learning_partner`/`learning_partner_name` are read-only - a subject is
    scoped to a partner only via the Learning Partner taxonomy-request
    approval flow (apps.accounts.admin_api), never through this endpoint.
    """

    learning_partner_name = serializers.CharField(
        source="learning_partner.first_name", read_only=True, default=None
    )

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
            "learning_partner",
            "learning_partner_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "slug",
            "learning_partner",
            "learning_partner_name",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        # Optional free text -> NULL instead of "" / whitespace.
        for field in ("description", "icon"):
            if field in attrs and isinstance(attrs[field], str):
                attrs[field] = attrs[field].strip() or None
        return attrs

    def validate_name(self, value):
        """
        Case-insensitive uniqueness check, scoped the same way the
        model's partial unique constraints are: within the global list, or
        within one Learning Partner's own list - never across the two, since
        two different partners (or a partner and the global list) may
        legitimately have the same name. A plain database IntegrityError
        would otherwise surface as an unfriendly 500-style error; this
        raises a clean 400 with a clear message instead. This endpoint never
        writes `learning_partner` itself (read-only - see the taxonomy
        request-approval flow for that), so a new row is always scoped
        global; editing an existing row keeps its own current scope.
        """
        value = value.strip() if isinstance(value, str) else value
        scope_partner_id = (
            self.instance.learning_partner_id if self.instance is not None else None
        )
        queryset = Subject.all_objects.filter(
            name__iexact=value, learning_partner_id=scope_partner_id
        )

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

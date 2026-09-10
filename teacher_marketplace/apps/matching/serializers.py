"""
Serializers for the matching app.
"""

from typing import Optional

from rest_framework import serializers

from apps.matching.models import (
    LanguageAlias,
    LeadAssignment,
    MatchingConfig,
    PincodeLocation,
    SubjectAlias,
)


class PincodeLocationSerializer(serializers.ModelSerializer):
    """
    Read/write representation of a PincodeLocation. `location` is
    accepted/returned as separate latitude/longitude floats (not a
    raw WKT/GeoJSON string) for simpler client integration - most
    frontend consumers work with plain lat/long pairs, not GIS
    serialization formats.
    """

    latitude = serializers.FloatField(write_only=True, min_value=-90, max_value=90)
    longitude = serializers.FloatField(write_only=True, min_value=-180, max_value=180)
    lat = serializers.SerializerMethodField()
    lng = serializers.SerializerMethodField()

    class Meta:
        model = PincodeLocation
        fields = (
            "id",
            "pincode",
            "latitude",
            "longitude",
            "lat",
            "lng",
            "city",
            "state",
            "country",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate_pincode(self, value):
        return value.strip() if isinstance(value, str) else value

    def validate(self, attrs):
        for field in ("city", "state", "country"):
            if field in attrs and isinstance(attrs[field], str):
                attrs[field] = attrs[field].strip() or None
        return attrs

    def get_lat(self, obj) -> Optional[float]:
        return obj.location.y if obj.location else None

    def get_lng(self, obj) -> Optional[float]:
        return obj.location.x if obj.location else None

    def create(self, validated_data):
        from django.contrib.gis.geos import Point

        lat = validated_data.pop("latitude")
        lng = validated_data.pop("longitude")
        validated_data["location"] = Point(lng, lat, srid=4326)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        from django.contrib.gis.geos import Point

        if "latitude" in validated_data or "longitude" in validated_data:
            lat = validated_data.pop("latitude", instance.location.y)
            lng = validated_data.pop("longitude", instance.location.x)
            validated_data["location"] = Point(lng, lat, srid=4326)
        return super().update(instance, validated_data)


def _clean_alias_text(value):
    value = value.strip() if isinstance(value, str) else value
    if not value:
        raise serializers.ValidationError("Alias text cannot be blank.")
    return value


class SubjectAliasSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)

    class Meta:
        model = SubjectAlias
        fields = ("id", "subject", "subject_name", "alias_text", "created_at")
        read_only_fields = ("id", "created_at")

    def validate_alias_text(self, value):
        return _clean_alias_text(value)


class LanguageAliasSerializer(serializers.ModelSerializer):
    language_name = serializers.CharField(source="language.name", read_only=True)

    class Meta:
        model = LanguageAlias
        fields = ("id", "language", "language_name", "alias_text", "created_at")
        read_only_fields = ("id", "created_at")

    def validate_alias_text(self, value):
        return _clean_alias_text(value)


class MatchingConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = MatchingConfig
        fields = (
            "id",
            "subject_match_threshold",
            "language_match_threshold",
            "time_match_threshold_minutes",
            "initial_location_radius_km",
            "location_radius_increment_km",
            "max_location_radius_km",
            "lead_response_window_hours",
            "subscription_priority_order",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate_subscription_priority_order(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list of plan names.")
        if len(value) > 20:
            raise serializers.ValidationError("At most 20 plan names.")
        cleaned = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise serializers.ValidationError(
                    "Each entry must be a non-empty plan name."
                )
            cleaned.append(item.strip())
        if len(cleaned) != len(set(c.lower() for c in cleaned)):
            raise serializers.ValidationError("Plan names must be unique.")
        return cleaned

    def validate(self, attrs):
        lo = attrs.get(
            "initial_location_radius_km",
            getattr(self.instance, "initial_location_radius_km", None),
        )
        hi = attrs.get(
            "max_location_radius_km",
            getattr(self.instance, "max_location_radius_km", None),
        )
        if lo is not None and hi is not None and lo > hi:
            raise serializers.ValidationError(
                {
                    "initial_location_radius_km": "Initial radius cannot exceed the max radius."
                }
            )
        return attrs


class SearchResultExplanationSerializer(serializers.Serializer):
    """
    Section 39's "why did this teacher match" explanation - a list
    of plain-language checkmark lines, deliberately excluding any
    commercial ranking detail (subscription tier, token balance) per
    the spec's explicit "Do not expose internal commercial ranking
    details" instruction.
    """

    subject_matched = serializers.BooleanField()
    language_matched = serializers.BooleanField()
    best_matching_day = serializers.CharField(allow_null=True)
    best_matching_time = serializers.CharField(allow_null=True)
    distance_km = serializers.FloatField(allow_null=True)
    within_radius = serializers.BooleanField(allow_null=True)


class TeacherSearchResultSerializer(serializers.Serializer):
    """
    One ranked teacher search result. Deliberately a plain
    Serializer (not ModelSerializer) since this represents a
    COMPUTED result (teacher + scores + explanation), not a direct
    database row.
    """

    teacher_id = serializers.UUIDField()
    teacher_name = serializers.CharField()
    subjects = serializers.ListField(child=serializers.CharField())
    languages = serializers.ListField(child=serializers.CharField())
    rating = serializers.FloatField()
    experience_years = serializers.IntegerField()
    teaching_mode = serializers.CharField()
    hourly_rate = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
    is_verified = serializers.BooleanField()
    match_percentage = serializers.IntegerField()
    explanation = SearchResultExplanationSerializer()


class LeadAssignmentSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a LeadAssignment for the teacher-
    facing "my assigned leads" view. Contact details are NOT
    included here at all.
    """

    subject_name = serializers.CharField(
        source="lead.student_requirement.subject.name", read_only=True
    )

    class Meta:
        model = LeadAssignment
        fields = (
            "id",
            "lead",
            "subject_name",
            "subscription_tier",
            "assignment_stage",
            "assigned_at",
            "expires_at",
            "status",
            "viewed_at",
            "responded_at",
            "response",
            "time_match_score",
            "location_score",
            "subject_match_score",
            "language_match_score",
            "created_at",
        )
        read_only_fields = fields


class AssignmentResponseInputSerializer(serializers.Serializer):
    """Validates POST body for accept/reject actions - just confirms intent, no free text needed."""

    pass

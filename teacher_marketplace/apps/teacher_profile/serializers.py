"""
Serializers for the teacher_profile app.

Covers:
    - TeacherAvailabilitySerializer  -> read/write for individual
                                        availability slots.
    - TeacherProfileSerializer        -> read representation, fully
                                        nested (subjects/languages/
                                        cities as objects, not just
                                        ids; includes teacher's
                                        basic info from Phase 1).
    - TeacherProfileWriteSerializer   -> write representation,
                                        accepts subject/language/
                                        city as plain UUID lists.
"""

from rest_framework import serializers

from apps.languages.models import Language
from apps.languages.serializers import LanguageSerializer
from apps.location.models import City
from apps.location.serializers import CitySerializer
from apps.subjects.models import Subject
from apps.subjects.serializers import SubjectSerializer
from apps.teacher_profile.models import (
    TeacherAvailability,
    TeacherProfile,
    TeacherScheduleException,
    TeacherWeeklyAvailability,
)
from apps.teachers.serializers import TeacherSerializer


class TeacherAvailabilitySerializer(serializers.ModelSerializer):
    """
    Read/write representation of a single availability slot.
    day_type/time_slot are validated against the model's own
    TextChoices via ChoiceField, giving a clean 400 with valid
    options listed if an invalid value is submitted.
    """

    class Meta:
        model = TeacherAvailability
        fields = ("id", "day_type", "time_slot", "created_at")
        read_only_fields = ("id", "created_at")


class TeacherProfileSerializer(serializers.ModelSerializer):
    """
    Read-only, fully nested representation of a TeacherProfile.
    Used for GET /teachers/profile/me/, search results, and lead
    dashboards. Embeds:
        - teacher: Phase 1's Teacher data (which itself embeds User)
        - subjects/languages/cities: full nested objects, not just ids
        - availability_slots: this teacher's selected slots
        - computed convenience fields: is_verified, years_of_experience
    """

    teacher = TeacherSerializer(read_only=True)
    subjects = SubjectSerializer(many=True, read_only=True)
    languages = LanguageSerializer(many=True, read_only=True)
    cities = CitySerializer(many=True, read_only=True)
    availability_slots = TeacherAvailabilitySerializer(many=True, read_only=True)
    is_verified = serializers.BooleanField(read_only=True)
    is_fully_verified = serializers.SerializerMethodField()
    years_of_experience = serializers.IntegerField(read_only=True)

    def get_is_fully_verified(self, obj) -> bool:
        tp = getattr(obj.teacher.user, "trust_profile", None)
        return bool(tp and tp.is_fully_verified)

    class Meta:
        model = TeacherProfile
        fields = (
            "id",
            "teacher",
            "headline",
            "teaching_mode",
            "hourly_rate",
            "monthly_rate",
            "monthly_rate_max",
            "rating",
            "verification_status",
            "moderation_status",
            "is_verified",
            "is_fully_verified",
            "years_of_experience",
            "subjects",
            "languages",
            "cities",
            "availability_slots",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class TeacherProfileWriteSerializer(serializers.ModelSerializer):
    """
    Write representation for creating/updating a TeacherProfile.
    Accepts subjects/languages/cities as plain lists of UUIDs
    (DRF's PrimaryKeyRelatedField), not nested objects - a teacher
    selects from the existing Subject/Language/City taxonomy, they
    don't create new taxonomy entries through this endpoint.

    `teacher` and `verification_status` are deliberately NOT
    writable here:
        - `teacher` is always set from request.user's Teacher
          profile in the view, never client-supplied (same
          ownership-safety reasoning as Phase 1's
          StudentCreateUpdateSerializer/TeacherCreateUpdateSerializer).
        - `verification_status` is Admin-only (set via Django Admin
          or a future dedicated endpoint) - a teacher must never be
          able to self-verify by including this field in their own
          profile update request.
    """

    subjects = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.filter(is_active=True),
        many=True,
        required=False,
    )
    languages = serializers.PrimaryKeyRelatedField(
        queryset=Language.objects.filter(is_active=True),
        many=True,
        required=False,
    )
    cities = serializers.PrimaryKeyRelatedField(
        queryset=City.objects.filter(is_active=True),
        many=True,
        required=False,
    )

    class Meta:
        model = TeacherProfile
        fields = (
            "id",
            "headline",
            "teaching_mode",
            "hourly_rate",
            "monthly_rate",
            "monthly_rate_max",
            "subjects",
            "languages",
            "cities",
        )
        read_only_fields = ("id",)

    def validate_hourly_rate(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Hourly rate cannot be negative.")
        return value

    def validate_monthly_rate(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Monthly rate cannot be negative.")
        return value

    def validate_monthly_rate_max(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Monthly rate cannot be negative.")
        return value

    def validate(self, attrs):
        # Fall back to the existing instance's value for whichever side of
        # the range wasn't included in a partial update, so a PATCH that
        # only sends one of the two fields still gets checked against the
        # other's current value.
        rate_min = attrs.get(
            "monthly_rate", getattr(self.instance, "monthly_rate", None)
        )
        rate_max = attrs.get(
            "monthly_rate_max", getattr(self.instance, "monthly_rate_max", None)
        )
        if rate_min is not None and rate_max is not None and rate_max < rate_min:
            raise serializers.ValidationError(
                {"monthly_rate_max": "The upper end can't be below the lower end."}
            )
        return attrs

    def validate_headline(self, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    def validate_subjects(self, value):
        if value and len(value) > 30:
            raise serializers.ValidationError("Select at most 30 subjects.")
        return value

    def validate_languages(self, value):
        if value and len(value) > 15:
            raise serializers.ValidationError("Select at most 15 languages.")
        return value

    def validate_cities(self, value):
        if value and len(value) > 30:
            raise serializers.ValidationError("Select at most 30 cities.")
        return value


class TeacherWeeklyAvailabilitySerializer(serializers.ModelSerializer):
    """Read/write representation of a single weekly availability window."""

    class Meta:
        model = TeacherWeeklyAvailability
        fields = (
            "id",
            "day_of_week",
            "start_time",
            "end_time",
            "timezone",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate_timezone(self, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise serializers.ValidationError(
                f"'{value}' is not a valid IANA timezone name."
            )
        return value

    def validate(self, attrs):
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start is not None and end is not None and start >= end:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time."}
            )
        return attrs


class TeacherScheduleExceptionSerializer(serializers.ModelSerializer):
    """Read/write representation of a one-off teacher schedule exception."""

    class Meta:
        model = TeacherScheduleException
        fields = (
            "id",
            "exception_type",
            "date",
            "start_time",
            "end_time",
            "timezone",
            "reason",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if bool(start) != bool(end):
            raise serializers.ValidationError(
                {
                    "end_time": "Set both start_time and end_time, or leave both blank for a full-day exception."
                }
            )
        if start and end and start >= end:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time."}
            )
        return attrs

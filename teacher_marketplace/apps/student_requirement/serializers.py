"""
Serializers for the student_requirement app.

Implements the spec's explicit validation requirements:
    - Budget: budget_min must not exceed budget_max
    - Location: city required when teaching_mode is Offline/Both
    - Duplicate Requirements: a student can't have two OPEN
      requirements for the same subject + teaching_mode
    - Subject Exists / Language Exists: enforced automatically by
      PrimaryKeyRelatedField's queryset (an invalid/inactive id is
      rejected with a clean 400 before it ever reaches the database)
"""

from rest_framework import serializers

from apps.languages.serializers import LanguageSerializer
from apps.location.serializers import CitySerializer
from apps.student_requirement.models import (
    RequirementStatus,
    StudentRequirement,
    StudentScheduleException,
    StudentSchedulePreference,
)
from apps.subjects.serializers import SubjectSerializer
from apps.teacher_profile.models import TeachingMode


class SchedulePreferenceReadSerializer(serializers.ModelSerializer):
    """Read-only view of a single structured day/time preference window."""

    day_of_week_label = serializers.CharField(
        source="get_day_of_week_display", read_only=True
    )

    class Meta:
        model = StudentSchedulePreference
        fields = (
            "id",
            "day_of_week",
            "day_of_week_label",
            "start_time",
            "end_time",
            "timezone",
            "flexibility",
            "priority",
            "created_at",
        )
        read_only_fields = fields


class StudentRequirementSerializer(serializers.ModelSerializer):
    """
    Read-only, nested representation of a StudentRequirement. Used
    for GET /student-requirements/ and /student-requirements/{id}/,
    and reused by lead_engine when building lead detail responses.
    """

    subject = SubjectSerializer(read_only=True)
    preferred_language = LanguageSerializer(read_only=True)
    city = CitySerializer(read_only=True)
    student_name = serializers.CharField(source="student.get_full_name", read_only=True)
    schedule_preferences = SchedulePreferenceReadSerializer(many=True, read_only=True)

    class Meta:
        model = StudentRequirement
        fields = (
            "id",
            "student_name",
            "subject",
            "student_class",
            "preferred_language",
            "budget_min",
            "budget_max",
            "teaching_mode",
            "city",
            "preferred_timing",
            "description",
            "status",
            "lead_distribution_status",
            "schedule_preferences",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class StudentSchedulePreferenceWriteSerializer(serializers.ModelSerializer):
    """
    Nested write-only shape for a single preferred day/time window,
    submitted inline with a requirement (see
    StudentRequirementWriteSerializer.schedule_preferences). Same
    field set as StudentSchedulePreferenceSerializer minus the
    read-only id/created_at - kept as its own class so the nested
    list has a stable child serializer regardless of definition
    order in this module.
    """

    class Meta:
        model = StudentSchedulePreference
        fields = (
            "day_of_week",
            "start_time",
            "end_time",
            "timezone",
            "flexibility",
            "priority",
        )

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
        if attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time."}
            )
        return attrs


class StudentRequirementWriteSerializer(serializers.ModelSerializer):
    """
    Write representation for creating/updating a StudentRequirement.

    PHASE 5 UPDATE: subject, preferred_language, and city/pincode are
    now PLAIN TEXT fields, resolved internally via
    SubjectMatchingService / LanguageMatchingService /
    LocationResolutionService (exact -> alias -> fuzzy, pg_trgm-
    backed). UUID input is no longer accepted on these fields per
    explicit decision - this is an intentional breaking change from
    the earlier UUID-based contract. The resolved UUIDs are stored
    on the model's existing FK fields exactly as before; only the
    API's INPUT shape has changed, not the database schema or the
    downstream matching/ranking/lead-distribution engines.

    SCHEDULE PREFERENCES: `schedule_preferences` accepts the
    student's preferred day/time windows inline with the requirement.
    They are persisted BEFORE lead generation/distribution runs (the
    view calls generate_leads_for_requirement right after save), so
    the tiered LeadAssignment distribution engine - whose
    EligibilityService gate hard-requires a real time overlap - can
    actually see them. Without this, a requirement created through
    the API had zero structured preferences at distribution time, so
    EligibilityService rejected every teacher on "no_time_overlap"
    and no LeadAssignment was ever created via the primary flow. The
    field stays OPTIONAL: a requirement with no preferences still
    generates soft Lead rows (time_score 0), it just won't drive the
    tiered offer cascade - identical to the previous behaviour.
    """

    subject = serializers.CharField(
        help_text="Subject name, e.g. 'Mathematics', 'math', 'maths'."
    )
    preferred_language = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Language name, e.g. 'English', 'Bengali'.",
    )
    city = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="City name (e.g. 'Kolkata') OR pincode (e.g. '700001').",
    )
    schedule_preferences = StudentSchedulePreferenceWriteSerializer(
        many=True,
        required=False,
        write_only=True,
        help_text="Preferred weekly day/time windows, e.g. "
        '[{"day_of_week": 1, "start_time": "18:00", "end_time": "20:00", '
        '"timezone": "Asia/Kolkata", "flexibility": "flexible"}].',
    )

    class Meta:
        model = StudentRequirement
        fields = (
            "id",
            "subject",
            "student_class",
            "preferred_language",
            "budget_min",
            "budget_max",
            "teaching_mode",
            "city",
            "preferred_timing",
            "description",
            "class_duration_minutes",
            "schedule_preferences",
        )
        read_only_fields = ("id",)

    def validate_subject(self, value):
        from apps.matching.services.subject_matching_service import (
            SubjectMatchingService,
        )

        result = SubjectMatchingService.match_by_text(value)
        if not result.is_eligible or result.matched_subject is None:
            raise serializers.ValidationError(
                f"Subject '{value}' not recognized. Please check the spelling or contact support."
            )
        return result.matched_subject

    def validate_preferred_language(self, value):
        if not value:
            return None
        from apps.matching.services.language_matching_service import (
            LanguageMatchingService,
        )

        result = LanguageMatchingService.match_by_text(value)
        if not result.is_eligible or result.matched_subject is None:
            raise serializers.ValidationError(
                f"Language '{value}' not recognized. Please check the spelling or contact support."
            )
        return result.matched_subject

    def validate_city(self, value):
        if not value:
            return None
        from apps.matching.services.location_resolution_service import (
            LocationResolutionService,
        )

        # On CREATE, resolve the City / pincode synchronously (fast DB match)
        # but defer the outbound city-centroid geocode - process_requirement_leads
        # backfills pincode_location before matching, so a slow geocoder never
        # delays the student's POST. On UPDATE there is no follow-up task, so
        # resolve fully here (unchanged behaviour).
        defer = self.instance is None
        return LocationResolutionService.resolve(value, defer_city_geocode=defer)

    def validate(self, attrs):
        """
        Budget/location-required-for-offline validation - same
        logic as before, now operating on already-resolved objects
        (attrs["subject"] is a Subject instance, attrs["city"] is a
        LocationResolutionResult or None) rather than raw ids.
        """
        # Optional free-text: normalise "" / "   " -> None so the DB never
        # holds a blank string (also satisfies the not-blank CHECK constraint).
        for field in ("student_class", "preferred_timing", "description"):
            if field in attrs and isinstance(attrs[field], str):
                attrs[field] = attrs[field].strip() or None

        prefs = attrs.get("schedule_preferences")
        if prefs is not None and len(prefs) > 20:
            raise serializers.ValidationError(
                {
                    "schedule_preferences": "A requirement can have at most 20 preferred time windows."
                }
            )

        budget_min = attrs.get("budget_min", getattr(self.instance, "budget_min", None))
        budget_max = attrs.get("budget_max", getattr(self.instance, "budget_max", None))
        if (
            budget_min is not None
            and budget_max is not None
            and budget_min > budget_max
        ):
            raise serializers.ValidationError(
                {"budget_min": "Minimum budget cannot exceed maximum budget."}
            )

        teaching_mode = attrs.get(
            "teaching_mode", getattr(self.instance, "teaching_mode", TeachingMode.BOTH)
        )
        location_result = attrs.get("city")
        if teaching_mode in (TeachingMode.OFFLINE, TeachingMode.BOTH):
            has_location = location_result is not None or (
                self.instance is not None
                and (self.instance.city_id or self.instance.pincode_location_id)
            )
            if not has_location:
                raise serializers.ValidationError(
                    {
                        "city": "City or pincode is required when teaching mode is Offline or Both."
                    }
                )

        if self.instance is None:
            student = self.context["request"].user
            subject = attrs.get("subject")
            duplicate_exists = StudentRequirement.objects.filter(
                student=student,
                subject=subject,
                teaching_mode=teaching_mode,
                status__in=[RequirementStatus.OPEN, RequirementStatus.MATCHED],
            ).exists()
            if duplicate_exists:
                raise serializers.ValidationError(
                    "You already have an open requirement for this subject "
                    "and teaching mode. Close it before submitting a new one."
                )

        return attrs

    def create(self, validated_data):
        """
        Unpacks the resolved subject/language/location objects into
        the model's existing FK fields - this is the ONLY place
        text-resolution results get translated into database FKs.

        Any inline schedule_preferences are persisted here too, via
        PreferenceService (same overlap/limit/full_clean guarantees
        as the standalone preferences endpoint), so they exist
        before the view runs lead generation + distribution.
        """
        location_result = validated_data.pop("city", None)
        student = validated_data.pop("student")
        preferences = validated_data.pop("schedule_preferences", [])

        requirement = StudentRequirement(student=student, **validated_data)
        if location_result is not None:
            requirement.city = location_result.city
            requirement.pincode_location = location_result.pincode_location
        requirement.save()

        self._apply_preferences(requirement, preferences)
        return requirement

    def update(self, instance, validated_data):
        location_result = validated_data.pop("city", None)
        preferences = validated_data.pop("schedule_preferences", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if location_result is not None:
            instance.city = location_result.city
            instance.pincode_location = location_result.pincode_location
        instance.save()

        # Only touch preferences when the caller explicitly sent the
        # key - a PATCH that omits it leaves existing windows alone.
        if preferences is not None:
            # Hard-delete: the unique (requirement, day, start, end, tz)
            # constraint is enforced at the DB level, so a soft-deleted
            # row would still block re-adding the same window.
            for existing in instance.schedule_preferences.all():
                existing.delete(hard=True)
            self._apply_preferences(instance, preferences)
        return instance

    @staticmethod
    def _apply_preferences(requirement, preferences):
        from django.core.exceptions import ValidationError as DjangoValidationError

        from apps.core.exceptions.custom_exceptions import ValidationException
        from apps.student_requirement.services.preference_service import (
            PreferenceService,
        )

        for pref in preferences:
            try:
                PreferenceService.create_preference(requirement, **pref)
            except (ValidationException, DjangoValidationError) as exc:
                detail = (
                    getattr(exc, "detail", None)
                    or getattr(exc, "messages", None)
                    or str(exc)
                )
                raise serializers.ValidationError({"schedule_preferences": detail})


class StudentSchedulePreferenceSerializer(serializers.ModelSerializer):
    """Read/write representation of a single schedule preference slot."""

    class Meta:
        model = StudentSchedulePreference
        fields = (
            "id",
            "day_of_week",
            "start_time",
            "end_time",
            "timezone",
            "flexibility",
            "priority",
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


class StudentScheduleExceptionSerializer(serializers.ModelSerializer):
    """Read/write representation of a one-off student schedule exception."""

    class Meta:
        model = StudentScheduleException
        fields = ("id", "date", "reason", "created_at")
        read_only_fields = ("id", "created_at")

    def validate_reason(self, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

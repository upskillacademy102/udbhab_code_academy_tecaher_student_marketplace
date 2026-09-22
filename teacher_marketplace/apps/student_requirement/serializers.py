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

import logging

from rest_framework import serializers

from apps.languages.serializers import LanguageSerializer
from apps.location.serializers import CitySerializer
from apps.student_requirement.models import (
    MAX_PREFERRED_LANGUAGES,
    RequirementStatus,
    StudentRequirement,
    StudentRequirementLanguage,
    StudentScheduleException,
    StudentSchedulePreference,
)
from apps.subjects.serializers import SubjectSerializer
from apps.teacher_profile.models import TeachingMode

logger = logging.getLogger("apps.student_requirement")


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
    preferred_languages = serializers.SerializerMethodField()
    no_language_preference = serializers.BooleanField(read_only=True)
    city = CitySerializer(read_only=True)
    # A requirement created via the pincode escape hatch (see validate_city /
    # LocationResolutionService.resolve) has city=None and only
    # pincode_location set - without this, the location a student typed in
    # was accepted and used for real matching, but never shown back to them
    # anywhere (looked, to them, like it had been silently dropped).
    pincode = serializers.SerializerMethodField()
    student_name = serializers.CharField(source="student.get_full_name", read_only=True)
    schedule_preferences = SchedulePreferenceReadSerializer(many=True, read_only=True)
    has_unlocked_lead = serializers.SerializerMethodField()

    class Meta:
        model = StudentRequirement
        fields = (
            "id",
            "student_name",
            "subject",
            "student_class",
            "preferred_languages",
            "no_language_preference",
            "budget_min",
            "budget_max",
            "teaching_mode",
            "city",
            "pincode",
            "preferred_timing",
            "description",
            "status",
            "lead_distribution_status",
            "schedule_preferences",
            "has_unlocked_lead",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_pincode(self, obj):
        loc = obj.pincode_location
        if loc is None or loc.pincode.startswith("CITY:"):
            return None
        return loc.pincode

    def get_has_unlocked_lead(self, obj):
        """
        True once ANY teacher has unlocked this requirement's contact
        details - the real "can the student still edit this" signal
        (see StudentRequirementWriteSerializer.validate), independent of
        `status` (which flips to MATCHED the moment a teacher is merely
        soft-matched, long before anyone actually unlocks anything).

        Prefers the `has_unlocked_lead` queryset annotation (Exists/
        OuterRef in StudentRequirementListCreateView/DetailView's
        get_queryset) when present - one query for the whole list/detail
        response - falling back to a direct query for an instance built
        outside that queryset (e.g. the object update() just saved and
        handed straight back to this serializer).
        """
        if hasattr(obj, "has_unlocked_lead"):
            return obj.has_unlocked_lead
        return obj.leads.filter(contact_unlocked=True).exists()

    def get_preferred_languages(self, obj):
        """
        Ranked most-to-least preferred (StudentRequirementLanguage.Meta.
        ordering = ["rank"]) - the response's array order IS the rank, no
        separate rank field needed on the wire.
        """
        return LanguageSerializer(
            [pl.language for pl in obj.preferred_languages.all()], many=True
        ).data


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

    PHASE 5 UPDATE: subject, preferred_languages, and city/pincode are
    now PLAIN TEXT fields, resolved internally via
    SubjectMatchingService / LanguageMatchingService /
    LocationResolutionService (exact -> alias -> fuzzy, pg_trgm-
    backed). UUID input is no longer accepted on these fields per
    explicit decision - this is an intentional breaking change from
    the earlier UUID-based contract. The resolved UUIDs are stored
    on the model's existing FK fields exactly as before; only the
    API's INPUT shape has changed, not the database schema or the
    downstream matching/ranking/lead-distribution engines.

    LANGUAGE IS MANDATORY: `preferred_languages` (a ranked list, most
    preferred first) and `no_language_preference` (the explicit "Any
    language" choice) are mutually exclusive and together required -
    every submission must supply at least one language OR set
    no_language_preference true. See `validate()` for the exact rule
    and StudentRequirement.no_language_preference's docstring for why
    this mirrors schedule_preferences' flexible/specific shape.

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
    preferred_languages = serializers.ListField(
        child=serializers.CharField(max_length=60),
        required=False,
        default=list,
        help_text=(
            "Ranked language names, most preferred first, e.g. "
            "['Bengali', 'English']. Required unless no_language_preference "
            "is true."
        ),
    )
    no_language_preference = serializers.BooleanField(
        required=False,
        default=False,
        help_text="True if the student is fine with any language of instruction.",
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
            "preferred_languages",
            "no_language_preference",
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
        from django.db import IntegrityError, transaction

        from apps.matching.services.subject_matching_service import (
            SubjectMatchingService,
        )
        from apps.subjects.models import Subject
        from apps.utils.validators import validate_taxonomy_name

        viewer = getattr(self.context.get("request"), "user", None)
        result = SubjectMatchingService.match_by_text(value, viewer=viewer)
        if result.is_eligible and result.matched_subject is not None:
            return result.matched_subject

        # No existing/alias/fuzzy match: this is a genuinely new subject a
        # student typed via the "Something else" escape, not a typo of an
        # existing one (that's what the fuzzy tier above already catches).
        # Add it to the taxonomy rather than bouncing the student - it's
        # then real, active, and available to every future picker/search.
        name = value.strip()
        try:
            validate_taxonomy_name(name)
        except Exception:
            raise serializers.ValidationError(
                f"Subject '{value}' not recognized. Please check the spelling or contact support."
            )

        try:
            with transaction.atomic():
                subject = Subject.objects.create(name=name, is_active=True)
            logger.info("Subject auto-created from student requirement: %s", name)
        except IntegrityError:
            # Lost a race with a concurrent identical submission.
            subject = Subject.objects.filter(name__iexact=name, is_active=True).first()
            if subject is None:
                raise serializers.ValidationError(
                    f"Subject '{value}' not recognized. Please check the spelling or contact support."
                )
        return subject

    def validate_preferred_languages(self, value):
        if len(value) > MAX_PREFERRED_LANGUAGES:
            raise serializers.ValidationError(
                f"Pick at most {MAX_PREFERRED_LANGUAGES} languages."
            )
        resolved = []
        seen_ids = set()
        for name in value:
            language = self._resolve_language(name)
            if language.id in seen_ids:
                raise serializers.ValidationError(
                    f"'{language.name}' was listed more than once."
                )
            seen_ids.add(language.id)
            resolved.append(language)
        return resolved

    def _resolve_language(self, value):
        """
        Exact/alias/fuzzy match via LanguageMatchingService, falling back
        to auto-creating a genuinely new language - same three-tier
        resolution as validate_subject, applied per-item since this field
        is now a ranked list rather than one value.
        """
        from django.db import IntegrityError, transaction

        from apps.languages.models import Language
        from apps.languages.services import derive_language_code
        from apps.matching.services.language_matching_service import (
            LanguageMatchingService,
        )
        from apps.utils.validators import validate_taxonomy_name

        viewer = getattr(self.context.get("request"), "user", None)
        result = LanguageMatchingService.match_by_text(value, viewer=viewer)
        if result.is_eligible and result.matched_subject is not None:
            return result.matched_subject

        name = value.strip()
        try:
            validate_taxonomy_name(name)
        except Exception:
            raise serializers.ValidationError(
                f"Language '{value}' not recognized. Please check the spelling or contact support."
            )

        code = derive_language_code(name)
        try:
            with transaction.atomic():
                language = Language.objects.create(name=name, code=code, is_active=True)
            logger.info(
                "Language auto-created from student requirement: %s (%s)", name, code
            )
        except IntegrityError:
            # Lost a race with a concurrent identical submission.
            language = Language.objects.filter(name__iexact=name, is_active=True).first()
            if language is None:
                raise serializers.ValidationError(
                    f"Language '{value}' not recognized. Please check the spelling or contact support."
                )
        return language

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
        # A requirement stays editable through OPEN/MATCHED/whatever
        # status - status flips to MATCHED the moment a teacher is merely
        # soft-matched (a Lead row exists), which is not a reason to lock
        # editing. The real lock is a teacher having actually unlocked the
        # student's contact details: at that point the requirement has
        # been acted on and changing it under a teacher's feet isn't safe.
        if self.instance is not None and self.instance.leads.filter(
            contact_unlocked=True
        ).exists():
            raise serializers.ValidationError(
                "This request can no longer be edited - a teacher has "
                "already unlocked your contact details."
            )

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

        # Language is a mandatory, mutually-exclusive choice: a ranked list
        # OR "any language", never neither, never both. On a full (create)
        # request both keys are always present (field defaults apply), so
        # this always runs. On a partial (PATCH) request it only runs if
        # the client actually touched one of the two keys - same "only
        # touch what was sent" contract as schedule_preferences/city -
        # so a PATCH that doesn't mention language leaves the existing,
        # already-valid choice alone.
        no_pref = attrs.get("no_language_preference")
        langs = attrs.get("preferred_languages")
        if no_pref is not None or langs is not None:
            if no_pref:
                # "Any language" wins - a list sent alongside it is dropped
                # rather than erroring, same leniency as WindowPicker's
                # flexible/windows toggle on the frontend.
                attrs["preferred_languages"] = []
            elif langs:
                attrs["no_language_preference"] = False
            else:
                raise serializers.ValidationError(
                    {
                        "preferred_languages": (
                            'Pick at least one language, or choose "Any language".'
                        )
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
        languages = validated_data.pop("preferred_languages", [])

        requirement = StudentRequirement(student=student, **validated_data)
        if location_result is not None:
            requirement.city = location_result.city
            requirement.pincode_location = location_result.pincode_location
        requirement.save()

        self._apply_preferences(requirement, preferences)
        self._apply_languages(requirement, languages)
        return requirement

    def update(self, instance, validated_data):
        location_result = validated_data.pop("city", None)
        preferences = validated_data.pop("schedule_preferences", None)
        languages = validated_data.pop("preferred_languages", None)
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

        # Same "only touch what was explicitly sent" contract - reached
        # whenever validate() put a (possibly empty, for the "switched to
        # Any language" case) list into validated_data.
        if languages is not None:
            for existing in instance.preferred_languages.all():
                existing.delete(hard=True)
            self._apply_languages(instance, languages)
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

    @staticmethod
    def _apply_languages(requirement, languages):
        StudentRequirementLanguage.objects.bulk_create(
            StudentRequirementLanguage(
                student_requirement=requirement, language=language, rank=rank
            )
            for rank, language in enumerate(languages, start=1)
        )


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

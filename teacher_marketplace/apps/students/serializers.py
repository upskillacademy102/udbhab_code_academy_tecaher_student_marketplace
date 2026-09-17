"""
Serializers for the students app.

Covers:
    - StudentSerializer        -> read representation (GET), embeds
                                   basic user info via UserSerializer.
    - StudentCreateUpdateSerializer -> write representation (POST/PUT/
                                   PATCH), used by the authenticated
                                   student to create/update their own
                                   profile.

Phase 1 scope note: no matching/search/ranking logic lives here -
these serializers only validate and shape Student profile data.
"""

import logging

from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.students.models import Student

logger = logging.getLogger("apps.students")


class StudentSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a Student profile, embedding the
    related User's public info. Used for GET /students/{id}/ and
    list endpoints.
    """

    user = UserSerializer(read_only=True)

    class Meta:
        model = Student
        fields = (
            "id",
            "user",
            "profile_photo",
            "education_level",
            "grade_or_year",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "pincode",
            "country",
            "preferred_subjects",
            "bio",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class StudentCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Write representation for creating/updating a Student profile.
    The `user` field is deliberately NOT writable here - it's
    always set from request.user in the view (a student can only
    ever create/edit their OWN profile), never accepted as
    client-supplied input.
    """

    class Meta:
        model = Student
        fields = (
            "id",
            "profile_photo",
            "education_level",
            "grade_or_year",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "pincode",
            "country",
            "preferred_subjects",
            "bio",
        )
        read_only_fields = ("id",)

    # Optional free-text fields: normalise "" / "   " -> None so the DB
    # only ever holds a real value or NULL, never a blank string.
    _NULLABLE_TEXT = (
        "grade_or_year",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "pincode",
        "country",
        "preferred_subjects",
        "bio",
    )

    def validate(self, attrs):
        for field in self._NULLABLE_TEXT:
            if field in attrs:
                v = attrs[field]
                if isinstance(v, str):
                    v = v.strip()
                    attrs[field] = v or None
        return attrs

    def create(self, validated_data):
        instance = super().create(validated_data)
        self._resolve_pincode(instance, "pincode" in validated_data)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        self._resolve_pincode(instance, "pincode" in validated_data)
        return instance

    @staticmethod
    def _resolve_pincode(instance, pincode_was_submitted: bool):
        """Mirrors TeacherCreateUpdateSerializer._resolve_pincode exactly -
        see that docstring. Best-effort here too: the address itself was
        already saved by super().create()/update() by the time this runs,
        and nothing currently queries a student's pincode_location, so a
        geocoding provider being unreachable must never fail the request -
        this just keeps the same structured-location capability available
        for a future in-person student-side matching use, same reasoning
        as the model field."""
        if not pincode_was_submitted:
            return
        if not instance.pincode:
            if instance.pincode_location_id is not None:
                instance.pincode_location = None
                instance.save(update_fields=["pincode_location"])
            return

        from apps.matching.services.geocoding_service import (
            GeocodingError,
            PincodeGeocodingService,
        )

        try:
            location = PincodeGeocodingService.get_or_geocode(instance.pincode)
        except GeocodingError:
            # A location left over from a DIFFERENT, previously-saved
            # pincode must not survive a failed re-geocode of a changed
            # one - see TeacherCreateUpdateSerializer._resolve_pincode's
            # docstring for why a stale-but-present location is worse
            # than none at all.
            stale = (
                instance.pincode_location_id is not None
                and instance.pincode_location.pincode != instance.pincode
            )
            if stale:
                instance.pincode_location = None
                instance.save(update_fields=["pincode_location"])
            logger.warning(
                "Could not resolve pincode %s for student %s - address saved, "
                "pincode_location %s.",
                instance.pincode,
                instance.pk,
                "cleared (was stale for a different pincode)" if stale else "left as-is",
            )
            return
        instance.pincode_location = location
        instance.save(update_fields=["pincode_location"])

    def validate_preferred_subjects(self, value):
        """
        Normalise the comma-separated list: trim each entry, drop blanks
        and duplicates, and cap it so the field can't be stuffed with
        junk (max 15 subjects, each 1-60 chars).
        """
        if not value:
            return value
        seen, subjects = set(), []
        for raw in value.split(","):
            s = raw.strip()
            if not s or s.lower() in seen:
                continue
            if len(s) > 60:
                raise serializers.ValidationError(
                    f"'{s[:20]}…' is too long for a subject name (max 60 characters)."
                )
            seen.add(s.lower())
            subjects.append(s)
        if len(subjects) > 15:
            raise serializers.ValidationError(
                "Please list at most 15 preferred subjects."
            )
        return ", ".join(subjects)

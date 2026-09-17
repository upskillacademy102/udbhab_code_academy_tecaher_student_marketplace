"""
Serializers for the teachers app.

Covers:
    - TeacherSerializer            -> read representation (GET),
                                       embeds basic user info via
                                       UserSerializer.
    - TeacherCreateUpdateSerializer -> write representation (POST/
                                       PUT/PATCH), used by the
                                       authenticated teacher to
                                       create/update their own
                                       profile.

Phase 1 scope note: no token/wallet/premium logic lives here -
these serializers only validate and shape Teacher profile data.
Note: student contact details are NOT part of this app at all
(Teacher never has a direct relation to Student contact info in
Phase 1) - that unlock mechanism is explicit later-phase business
logic (wallet/lead matching), so no field or serializer here even
hints at it.
"""

import logging

from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.teachers.models import Teacher

logger = logging.getLogger("apps.teachers")


class TeacherSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a Teacher profile, embedding the
    related User's public info. Used for GET /teachers/{id}/ and
    list endpoints - this is what a Student would see when browsing
    teachers for free. Uses PublicUserSerializer, so a teacher's
    email/mobile are never exposed through search/browse - direct
    contact is unlock-gated via the lead flow. Admins see full
    contact details through /api/v1/admin/users/.
    """

    user = PublicUserSerializer(read_only=True)
    verification_status = serializers.SerializerMethodField()

    class Meta:
        model = Teacher
        fields = (
            "id",
            "user",
            "profile_photo",
            "bio",
            "experience_years",
            "qualification_level",
            "qualification_detail",
            "subjects_taught",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "pincode",
            "country",
            "verification_status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_verification_status(self, obj) -> str:
        """From the marketplace profile if one exists, else 'pending'."""
        profile = getattr(obj, "marketplace_profile", None)
        return profile.verification_status if profile is not None else "pending"


class TeacherCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Write representation for creating/updating a Teacher profile.
    The `user` field is deliberately NOT writable here - always set
    from request.user in the view, never accepted as client input,
    for the same security reasoning as StudentCreateUpdateSerializer.
    """

    class Meta:
        model = Teacher
        fields = (
            "id",
            "profile_photo",
            "bio",
            "experience_years",
            "qualification_level",
            "qualification_detail",
            "subjects_taught",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "pincode",
            "country",
        )
        read_only_fields = ("id",)

    def validate_experience_years(self, value):
        """
        Range check mirrors the model-level MinValueValidator/
        MaxValueValidator(0, 80) - duplicated here so invalid
        values are rejected at the serializer layer with a clear
        DRF-style field error, rather than only surfacing as a
        less friendly IntegrityError/ValidationError at save time.
        """
        if value is not None and not (0 <= value <= 80):
            raise serializers.ValidationError(
                "Years of experience must be between 0 and 80."
            )
        return value

    _NULLABLE_TEXT = (
        "bio",
        "qualification_detail",
        "subjects_taught",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "pincode",
        "country",
    )

    def validate(self, attrs):
        # Optional free-text: "" / "   " -> None (matches the not-blank DB CHECK).
        for field in self._NULLABLE_TEXT:
            if field in attrs and isinstance(attrs[field], str):
                attrs[field] = attrs[field].strip() or None

        # A full address is required once this teacher's marketplace listing
        # (TeacherProfile.teaching_mode) says Offline or Both - a purely
        # Online teacher has nothing to deliver an in-person lesson to.
        # Mirrors StudentRequirementWriteSerializer's "city required when
        # teaching_mode is Offline or Both" rule exactly, just cross-
        # referencing the related TeacherProfile (teaching_mode lives
        # there, not on this model) instead of a field on this same one.
        from apps.teacher_profile.models import TeacherProfile, TeachingMode

        teaching_mode = None
        if self.instance is not None:
            try:
                teaching_mode = self.instance.marketplace_profile.teaching_mode
            except TeacherProfile.DoesNotExist:
                teaching_mode = None

        if teaching_mode in (TeachingMode.OFFLINE, TeachingMode.BOTH):
            address_line1 = attrs.get(
                "address_line1", getattr(self.instance, "address_line1", None)
            )
            city = attrs.get("city", getattr(self.instance, "city", None))
            pincode = attrs.get("pincode", getattr(self.instance, "pincode", None))
            if not (address_line1 and city and pincode):
                raise serializers.ValidationError(
                    {
                        "address_line1": (
                            "A full address (address, city, and PIN code) is "
                            "required once you offer in-person or either lessons."
                        )
                    }
                )
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
        """
        Keeps `pincode_location` (what LocationMatchingService actually
        queries) in sync with the plain-text `pincode` field a teacher
        types into the address form - same geocode-and-cache service
        MyPincodeView already uses, so both paths converge on the same
        PincodeLocation rows rather than resolving pincodes twice over.
        Only runs when `pincode` was actually part of this request - a
        PATCH that doesn't touch it must not re-geocode or clear anything.

        Best-effort: the address itself (address_line1/city/pincode) was
        already persisted by super().create()/update() above by the time
        this runs, so a geocoding provider being unreachable must never
        undo that save or fail the whole request - it only means
        `pincode_location` stays unresolved until a future save retries it.

        IMPORTANT: on a failed re-geocode, an existing `pincode_location`
        left over from a PREVIOUS, different pincode must be cleared, not
        left in place - otherwise distance-based matching would keep
        using a stale location that no longer matches the pincode text
        actually on file (a teacher who changes their pincode, hits a
        transient provider outage, and is silently matched against their
        OLD address instead of the new one - or not at all - is worse
        than a teacher with no resolved location at all).
        """
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
            stale = (
                instance.pincode_location_id is not None
                and instance.pincode_location.pincode != instance.pincode
            )
            if stale:
                instance.pincode_location = None
                instance.save(update_fields=["pincode_location"])
            logger.warning(
                "Could not resolve pincode %s for teacher %s - address saved, "
                "pincode_location %s.",
                instance.pincode,
                instance.pk,
                "cleared (was stale for a different pincode)" if stale else "left as-is",
            )
            return
        instance.pincode_location = location
        instance.save(update_fields=["pincode_location"])

    def validate_subjects_taught(self, value):
        """
        Normalise the comma-separated list: trim, drop blanks + case-insensitive
        duplicates, and cap it (max 20 subjects, each 1-60 chars) so the field
        can't be stuffed with junk. Mirrors the student side.
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
        if len(subjects) > 20:
            raise serializers.ValidationError("Please list at most 20 subjects.")
        return ", ".join(subjects)

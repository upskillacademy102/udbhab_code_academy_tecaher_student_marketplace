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

from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer
from apps.teachers.models import Teacher


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
            "city",
            "state",
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
            "city",
            "state",
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
        "city",
        "state",
        "country",
    )

    def validate(self, attrs):
        # Optional free-text: "" / "   " -> None (matches the not-blank DB CHECK).
        for field in self._NULLABLE_TEXT:
            if field in attrs and isinstance(attrs[field], str):
                attrs[field] = attrs[field].strip() or None
        return attrs

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

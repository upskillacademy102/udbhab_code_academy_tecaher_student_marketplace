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

from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.students.models import Student


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
            "city",
            "state",
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
            "city",
            "state",
            "country",
            "preferred_subjects",
            "bio",
        )
        read_only_fields = ("id",)

    # Optional free-text fields: normalise "" / "   " -> None so the DB
    # only ever holds a real value or NULL, never a blank string.
    _NULLABLE_TEXT = (
        "grade_or_year",
        "city",
        "state",
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

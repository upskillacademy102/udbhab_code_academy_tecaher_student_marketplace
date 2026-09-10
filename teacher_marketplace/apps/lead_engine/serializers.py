"""
Serializers for the lead_engine app.

CONTACT MASKING RULE: LeadSerializer exposes real student contact
details (name, phone, email) ONLY when lead.contact_unlocked is
True - which, as of Phase 3, happens exclusively via
apps.lead_engine.unlock_service.unlock_lead_contact(), following
the spec's exact free-quota/token-deduction workflow. Every lead
starts masked as "********" and stays masked until that specific
teacher successfully unlocks that specific lead. There is no other
code path anywhere in this project that sets contact_unlocked to
True.
"""

from rest_framework import serializers

from apps.lead_engine.models import (
    Lead,
    LeadMatchScore,
    LeadUnlockHistory,
    LeadUnlockPricing,
)
from apps.student_requirement.serializers import StudentRequirementSerializer

MASKED_VALUE = "********"


class LeadStudentRequirementSerializer(StudentRequirementSerializer):
    """
    A restricted view of StudentRequirement for the teacher-facing
    Lead Dashboard. Extends StudentRequirementSerializer but
    overrides student_name to always show a masked value - a
    teacher should see WHAT a student needs (subject, budget,
    location, timing), never WHO the student is, until contact is
    unlocked (Phase 3).
    """

    student_name = serializers.SerializerMethodField()

    def get_student_name(self, obj) -> str:
        return MASKED_VALUE


class LeadSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a Lead for the teacher-facing Lead
    Dashboard. Nests the (contact-masked) StudentRequirement and
    exposes explicit masked_contact fields, per the spec's example:

        Student Name  ********
        Phone          ********
        Email          ********

    masked_contact is ALWAYS present and ALWAYS masked in Phase 2 -
    the `if lead.contact_unlocked` branch exists structurally so
    Phase 3 can populate real values there without restructuring
    this serializer, but that branch is currently unreachable since
    nothing in this codebase ever sets contact_unlocked to True.
    """

    student_requirement = LeadStudentRequirementSerializer(read_only=True)
    masked_contact = serializers.SerializerMethodField()
    my_rating = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = (
            "id",
            "student_requirement",
            "status",
            "is_viewed",
            "viewed_at",
            "contact_unlocked",
            "masked_contact",
            "my_rating",
            "created_at",
        )
        read_only_fields = fields

    def get_my_rating(self, lead) -> str | None:
        """The requesting teacher's quality verdict on this lead, or null."""
        request = self.context.get("request")
        teacher = getattr(
            getattr(request, "user", None), "teacher_profile", None
        )
        if teacher is None:
            return None
        from apps.trust.models import LeadQualityRating

        row = (
            LeadQualityRating.objects.filter(teacher=teacher, lead=lead)
            .values_list("verdict", flat=True)
            .first()
        )
        return row

    def get_masked_contact(self, lead) -> dict:
        """
        Returns the contact info block shown to the teacher.

        PHASE 3 UPDATE: the `if lead.contact_unlocked` branch below
        is now a REAL, reachable code path - apps.lead_engine.
        unlock_service.unlock_lead_contact() is the only place that
        sets contact_unlocked=True, always immediately after either
        a free-quota consumption or a successful token debit (see
        that module for the full STEP 1/STEP 2 logic). Until a
        teacher successfully unlocks a specific lead, this always
        returns masked values, exactly as in Phase 2.
        """
        if lead.contact_unlocked:
            student = lead.student_requirement.student
            return {
                "student_name": student.get_full_name(),
                "phone": student.mobile,
                "email": student.email,
            }

        return {
            "student_name": MASKED_VALUE,
            "phone": MASKED_VALUE,
            "email": MASKED_VALUE,
        }


class LeadListSerializer(serializers.ModelSerializer):
    """
    Lighter-weight serializer for the Lead LIST view (as opposed to
    LeadSerializer's fuller detail view) - avoids nesting the full
    StudentRequirement (with its own nested subject/language/city
    objects) on every row of a potentially long lead list, keeping
    list responses smaller. Still fully masks contact info.
    """

    subject_name = serializers.CharField(
        source="student_requirement.subject.name", read_only=True
    )
    teaching_mode = serializers.CharField(
        source="student_requirement.teaching_mode", read_only=True
    )
    city_name = serializers.CharField(
        source="student_requirement.city.name", read_only=True, default=None
    )
    budget_min = serializers.DecimalField(
        source="student_requirement.budget_min",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    budget_max = serializers.DecimalField(
        source="student_requirement.budget_max",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    student_name = serializers.SerializerMethodField()
    my_rating = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = (
            "id",
            "subject_name",
            "teaching_mode",
            "city_name",
            "budget_min",
            "budget_max",
            "student_name",
            "status",
            "is_viewed",
            "contact_unlocked",
            "my_rating",
            "created_at",
        )
        read_only_fields = fields

    def get_student_name(self, obj) -> str:
        return MASKED_VALUE

    def get_my_rating(self, obj) -> str | None:
        """This teacher's quality verdict on the lead, or null if unrated.
        Only populated when the view supplied a ``my_ratings`` context map."""
        ratings = self.context.get("my_ratings")
        if ratings is None:
            return None
        return ratings.get(obj.id)


class LeadUnlockPricingSerializer(serializers.ModelSerializer):
    """Read representation of a LeadUnlockPricing row."""

    class Meta:
        model = LeadUnlockPricing
        fields = ("id", "tier", "token_cost", "is_active", "created_at", "updated_at")
        read_only_fields = fields


class LeadUnlockPricingWriteSerializer(serializers.ModelSerializer):
    """Admin-only write representation for configuring unlock pricing."""

    class Meta:
        model = LeadUnlockPricing
        fields = ("id", "tier", "token_cost", "is_active")
        read_only_fields = ("id",)

    def validate_token_cost(self, value):
        if value <= 0:
            raise serializers.ValidationError("Token cost must be positive.")
        return value


class LeadUnlockHistorySerializer(serializers.ModelSerializer):
    """
    Read-only representation of a single unlock event, used for a
    teacher's own unlock history and for Admin's platform-wide
    "Lead Unlock History" view (per the spec's Admin Panel
    requirement). Nests minimal lead/subject context so the row is
    meaningful without a second lookup.
    """

    subject_name = serializers.CharField(
        source="lead.student_requirement.subject.name", read_only=True
    )
    teacher_name = serializers.CharField(
        source="teacher.user.get_full_name", read_only=True
    )

    class Meta:
        model = LeadUnlockHistory
        fields = (
            "id",
            "teacher_name",
            "lead",
            "subject_name",
            "is_free_unlock",
            "tokens_deducted",
            "created_at",
        )
        read_only_fields = fields


class LeadMatchScoreSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a LeadMatchScore, shaped to match
    the spec's exact example response structure under "Match
    Result" - includes teacher_id/teacher_name computed from the
    related Lead, alongside the stored score breakdown fields.
    """

    teacher_id = serializers.UUIDField(
        source="lead.teacher_profile.teacher.id", read_only=True
    )
    teacher_name = serializers.CharField(
        source="lead.teacher_profile.teacher.user.get_full_name", read_only=True
    )
    best_matching_day = serializers.SerializerMethodField()

    class Meta:
        model = LeadMatchScore
        fields = (
            "teacher_id",
            "teacher_name",
            "match_score",
            "subject_score",
            "language_score",
            "time_score",
            "location_score",
            "budget_score",
            "rating_score",
            "experience_score",
            "verification_score",
            "response_rate_score",
            "premium_score",
            "best_matching_day",
            "best_matching_start_time",
            "best_matching_end_time",
            "best_matching_timezone",
            "availability_status",
        )
        read_only_fields = fields

    def get_best_matching_day(self, obj) -> str | None:
        """
        Converts the stored integer (1=Monday...7=Sunday) into the
        display name string, matching the spec's exact example
        ("best_matching_day": "Monday").
        """
        if obj.best_matching_day is None:
            return None
        from apps.teacher_profile.models import DayOfWeek

        return DayOfWeek(obj.best_matching_day).label

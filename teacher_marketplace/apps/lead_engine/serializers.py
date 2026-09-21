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
    Dashboard detail view. Nests the (contact-masked) StudentRequirement
    and exposes explicit masked_contact fields, per the spec's example:

        Student Name  ********
        Phone          ********
        Email          ********

    masked_contact is ALWAYS present and ALWAYS masked in Phase 2 -
    the `if lead.contact_unlocked` branch exists structurally so
    Phase 3 can populate real values there without restructuring
    this serializer, but that branch is currently unreachable since
    nothing in this codebase ever sets contact_unlocked to True.

    ALSO exposes the same flat convenience fields as LeadListSerializer
    (subject_name, teaching_mode, city_name, budget_min, budget_max,
    description, preferred_timing) plus flat student_name/student_mobile/
    student_email (populated only once contact_unlocked, else null) - so
    the detail endpoint's top-level shape is a superset of the list
    endpoint's, never a DIFFERENT one. This was previously not the case:
    the detail endpoint only nested this data under student_requirement/
    masked_contact, while a consumer coded against the list endpoint's
    flat contract (a reasonable assumption for "the same resource, more
    detail") silently got nothing back for every one of these fields -
    including, worst of all, the unlocked contact details themselves.
    Both shapes are kept so nothing that already reads the nested one
    (e.g. the legacy Django lead-detail page) breaks.
    """

    student_requirement = LeadStudentRequirementSerializer(read_only=True)
    masked_contact = serializers.SerializerMethodField()
    my_rating = serializers.SerializerMethodField()

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
    description = serializers.CharField(
        source="student_requirement.description", read_only=True, default=None
    )
    preferred_timing = serializers.CharField(
        source="student_requirement.preferred_timing", read_only=True, default=None
    )
    student_name = serializers.SerializerMethodField()
    student_mobile = serializers.SerializerMethodField()
    student_email = serializers.SerializerMethodField()
    unlocked_count = serializers.SerializerMethodField()
    is_direct_offer = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = (
            "id",
            "student_requirement",
            "subject_name",
            "teaching_mode",
            "city_name",
            "budget_min",
            "budget_max",
            "description",
            "preferred_timing",
            "status",
            "is_viewed",
            "viewed_at",
            "contact_unlocked",
            "masked_contact",
            "student_name",
            "student_mobile",
            "student_email",
            "my_rating",
            "unlocked_count",
            "is_direct_offer",
            "created_at",
        )
        read_only_fields = fields

    def get_student_name(self, lead) -> str | None:
        """Flat, unlock-gated counterpart to masked_contact['student_name']."""
        if not lead.contact_unlocked:
            return None
        return lead.student_requirement.student.get_full_name()

    def get_student_mobile(self, lead) -> str | None:
        if not lead.contact_unlocked:
            return None
        return lead.student_requirement.student.mobile

    def get_student_email(self, lead) -> str | None:
        if not lead.contact_unlocked:
            return None
        return lead.student_requirement.student.email

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

    def get_unlocked_count(self, lead) -> int | None:
        """
        How many teachers (across the whole eligible pool, not just
        this one) have unlocked this lead - the "N teachers already
        unlocked this lead" contrasting badge. Only meaningful for
        shared/pooled ONLINE leads, but harmless to show for any
        mode. Populated only when the view supplied it in context
        (LeadDetailView.get) - null otherwise, same convention as
        get_my_rating.
        """
        return self.context.get("unlocked_count")

    def get_is_direct_offer(self, lead) -> bool:
        """True when this teacher was picked directly ("Learn with this
        teacher") rather than matched into the general pool - see
        LeadDetailView.get. Rejecting this kind of lead has no "next
        teacher" to fall through to, unlike an ordinary cascading lead, so
        the frontend needs this to show accurate reject-consequence copy."""
        return bool(self.context.get("is_direct_offer"))

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
    list responses smaller.

    student_name/student_mobile stay masked until contact_unlocked - same
    unlock-gated rule as LeadSerializer's flat contact fields, so a
    dashboard/list row can show the real name and number for a lead this
    teacher has already paid to unlock, without a second request to the
    detail endpoint.
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
    description = serializers.CharField(
        source="student_requirement.description", read_only=True, default=None
    )
    preferred_timing = serializers.CharField(
        source="student_requirement.preferred_timing", read_only=True, default=None
    )
    student_name = serializers.SerializerMethodField()
    student_mobile = serializers.SerializerMethodField()
    my_rating = serializers.SerializerMethodField()
    unlocked_count = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = (
            "id",
            "subject_name",
            "teaching_mode",
            "city_name",
            "budget_min",
            "budget_max",
            "description",
            "preferred_timing",
            "student_name",
            "student_mobile",
            "status",
            "is_viewed",
            "contact_unlocked",
            "my_rating",
            "unlocked_count",
            "created_at",
        )
        read_only_fields = fields

    def get_student_name(self, obj) -> str:
        if not obj.contact_unlocked:
            return MASKED_VALUE
        return obj.student_requirement.student.get_full_name()

    def get_student_mobile(self, obj) -> str | None:
        if not obj.contact_unlocked:
            return None
        return obj.student_requirement.student.mobile

    def get_my_rating(self, obj) -> str | None:
        """This teacher's quality verdict on the lead, or null if unrated.
        Only populated when the view supplied a ``my_ratings`` context map."""
        ratings = self.context.get("my_ratings")
        if ratings is None:
            return None
        return ratings.get(obj.id)

    def get_unlocked_count(self, obj) -> int | None:
        """How many teachers across the whole pool have unlocked this
        lead - see LeadSerializer.get_unlocked_count. Only populated
        when the view supplied an ``unlock_counts`` context map."""
        counts = self.context.get("unlock_counts")
        if counts is None:
            return None
        return counts.get(obj.id, 0)


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

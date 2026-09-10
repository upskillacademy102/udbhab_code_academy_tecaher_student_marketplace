"""
Models for the matching app.

Covers:
    - PincodeLocation: real geographic coordinates per pincode,
      used by LocationMatchingService for haversine/PostGIS
      distance queries. Coordinates are never invented - this
      table must be seeded from a real data source (see the admin
      import path noted in this app's admin.py).
    - SubjectAlias / LanguageAlias: alternate names/spellings
      ("Math" -> Mathematics) checked AFTER exact FK match and
      BEFORE fuzzy fallback, per the matching spec's exact
      precedence: normalized ID -> alias -> fuzzy. alias_text has a
      GIN trigram index (pg_trgm, enabled at the database level) so
      the fuzzy fallback itself can run as an indexed SQL query
      rather than a Python-side scan.
    - LeadAssignment: the formal, auditable per-teacher lead offer
      record the spec explicitly requires instead of a bare
      lead.teacher_id - one row per (lead, teacher) pairing, with
      its own state machine and timing.
    - MatchingConfig: DB-backed override for matching thresholds/
      radii/weights, per the spec's explicit preference for
      admin-editable configuration over redeploy-required settings.
      Falls back to settings.py defaults if no config row exists.
"""

from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import validate_no_control_characters, validate_place_name

# Sane ceilings for admin-editable matching parameters.
MAX_MATCH_MINUTES = 1_440  # 24h
MAX_RADIUS_KM = 5_000
MAX_RESPONSE_WINDOW_HOURS = 720  # 30 days
MAX_PRIORITY_ORDER_ENTRIES = 20


# ==============================================================
# PINCODE / GEOGRAPHIC LOCATION
# ==============================================================
class PincodeLocation(BaseModel):
    """
    Real geographic coordinates for a pincode/ZIP code. This is
    reference data - it must be imported from a genuine geocoding
    source (e.g. a national postal dataset or a geocoding API),
    never fabricated. See admin.py for the bulk-import mechanism.

    `location` uses geography=True (not a plain planar PointField)
    so PostGIS computes distances using great-circle math over the
    Earth's actual curvature, which is what ST_Distance/ST_DWithin
    need to return correct real-world kilometre distances rather
    than flat-plane approximations that grow increasingly wrong
    over longer distances.
    """

    pincode = models.CharField(
        _("pincode"),
        # Real pincodes are <= 10 chars, but this column also stores the
        # synthetic city-centroid key f"CITY:{city.id}" (see
        # PincodeGeocodingService.get_or_geocode_city), which is ~41 chars.
        max_length=64,
        unique=True,
        db_index=True,
        validators=[validate_no_control_characters],
    )
    location = gis_models.PointField(
        _("location"),
        geography=True,
        srid=4326,
        help_text=_("WGS84 latitude/longitude point for this pincode."),
    )
    city = models.CharField(
        _("city"),
        max_length=100,
        null=True,
        blank=True,
        validators=[validate_place_name],
    )
    state = models.CharField(
        _("state"),
        max_length=100,
        null=True,
        blank=True,
        validators=[validate_place_name],
    )
    country = models.CharField(
        _("country"),
        max_length=100,
        null=True,
        blank=True,
        validators=[validate_place_name],
    )

    class Meta:
        verbose_name = _("Pincode Location")
        verbose_name_plural = _("Pincode Locations")
        ordering = ["pincode"]
        constraints = [
            models.CheckConstraint(
                name="pincode_location_pincode_not_blank",
                check=~models.Q(pincode__regex=r"^\s*$"),
            ),
        ]

    def __str__(self):
        return f"{self.pincode} ({self.city or 'unknown'})"


# ==============================================================
# SUBJECT / LANGUAGE ALIASES (alias tier, before fuzzy fallback)
# ==============================================================
class SubjectAlias(BaseModel):
    """
    An alternate name/spelling for a Subject (e.g. "Math" ->
    Mathematics). Checked after exact Subject FK match and before
    fuzzy matching, per SubjectMatchingService's three-tier
    precedence.
    """

    subject = models.ForeignKey(
        "subjects.Subject",
        related_name="aliases",
        on_delete=models.CASCADE,
    )
    alias_text = models.CharField(
        _("alias text"),
        max_length=150,
        db_index=True,
        validators=[validate_no_control_characters],
    )

    class Meta:
        verbose_name = _("Subject Alias")
        verbose_name_plural = _("Subject Aliases")
        ordering = ["alias_text"]
        constraints = [
            models.UniqueConstraint(
                fields=["subject", "alias_text"], name="unique_subject_alias"
            ),
            models.CheckConstraint(
                name="subject_alias_text_not_blank",
                check=~models.Q(alias_text__regex=r"^\s*$"),
            ),
        ]
        indexes = [
            # GIN trigram index - lets pg_trgm's similarity()/%
            # operator use an index scan for the fuzzy fallback tier,
            # instead of a sequential scan across every alias row.
            GinIndex(
                fields=["alias_text"],
                name="idx_subject_alias_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.alias_text} -> {self.subject.name}"


class LanguageAlias(BaseModel):
    """Mirrors SubjectAlias exactly, for Language."""

    language = models.ForeignKey(
        "languages.Language",
        related_name="aliases",
        on_delete=models.CASCADE,
    )
    alias_text = models.CharField(
        _("alias text"),
        max_length=100,
        db_index=True,
        validators=[validate_no_control_characters],
    )

    class Meta:
        verbose_name = _("Language Alias")
        verbose_name_plural = _("Language Aliases")
        ordering = ["alias_text"]
        constraints = [
            models.UniqueConstraint(
                fields=["language", "alias_text"], name="unique_language_alias"
            ),
            models.CheckConstraint(
                name="language_alias_text_not_blank",
                check=~models.Q(alias_text__regex=r"^\s*$"),
            ),
        ]
        indexes = [
            GinIndex(
                fields=["alias_text"],
                name="idx_language_alias_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.alias_text} -> {self.language.name}"


# ==============================================================
# LEAD ASSIGNMENT (formal state machine)
# ==============================================================
class AssignmentStatus(models.TextChoices):
    ASSIGNED = "assigned", _("Assigned")
    VIEWED = "viewed", _("Viewed")
    ACCEPTED = "accepted", _("Accepted")
    REJECTED = "rejected", _("Rejected")
    EXPIRED = "expired", _("Expired")
    CANCELLED = "cancelled", _("Cancelled")


class AssignmentResponse(models.TextChoices):
    ACCEPT = "accept", _("Accept")
    REJECT = "reject", _("Reject")


# Valid state transitions - enforced in
# apps.matching.services.lead_distribution_service, not here, but
# declared alongside the states they govern so both stay easy to
# find together.
VALID_ASSIGNMENT_TRANSITIONS = {
    AssignmentStatus.ASSIGNED: {
        AssignmentStatus.VIEWED,
        AssignmentStatus.ACCEPTED,
        AssignmentStatus.REJECTED,
        AssignmentStatus.EXPIRED,
        AssignmentStatus.CANCELLED,
    },
    AssignmentStatus.VIEWED: {
        AssignmentStatus.ACCEPTED,
        AssignmentStatus.REJECTED,
        AssignmentStatus.EXPIRED,
        AssignmentStatus.CANCELLED,
    },
    AssignmentStatus.ACCEPTED: set(),  # terminal
    AssignmentStatus.REJECTED: set(),  # terminal
    AssignmentStatus.EXPIRED: set(),  # terminal
    AssignmentStatus.CANCELLED: set(),  # terminal
}


class LeadAssignment(BaseModel):
    """
    A single teacher's offer for a specific Lead, at a specific
    distribution stage (subscription tier). One (lead, teacher)
    pair has exactly one LeadAssignment row - never re-created if
    the same teacher were somehow re-offered the same lead.

    Every field the spec lists is present: subscription_tier,
    assignment_stage, assigned_at, expires_at, status, viewed_at,
    responded_at, response, plus the four score components snapshot
    at assignment time (so historical assignments remain accurate
    even if the underlying MatchScoreService logic changes later).
    """

    lead = models.ForeignKey(
        "lead_engine.Lead",
        related_name="assignments",
        on_delete=models.CASCADE,
    )
    teacher = models.ForeignKey(
        "teachers.Teacher",
        related_name="lead_assignments",
        on_delete=models.CASCADE,
    )
    subscription_tier = models.CharField(
        _("subscription tier"),
        max_length=50,
        help_text=_(
            "Snapshot of the teacher's plan name at assignment time, e.g. 'Elite', 'Free'."
        ),
    )
    assignment_stage = models.PositiveSmallIntegerField(
        _("assignment stage"),
        help_text=_(
            "1 = first (highest-tier) group offered, 2 = next group after expiry/rejection, etc."
        ),
    )
    assigned_at = models.DateTimeField(_("assigned at"))
    expires_at = models.DateTimeField(_("expires at"))
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ASSIGNED,
        db_index=True,
    )
    viewed_at = models.DateTimeField(_("viewed at"), null=True, blank=True)
    responded_at = models.DateTimeField(_("responded at"), null=True, blank=True)
    response = models.CharField(
        _("response"),
        max_length=10,
        choices=AssignmentResponse.choices,
        null=True,
        blank=True,
    )

    ranking_score = models.FloatField(_("ranking score"), null=True, blank=True)
    time_match_score = models.PositiveSmallIntegerField(
        _("time match score"),
        validators=[MaxValueValidator(100)],
        null=True,
        blank=True,
    )
    location_score = models.PositiveSmallIntegerField(
        _("location score"), validators=[MaxValueValidator(100)], null=True, blank=True
    )
    subject_match_score = models.PositiveSmallIntegerField(
        _("subject match score"),
        validators=[MaxValueValidator(100)],
        null=True,
        blank=True,
    )
    language_match_score = models.PositiveSmallIntegerField(
        _("language match score"),
        validators=[MaxValueValidator(100)],
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Lead Assignment")
        verbose_name_plural = _("Lead Assignments")
        ordering = ["-assigned_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["lead", "teacher"], name="unique_assignment_per_lead_teacher"
            ),
        ]
        indexes = [
            # Hot path for the Celery expiry task: "find all ASSIGNED
            # rows whose expires_at has passed."
            models.Index(
                fields=["status", "expires_at"], name="idx_assignment_expiry_scan"
            ),
            # Hot path for "what's the current stage of this lead's
            # distribution" and "does this teacher have an open offer."
            models.Index(
                fields=["lead", "assignment_stage"], name="idx_assignment_lead_stage"
            ),
            models.Index(
                fields=["teacher", "status"], name="idx_assignment_teacher_status"
            ),
        ]

    def __str__(self):
        return f"{self.lead} -> {self.teacher.user.get_full_name()} (stage {self.assignment_stage}, {self.status})"

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in VALID_ASSIGNMENT_TRANSITIONS.get(self.status, set())


# ==============================================================
# MATCHING CONFIG (DB-backed override of settings.py defaults)
# ==============================================================
class MatchingConfig(BaseModel):
    """
    Single active row (enforced by is_active + service-layer logic,
    not a hard singleton constraint, so a new config can be created
    and activated as a versioned change rather than mutating history
    in place). Admin-editable thresholds/radii - see
    apps.matching.services for how these override settings.py
    defaults when present.
    """

    subject_match_threshold = models.PositiveSmallIntegerField(
        _("subject match threshold"), default=70, validators=[MaxValueValidator(100)]
    )
    language_match_threshold = models.PositiveSmallIntegerField(
        _("language match threshold"), default=70, validators=[MaxValueValidator(100)]
    )
    time_match_threshold_minutes = models.PositiveSmallIntegerField(
        _("time match threshold (minutes)"),
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_MATCH_MINUTES)],
        help_text=_("Minimum overlap, in minutes, required for time-eligibility."),
    )
    initial_location_radius_km = models.PositiveSmallIntegerField(
        _("initial radius (km)"),
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_RADIUS_KM)],
    )
    location_radius_increment_km = models.PositiveSmallIntegerField(
        _("radius increment (km)"),
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_RADIUS_KM)],
    )
    max_location_radius_km = models.PositiveSmallIntegerField(
        _("max radius (km)"),
        default=20,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_RADIUS_KM)],
    )
    lead_response_window_hours = models.PositiveSmallIntegerField(
        _("lead response window (hours)"),
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_RESPONSE_WINDOW_HOURS)],
    )
    subscription_priority_order = models.JSONField(
        _("subscription priority order"),
        default=list,
        help_text=_(
            "Ordered list of plan names, highest priority first, e.g. ['Elite', 'Professional', 'Free']."
        ),
    )
    is_active = models.BooleanField(_("is active"), default=True, db_index=True)

    class Meta:
        verbose_name = _("Matching Configuration")
        verbose_name_plural = _("Matching Configurations")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                name="matching_config_sane_ranges",
                check=(
                    models.Q(subject_match_threshold__lte=100)
                    & models.Q(language_match_threshold__lte=100)
                    & models.Q(time_match_threshold_minutes__gte=1)
                    & models.Q(time_match_threshold_minutes__lte=MAX_MATCH_MINUTES)
                    & models.Q(initial_location_radius_km__gte=1)
                    & models.Q(initial_location_radius_km__lte=MAX_RADIUS_KM)
                    & models.Q(location_radius_increment_km__gte=1)
                    & models.Q(location_radius_increment_km__lte=MAX_RADIUS_KM)
                    & models.Q(max_location_radius_km__gte=1)
                    & models.Q(max_location_radius_km__lte=MAX_RADIUS_KM)
                    & models.Q(lead_response_window_hours__gte=1)
                    & models.Q(
                        lead_response_window_hours__lte=MAX_RESPONSE_WINDOW_HOURS
                    )
                    & models.Q(
                        initial_location_radius_km__lte=models.F(
                            "max_location_radius_km"
                        )
                    )
                ),
            ),
        ]

    def __str__(self):
        return f"MatchingConfig ({'active' if self.is_active else 'inactive'}, {self.created_at:%Y-%m-%d})"

    @classmethod
    def get_active(cls):
        """
        Returns the current active config row, or None if none
        exists yet - callers fall back to settings.py defaults in
        that case (see apps.matching.services.config_service, next
        file), so a fresh install with no admin-configured row
        still works correctly out of the box.
        """
        return cls.objects.filter(is_active=True).order_by("-created_at").first()

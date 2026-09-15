"""
TeacherProfile and TeacherAvailability models for the Teacher
Marketplace Platform.

DESIGN DECISION - relationship to Phase 1's Teacher model:
TeacherProfile has a OneToOneField to apps.teachers.Teacher (NOT
directly to User). Phase 1's Teacher model already holds basic
profile data: profile_photo, bio, experience_years,
qualification_level, qualification_detail, subjects_taught (free
text), city/state/country (free text). Rather than duplicating
those fields here, TeacherProfile extends Teacher with the NEW
marketplace-core fields this phase introduces: headline, teaching
mode, hourly rate, rating, verification status, and - critically -
PROPER relational Many-to-Many fields to Subject/Language/City
(replacing the free-text subjects_taught/city fields for search
and matching purposes).

Phase 1's Teacher.subjects_taught/city/state/country fields are
left untouched (not removed) for backward compatibility, but
TeacherProfile.subjects/cities are what search_engine, lead_engine,
and the search app will actually query against going forward,
since only these are proper relational, filterable fields.

Availability is modeled as a separate model (TeacherAvailability)
with one row per (day_type, time_slot) combination a teacher
selects, rather than a fixed set of boolean fields on TeacherProfile
- this scales cleanly if more slot granularity is added later
without a schema migration on TeacherProfile itself.
"""

from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.languages.models import Language
from apps.location.models import City
from apps.subjects.models import Subject
from apps.teachers.models import Teacher
from apps.utils.validators import validate_no_control_characters

# An hourly rate above this is a data-entry error, not a real price.
MAX_HOURLY_RATE = Decimal("1000000.00")
# Same reasoning, scaled for a monthly figure rather than per-hour.
MAX_MONTHLY_RATE = Decimal("10000000.00")


class TeachingMode(models.TextChoices):
    ONLINE = "online", _("Online")
    OFFLINE = "offline", _("Offline")
    BOTH = "both", _("Both")


class VerificationStatus(models.TextChoices):
    """
    Tracks whether an admin has reviewed and verified this teacher's
    credentials. PENDING is the default for every newly created
    profile - actual verification is an admin action (via Django
    Admin or a future dedicated endpoint), not something a teacher
    can set on themselves.
    """

    PENDING = "pending", _("Pending")
    VERIFIED = "verified", _("Verified")
    REJECTED = "rejected", _("Rejected")


class ModerationStatus(models.TextChoices):
    """
    Content-moderation state of a marketplace profile (Phase 8b). CLEAR is
    the default; HELD means an automated content scan (or an admin) flagged
    the profile for off-platform contact / payment info - it stays visible
    to the teacher but is hidden from search + lead distribution while
    ``TRUST_ENABLE_CONTACT_LEAKAGE_SCAN`` is on, until the content is fixed
    or an admin clears it.
    """

    CLEAR = "clear", _("Clear")
    HELD = "held", _("Held for review")


class DayType(models.TextChoices):
    WEEKDAYS = "weekdays", _("Weekdays")
    WEEKENDS = "weekends", _("Weekends")


class TimeSlot(models.TextChoices):
    MORNING = "morning", _("Morning")
    AFTERNOON = "afternoon", _("Afternoon")
    EVENING = "evening", _("Evening")


class TeacherProfile(BaseModel):
    """
    Professional/marketplace profile for a Teacher. One-to-one with
    Phase 1's Teacher model (which itself is one-to-one with User).

    Inherits from BaseModel: UUID PK, created_at/updated_at,
    soft-delete, and audit fields are already provided.
    """

    teacher = models.OneToOneField(
        Teacher,
        related_name="marketplace_profile",
        on_delete=models.CASCADE,
        help_text=_("The Phase 1 Teacher record this professional profile extends."),
    )
    headline = models.CharField(
        _("headline"),
        max_length=200,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
        help_text=_(
            "Short tagline, e.g. 'Experienced Mathematics Tutor for Grades 6-12'."
        ),
    )
    teaching_mode = models.CharField(
        _("teaching mode"),
        max_length=10,
        choices=TeachingMode.choices,
        default=TeachingMode.BOTH,
        db_index=True,
    )
    hourly_rate = models.DecimalField(
        _("hourly rate"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_HOURLY_RATE),
        ],
        help_text=_(
            "Hourly rate in the platform's base currency. Optional - a "
            "teacher may share this, a monthly_rate, both, or neither."
        ),
    )
    monthly_rate = models.DecimalField(
        _("monthly rate"),
        max_digits=11,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_MONTHLY_RATE),
        ],
        help_text=_(
            "Monthly rate in the platform's base currency - the low end of "
            "the range when monthly_rate_max is also set (fees genuinely "
            "vary by class size/level for most teachers), or a single fixed "
            "price when monthly_rate_max is left blank. Optional - a "
            "teacher may share this, an hourly_rate, both, or neither."
        ),
    )
    monthly_rate_max = models.DecimalField(
        _("monthly rate (up to)"),
        max_digits=11,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_MONTHLY_RATE),
        ],
        help_text=_(
            "The high end of the monthly rate range. Meaningless without "
            "monthly_rate also set - see that field's help text."
        ),
    )
    rating = models.DecimalField(
        _("rating"),
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("5.00")),
        ],
        help_text=_(
            "Average rating out of 5.00. Phase 2 note: this field exists "
            "for search/display/sorting purposes, but no review/rating "
            "submission system is built in this phase - it is manually "
            "adjustable (e.g. via Admin) until a later phase introduces "
            "actual student reviews."
        ),
    )
    verification_status = models.CharField(
        _("verification status"),
        max_length=10,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        db_index=True,
    )
    moderation_status = models.CharField(
        _("moderation status"),
        max_length=8,
        choices=ModerationStatus.choices,
        default=ModerationStatus.CLEAR,
        db_index=True,
        help_text=_(
            "HELD = flagged for off-platform contact/payment content; hidden "
            "from search + lead distribution (Phase 8b), still visible to the teacher."
        ),
    )

    # ------------------------------------------------------------
    # Relational taxonomy (search/matching depends on these, unlike
    # Phase 1 Teacher's free-text equivalents)
    # ------------------------------------------------------------
    subjects = models.ManyToManyField(
        Subject,
        related_name="teacher_profiles",
        blank=True,
        help_text=_("Subjects this teacher can teach."),
    )
    languages = models.ManyToManyField(
        Language,
        related_name="teacher_profiles",
        blank=True,
        help_text=_("Languages this teacher can teach in."),
    )
    cities = models.ManyToManyField(
        City,
        related_name="teacher_profiles",
        blank=True,
        help_text=_(
            "Cities this teacher offers offline/in-person teaching in. "
            "Not required for teachers who are Online-only."
        ),
    )

    class Meta:
        verbose_name = _("Teacher Profile")
        verbose_name_plural = _("Teacher Profiles")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["teaching_mode", "verification_status"]),
            models.Index(fields=["hourly_rate"]),
            models.Index(fields=["rating"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="teacher_profile_headline_not_blank",
                check=models.Q(headline__isnull=True)
                | ~models.Q(headline__regex=r"^\s*$"),
            ),
            models.CheckConstraint(
                name="teacher_profile_hourly_rate_range",
                check=models.Q(hourly_rate__isnull=True)
                | (
                    models.Q(hourly_rate__gte=Decimal("0.00"))
                    & models.Q(hourly_rate__lte=MAX_HOURLY_RATE)
                ),
            ),
            models.CheckConstraint(
                name="teacher_profile_monthly_rate_range",
                check=models.Q(monthly_rate__isnull=True)
                | (
                    models.Q(monthly_rate__gte=Decimal("0.00"))
                    & models.Q(monthly_rate__lte=MAX_MONTHLY_RATE)
                ),
            ),
            models.CheckConstraint(
                name="teacher_profile_monthly_rate_max_range",
                check=models.Q(monthly_rate_max__isnull=True)
                | (
                    models.Q(monthly_rate_max__gte=Decimal("0.00"))
                    & models.Q(monthly_rate_max__lte=MAX_MONTHLY_RATE)
                ),
            ),
            models.CheckConstraint(
                name="teacher_profile_monthly_rate_max_gte_min",
                check=models.Q(monthly_rate_max__isnull=True)
                | models.Q(monthly_rate__isnull=True)
                | models.Q(monthly_rate_max__gte=models.F("monthly_rate")),
            ),
        ]

    def __str__(self):
        return f"Marketplace Profile: {self.teacher.user.get_full_name()}"

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VerificationStatus.VERIFIED

    @property
    def years_of_experience(self):
        """
        Delegates to Phase 1's Teacher.experience_years rather than
        duplicating an experience field here - "Years of Experience"
        from the spec is already captured on Teacher, so this is a
        read-through property, not a new stored column.
        """
        return self.teacher.experience_years


class TeacherAvailability(BaseModel):
    """
    A single availability slot for a teacher: one (day_type,
    time_slot) combination. A teacher selecting "Weekdays Morning"
    and "Weekends Evening" would have two rows here, not one row
    with multiple boolean flags - this scales more cleanly if slot
    granularity changes later (e.g. adding "Late Night") without a
    schema migration.
    """

    teacher_profile = models.ForeignKey(
        TeacherProfile,
        related_name="availability_slots",
        on_delete=models.CASCADE,
    )
    day_type = models.CharField(
        _("day type"),
        max_length=10,
        choices=DayType.choices,
    )
    time_slot = models.CharField(
        _("time slot"),
        max_length=10,
        choices=TimeSlot.choices,
    )

    class Meta:
        verbose_name = _("Teacher Availability")
        verbose_name_plural = _("Teacher Availability Slots")
        ordering = ["day_type", "time_slot"]
        constraints = [
            models.UniqueConstraint(
                fields=["teacher_profile", "day_type", "time_slot"],
                name="unique_availability_slot_per_teacher",
            ),
        ]

    def __str__(self):
        return f"{self.teacher_profile} - {self.get_day_type_display()} {self.get_time_slot_display()}"


# ==============================================================
# WEEKLY AVAILABILITY (new, structured - Time Compatibility feature)
# ==============================================================
class DayOfWeek(models.IntegerChoices):
    """
    Uses ISO 8601 weekday numbering (Monday=1 ... Sunday=7), stored
    as an integer rather than a string - this makes "is this day
    before/after that day" and grouping/ordering queries trivial
    and consistent with Python's own datetime.isoweekday(), which
    the matching engine's timezone-conversion logic (in
    TimeCompatibilityService) needs to align against real calendar
    dates for DST-correct comparisons.
    """

    MONDAY = 1, _("Monday")
    TUESDAY = 2, _("Tuesday")
    WEDNESDAY = 3, _("Wednesday")
    THURSDAY = 4, _("Thursday")
    FRIDAY = 5, _("Friday")
    SATURDAY = 6, _("Saturday")
    SUNDAY = 7, _("Sunday")


# Reasonable application limit on availability windows per teacher,
# per the spec's "unlimited... subject to reasonable application
# limits" - enforced in the service layer (availability_service.py),
# not here, but the constant lives alongside the model it constrains
# so both stay easy to find together.
MAX_AVAILABILITY_WINDOWS_PER_TEACHER = 50


class TeacherWeeklyAvailability(BaseModel):
    """
    A single recurring weekly availability window for a teacher,
    e.g. "Monday, 18:00-20:00, Asia/Kolkata". A teacher has one row
    per window - multiple windows on the same day are multiple
    rows (per the spec's explicit "multiple windows on the same
    day" requirement), not a single row with a list field.

    This is a NEW, structured model - it does NOT replace or alter
    apps.teacher_profile.models.TeacherAvailability (the Phase 2
    categorical day_type/time_slot model). That model is left
    fully intact for backward compatibility; the new matching
    engine (Phase 4) reads exclusively from THIS model. See the
    module-level migration note in this app's admin.py for the
    operational implication (teachers need to re-enter availability
    in this new structured format - existing categorical data
    cannot be losslessly converted to precise times).

    start_time/end_time are stored as plain Django TimeField values
    IN THE TEACHER'S OWN LOCAL TIMEZONE (the `timezone` field on
    this same row) - NOT normalized to UTC at rest. This is a
    deliberate choice: a recurring weekly "Monday 18:00-20:00"
    slot's correct UTC equivalent shifts across DST transitions
    (e.g. India has no DST, but a teacher in America/New_York does)
    - storing a fixed UTC time would silently become wrong twice a
    year for such teachers. Instead, conversion to UTC/any other
    timezone happens at COMPARISON time (in
    TimeCompatibilityService), using Python's zoneinfo against a
    real calendar date, which correctly accounts for DST. See that
    service's module docstring for the full reasoning.
    """

    teacher_profile = models.ForeignKey(
        TeacherProfile,
        related_name="weekly_availability",
        on_delete=models.CASCADE,
    )
    day_of_week = models.PositiveSmallIntegerField(
        _("day of week"),
        choices=DayOfWeek.choices,
        db_index=True,
    )
    start_time = models.TimeField(
        _("start time"),
        help_text=_("Local start time in this row's timezone, e.g. 18:00."),
    )
    end_time = models.TimeField(
        _("end time"),
        help_text=_("Local end time in this row's timezone, e.g. 20:00."),
    )
    timezone = models.CharField(
        _("timezone"),
        max_length=64,
        help_text=_("IANA timezone name, e.g. 'Asia/Kolkata', 'America/New_York'."),
    )
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        db_index=True,
        help_text=_(
            "Inactive windows are excluded from matching without deleting the row."
        ),
    )

    class Meta:
        verbose_name = _("Teacher Weekly Availability")
        verbose_name_plural = _("Teacher Weekly Availability Windows")
        ordering = ["day_of_week", "start_time"]
        constraints = [
            # "No duplicate availability windows" from the spec -
            # interpreted as: the exact same (day, start, end,
            # timezone) combination cannot be added twice for the
            # same teacher. Overlapping-but-not-identical windows
            # (e.g. 18:00-19:00 and 18:30-19:30) are NOT blocked at
            # the database level - see validate_no_overlap() below
            # for why that's handled in application logic instead.
            models.UniqueConstraint(
                fields=[
                    "teacher_profile",
                    "day_of_week",
                    "start_time",
                    "end_time",
                    "timezone",
                ],
                name="unique_teacher_availability_window",
            ),
            models.CheckConstraint(
                name="teacher_avail_start_before_end",
                check=models.Q(start_time__lt=models.F("end_time")),
            ),
            models.CheckConstraint(
                name="teacher_avail_timezone_not_blank",
                check=~models.Q(timezone__regex=r"^\s*$"),
            ),
        ]
        indexes = [
            # Composite index matching the matching engine's exact
            # lookup pattern: "give me this teacher's active windows
            # for a specific day" - the single most frequent query
            # this table will serve, run once per candidate teacher
            # per matching pass.
            models.Index(
                fields=["teacher_profile", "day_of_week", "is_active"],
                name="idx_teacher_avail_lookup",
            ),
            # Supports demand/supply analytics ("most available
            # teacher time slots") which aggregates ACROSS teachers
            # by day, independent of any single teacher_profile.
            models.Index(
                fields=["day_of_week", "is_active"], name="idx_avail_day_analytics"
            ),
        ]

    def __str__(self):
        return (
            f"{self.teacher_profile} - {self.get_day_of_week_display()} "
            f"{self.start_time}-{self.end_time} ({self.timezone})"
        )

    def clean(self):
        """
        Model-level validation (start_time < end_time, valid
        timezone). Called by full_clean() - the service layer
        (availability_service.py) explicitly calls full_clean()
        before save(), since plain .save() does NOT run this
        automatically (a recurring gotcha already noted elsewhere
        in this codebase's serializer-level duplicate validators).
        """
        errors = {}

        if self.start_time is not None and self.end_time is not None:
            if self.start_time >= self.end_time:
                errors["end_time"] = _("End time must be after start time.")

        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError:
                errors["timezone"] = _(
                    "'%(tz)s' is not a valid IANA timezone name."
                ) % {"tz": self.timezone}

        if errors:
            raise DjangoValidationError(errors)


class ExceptionType(models.TextChoices):
    """
    Matches the spec's exact examples under Availability Exceptions:
    Vacation, Holiday, Temporary Unavailability, One-time Schedule
    Change.
    """

    VACATION = "vacation", _("Vacation")
    HOLIDAY = "holiday", _("Holiday")
    TEMPORARY_UNAVAILABLE = "temporary_unavailable", _("Temporary Unavailability")
    SCHEDULE_CHANGE = "schedule_change", _("One-time Schedule Change")


class TeacherScheduleException(BaseModel):
    """
    A one-off exception to a teacher's recurring weekly
    availability - either a full-day unavailability (start_time/
    end_time both null) or a specific time range on that date.

    Per the spec's explicit design principle ("Create an exception
    model rather than modifying the recurring weekly schedule"),
    this NEVER mutates TeacherWeeklyAvailability rows - the
    matching engine checks both tables together (recurring
    availability first, then excludes/adjusts for any overlapping
    exception on the specific date being matched against).
    """

    teacher_profile = models.ForeignKey(
        TeacherProfile,
        related_name="schedule_exceptions",
        on_delete=models.CASCADE,
    )
    exception_type = models.CharField(
        _("exception type"),
        max_length=25,
        choices=ExceptionType.choices,
        default=ExceptionType.TEMPORARY_UNAVAILABLE,
    )
    date = models.DateField(
        _("date"),
        db_index=True,
        help_text=_("The specific calendar date this exception applies to."),
    )
    start_time = models.TimeField(
        _("start time"),
        null=True,
        blank=True,
        help_text=_(
            "Leave blank (with end_time also blank) to mark the ENTIRE day unavailable."
        ),
    )
    end_time = models.TimeField(
        _("end time"),
        null=True,
        blank=True,
    )
    timezone = models.CharField(
        _("timezone"),
        max_length=64,
        help_text=_("IANA timezone name for start_time/end_time, if set."),
    )
    reason = models.CharField(
        _("reason"),
        max_length=255,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
    )

    class Meta:
        verbose_name = _("Teacher Schedule Exception")
        verbose_name_plural = _("Teacher Schedule Exceptions")
        ordering = ["date"]
        indexes = [
            models.Index(
                fields=["teacher_profile", "date"], name="idx_teacher_exception_date"
            ),
        ]
        constraints = [
            models.CheckConstraint(
                name="teacher_exception_reason_not_blank",
                check=models.Q(reason__isnull=True) | ~models.Q(reason__regex=r"^\s*$"),
            ),
            models.CheckConstraint(
                name="teacher_exception_time_pair",
                # both set or both null (no half-specified time range)
                check=(
                    (
                        models.Q(start_time__isnull=True)
                        & models.Q(end_time__isnull=True)
                    )
                    | (
                        models.Q(start_time__isnull=False)
                        & models.Q(end_time__isnull=False)
                    )
                ),
            ),
            models.CheckConstraint(
                name="teacher_exception_start_before_end",
                check=models.Q(start_time__isnull=True)
                | models.Q(start_time__lt=models.F("end_time")),
            ),
        ]

    def __str__(self):
        scope = (
            "Full day"
            if self.start_time is None
            else f"{self.start_time}-{self.end_time}"
        )
        return f"{self.teacher_profile} unavailable {self.date} ({scope})"

    @property
    def is_full_day(self) -> bool:
        return self.start_time is None and self.end_time is None

    def clean(self):
        errors = {}
        if bool(self.start_time) != bool(self.end_time):
            errors["end_time"] = _(
                "start_time and end_time must both be set, or both left blank for a full-day exception."
            )
        elif self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = _("End time must be after start time.")

        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError:
                errors["timezone"] = _(
                    "'%(tz)s' is not a valid IANA timezone name."
                ) % {"tz": self.timezone}

        if errors:
            raise DjangoValidationError(errors)

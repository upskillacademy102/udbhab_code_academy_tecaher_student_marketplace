"""
StudentRequirement model for the Teacher Marketplace Platform.

This is the core "demand" side of the marketplace - a student
describes what they're looking for (subject, budget, mode,
location, timing), and lead_engine (built later in this phase)
matches it against TeacherProfile records to generate Lead rows.

Phase 2 scope: this model, its validations (budget, duplicate
detection), and CRUD/list APIs. The actual matching algorithm that
CONSUMES this data lives in apps.lead_engine, not here - this app
only owns the requirement data itself.
"""

from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.languages.models import Language
from apps.location.models import City
from apps.subjects.models import Subject
from apps.teacher_profile.models import DayOfWeek, TeachingMode
from apps.utils.validators import validate_no_control_characters

# A learning requirement's budget is a per-month amount (matches
# TeacherProfile.monthly_rate's ceiling in apps/teacher_profile/models.py,
# which is what it's scored against - see
# MatchingService._budget_score) - anything above this is a data-entry
# error, not a real budget.
MAX_REQUIREMENT_BUDGET = Decimal("10000000.00")
MIN_CLASS_DURATION_MINUTES = 15
MAX_CLASS_DURATION_MINUTES = 480

# A student ranks up to this many languages, most preferred first - see
# StudentRequirementLanguage. Kept small: this is a preference order, not a
# taxonomy browse, and MatchingService._language_score's rank-decay table
# only has this many distinct steps.
MAX_PREFERRED_LANGUAGES = 5


class LeadDistributionStatus(models.TextChoices):
    """
    Progress of the ASYNC lead generation + distribution pipeline for
    this requirement (apps.lead_engine.tasks.process_requirement_leads).

    This is deliberately separate from RequirementStatus, which is the
    student-facing lifecycle (open / matched / closed / expired). This
    field is the operational state of the background job:

        PENDING     - created before async distribution existed, or the
                      task has not been queued yet
        QUEUED      - requirement committed, Celery task enqueued
        PROCESSING  - a worker has picked the task up
        COMPLETED   - candidate discovery + lead/assignment creation done
        FAILED      - permanent failure after retries were exhausted
        HELD        - not distributed: the student is shadow-limited
                      (apps.trust requirement-velocity / risk). An admin
                      can release it; the task is never auto-enqueued.
    """

    PENDING = "pending", _("Pending")
    QUEUED = "queued", _("Queued")
    PROCESSING = "processing", _("Processing")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")
    HELD = "held", _("Held for review")


class RequirementStatus(models.TextChoices):
    """
    Lifecycle status of a student's requirement.
        OPEN       - actively looking, lead_engine should match it
        MATCHED    - at least one Lead has been generated for it
                     (set by lead_engine, not directly by the student)
        CLOSED     - student found a teacher / no longer needs this
        EXPIRED    - system-level auto-expiry for stale requirements
                     (Phase 2 stores this state; actual auto-expiry
                     scheduling/cron is a later-phase operational
                     concern, not built here)
    """

    OPEN = "open", _("Open")
    MATCHED = "matched", _("Matched")
    CLOSED = "closed", _("Closed")
    EXPIRED = "expired", _("Expired")


class StudentRequirement(BaseModel):
    """
    A student's learning requirement post. Inherits from BaseModel:
    UUID PK, created_at/updated_at (satisfies the spec's "Created
    Date" field), soft-delete, and audit fields are already
    provided.
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="requirements",
        on_delete=models.CASCADE,
        limit_choices_to={"role": "student"},
        help_text=_("The Student who submitted this requirement."),
    )
    subject = models.ForeignKey(
        Subject,
        related_name="requirements",
        on_delete=models.PROTECT,
        help_text=_("The subject the student needs help with."),
    )
    student_class = models.CharField(
        _("class"),
        max_length=50,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
        help_text=_("e.g. 'Grade 10', '1st Year B.Com', 'Adult Learner'."),
    )
    no_language_preference = models.BooleanField(
        _("any language is fine"),
        default=False,
        help_text=_(
            "Explicitly set when the student picked 'Any language' instead "
            "of ranking specific ones. Mutually exclusive with having any "
            "StudentRequirementLanguage rows - enforced in the write "
            "serializer, same 'flexible vs specific' shape as "
            "StudentSchedulePreference's flexibility field. Language is a "
            "mandatory choice: every requirement has either this set True "
            "or at least one ranked language."
        ),
    )
    budget_min = models.DecimalField(
        _("budget (min, per month)"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_REQUIREMENT_BUDGET),
        ],
        help_text=_(
            "The low end of what the student can pay per month. Compared "
            "against a teacher's monthly_rate in MatchingService - see "
            "apps.teacher_profile.models.TeacherProfile.monthly_rate."
        ),
    )
    budget_max = models.DecimalField(
        _("budget (max, per month)"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(MAX_REQUIREMENT_BUDGET),
        ],
        help_text=_(
            "The high end of what the student can pay per month. Compared "
            "against a teacher's monthly_rate in MatchingService - see "
            "apps.teacher_profile.models.TeacherProfile.monthly_rate."
        ),
    )
    teaching_mode = models.CharField(
        _("teaching mode"),
        max_length=10,
        choices=TeachingMode.choices,
        default=TeachingMode.BOTH,
        db_index=True,
    )
    city = models.ForeignKey(
        City,
        related_name="requirements",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_(
            "Required for Offline/Both teaching mode; optional for "
            "purely Online requirements."
        ),
    )
    pincode_location = models.ForeignKey(
        "matching.PincodeLocation",
        related_name="requirements",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_(
            "Structured pincode for offline distance matching, distinct from city (free-text/FK reference)."
        ),
    )
    preferred_timing = models.CharField(
        _("preferred timing"),
        max_length=255,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
        help_text=_("Free-text description, e.g. 'Weekday evenings after 6pm'."),
    )
    offer_teacher = models.ForeignKey(
        "teachers.Teacher",
        related_name="direct_offers",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_(
            "Set only for a direct 'Learn with this teacher' offer - "
            "targets exactly this one teacher instead of the general "
            "matching pool. Non-null is what makes this a direct offer; "
            "never settable through the normal requirement create/update "
            "serializer, only through DirectOfferCreateView."
        ),
    )

    class ClassDuration(models.IntegerChoices):
        """
        Matches the spec's exact example durations. Stored as
        minutes (an integer), not a choice of pre-formatted
        strings, so the matching engine's duration-fit check
        (TimeCompatibilityService) can do direct arithmetic against
        it without parsing.
        """

        THIRTY_MIN = 30, _("30 minutes")
        FORTY_FIVE_MIN = 45, _("45 minutes")
        SIXTY_MIN = 60, _("60 minutes")
        NINETY_MIN = 90, _("90 minutes")
        ONE_TWENTY_MIN = 120, _("120 minutes")

    class_duration_minutes = models.PositiveSmallIntegerField(
        _("class duration (minutes)"),
        choices=ClassDuration.choices,
        default=ClassDuration.SIXTY_MIN,
        validators=[
            MinValueValidator(MIN_CLASS_DURATION_MINUTES),
            MaxValueValidator(MAX_CLASS_DURATION_MINUTES),
        ],
        help_text=_(
            "Requested class length in minutes. One of the preset values "
            "(30 / 45 / 60 / 90 / 120); the API rejects other values. The "
            "range validators + DB CHECK (15-480) are a floor/ceiling guard "
            "for any non-API write path."
        ),
    )
    description = models.CharField(
        _("description"),
        max_length=2000,
        null=True,
        blank=True,
        help_text=_("Additional details about what the student is looking for."),
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=RequirementStatus.choices,
        default=RequirementStatus.OPEN,
        db_index=True,
    )
    lead_distribution_status = models.CharField(
        _("lead distribution status"),
        max_length=12,
        choices=LeadDistributionStatus.choices,
        default=LeadDistributionStatus.PENDING,
        db_index=True,
        help_text=_(
            "Progress of the async lead generation/distribution job for this requirement."
        ),
    )

    class Meta:
        verbose_name = _("Student Requirement")
        verbose_name_plural = _("Student Requirements")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "subject"]),
            models.Index(fields=["status", "teaching_mode"]),
            models.Index(fields=["student", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="requirement_budget_min_lte_max",
                check=(
                    models.Q(budget_min__isnull=True)
                    | models.Q(budget_max__isnull=True)
                    | models.Q(budget_min__lte=models.F("budget_max"))
                ),
            ),
            models.CheckConstraint(
                name="requirement_class_duration_range",
                check=models.Q(class_duration_minutes__gte=MIN_CLASS_DURATION_MINUTES)
                & models.Q(class_duration_minutes__lte=MAX_CLASS_DURATION_MINUTES),
            ),
            models.CheckConstraint(
                name="requirement_text_fields_not_blank",
                check=(
                    (
                        models.Q(student_class__isnull=True)
                        | ~models.Q(student_class__regex=r"^\s*$")
                    )
                    & (
                        models.Q(preferred_timing__isnull=True)
                        | ~models.Q(preferred_timing__regex=r"^\s*$")
                    )
                    & (
                        models.Q(description__isnull=True)
                        | ~models.Q(description__regex=r"^\s*$")
                    )
                ),
            ),
        ]

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.subject.name} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status == RequirementStatus.OPEN

    @property
    def preferred_language_ids(self) -> list:
        """
        Flat list of Language ids from the ranked preference list, rank
        order preserved. Reads via `.all()` (not `.values_list()`) so a
        caller that already did
        `prefetch_related_objects([requirement], "preferred_languages")`
        (see lead_generation_service.generate_leads_for_requirement) gets
        this from the prefetch cache instead of one query per access - the
        same N+1 trap schedule_preferences hit before that prefetch was
        added.
        """
        return [pl.language_id for pl in self.preferred_languages.all()]


# ==============================================================
# STUDENT PREFERRED LANGUAGES (ranked, replaces the old single FK)
# ==============================================================
class StudentRequirementLanguage(BaseModel):
    """
    One entry in a requirement's ranked language preference list - rank 1
    is the student's most preferred language, rank 2 the next, and so on.

    MatchingService._language_score uses the full ranked list (matching a
    higher-ranked language scores a candidate teacher higher), while the
    Offers hard-eligibility gate (EligibilityService, via
    LanguageMatchingService.match_by_ids) accepts a teacher who speaks ANY
    listed language, not only the top-ranked one - rank affects relative
    ranking among eligible teachers, not eligibility itself.
    """

    student_requirement = models.ForeignKey(
        StudentRequirement,
        related_name="preferred_languages",
        on_delete=models.CASCADE,
    )
    language = models.ForeignKey(
        Language,
        related_name="+",
        on_delete=models.CASCADE,
    )
    rank = models.PositiveSmallIntegerField(
        _("rank"),
        validators=[MinValueValidator(1), MaxValueValidator(MAX_PREFERRED_LANGUAGES)],
        help_text=_("1-based preference order - 1 is most preferred."),
    )

    class Meta:
        verbose_name = _("Student Preferred Language")
        verbose_name_plural = _("Student Preferred Languages")
        ordering = ["rank"]
        constraints = [
            models.UniqueConstraint(
                fields=["student_requirement", "rank"],
                name="requirement_language_rank_unique",
            ),
            models.UniqueConstraint(
                fields=["student_requirement", "language"],
                name="requirement_language_unique",
            ),
        ]

    def __str__(self):
        return f"{self.student_requirement} - #{self.rank} {self.language.name}"


# ==============================================================
# STUDENT SCHEDULE PREFERENCES (new, structured)
# ==============================================================
class PreferenceFlexibility(models.TextChoices):
    FIXED = "fixed", _("Fixed")
    FLEXIBLE = "flexible", _("Flexible")


class PreferencePriority(models.TextChoices):
    HIGH = "high", _("High Priority")
    MEDIUM = "medium", _("Medium Priority")
    LOW = "low", _("Low Priority")


MAX_PREFERENCE_WINDOWS_PER_REQUIREMENT = 20


class StudentSchedulePreference(BaseModel):
    """
    A single preferred weekly time slot for a StudentRequirement,
    e.g. "Monday, 18:30-20:00, Asia/Kolkata, FIXED". Mirrors
    TeacherWeeklyAvailability's design exactly (local-time storage,
    IANA timezone field, DST-safe comparison deferred to matching
    time) - see that model's docstring for the full reasoning,
    which applies identically here.

    A StudentRequirement can have multiple preference rows (one per
    slot), matching the spec's "Students may select multiple
    preferred days" requirement.
    """

    student_requirement = models.ForeignKey(
        StudentRequirement,
        related_name="schedule_preferences",
        on_delete=models.CASCADE,
    )
    day_of_week = models.PositiveSmallIntegerField(
        _("day of week"),
        choices=DayOfWeek.choices,
        db_index=True,
    )
    start_time = models.TimeField(_("start time"))
    end_time = models.TimeField(_("end time"))
    timezone = models.CharField(
        _("timezone"),
        max_length=64,
        help_text=_("IANA timezone name, e.g. 'Asia/Kolkata'."),
    )
    flexibility = models.CharField(
        _("flexibility"),
        max_length=10,
        choices=PreferenceFlexibility.choices,
        default=PreferenceFlexibility.FLEXIBLE,
        help_text=_(
            "FIXED: little/no overlap heavily penalizes a teacher's time "
            "score. FLEXIBLE: partial overlap can still score reasonably."
        ),
    )
    priority = models.CharField(
        _("priority"),
        max_length=10,
        choices=PreferencePriority.choices,
        default=PreferencePriority.MEDIUM,
        help_text=_(
            "Relative importance of this slot when the student has multiple preferences."
        ),
    )

    class Meta:
        verbose_name = _("Student Schedule Preference")
        verbose_name_plural = _("Student Schedule Preferences")
        ordering = ["day_of_week", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "student_requirement",
                    "day_of_week",
                    "start_time",
                    "end_time",
                    "timezone",
                ],
                name="unique_student_preference_window",
            ),
            models.CheckConstraint(
                name="student_pref_start_before_end",
                check=models.Q(start_time__lt=models.F("end_time")),
            ),
            models.CheckConstraint(
                name="student_pref_timezone_not_blank",
                check=~models.Q(timezone__regex=r"^\s*$"),
            ),
        ]
        indexes = [
            # Mirrors idx_teacher_avail_lookup's exact reasoning:
            # the matching engine's hot-path query is "give me this
            # requirement's preferences for a specific day."
            models.Index(
                fields=["student_requirement", "day_of_week"],
                name="idx_student_pref_lookup",
            ),
            # Cross-requirement aggregation for "most requested
            # days/time slots" analytics (spec's Analytics section).
            models.Index(fields=["day_of_week"], name="idx_pref_day_analytics"),
        ]

    def __str__(self):
        return (
            f"{self.student_requirement} - {self.get_day_of_week_display()} "
            f"{self.start_time}-{self.end_time} ({self.flexibility})"
        )

    def clean(self):
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


class StudentScheduleException(BaseModel):
    """
    A one-off exception to a student's preferred schedule (e.g. a
    student holiday) - mirrors TeacherScheduleException's design
    and reasoning exactly (see that model's docstring). Never
    mutates StudentSchedulePreference rows.
    """

    student_requirement = models.ForeignKey(
        StudentRequirement,
        related_name="schedule_exceptions",
        on_delete=models.CASCADE,
    )
    date = models.DateField(_("date"), db_index=True)
    reason = models.CharField(
        _("reason"),
        max_length=255,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
    )

    class Meta:
        verbose_name = _("Student Schedule Exception")
        verbose_name_plural = _("Student Schedule Exceptions")
        ordering = ["date"]
        indexes = [
            models.Index(
                fields=["student_requirement", "date"],
                name="idx_student_exception_date",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                name="student_exception_reason_not_blank",
                check=models.Q(reason__isnull=True) | ~models.Q(reason__regex=r"^\s*$"),
            ),
        ]

    def __str__(self):
        return f"{self.student_requirement} unavailable {self.date}"

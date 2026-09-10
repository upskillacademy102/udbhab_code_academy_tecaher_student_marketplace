"""
Teacher model for the Teacher Marketplace Platform.

Per Phase 1 scope ("Only create Models, Serializer, APIView, URLs")
this model holds only descriptive profile data linked to a User
with role=teacher:
    - Profile Photo
    - Bio
    - Experience
    - Qualification

No token/wallet balance, no premium membership flags, no lead-
unlock tracking - those are explicit later-phase business logic
(wallet, payments, lead matching) per your project rules.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import (
    validate_image_upload,
    validate_no_control_characters,
    validate_place_name,
)


class QualificationLevel(models.TextChoices):
    """
    Highest qualification level held by the teacher. Kept as a
    small fixed set of choices for consistent filtering later,
    with the specific degree/subject captured in the free-text
    `qualification_detail` field alongside it.
    """

    HIGH_SCHOOL = "high_school", _("High School")
    DIPLOMA = "diploma", _("Diploma")
    BACHELORS = "bachelors", _("Bachelor's Degree")
    MASTERS = "masters", _("Master's Degree")
    DOCTORATE = "doctorate", _("Doctorate (PhD)")
    PROFESSIONAL_CERTIFICATION = "professional_certification", _(
        "Professional Certification"
    )
    OTHER = "other", _("Other")


class Teacher(BaseModel):
    """
    Teacher profile, one-to-one with a User (role=teacher).

    Inherits from BaseModel: UUID PK, created_at/updated_at,
    soft-delete, and audit fields (created_by/updated_by) are
    already provided.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="teacher_profile",
        on_delete=models.CASCADE,
        help_text=_("The User account this teacher profile belongs to."),
    )
    profile_photo = models.ImageField(
        _("profile photo"),
        upload_to="teachers/profile_photos/%Y/%m/",
        null=True,
        blank=True,
        validators=[validate_image_upload],
    )
    bio = models.CharField(
        _("bio"),
        max_length=2000,
        null=True,
        blank=True,
        help_text=_(
            "Short description of teaching style, background, and specialties."
        ),
    )
    experience_years = models.PositiveSmallIntegerField(
        _("years of experience"),
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(80)],
        help_text=_("Total years of teaching experience."),
    )
    qualification_level = models.CharField(
        _("qualification level"),
        max_length=30,
        choices=QualificationLevel.choices,
        null=True,
        blank=True,
    )
    qualification_detail = models.CharField(
        _("qualification detail"),
        max_length=255,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
        help_text=_("e.g. 'M.Sc. Mathematics, Delhi University'."),
    )
    subjects_taught = models.CharField(
        _("subjects taught"),
        max_length=500,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
        help_text=_("Comma-separated list of subjects this teacher can teach."),
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
    pincode_location = models.ForeignKey(
        "matching.PincodeLocation",
        related_name="teachers",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_(
            "Structured pincode/location for offline distance matching. "
            "Distinct from the free-text city/state/country fields above - "
            "this is what LocationMatchingService actually queries against."
        ),
    )

    class Meta:
        verbose_name = _("Teacher")
        verbose_name_plural = _("Teachers")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["city", "qualification_level"]),
            models.Index(fields=["experience_years"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="teacher_text_fields_not_blank",
                check=(
                    (models.Q(bio__isnull=True) | ~models.Q(bio__regex=r"^\s*$"))
                    & (
                        models.Q(qualification_detail__isnull=True)
                        | ~models.Q(qualification_detail__regex=r"^\s*$")
                    )
                    & (
                        models.Q(subjects_taught__isnull=True)
                        | ~models.Q(subjects_taught__regex=r"^\s*$")
                    )
                    & (models.Q(city__isnull=True) | ~models.Q(city__regex=r"^\s*$"))
                    & (models.Q(state__isnull=True) | ~models.Q(state__regex=r"^\s*$"))
                    & (
                        models.Q(country__isnull=True)
                        | ~models.Q(country__regex=r"^\s*$")
                    )
                ),
            ),
        ]

    def __str__(self):
        return f"Teacher: {self.user.get_full_name()} ({self.user.email})"

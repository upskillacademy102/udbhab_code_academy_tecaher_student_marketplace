"""
Student model for the Teacher Marketplace Platform.

Per Phase 1 scope ("Only create Models, Serializer, APIView, URLs -
No business logic"), this model holds only descriptive profile
data linked to a User with role=student. No search/matching logic,
no lead generation, no payment-related fields - those belong to
later phases.

Design note: Student is a separate model (not extra fields bolted
onto User) linked via a OneToOneField, keeping User focused purely
on authentication/identity while allowing Student-specific fields
to evolve independently (e.g. adding grade-level-specific fields
later) without touching the auth model at all.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import (
    validate_image_upload,
    validate_no_control_characters,
    validate_place_name,
)


class EducationLevel(models.TextChoices):
    """
    Broad education level the student is currently at, used to help
    narrow down which teachers/subjects are relevant. Kept as a
    small fixed set of choices rather than a free-text field for
    consistent filtering in later phases.
    """

    SCHOOL = "school", _("School")
    HIGH_SCHOOL = "high_school", _("High School")
    UNDERGRADUATE = "undergraduate", _("Undergraduate")
    POSTGRADUATE = "postgraduate", _("Postgraduate")
    COMPETITIVE_EXAM = "competitive_exam", _("Competitive Exam Preparation")
    HOBBY_OTHER = "hobby_other", _("Hobby / Other")


class Student(BaseModel):
    """
    Student profile, one-to-one with a User (role=student).

    Inherits from BaseModel: UUID PK, created_at/updated_at,
    soft-delete, and audit fields (created_by/updated_by) are
    already provided.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="student_profile",
        on_delete=models.CASCADE,
        help_text=_("The User account this student profile belongs to."),
    )
    profile_photo = models.ImageField(
        _("profile photo"),
        upload_to="students/profile_photos/%Y/%m/",
        null=True,
        blank=True,
        validators=[validate_image_upload],
    )
    education_level = models.CharField(
        _("education level"),
        max_length=30,
        choices=EducationLevel.choices,
        null=True,
        blank=True,
    )
    grade_or_year = models.CharField(
        _("grade / year"),
        max_length=50,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
        help_text=_("e.g. 'Grade 10', '2nd Year B.Sc', 'UPSC Aspirant'."),
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
    preferred_subjects = models.CharField(
        _("preferred subjects"),
        max_length=500,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
        help_text=_(
            "Comma-separated list of subjects the student is looking for help with."
        ),
    )
    bio = models.CharField(
        _("bio"),
        max_length=1000,
        null=True,
        blank=True,
        help_text=_("Short description of what the student is looking for."),
    )

    class Meta:
        verbose_name = _("Student")
        verbose_name_plural = _("Students")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["city", "education_level"]),
        ]
        constraints = [
            # Belt-and-braces at the DB level: reject a row whose optional
            # text fields are present but empty/whitespace-only (the API
            # normalises "" -> NULL, this stops anything else from slipping
            # a blank string in).
            models.CheckConstraint(
                name="student_text_fields_not_blank",
                check=(
                    (
                        models.Q(grade_or_year__isnull=True)
                        | ~models.Q(grade_or_year__regex=r"^\s*$")
                    )
                    & (models.Q(city__isnull=True) | ~models.Q(city__regex=r"^\s*$"))
                    & (models.Q(state__isnull=True) | ~models.Q(state__regex=r"^\s*$"))
                    & (
                        models.Q(country__isnull=True)
                        | ~models.Q(country__regex=r"^\s*$")
                    )
                    & (models.Q(bio__isnull=True) | ~models.Q(bio__regex=r"^\s*$"))
                ),
            ),
        ]

    def __str__(self):
        return f"Student: {self.user.get_full_name()} ({self.user.email})"

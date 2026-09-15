"""
Subject model for the Teacher Marketplace Platform.

Subjects are the core taxonomy students search by and teachers
tag their profiles with (via a Many-to-Many relationship on
TeacherProfile, built in apps/teacher_profile in this same phase).

Phase 2 scope: this model and its CRUD APIs are pure reference-data
management - no matching/lead logic lives here (that's lead_engine).
"""

from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import validate_no_control_characters, validate_taxonomy_name


class Subject(BaseModel):
    """
    A subject that can be taught/learned on the platform (e.g.
    Mathematics, Physics, Guitar, Spoken English).

    Inherits from BaseModel: UUID PK, created_at/updated_at,
    soft-delete, and audit fields are already provided.
    """

    name = models.CharField(
        _("name"),
        max_length=150,
        unique=True,
        db_index=True,
        validators=[validate_taxonomy_name],
        help_text=_("Display name of the subject, e.g. 'Mathematics'."),
    )
    slug = models.SlugField(
        _("slug"),
        max_length=170,
        unique=True,
        blank=True,
        help_text=_("URL-friendly identifier, auto-generated from name if left blank."),
    )
    description = models.CharField(
        _("description"),
        max_length=1000,
        null=True,
        blank=True,
        help_text=_("Optional short description of what this subject covers."),
    )
    icon = models.CharField(
        _("icon"),
        max_length=100,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
        help_text=_(
            "Icon identifier for frontend display (e.g. an icon library "
            "class name or a media path). Not a file upload in Phase 2 - "
            "kept as a simple string reference."
        ),
    )
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        db_index=True,
        help_text=_(
            "Inactive subjects are hidden from search/selection but not "
            "deleted, preserving historical data on existing profiles/"
            "requirements that reference them."
        ),
    )
    is_skill_based = models.BooleanField(
        _("is skill based"),
        default=False,
        db_index=True,
        help_text=_(
            "True for subjects learned as a skill rather than an academic "
            "grade (e.g. Music, an instrument, Karate) - the sign-up 'What "
            "level?' step offers Novice/Intermediate/Expert for these "
            "instead of the Class 1-5 / Undergraduate / ... academic bands, "
            "which don't make sense for e.g. a 40-year-old learning guitar."
        ),
    )

    class Meta:
        verbose_name = _("Subject")
        verbose_name_plural = _("Subjects")
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                name="subject_name_not_blank",
                check=~models.Q(name__regex=r"^\s*$"),
            ),
            models.CheckConstraint(
                name="subject_text_fields_not_blank",
                check=(
                    (
                        models.Q(description__isnull=True)
                        | ~models.Q(description__regex=r"^\s*$")
                    )
                    & (models.Q(icon__isnull=True) | ~models.Q(icon__regex=r"^\s*$"))
                ),
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """
        Auto-generates the slug from `name` if not explicitly
        provided. Kept as simple slug generation (no uniqueness
        collision-suffixing beyond the database's unique constraint
        raising an error) since subject names are curated/admin-
        managed data, not high-volume user input where collisions
        are likely.
        """
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

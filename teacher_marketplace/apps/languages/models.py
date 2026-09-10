"""
Language model for the Teacher Marketplace Platform.

Languages are referenced by TeacherProfile (Many-to-Many, in
apps/teacher_profile) as "preferred languages" a teacher can teach
in, and by StudentRequirement (in apps/student_requirement) as a
student's preferred language for learning.

Phase 2 scope: this model and its CRUD APIs are pure reference-data
management - no matching/lead logic lives here (that's lead_engine).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import validate_language_code, validate_taxonomy_name


class Language(BaseModel):
    """
    A language available on the platform (e.g. English, Hindi,
    Spanish). Inherits from BaseModel: UUID PK, created_at/
    updated_at, soft-delete, and audit fields are already provided.
    """

    name = models.CharField(
        _("name"),
        max_length=100,
        unique=True,
        db_index=True,
        validators=[validate_taxonomy_name],
        help_text=_("Display name of the language, e.g. 'English'."),
    )
    code = models.CharField(
        _("code"),
        max_length=10,
        unique=True,
        db_index=True,
        validators=[validate_language_code],
        help_text=_(
            "Short language code, e.g. 'en', 'hi', 'es'. Recommended: "
            "ISO 639-1 two-letter codes for consistency, though not "
            "strictly enforced to allow regional variants if needed."
        ),
    )
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        db_index=True,
        help_text=_(
            "Inactive languages are hidden from search/selection but not "
            "deleted, preserving historical data on existing profiles/"
            "requirements that reference them."
        ),
    )

    class Meta:
        verbose_name = _("Language")
        verbose_name_plural = _("Languages")
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                name="language_name_and_code_not_blank",
                check=~models.Q(name__regex=r"^\s*$") & ~models.Q(code__regex=r"^\s*$"),
            ),
            models.CheckConstraint(
                name="language_code_format",
                check=models.Q(code__regex=r"^[a-z][a-z0-9-]{1,9}$"),
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        """
        Normalizes the code to lowercase for consistency (e.g. 'EN'
        and 'en' should never both exist as separate rows) - mirrors
        the kind of light, non-business normalization already used
        elsewhere (e.g. RegisterSerializer.validate_email normalizing
        case via User.objects.normalize_email).
        """
        if self.code:
            self.code = self.code.strip().lower()
        super().save(*args, **kwargs)

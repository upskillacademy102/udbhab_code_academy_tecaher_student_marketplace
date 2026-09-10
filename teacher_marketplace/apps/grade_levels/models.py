"""
GradeLevel model - the admin-manageable "class / year" taxonomy.

Same reference-data shape as apps.subjects.Subject / apps.languages.Language
(name + is_active, CRUD via an admin-only-write API), plus a `sort_order`
so the dropdown can present "Class 1, Class 2, ..., Class 12, Undergraduate,
..." in a sensible order rather than alphabetically (which would put
"Class 10" before "Class 2").
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import validate_taxonomy_name


class GradeLevel(BaseModel):
    """
    A selectable class/grade/year option (e.g. "Class 10", "1st Year
    B.Com", "Adult Learner"). Referenced by name (not FK) from
    apps.students.Student.grade_or_year and
    apps.student_requirement.StudentRequirement.student_class, mirroring
    how Country/State/City are referenced by name from Student/Teacher's
    plain city/state/country fields - the dropdown is populated live from
    this table, but the field it fills stays a simple CharField.
    """

    name = models.CharField(
        _("name"),
        max_length=100,
        unique=True,
        db_index=True,
        validators=[validate_taxonomy_name],
        help_text=_("Display name, e.g. 'Class 10', 'Undergraduate'."),
    )
    sort_order = models.PositiveSmallIntegerField(
        _("sort order"),
        default=0,
        help_text=_(
            "Lower numbers show first in the dropdown. Options with the "
            "same sort_order fall back to alphabetical order."
        ),
    )
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        db_index=True,
        help_text=_(
            "Inactive grade levels are hidden from selection but not "
            "deleted, preserving historical data on existing profiles/"
            "requirements that reference them."
        ),
    )

    class Meta:
        verbose_name = _("Grade Level")
        verbose_name_plural = _("Grade Levels")
        ordering = ["sort_order", "name"]
        constraints = [
            models.CheckConstraint(
                name="grade_level_name_not_blank",
                check=~models.Q(name__regex=r"^\s*$"),
            ),
        ]

    def __str__(self):
        return self.name

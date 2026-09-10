"""
Location models for the Teacher Marketplace Platform.

Implements a three-level hierarchy:
    Country -> State -> City

Each level has a ForeignKey to its parent (State -> Country,
City -> State), not a flat/denormalized structure - this lets
search APIs correctly answer "all cities in this state" or "all
states in this country" without string-matching on name.

Referenced later in this phase by:
    - TeacherProfile (Many-to-Many to City - a teacher may serve
      multiple cities)
    - StudentRequirement (ForeignKey to City - a student's location)

Phase 2 scope: these are pure reference-data models with CRUD/
search APIs. No geolocation/distance-based matching logic lives
here (that would be a more advanced later-phase feature).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import (
    validate_country_code,
    validate_no_control_characters,
    validate_place_name,
)


class Country(BaseModel):
    """
    A country. Top of the location hierarchy.
    """

    name = models.CharField(
        _("name"),
        max_length=150,
        unique=True,
        db_index=True,
        validators=[validate_place_name],
    )
    code = models.CharField(
        _("code"),
        max_length=3,
        unique=True,
        db_index=True,
        validators=[validate_country_code],
        help_text=_("ISO 3166-1 alpha-2 or alpha-3 country code, e.g. 'IN', 'US'."),
    )
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        db_index=True,
    )

    class Meta:
        verbose_name = _("Country")
        verbose_name_plural = _("Countries")
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                name="country_name_not_blank",
                check=~models.Q(name__regex=r"^\s*$"),
            ),
            models.CheckConstraint(
                name="country_code_format",
                check=models.Q(code__regex=r"^[A-Z]{2,3}$"),
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


class State(BaseModel):
    """
    A state/province, belonging to exactly one Country.
    """

    country = models.ForeignKey(
        Country,
        related_name="states",
        on_delete=models.CASCADE,
        help_text=_("The country this state belongs to."),
    )
    name = models.CharField(
        _("name"),
        max_length=150,
        db_index=True,
        validators=[validate_place_name],
    )
    code = models.CharField(
        _("code"),
        max_length=10,
        null=True,
        blank=True,
        validators=[validate_no_control_characters],
        help_text=_("Optional short state code, e.g. 'MH', 'CA'."),
    )
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        db_index=True,
    )

    class Meta:
        verbose_name = _("State")
        verbose_name_plural = _("States")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["country", "name"],
                name="unique_state_name_per_country",
            ),
            models.CheckConstraint(
                name="state_name_not_blank",
                check=~models.Q(name__regex=r"^\s*$"),
            ),
            models.CheckConstraint(
                name="state_code_not_blank",
                check=models.Q(code__isnull=True) | ~models.Q(code__regex=r"^\s*$"),
            ),
        ]
        indexes = [
            models.Index(fields=["country", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name}, {self.country.name}"


class City(BaseModel):
    """
    A city, belonging to exactly one State.
    """

    state = models.ForeignKey(
        State,
        related_name="cities",
        on_delete=models.CASCADE,
        help_text=_("The state this city belongs to."),
    )
    name = models.CharField(
        _("name"),
        max_length=150,
        db_index=True,
        validators=[validate_place_name],
    )
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        db_index=True,
    )

    class Meta:
        verbose_name = _("City")
        verbose_name_plural = _("Cities")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["state", "name"],
                name="unique_city_name_per_state",
            ),
            models.CheckConstraint(
                name="city_name_not_blank",
                check=~models.Q(name__regex=r"^\s*$"),
            ),
        ]
        indexes = [
            models.Index(fields=["state", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name}, {self.state.name}"

    @property
    def country(self):
        """
        Convenience accessor to reach Country directly from a City
        instance without the caller needing to traverse
        city.state.country manually every time (e.g. in serializers
        building a flattened location representation).
        """
        return self.state.country

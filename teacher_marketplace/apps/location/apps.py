"""
App configuration for the location app.

This app owns the Country/State/City reference-data hierarchy and
its CRUD + search APIs. Referenced later in this phase by
TeacherProfile (Many-to-Many to City) and StudentRequirement
(ForeignKey to City).
"""

from django.apps import AppConfig


class LocationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.location"
    verbose_name = "Location"

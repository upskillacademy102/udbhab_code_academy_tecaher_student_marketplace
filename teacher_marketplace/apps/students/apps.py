"""
App configuration for the students app.

This app owns the Student profile model - descriptive data linked
one-to-one with a User (role=student). Contains no matching/search
business logic per Phase 1 scope.
"""

from django.apps import AppConfig


class StudentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.students"
    verbose_name = "Students"

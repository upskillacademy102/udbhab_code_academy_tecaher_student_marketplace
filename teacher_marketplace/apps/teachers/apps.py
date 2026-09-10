"""
App configuration for the teachers app.

This app owns the Teacher profile model - descriptive data linked
one-to-one with a User (role=teacher). Contains no token/wallet/
premium-membership business logic per Phase 1 scope.
"""

from django.apps import AppConfig


class TeachersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.teachers"
    verbose_name = "Teachers"

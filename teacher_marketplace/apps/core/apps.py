"""
App configuration for the core app.

This app contains cross-cutting infrastructure used across the
whole project: custom exceptions, the custom DRF exception
handler, the exception-handling middleware, and the standard
API response envelope helper. It has no models, so it requires
no migrations.
"""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"

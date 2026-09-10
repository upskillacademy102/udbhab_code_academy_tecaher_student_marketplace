"""
App configuration for the utils app.

This app contains reusable, model-independent helper logic shared
across the project - starting with field validators (email,
mobile, password strength). Future phases may add here: currency/
token formatting helpers, date/time helpers, or generic pagination
utilities, as long as they remain free of business/domain logic.
It has no models, so it requires no migrations.
"""

from django.apps import AppConfig


class UtilsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.utils"
    verbose_name = "Utils"

"""
App configuration for the search app.

This app has no models of its own - it exposes a read-only teacher
search API that queries apps.teacher_profile.TeacherProfile
directly, with filtering, sorting, and pagination.
"""

from django.apps import AppConfig


class SearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.search"
    verbose_name = "Search"

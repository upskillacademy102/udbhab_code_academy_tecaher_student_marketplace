"""
App configuration for the teacher_profile app.

This app owns TeacherProfile (extending Phase 1's Teacher with
marketplace-core fields: headline, teaching mode, hourly rate,
rating, verification status, and relational subjects/languages/
cities) and TeacherAvailability (weekday/weekend x morning/
afternoon/evening slot selection).
"""

from django.apps import AppConfig


class TeacherProfileConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.teacher_profile"
    verbose_name = "Teacher Profile"

"""
App configuration for the languages app.

This app owns the Language reference-data model and its CRUD APIs.
Languages are referenced (via Many-to-Many) by TeacherProfile in
apps.teacher_profile, and directly by StudentRequirement in
apps.student_requirement, both built later in this phase.
"""

from django.apps import AppConfig


class LanguagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.languages"
    verbose_name = "Languages"

"""
App configuration for the student_requirement app.

This app owns the StudentRequirement model - the "demand" side of
the marketplace that apps.lead_engine (built next) reads from to
generate matching Lead records for teachers.
"""

from django.apps import AppConfig


class StudentRequirementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.student_requirement"
    verbose_name = "Student Requirement"

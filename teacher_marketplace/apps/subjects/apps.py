"""
App configuration for the subjects app.

This app owns the Subject reference-data model and its CRUD APIs.
Subjects are referenced (via Many-to-Many) by TeacherProfile in
apps.teacher_profile, and directly by StudentRequirement in
apps.student_requirement, both built later in this phase.
"""

from django.apps import AppConfig


class SubjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.subjects"
    verbose_name = "Subjects"

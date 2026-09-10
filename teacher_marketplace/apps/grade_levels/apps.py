"""
App configuration for the grade_levels app.

This app owns the GradeLevel reference-data model and its CRUD API -
the admin-manageable "class / year" taxonomy (e.g. "Class 10",
"Undergraduate", "Competitive Exam Prep") that replaces free-typed
class/grade text on the Student profile (`grade_or_year`) and the
requirement-posting form (`StudentRequirement.student_class`). Both of
those remain plain CharFields (storing the chosen name) - this app just
gives the frontend a live, admin-extensible list to pick from instead of
an open text box, the same role apps.subjects and apps.languages already
play for their fields.
"""

from django.apps import AppConfig


class GradeLevelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.grade_levels"
    verbose_name = "Grade Levels"

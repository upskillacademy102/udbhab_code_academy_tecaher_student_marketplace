"""
App configuration for the lead_engine app.

This app owns the Lead model (linking StudentRequirement to
matching TeacherProfile records) and the matching algorithm in
services.py. Lead records are exclusively system-generated - see
services.generate_leads_for_requirement(), called from
apps.student_requirement's requirement-creation view.
"""

from django.apps import AppConfig


class LeadEngineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.lead_engine"
    verbose_name = "Lead Engine"

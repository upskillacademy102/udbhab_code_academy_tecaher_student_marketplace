"""
App configuration for the matching app.

This app owns the eligibility/scoring/ranking/lead-distribution
engine described in the current implementation phase: pincode-based
geographic matching, subject/language alias+fuzzy matching,
LeadAssignment (formal state machine), and Celery-driven lead
expiry. Models and services are being built incrementally - this
scaffold exists so the app is a valid, importable Django app while
that work is in progress.
"""

from django.apps import AppConfig


class MatchingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.matching"
    verbose_name = "Matching Engine"

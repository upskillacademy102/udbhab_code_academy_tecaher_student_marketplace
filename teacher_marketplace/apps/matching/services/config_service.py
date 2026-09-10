"""
Configuration resolution service for the matching app.

Every matching/eligibility service reads its thresholds through
get_config() rather than importing settings.MATCHING_* directly -
this is the single place that implements "DB-backed config,
settings.py as fallback," per the spec's explicit preference for
admin-editable configuration. A fresh install with no MatchingConfig
row yet still works correctly (falls through to settings.py), so
this app is functional immediately after migration, before any
admin has touched the config screen.
"""

from django.conf import settings

from apps.matching.models import MatchingConfig


class ResolvedConfig:
    """
    Plain data holder for resolved matching configuration values -
    whichever source (DB row or settings.py) each value actually
    came from is irrelevant to callers; they just read attributes.
    """

    def __init__(self, config_row: MatchingConfig = None):
        self._row = config_row

    def _get(self, db_field: str, settings_name: str, default):
        if self._row is not None:
            value = getattr(self._row, db_field, None)
            if value is not None and value != []:
                return value
        return getattr(settings, settings_name, default)

    @property
    def subject_match_threshold(self) -> int:
        return self._get("subject_match_threshold", "SUBJECT_MATCH_THRESHOLD", 70)

    @property
    def language_match_threshold(self) -> int:
        return self._get("language_match_threshold", "LANGUAGE_MATCH_THRESHOLD", 70)

    @property
    def time_match_threshold_minutes(self) -> int:
        return self._get("time_match_threshold_minutes", "TIME_MATCH_THRESHOLD", 1)

    @property
    def initial_location_radius_km(self) -> int:
        return self._get("initial_location_radius_km", "INITIAL_LOCATION_RADIUS_KM", 1)

    @property
    def location_radius_increment_km(self) -> int:
        return self._get(
            "location_radius_increment_km", "LOCATION_RADIUS_INCREMENT_KM", 3
        )

    @property
    def max_location_radius_km(self) -> int:
        return self._get("max_location_radius_km", "MAX_LOCATION_RADIUS_KM", 20)

    @property
    def lead_response_window_hours(self) -> int:
        return self._get("lead_response_window_hours", "LEAD_RESPONSE_WINDOW_HOURS", 24)

    @property
    def subscription_priority_order(self) -> list:
        return self._get(
            "subscription_priority_order", "SUBSCRIPTION_PRIORITY_ORDER", ["Free"]
        )


def get_config() -> ResolvedConfig:
    """
    Entry point every matching service calls. Queries MatchingConfig
    fresh on every call (not cached at import time) so an admin
    change takes effect immediately - matches the same reasoning
    already established in lead_engine.matching_service.MatchingService._get_weights().
    """
    return ResolvedConfig(MatchingConfig.get_active())

"""
App configuration for the trust app.

`apps.trust` is the home for the platform's identity-verification and
fraud-prevention layer:

    * pluggable verification providers (SMS OTP, government ID, selfie
      liveness, phone reachability, bank penny-drop, CAPTCHA, content
      classification) - abstract interfaces with dev adapters here,
      real vendors swapped in per environment via settings;
    * per-user ``TrustProfile`` (verification score, risk score/state);
    * the shared ``ManualReviewItem`` queue every fraud signal feeds into;
    * OTP, step-up re-verification, duplicate detection, teacher
      verification progress, lead-quality feedback, risk scoring
      (added phase by phase - see the plan).

Every enforcement gate this app introduces is behind its own
``settings`` feature flag, default OFF, so nothing changes behaviour
until it is explicitly switched on.
"""

from django.apps import AppConfig


class TrustConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.trust"
    verbose_name = "Trust & Verification"

    def ready(self):
        # Registers the post_save signal that gives every new User a
        # TrustProfile row. Imported here (not at module top) so it runs
        # only once the app registry is fully populated.
        from apps.trust import signals  # noqa: F401

"""
Test settings - inherits local development configuration but silences
the per-query SQL DEBUG logging development.py turns on (which makes
test output unreadable) and uses fast, isolated in-process backends
for cache and password hashing.

Run:  python manage.py test --settings=config.settings.test
"""

from config.settings.development import *  # noqa: F401,F403

# development.py sets django.db.backends -> DEBUG on the console; undo that.
LOGGING["loggers"]["django.db.backends"]["level"] = "WARNING"  # noqa: F405

# Deterministic, per-process cache so PreferenceService's cache
# invalidation can't leak state between tests.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-snapshot",
    }
}

# Faster hashing - tests create a lot of users.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Never hit the network for geocoding during tests.
GEOCODING_PROVIDER = "nominatim"

# Run Celery tasks inline if a test calls one directly.
CELERY_TASK_ALWAYS_EAGER = True

# Rate limits are exercised by their own dedicated tests; the shared
# per-IP counter otherwise leaks across the whole suite and fails
# unrelated tests once the cumulative anon-request count crosses 100.
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
    "anon": None,
    "user": None,
    "login": None,
    "register": None,
    "password_reset": None,
    "admin_login": None,
    "otp_request": None,
}
# The auth-throttle tests re-enable specific scopes with @override_settings.

# ==========================================================
# TRUST & FRAUD PREVENTION - deterministic baseline for the suite
# ==========================================================
# Every enforcement flag OFF regardless of the developer's environment;
# gate-specific tests turn their own flag ON with @override_settings.
# Providers pinned to their dev adapters.
for _flag in (
    "TRUST_REQUIRE_EMAIL_VERIFICATION",
    "TRUST_REQUIRE_MOBILE_VERIFICATION",
    "TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST",
    "TRUST_TEACHER_FLOOR_FOR_LEADS",
    "TRUST_VERIFICATION_SCORE_AFFECTS_RANKING",
    "TRUST_ENABLE_CAPTCHA",
    "TRUST_ENABLE_DEDUP_BLOCKING",
    "TRUST_ENABLE_STEP_UP_REVERIFICATION",
    "TRUST_ENABLE_REQUIREMENT_VELOCITY",
    "TRUST_ENABLE_PHONE_REACHABILITY_CHECK",
    "TRUST_ENABLE_LEAD_QUALITY_CLAWBACK",
    "TRUST_ENABLE_PAYMENT_RISK_CHECKS",
    "TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN",
    "TRUST_ENABLE_CONTACT_LEAKAGE_SCAN",
    "TRUST_ENABLE_REVIEW_SYSTEM",
    "TRUST_ENABLE_USER_BLOCKING",
    "TRUST_ENABLE_ANOMALY_ALERTS",
    "TRUST_ENABLE_RISK_AUTO_ACTIONS",
    "TRUST_ENABLE_SUSPENSION_APPEALS",
):
    globals()[_flag] = False
TRUST_SMS_PROVIDER = "console"
TRUST_ID_PROVIDER = "manual"
TRUST_LIVENESS_PROVIDER = "manual"
TRUST_PHONE_REACHABILITY_PROVIDER = "stub"
TRUST_PENNY_DROP_PROVIDER = "manual"
TRUST_CAPTCHA_PROVIDER = "stub"
TRUST_CONTENT_CLASSIFIER_PROVIDER = "regex"
TRUST_GEOIP_PROVIDER = "stub"

# Fake-lead auto-ban is always-on in production (no enable flag), so pin the
# thresholds out of reach for the general suite - the same tactic as
# TRUST_CAPTCHA_SWITCH_THRESHOLD. test_fake_lead_reports.py overrides these
# back to small values to exercise the auto-ban path deliberately.
FAKE_LEAD_AUTOBAN_WEEKLY = 10_000
FAKE_LEAD_AUTOBAN_MONTHLY = 10_000

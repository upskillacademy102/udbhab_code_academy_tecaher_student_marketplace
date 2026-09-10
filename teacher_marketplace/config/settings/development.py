"""
Development settings for the Teacher Marketplace Platform.

Activated via:
    DJANGO_SETTINGS_MODULE=config.settings.development

Inherits everything from base.py and overrides only what should
differ locally: DEBUG, ALLOWED_HOSTS, relaxed security headers,
and dev-only tooling.

NEVER deploy this settings module to a live/production server.
"""

from decouple import Csv, config

from .base import *  # noqa: F401, F403
from .base import INSTALLED_APPS, LOGGING

# ==========================================================
# DEBUG
# ==========================================================
DEBUG = config("DEBUG", default=True, cast=bool)

# ==========================================================
# ALLOWED HOSTS
# ==========================================================
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1",
    cast=Csv(),
)

# ==========================================================
# DEV-ONLY APPS
# ==========================================================
INSTALLED_APPS = INSTALLED_APPS + [
    "django_extensions",
]

# ==========================================================
# SECURITY (relaxed for local HTTP development)
# ==========================================================
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# ==========================================================
# CORS (permissive for local frontend dev)
# ==========================================================
CORS_ALLOW_ALL_ORIGINS = True

# ==========================================================
# EMAIL
# ==========================================================
# Console backend (prints emails to the terminal instead of sending
# them) is the default for local dev, but set EMAIL_BACKEND=
# django.core.mail.backends.smtp.EmailBackend in .env (with real
# EMAIL_HOST_USER/EMAIL_HOST_PASSWORD) to actually send mail, e.g. for
# testing the OTP flow end-to-end against a real inbox. Previously this
# was hardcoded to the console backend here, silently overriding
# whatever .env said - fixed to respect it like every other setting.
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)

# ==========================================================
# LOGGING OVERRIDES
# ==========================================================
# Show raw SQL queries in the console during local development.
LOGGING["loggers"]["django.db.backends"]["level"] = "DEBUG"
LOGGING["loggers"]["django.db.backends"]["handlers"] = ["console"]

# ==========================================================
# DRF - browsable API enabled locally for manual testing
# ==========================================================
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = (
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
)

# ==========================================================
# INTERNAL IPS (for Django Debug Toolbar, if added later)
# ==========================================================
INTERNAL_IPS = [
    "127.0.0.1",
]

# ==========================================================
# CELERY - run tasks in-process during local development
# ==========================================================
# Local dev normally has no Redis broker / worker running. Without this,
# every `.delay()` (e.g. lead generation + distribution enqueued from a
# requirement POST) fails to reach the broker and the work never runs -
# so a student's requirement never produces a Lead for the teacher.
# Eager mode executes the task synchronously in the web process instead.
# Set CELERY_TASK_ALWAYS_EAGER=False in .env (and run a real worker) to
# exercise the true async path locally.
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=True, cast=bool)
CELERY_TASK_EAGER_PROPAGATES = True

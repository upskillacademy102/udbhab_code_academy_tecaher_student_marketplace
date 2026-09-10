"""
Production settings for the Teacher Marketplace Platform.

Activated via:
    DJANGO_SETTINGS_MODULE=config.settings.production

Inherits everything from base.py and overrides only what must
differ in production: DEBUG=False, strict ALLOWED_HOSTS, HTTPS
enforcement, secure cookies, and real email delivery.

This module intentionally fails loudly (via decouple, which raises
if a required env var is missing) rather than falling back to an
insecure default - production must never silently boot with weak
settings.
"""

from decouple import Csv, config

from .base import *  # noqa: F401, F403
from .base import SPECTACULAR_SETTINGS

# ==========================================================
# DEBUG
# ==========================================================
# No default here on purpose - if DEBUG is not explicitly set to
# False in the production environment, this line raises rather
# than risk DEBUG=True leaking into production.
DEBUG = config("DEBUG", cast=bool)

if DEBUG:
    raise ValueError(
        "DEBUG must be False when using config.settings.production. "
        "Check your environment variables."
    )

# ==========================================================
# ALLOWED HOSTS
# ==========================================================
# No default - production must explicitly declare its real domains.
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())

# ==========================================================
# SECURITY - HTTPS / HSTS
# ==========================================================
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# JWT auth cookies must be HTTPS-only in production.
JWT_AUTH_COOKIE_SECURE = True

# CSRF trusted origins are mandatory in production - no localhost default.
# Must include the scheme, e.g. "https://app.example.com".
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", cast=Csv())

# If the browser client is served from a DIFFERENT origin than the API,
# the JWT cookies must be SameSite=None to be sent on cross-site XHR, and
# SameSite=None requires Secure=True (already enforced above). Set
# JWT_AUTH_COOKIE_SAMESITE=None in the environment for that deployment
# shape; keep the default "Lax" for a same-origin / reverse-proxied SPA.
if config("JWT_AUTH_COOKIE_SAMESITE", default="Lax") == "None":
    JWT_AUTH_COOKIE_SAMESITE = "None"

# OpenAPI schema / Swagger / ReDoc: authenticated staff only in
# production (they are open in development for convenience). Enforced by
# a permission on the spectacular views - see config/urls.py.
SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"],
}
SECURE_HSTS_SECONDS = config(
    "SECURE_HSTS_SECONDS", default=31536000, cast=int
)  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

# Trust the X-Forwarded-Proto header from the reverse proxy /
# load balancer (e.g. Nginx, AWS ALB) to correctly detect HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ==========================================================
# CORS - strict allow-list only (from base.py's CORS_ALLOWED_ORIGINS)
# ==========================================================
CORS_ALLOW_ALL_ORIGINS = False

# ==========================================================
# STATIC FILES - served via WhiteNoise
# ==========================================================
MIDDLEWARE = MIDDLEWARE.copy()
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ==========================================================
# CACHE - shared Redis backend for accurate cross-worker rate limiting
# ==========================================================
# DRF throttle counters live in the default cache. With the built-in
# per-process LocMemCache and N Gunicorn workers, the effective limit is
# N x the configured rate. Point the default cache at Redis so every worker
# shares one counter and the limits mean exactly what they say.
#
# Set REDIS_CACHE_URL in the environment (e.g. redis://127.0.0.1:6379/1 -
# a DIFFERENT db index from Celery's /0). If it is unset, the per-process
# LocMemCache is kept - throttling still works, just per-worker.
#
# Short socket timeouts + the fail-open throttle classes
# (apps.core.throttling) mean a Redis outage degrades to "limits not
# enforced this instant", never to a 500.
_REDIS_CACHE_URL = config("REDIS_CACHE_URL", default="")
if _REDIS_CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _REDIS_CACHE_URL,
            "OPTIONS": {
                "socket_connect_timeout": 0.2,
                "socket_timeout": 0.2,
            },
        }
    }

# ==========================================================
# EMAIL - real SMTP delivery
# ==========================================================
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# ==========================================================
# ADMINS - receive error emails via mail_admins handler in logging.py
# ==========================================================
ADMINS = [
    tuple(pair.split(":"))
    for pair in config("DJANGO_ADMINS", default="", cast=Csv())
    if pair
]
# Expected env format: DJANGO_ADMINS=Admin Name:admin@example.com,...
SERVER_EMAIL = config("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)

# ==========================================================
# DATABASE - enforce persistent connections in production
# ==========================================================
DATABASES["default"]["CONN_MAX_AGE"] = config("DB_CONN_MAX_AGE", default=60, cast=int)
DATABASES["default"]["OPTIONS"] = {
    "sslmode": config("DB_SSL_MODE", default="require"),
}

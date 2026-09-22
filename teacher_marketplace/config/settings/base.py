"""
Base settings for the Teacher Marketplace Platform.

This module contains configuration shared across ALL environments.
Environment-specific files (development.py, production.py) import
everything from here with `from .base import *` and override only
what needs to differ per environment.

Docs: https://docs.djangoproject.com/en/5.0/topics/settings/
"""

import os
from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

# ==========================================================
# BASE DIRECTORY
# ==========================================================
# config/settings/base.py -> config/settings -> config -> BASE_DIR
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ==========================================================
# SECURITY
# ==========================================================
SECRET_KEY = config("SECRET_KEY")

# DEBUG and ALLOWED_HOSTS are deliberately NOT set here.
# They differ meaningfully enough between environments that
# each environment file must declare them explicitly. This
# avoids a dangerous accidental default (e.g. DEBUG=True
# silently leaking into production).

# ==========================================================
# APPLICATION DEFINITION
# ==========================================================
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "django_filters",
    "corsheaders",
    "django_celery_beat",
]

LOCAL_APPS = [
    "apps.common",
    "apps.core",
    "apps.utils",
    "apps.accounts",
    "apps.students",
    "apps.teachers",
    "apps.subjects",
    "apps.languages",
    "apps.grade_levels",
    "apps.location",
    "apps.teacher_profile",
    "apps.student_requirement",
    "apps.lead_engine",
    "apps.search",
    "apps.wallet",
    "apps.payments",
    "apps.subscriptions",
    "apps.notifications",
    "apps.analytics",
    "apps.matching",
    "apps.trust",
    "apps.reviews",
    "apps.support",
    "apps.ops",
    "apps.learning_partner",
    "apps.web",
]

# ==========================================================
# FRONTEND (apps.web) - server-rendered app shell + Tailwind/Alpine
# ==========================================================
SITE_NAME = config("SITE_NAME", default="Udbhab")
SITE_TAGLINE = config("SITE_TAGLINE", default="Find the right teacher.")
# Where the browser reaches the DRF API from (same origin in this setup).
API_BASE_URL = config("API_BASE_URL", default="/api/v1")
LOGIN_URL = "/login/"

# ==========================================================
# PRIVILEGED-ACCESS CONTROLS (apps.accounts + apps.ops)
# ==========================================================
# An `admin`-role account can only obtain a session after an active
# Super Admin approves its login request. Super Admin login stays
# direct (bootstrap via `createsuperuser`).
ADMIN_LOGIN_REQUIRES_APPROVAL = config(
    "ADMIN_LOGIN_REQUIRES_APPROVAL", default=True, cast=bool
)
ADMIN_LOGIN_REQUEST_TTL_MINUTES = config(
    "ADMIN_LOGIN_REQUEST_TTL_MINUTES", default=15, cast=int
)
# How long a Super Admin's "act as user" session stays valid.
IMPERSONATION_TTL_MINUTES = config("IMPERSONATION_TTL_MINUTES", default=30, cast=int)

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ==========================================================
# MIDDLEWARE
# ==========================================================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Runs high so its response headers land on every response that flows
    # back out, including error responses produced further down the stack.
    "apps.core.middleware.security_headers.SecurityHeadersMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.exception_middleware.ExceptionHandlingMiddleware",
]

ROOT_URLCONF = "config.urls"

# ==========================================================
# TEMPLATES
# ==========================================================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.web.context.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ==========================================================
# DATABASE (PostgreSQL)
# ==========================================================
DATABASES = {
    "default": {
        "ENGINE": config("DB_ENGINE", default="django.contrib.gis.db.backends.postgis"),
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ==========================================================
# REQUEST BODY LIMITS (DoS / resource-exhaustion guard)
# ==========================================================
# The API speaks JSON; every real request body is a few KB. A 2.5 MB
# ceiling on non-file POST data is already generous (file-upload fields
# are exempt from this check and separately validated — see the
# profile-photo validator in apps.utils.validators).
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024  # 2 MB
# Hash-flooding / parser-exhaustion guard. High enough for Django-admin
# bulk actions on large change-lists, low enough to bound abuse.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000
# No endpoint accepts more than one file (a single profile photo).
DATA_UPLOAD_MAX_NUMBER_FILES = 10

# ==========================================================
# GDAL / GEOS (GeoDjango, Windows-specific path configuration)
# ==========================================================
# Windows doesn't expose these to Django's default search list -
# point directly at the DLLs installed alongside PostGIS via
# Stack Builder. Overridable per-machine via .env (GDAL_LIBRARY_PATH /
# GEOS_LIBRARY_PATH) so a local PostGIS bundle installed elsewhere works
# without editing this file. An empty value lets GeoDjango fall back to
# its own DLL search (e.g. a non-Windows host).
GDAL_LIBRARY_PATH = config(
    "GDAL_LIBRARY_PATH",
    default=r"C:\Program Files\PostgreSQL\17\bin\libgdal-35.dll",
)
GEOS_LIBRARY_PATH = config(
    "GEOS_LIBRARY_PATH",
    default=r"C:\Program Files\PostgreSQL\17\bin\libgeos_c.dll",
)

# GDAL on Windows needs its sibling DLLs on PATH and the PROJ coordinate
# database (proj.db) discoverable. Both live alongside the DLLs in a
# PostGIS install; wire them up from GDAL_LIBRARY_PATH's directory so a
# local dev machine works without a system-wide PostgreSQL on PATH.
_gdal_dir = os.path.dirname(GDAL_LIBRARY_PATH)
if _gdal_dir and os.path.isdir(_gdal_dir):
    os.environ["PATH"] = _gdal_dir + os.pathsep + os.environ.get("PATH", "")
    _proj_data = config("PROJ_DATA", default="") or config("PROJ_LIB", default="")
    if not _proj_data:
        for _cand in (
            os.path.join(_gdal_dir, "..", "share", "proj"),
            os.path.join(_gdal_dir, "..", "share", "contrib", "postgis-3.6", "proj"),
            os.path.join(_gdal_dir, "..", "share", "gdal"),
        ):
            if os.path.isfile(os.path.join(_cand, "proj.db")):
                _proj_data = os.path.abspath(_cand)
                break
    if _proj_data:
        os.environ["PROJ_DATA"] = _proj_data
        os.environ["PROJ_LIB"] = _proj_data

# ==========================================================
# CUSTOM USER MODEL
# ==========================================================
AUTH_USER_MODEL = "accounts.User"

# ==========================================================
# PASSWORD VALIDATION
# ==========================================================
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    {
        "NAME": "apps.utils.validators.PasswordStrengthValidator",
    },
]

# ==========================================================
# PASSWORD HASHING
# ==========================================================
# Argon2id first: memory-hard (GPU/ASIC-resistant), OWASP's first
# recommendation, and ~4-8x faster than Django's default 1.2M-iteration
# PBKDF2 on typical hardware. The PBKDF2 hashers stay in the list so
# passwords hashed before this change keep validating and are transparently
# re-hashed to Argon2 on the user's next successful login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# ==========================================================
# INTERNATIONALIZATION
# ==========================================================
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True  # All datetimes stored/queried in UTC, converted at display time

# ==========================================================
# STATIC & MEDIA FILES
# ==========================================================
STATIC_URL = config("STATIC_URL", default="/static/")
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = config("MEDIA_URL", default="/media/")
MEDIA_ROOT = BASE_DIR / "media"

# ==========================================================
# DEFAULT PRIMARY KEY (overridden per-model with UUIDModel,
# but kept here as a safe fallback for any app that forgets to
# inherit from it)
# ==========================================================
# NOTE: Actual UUID PKs are enforced via apps.common.models.UUIDModel
# which every domain model inherits from. DEFAULT_AUTO_FIELD above
# only affects models that do NOT explicitly declare a PK.

# ==========================================================
# DJANGO REST FRAMEWORK
# ==========================================================
REST_FRAMEWORK = {
    # CookieJWTAuthentication reads the access token from an httpOnly
    # cookie when there is no Authorization header (browser / Swagger),
    # and otherwise behaves exactly like the header-based class. Both
    # classes enforce the single-active-session `sid` check.
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.accounts.authentication.CookieJWTAuthentication",
        "apps.accounts.authentication.SessionAwareJWTAuthentication",
    ),
    # IsAuthenticated MUST stay first: it produces 401 for missing /
    # invalid / expired credentials. RoleBasedAPIPermission then applies
    # the centralised, default-deny role->method->endpoint policy
    # (apps.accounts.api_permissions) and produces 403 for an
    # authenticated user whose role is not granted the route.
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
        "apps.accounts.permissions.RoleBasedAPIPermission",
    ),
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_PARSER_CLASSES": (
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Fail-open variants of the stock throttles: if the throttle cache
    # backend errors, the request is allowed (every auth/permission check
    # still runs) rather than 500-ing the whole API. See apps.core.throttling.
    "DEFAULT_THROTTLE_CLASSES": (
        "apps.core.throttling.ResilientAnonRateThrottle",
        "apps.core.throttling.ResilientUserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
        # Tight, named ceilings on abuse-prone auth endpoints. See
        # apps.core.throttling. Chosen far above any real user's rate and
        # far below a brute-force / enumeration rate.
        "login": "10/min",  # per (IP, email)
        "register": "30/hour",  # per IP
        "password_reset": "10/hour",  # per IP
        "admin_login": "20/hour",  # per IP
        "otp_request": "6/hour",  # per (user, channel)
    },
    "EXCEPTION_HANDLER": "apps.core.exceptions.handlers.custom_exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

# ==========================================================
# SIMPLE JWT
# ==========================================================
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=60, cast=int)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7, cast=int)
    ),
    "ROTATE_REFRESH_TOKENS": config(
        "JWT_ROTATE_REFRESH_TOKENS", default=True, cast=bool
    ),
    "BLACKLIST_AFTER_ROTATION": config(
        "JWT_BLACKLIST_AFTER_ROTATION", default=True, cast=bool
    ),
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
}

# ==========================================================
# JWT httpOnly COOKIES
# ==========================================================
# On login the access + refresh tokens are ALSO set as httpOnly cookies
# so a browser / Swagger session carries authentication automatically -
# no manual "Bearer" paste. Programmatic clients can ignore the cookies
# and keep using the Authorization header. Logout clears them.
#
# Secure is off by default for local HTTP dev and forced on in
# production.py. SameSite=Lax is safe for a same-origin SPA / Swagger;
# a cross-origin SPA must set JWT_AUTH_COOKIE_SAMESITE=None (which also
# requires Secure=True, i.e. HTTPS).
JWT_AUTH_COOKIE = config("JWT_AUTH_COOKIE", default="access")
JWT_REFRESH_COOKIE = config("JWT_REFRESH_COOKIE", default="refresh")
JWT_AUTH_COOKIE_SECURE = config("JWT_AUTH_COOKIE_SECURE", default=False, cast=bool)
JWT_AUTH_COOKIE_SAMESITE = config("JWT_AUTH_COOKIE_SAMESITE", default="Lax")
JWT_AUTH_COOKIE_HTTPONLY = True

# ==========================================================
# DRF-SPECTACULAR (Swagger / OpenAPI)
# ==========================================================
SPECTACULAR_SETTINGS = {
    "TITLE": "Teacher Marketplace Platform API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]+/",
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
    # Several models legitimately have a `status` field with different
    # choice sets (Payment, LeadAssignment, StudentRequirement, ...).
    # Give the recurring ones stable, meaningful component names so the
    # generated schema doesn't fall back to "StatusA3eEnum"-style hashes.
    "ENUM_NAME_OVERRIDES": {
        "RequirementStatusEnum": "apps.student_requirement.models.RequirementStatus",
        "LeadDistributionStatusEnum": "apps.student_requirement.models.LeadDistributionStatus",
        "AssignmentStatusEnum": "apps.matching.models.AssignmentStatus",
        "AssignmentResponseEnum": "apps.matching.models.AssignmentResponse",
        "LeadStatusEnum": "apps.lead_engine.models.LeadStatus",
        "PlanStatusEnum": "apps.subscriptions.models.PlanStatus",
        "SubscriptionStatusEnum": "apps.subscriptions.models.SubscriptionStatus",
        "PaymentStatusEnum": "apps.payments.models.PaymentStatus",
        "PaymentTypeEnum": "apps.payments.models.PaymentType",
        "WalletTransactionStatusEnum": "apps.wallet.models.TransactionStatus",
        "WalletTransactionTypeEnum": "apps.wallet.models.TransactionType",
        "AuditStatusEnum": "apps.ops.models.AuditStatus",
        "AuditCategoryEnum": "apps.ops.models.AuditCategory",
        "AdminLoginRequestStatusEnum": "apps.accounts.models.AdminLoginRequest.Status",
        "VerificationStatusEnum": "apps.teacher_profile.models.VerificationStatus",
        "TeachingModeEnum": "apps.teacher_profile.models.TeachingMode",
        "UserRoleEnum": "apps.accounts.models.UserRole",
    },
    # Swagger "Try it out": logging in via POST /api/v1/auth/login/ sets
    # an httpOnly cookie the browser then sends automatically, so no
    # manual "Authorize" step is needed. persistAuthorization keeps any
    # Bearer token entered manually across page reloads too.
    "SWAGGER_UI_SETTINGS": {
        "persistAuthorization": True,
        "withCredentials": True,
    },
    "DESCRIPTION": (
        "API documentation for the Teacher Marketplace Platform. "
        "Students search and contact teachers for free. Teachers "
        "purchase tokens to unlock student contact details.\n\n"
        "**Auth:** POST `/api/v1/auth/login/` once - the response sets "
        "httpOnly `access` / `refresh` cookies that every subsequent "
        "request carries automatically. Non-browser clients may instead "
        "send `Authorization: Bearer <access>`. Only one account may be "
        "logged in at a time; call `/api/v1/auth/logout/` before "
        "switching accounts."
    ),
}

# ==========================================================
# CORS
# ==========================================================
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000",
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = config("CORS_ALLOW_CREDENTIALS", default=True, cast=bool)

# ==========================================================
# CSRF / COOKIE SECURITY
# ==========================================================
# CSRF_TRUSTED_ORIGINS is required for the Django admin (and the DRF
# browsable API) to accept POSTs over HTTPS from a named domain, and for
# any same-site cookie-authenticated write from the SPA origin.
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:3000,http://127.0.0.1:3000",
    cast=Csv(),
)

# The JWT API itself is not CSRF-exposed: DRF views are csrf_exempt and
# JWTAuthentication/CookieJWTAuthentication never invoke the CSRF check
# (only SessionAuthentication does). The httpOnly JWT cookies are
# additionally protected by SameSite (Lax by default, see SIMPLE_JWT
# cookie block above) which blocks them from riding cross-site
# state-changing requests. Session/CSRF cookies are pinned to Lax too.
SESSION_COOKIE_SAMESITE = config("SESSION_COOKIE_SAMESITE", default="Lax")
CSRF_COOKIE_SAMESITE = config("CSRF_COOKIE_SAMESITE", default="Lax")

# Cookies are never readable by JavaScript (defence against a stolen session
# via XSS). The JWT auth cookies set their own HttpOnly flag in cookies.py.
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # the SPA must read the token to echo it back

# ==========================================================
# SECURITY RESPONSE HEADERS (all environments)
# ==========================================================
# These are inert on plain-HTTP localhost (they only constrain the browser,
# never the server) so they are safe to apply everywhere. HTTPS-only
# behaviour (SSL redirect, HSTS, Secure cookies) stays in production.py /
# development.py where it differs per environment.
#
#   nosniff      - browser must honour the declared Content-Type, so a JSON
#                  response can't be coerced into executing as HTML/JS.
#   X-Frame DENY - the site can never be embedded in a frame (clickjacking).
#   referrer     - outbound links leak only the origin, never the full path
#                  (which can carry ids / tokens), and nothing on downgrade.
#   COOP         - a popup this page opens can't get a handle back to it.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Content-Security-Policy + Permissions-Policy are attached by
# apps.core.middleware.security_headers.SecurityHeadersMiddleware. Override
# CONTENT_SECURITY_POLICY / PERMISSIONS_POLICY here (or per-environment) to
# adjust; set CONTENT_SECURITY_POLICY_REPORT_ONLY=True to trial a stricter
# policy without enforcing it.

# ==========================================================
# EMAIL (console backend by default; overridden in production)
# ==========================================================
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="noreply@teachermarketplace.com"
)
# Shown to users on the /suspended/ page as the manual appeal channel.
SUPPORT_EMAIL = config("SUPPORT_EMAIL", default=DEFAULT_FROM_EMAIL)
# Optional ops inbox notified when a suspension appeal is filed ("" = off).
TRUST_APPEALS_NOTIFY_EMAIL = config("TRUST_APPEALS_NOTIFY_EMAIL", default="")

# ==========================================================
# FRONTEND URL (used in password reset emails, etc.)
# ==========================================================
FRONTEND_BASE_URL = config("FRONTEND_BASE_URL", default="http://localhost:3000")

# ==========================================================
# MATCHING ENGINE WEIGHTS
# ==========================================================
# Component weights for the lead-matching composite score, per
# apps.lead_engine.services.matching_service.MatchingService. Must
# sum to 100. Time compatibility is deliberately weighted highest
# (30%) per the explicit business requirement: "RIGHT TEACHER +
# RIGHT SUBJECT + RIGHT TIME is more valuable than PREMIUM TEACHER +
# WRONG TIME." Kept in settings (not hardcoded in matching_service.py)
# so an admin-configurable override can read/write this dict in a
# future phase without changing matching logic code.
MATCHING_WEIGHTS = {
    "subject": 25,
    "time": 30,
    "language": 15,
    "location": 10,
    "budget": 5,
    "rating": 5,
    "experience": 3,
    "verification": 3,
    "response_rate": 2,
    "premium": 2,
}
# Minimum composite match_score (0-100) a teacher must reach to
# receive a generated Lead for a StudentRequirement. Set moderately
# (not 0) per the explicit business rule: "avoid sending obviously
# incompatible leads." Does NOT apply to general search browsing
# (apps.search) - only to automatic Lead generation at requirement-
# submission time.
MINIMUM_LEAD_MATCH_SCORE = 40
# ==========================================================
# RAZORPAY
# ==========================================================
RAZORPAY_KEY_ID = config("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = config("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = config("RAZORPAY_WEBHOOK_SECRET")

# ==========================================================
# CELERY
# ==========================================================
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND", default="redis://localhost:6379/0"
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# At-least-once delivery: a task is ack'd only after it finishes, so a
# worker crash mid-task re-queues it rather than silently dropping it.
# Every task in this project is written to be idempotent, so a
# re-delivery is safe. task_reject_on_worker_lost pairs with acks_late
# to re-queue (not error) when a worker dies hard (OOM kill, SIGKILL).
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
# A single lead-distribution task should never run for minutes; these
# limits stop a pathological requirement (or a hung external call) from
# pinning a worker forever. Soft limit raises inside the task so it can
# mark itself failed cleanly; hard limit kills the worker process.
CELERY_TASK_SOFT_TIME_LIMIT = config(
    "CELERY_TASK_SOFT_TIME_LIMIT", default=120, cast=int
)
CELERY_TASK_TIME_LIMIT = config("CELERY_TASK_TIME_LIMIT", default=180, cast=int)
# Fair dispatch - don't let one worker hoard queued requirements while
# others idle (matters once lead volume grows).
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# Synchronous, in-process execution unless a real broker is wired up.
# Overridden to True in config/settings/test.py.
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=False, cast=bool)
CELERY_TASK_EAGER_PROPAGATES = True

# ==========================================================
# CELERY BEAT SCHEDULE
# ==========================================================
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Static fallback schedule - django-celery-beat's DatabaseScheduler
# also supports fully admin-editable periodic tasks via Django
# Admin once migrations run (PeriodicTask model), which is the
# recommended way to adjust this interval without a redeploy. This
# entry seeds a sensible default (every 5 minutes) so the task runs
# even before an admin has configured anything in the DB-backed
# schedule UI.
CELERY_BEAT_SCHEDULE = {
    "expire-lead-assignments": {
        "task": "apps.matching.tasks.expire_lead_assignments",
        "schedule": 300.0,  # seconds = 5 minutes
    },
    # Time-based subscription-tier reveal for ONLINE leads - brings in the
    # next tier on a fixed clock (online_tier_window_hours), independent of
    # whether the current tier's assignment was unlocked/rejected/expired.
    "reveal-online-lead-tiers": {
        "task": "apps.matching.tasks.reveal_online_lead_tiers",
        "schedule": 300.0,  # every 5 minutes
    },
    # Safety net: re-queue any requirement whose async lead distribution
    # never completed (broker outage at creation time, worker killed
    # mid-task, lost result). The task it re-queues is idempotent.
    "requeue-stuck-lead-distributions": {
        "task": "apps.lead_engine.tasks.requeue_stuck_requirement_distributions",
        "schedule": 600.0,  # every 10 minutes
    },
    # Apply email/mobile changes whose step-up cooldown has elapsed, and
    # expire change requests that were never confirmed. Idempotent.
    "apply-due-sensitive-changes": {
        "task": "apps.trust.tasks.apply_due_sensitive_changes",
        "schedule": 60.0,  # every minute
    },
    # Nightly safety-net for teacher verification scores (inline recompute
    # already runs on the events that matter). Idempotent.
    "recompute-teacher-verification-scores": {
        "task": "apps.trust.tasks.recompute_teacher_verification_scores",
        "schedule": 6 * 60 * 60.0,  # every 6 hours
    },
    # Daily payment-ledger reconciliation (Payment vs WalletTransaction vs
    # gateway). Idempotent; each run covers the window since the last run.
    "reconcile-payments": {
        "task": "apps.payments.tasks.reconcile_payments",
        "schedule": 24 * 60 * 60.0,  # daily
    },
    # Release new-account cooldown wallet holds once their window elapses.
    # Idempotent; a no-op unless TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN is on.
    "release-cooldown-holds": {
        "task": "apps.payments.tasks.release_due_cooldown_holds",
        "schedule": 60 * 60.0,  # hourly
    },
    # Nightly risk-score sweep: decay expired signals, keep risk_state +
    # the RISK_ESCALATION queue item accurate. Idempotent.
    "recompute-risk-scores": {
        "task": "apps.trust.tasks.recompute_risk_scores",
        "schedule": 6 * 60 * 60.0,  # every 6 hours
    },
}

# ==========================================================
# MATCHING ENGINE - MATCHING/ELIGIBILITY CONFIG
# ==========================================================
# Defaults only - apps.matching.models.MatchingConfig provides a
# DB-backed override so admins can adjust these without redeploy,
# per the spec's explicit "prefer database-backed configuration"
# requirement. These settings values are the fallback used only if
# no MatchingConfig row exists yet (e.g. immediately after a fresh
# migration, before an admin has configured anything).
SUBJECT_MATCH_THRESHOLD = 70
LANGUAGE_MATCH_THRESHOLD = 70
TIME_MATCH_THRESHOLD = 1  # any actual overlap > 0 minutes counts as time-eligible
INITIAL_LOCATION_RADIUS_KM = 1
LOCATION_RADIUS_INCREMENT_KM = 3
MAX_LOCATION_RADIUS_KM = 20
OFFLINE_RESPONSE_WINDOW_HOURS = 24
ONLINE_TIER_WINDOW_HOURS = 8
LEAD_VISIBILITY_WINDOW_HOURS = 24
SUBSCRIPTION_PRIORITY_ORDER = [
    "Elite",
    "Professional",
    "Free",
]  # highest first; admin-editable via MatchingConfig

# ==========================================================
# LEAD UNLOCK ENTITLEMENTS  (token system temporarily disabled)
# ==========================================================
# TOKEN_SYSTEM_ENABLED=False puts the platform on the subscription-
# allowance model: every lead costs exactly one unlock, a teacher's
# monthly allowance comes from their plan (Free 4 / Professional 10 /
# Elite 40), and paid top-ups top up a separate never-expiring bucket.
#
# The token / wallet / package machinery is NOT deleted while this is
# False - it is pinned and hidden:
#   - get_unlock_token_cost() returns FIXED_LEAD_UNLOCK_COST (1) instead
#     of a per-tier LeadUnlockPricing lookup, so PricingTier and the
#     fuzzy student_class keyword matcher stop running entirely.
#   - the Wallet stays the ledger for PURCHASED unlocks (top-ups), which
#     is what keeps the Razorpay flow, the audit trail, the refund path
#     and the Phase 7 reconciliation/dispute hardening intact.
#   - TokenPriorityService returns 0 so a purchased balance can never buy
#     search ranking - top-ups grant volume, never priority.
#   - the wallet / buy-tokens pages and the token vocabulary are hidden
#     from every teacher-facing surface.
#
# Setting this back to True restores the original variable-cost token
# economy with no data migration. See LEAD_UNLOCK_ENTITLEMENTS.md.
TOKEN_SYSTEM_ENABLED = config("TOKEN_SYSTEM_ENABLED", default=False, cast=bool)

# Length of one entitlement period. A rolling 30-day cycle, NOT a
# calendar month - the subscription period and the unlock allowance
# period are the same clock (see SubscriptionService.subscribe), so a
# renewal and an allowance reset can never drift apart.
LEAD_UNLOCK_CYCLE_DAYS = config("LEAD_UNLOCK_CYCLE_DAYS", default=30, cast=int)

# What one lead costs while TOKEN_SYSTEM_ENABLED is False. Every lead is
# worth exactly 1 unlock regardless of category.
FIXED_LEAD_UNLOCK_COST = 1

# Plans whose teachers may buy AND spend top-up packs. Every plan,
# including Free (decided 2026-09-09): extra unlocks sell capacity, and
# the subscription sells priority. A Free teacher can buy the capacity to
# unlock more of the leads that reach them, but stays last in
# LeadDistributionService's tier cascade, so paid teachers still see every
# lead first. Buying unlocks never moves a teacher up a tier.
#
# Consequence to watch: at Rs.9.80/unlock the 5-pack undercuts
# Professional's Rs.16.50 marginal rate, so a Free teacher who only wants
# volume can beat Professional on price. The subscription's value is the
# priority, the featured listing and the reach - if paid signups stall,
# this list is the lever to re-gate (set it back to
# ["Professional", "Elite"]).
TOPUP_ELIGIBLE_PLANS = config(
    "TOPUP_ELIGIBLE_PLANS", default="Free,Professional,Elite", cast=Csv()
)

# ==========================================================
# GEOCODING
# ==========================================================
GEOCODING_PROVIDER = config("GEOCODING_PROVIDER", default="nominatim")
GOOGLE_GEOCODING_API_KEY = config("GOOGLE_GEOCODING_API_KEY", default="")

# ==========================================================
# TRUST & FRAUD PREVENTION  (apps.trust)
# ==========================================================
# Every enforcement gate below defaults OFF. Turn one ON only once its
# flow has been proven end-to-end (see TRUST_AND_FRAUD.md for the
# recommended activation order). With every flag OFF the platform
# behaves exactly as it did before apps.trust existed.
#
# --- Provider selectors (which adapter each capability uses) -----------
# Dev defaults make every flow work with no third-party account:
#   console -> logs instead of sending (SMS)
#   stub    -> deterministic success (phone reachability, CAPTCHA)
#   manual  -> routes to the ManualReviewItem queue (ID, liveness, penny-drop)
#   regex   -> real dependency-free implementation (content classifier)
TRUST_SMS_PROVIDER = config("TRUST_SMS_PROVIDER", default="console")
# Used only when TRUST_SMS_PROVIDER=msg91 (real SMS delivery via
# https://msg91.com). MSG91_TEMPLATE_ID is the ID of a DLT-approved OTP
# template created in the MSG91 dashboard (Indian telecom regulation
# requires transactional SMS to Indian numbers to use a pre-registered
# template - see apps/trust/providers/msg91.py).
MSG91_AUTH_KEY = config("MSG91_AUTH_KEY", default="")
MSG91_TEMPLATE_ID = config("MSG91_TEMPLATE_ID", default="")
TRUST_ID_PROVIDER = config("TRUST_ID_PROVIDER", default="manual")
TRUST_LIVENESS_PROVIDER = config("TRUST_LIVENESS_PROVIDER", default="manual")
TRUST_PHONE_REACHABILITY_PROVIDER = config(
    "TRUST_PHONE_REACHABILITY_PROVIDER", default="stub"
)
TRUST_PENNY_DROP_PROVIDER = config("TRUST_PENNY_DROP_PROVIDER", default="manual")
TRUST_CAPTCHA_PROVIDER = config("TRUST_CAPTCHA_PROVIDER", default="stub")
TRUST_CONTENT_CLASSIFIER_PROVIDER = config(
    "TRUST_CONTENT_CLASSIFIER_PROVIDER", default="regex"
)
TRUST_GEOIP_PROVIDER = config("TRUST_GEOIP_PROVIDER", default="stub")

# --- Enforcement feature flags (all default False) --------------------
TRUST_REQUIRE_EMAIL_VERIFICATION = config(
    "TRUST_REQUIRE_EMAIL_VERIFICATION", default=False, cast=bool
)
TRUST_REQUIRE_MOBILE_VERIFICATION = config(
    "TRUST_REQUIRE_MOBILE_VERIFICATION", default=False, cast=bool
)
TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST = config(
    "TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST", default=False, cast=bool
)
TRUST_TEACHER_FLOOR_FOR_LEADS = config(
    "TRUST_TEACHER_FLOOR_FOR_LEADS", default=False, cast=bool
)
TRUST_VERIFICATION_SCORE_AFFECTS_RANKING = config(
    "TRUST_VERIFICATION_SCORE_AFFECTS_RANKING", default=False, cast=bool
)
TRUST_ENABLE_CAPTCHA = config("TRUST_ENABLE_CAPTCHA", default=False, cast=bool)
TRUST_ENABLE_DEDUP_BLOCKING = config(
    "TRUST_ENABLE_DEDUP_BLOCKING", default=False, cast=bool
)
TRUST_ENABLE_STEP_UP_REVERIFICATION = config(
    "TRUST_ENABLE_STEP_UP_REVERIFICATION", default=False, cast=bool
)
TRUST_ENABLE_REQUIREMENT_VELOCITY = config(
    "TRUST_ENABLE_REQUIREMENT_VELOCITY", default=False, cast=bool
)
TRUST_ENABLE_PHONE_REACHABILITY_CHECK = config(
    "TRUST_ENABLE_PHONE_REACHABILITY_CHECK", default=False, cast=bool
)
# Defaults ON, unlike the other trust gates: under the unlock-allowance
# model, refunding a corroborated fake / unreachable lead is a promise we
# make to teachers up front, not an optional enforcement escalation. Still
# requires TRUST_LEAD_QUALITY_CORROBORATION distinct teachers to agree.
TRUST_ENABLE_LEAD_QUALITY_CLAWBACK = config(
    "TRUST_ENABLE_LEAD_QUALITY_CLAWBACK", default=True, cast=bool
)
TRUST_ENABLE_PAYMENT_RISK_CHECKS = config(
    "TRUST_ENABLE_PAYMENT_RISK_CHECKS", default=False, cast=bool
)
TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN = config(
    "TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN", default=False, cast=bool
)
TRUST_ENABLE_CONTACT_LEAKAGE_SCAN = config(
    "TRUST_ENABLE_CONTACT_LEAKAGE_SCAN", default=False, cast=bool
)
TRUST_ENABLE_REVIEW_SYSTEM = config(
    "TRUST_ENABLE_REVIEW_SYSTEM", default=False, cast=bool
)
TRUST_ENABLE_USER_BLOCKING = config(
    "TRUST_ENABLE_USER_BLOCKING", default=False, cast=bool
)
TRUST_ENABLE_ANOMALY_ALERTS = config(
    "TRUST_ENABLE_ANOMALY_ALERTS", default=False, cast=bool
)
TRUST_ENABLE_RISK_AUTO_ACTIONS = config(
    "TRUST_ENABLE_RISK_AUTO_ACTIONS", default=False, cast=bool
)
# When on, a risk-suspended user is shown the /suspended/ page and can
# file an in-app appeal; off, that page only offers a support email.
TRUST_ENABLE_SUSPENSION_APPEALS = config(
    "TRUST_ENABLE_SUSPENSION_APPEALS", default=False, cast=bool
)

# --- Tunables (used by later phases) ----------------------------------
TRUST_OTP_TTL_MINUTES = config("TRUST_OTP_TTL_MINUTES", default=10, cast=int)
TRUST_OTP_MAX_ATTEMPTS = config("TRUST_OTP_MAX_ATTEMPTS", default=5, cast=int)
TRUST_CAPTCHA_SWITCH_THRESHOLD = config(
    "TRUST_CAPTCHA_SWITCH_THRESHOLD", default=10, cast=int
)
TRUST_SENSITIVE_CHANGE_COOLDOWN_MINUTES = config(
    "TRUST_SENSITIVE_CHANGE_COOLDOWN_MINUTES", default=60, cast=int
)
TRUST_REQUIREMENT_MAX_PER_DAY = config(
    "TRUST_REQUIREMENT_MAX_PER_DAY", default=10, cast=int
)
TRUST_REQUIREMENT_MAX_OPEN = config("TRUST_REQUIREMENT_MAX_OPEN", default=15, cast=int)
TRUST_LEAD_QUALITY_CORROBORATION = config(
    "TRUST_LEAD_QUALITY_CORROBORATION", default=2, cast=int
)

# --- Fake-lead reporting -> superadmin alerts + automatic ban ---------
# Every time a teacher rates an unlocked lead "fake", a FAKE_LEAD_REPORT
# review-queue item for that student is opened or updated (so the Super
# Admin dashboard reflects it) and the auto-ban thresholds below are
# checked. This runs UNCONDITIONALLY - there is no enable flag - because
# the auto-ban is a deliberate always-on safety mechanism, not an
# optional enforcement escalation.
#
# Counting is by DISTINCT teacher (a teacher who flags several of one
# student's leads still counts once), over a rolling window. A student is
# permanently banned (User.is_active = False, sessions killed; only a
# Super Admin can reactivate) when EITHER window is exceeded:
#   > FAKE_LEAD_AUTOBAN_WEEKLY   distinct teachers in the last 7 days, or
#   > FAKE_LEAD_AUTOBAN_MONTHLY  distinct teachers in the last 30 days.
# FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS is a hard floor: no automatic
# ban ever fires below it, whatever the window thresholds are set to, so
# one or two teachers acting together can never get a student banned.
FAKE_LEAD_AUTOBAN_WEEKLY = config("FAKE_LEAD_AUTOBAN_WEEKLY", default=10, cast=int)
FAKE_LEAD_AUTOBAN_MONTHLY = config("FAKE_LEAD_AUTOBAN_MONTHLY", default=15, cast=int)
FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS = config(
    "FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS", default=3, cast=int
)
FAKE_LEAD_REPORT_WEEKLY_WINDOW_DAYS = config(
    "FAKE_LEAD_REPORT_WEEKLY_WINDOW_DAYS", default=7, cast=int
)
FAKE_LEAD_REPORT_MONTHLY_WINDOW_DAYS = config(
    "FAKE_LEAD_REPORT_MONTHLY_WINDOW_DAYS", default=30, cast=int
)

# A Learning Partner can ENDORSE an existing fake-lead report on one of
# their own referred students (apps.learning_partner.views.
# LPEndorseFakeReportView) - they cannot originate one from nothing, only
# add weight to a signal a real teacher already raised... except the
# distinct-teacher counts above don't actually require that ordering, so
# in practice an endorsement counts toward the SAME rolling-window totals
# as a real teacher's fake rating, at this multiplier
# (apps.trust.services.lead_quality_service.LeadQualityService.
# fake_report_stats). With the defaults above (FAKE_LEAD_AUTOBAN_WEEKLY=10,
# strict >), 2 endorsements alone (weight 10) sit exactly AT that line, not
# over it - a 3rd endorsement or a real teacher report is what actually
# tips it. Discuss with the user before changing this weight or the ">"
# comparisons above - the sensitivity is a product decision, not a default
# to silently tune.
LEARNING_PARTNER_FAKE_REPORT_WEIGHT = config(
    "LEARNING_PARTNER_FAKE_REPORT_WEIGHT", default=5, cast=int
)

# Brute-force protection on the admin/super-admin staff-login endpoints
# (apps.trust.services.staff_login_guard_service.StaffLoginGuardService).
# >= STAFF_LOGIN_BRUTEFORCE_THRESHOLD failed attempts within a rolling 24h
# window against the SAME real account auto-bans that account (a real,
# superadmin-reversible AccountSanction, same pattern as the fake-lead
# auto-ban above). The same threshold, hit by attempts against identifiers
# that don't resolve to any real account, instead blocks the source IP
# from the staff-login endpoints for STAFF_LOGIN_IP_BLOCK_MINUTES.
STAFF_LOGIN_BRUTEFORCE_THRESHOLD = config(
    "STAFF_LOGIN_BRUTEFORCE_THRESHOLD", default=10, cast=int
)
STAFF_LOGIN_IP_BLOCK_MINUTES = config(
    "STAFF_LOGIN_IP_BLOCK_MINUTES", default=60, cast=int
)

# Phase 7 - payment / transaction fraud
# One payment instrument (card fingerprint / UPI VPA) funding more than
# this many distinct teacher accounts opens a payment-risk review item.
TRUST_PAYMENT_INSTRUMENT_MAX_ACCOUNTS = config(
    "TRUST_PAYMENT_INSTRUMENT_MAX_ACCOUNTS", default=3, cast=int
)
# Failed payment attempts by one teacher within a rolling hour before a
# payment-risk signal is raised.
TRUST_PAYMENT_FAILED_BURST = config("TRUST_PAYMENT_FAILED_BURST", default=5, cast=int)
# A new order whose amount exceeds this multiple of the teacher's largest
# previous successful payment is flagged as an amount spike.
TRUST_PAYMENT_SPIKE_MULTIPLIER = config(
    "TRUST_PAYMENT_SPIKE_MULTIPLIER", default=5, cast=int
)
# New-account cooldown: for this many hours after signup a teacher's
# single-purchase value is capped and freshly bought tokens are held.
TRUST_NEW_ACCOUNT_COOLDOWN_HOURS = config(
    "TRUST_NEW_ACCOUNT_COOLDOWN_HOURS", default=24, cast=int
)
TRUST_NEW_ACCOUNT_MAX_PURCHASE = config(
    "TRUST_NEW_ACCOUNT_MAX_PURCHASE", default=2000, cast=int
)
# Phase 9 - anomaly alerts. Distinct users sharing one device fingerprint
# within 24h before a many-accounts anomaly is raised.
TRUST_ANOMALY_ACCOUNTS_PER_DEVICE = config(
    "TRUST_ANOMALY_ACCOUNTS_PER_DEVICE", default=4, cast=int
)
TRUST_NEW_ACCOUNT_COOLDOWN_HOURS = config(
    "TRUST_NEW_ACCOUNT_COOLDOWN_HOURS", default=24, cast=int
)

# ==========================================================
# LOGGING
# ==========================================================
# Delegated to a dedicated module to keep this file readable.
from config.settings.logging import LOGGING  # noqa: E402, F401

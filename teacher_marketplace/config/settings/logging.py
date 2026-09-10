"""
Logging configuration for the Teacher Marketplace Platform.

Imported directly into base.py via:
    from config.settings.logging import LOGGING

Kept in its own file (rather than inlined in base.py) because
logging configs tend to grow large and are easier to reason
about in isolation.

Docs: https://docs.djangoproject.com/en/5.0/topics/logging/
"""

from pathlib import Path

# BASE_DIR duplicated here (rather than imported from base.py) to
# avoid a circular import, since base.py imports LOGGING from this
# module. This file must stay import-independent from base.py.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": (
                "[{asctime}] {levelname} {name} "
                "({module}.{funcName}:{lineno}) - {message}"
            ),
            "style": "{",
        },
        "simple": {
            "format": "[{asctime}] {levelname} {name} - {message}",
            "style": "{",
        },
    },
    "filters": {
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file_general": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "general.log",
            "maxBytes": 1024 * 1024 * 5,  # 5 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        "file_error": {
            "level": "ERROR",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "error.log",
            "maxBytes": 1024 * 1024 * 5,  # 5 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        "mail_admins": {
            "level": "ERROR",
            "class": "django.utils.log.AdminEmailHandler",
            "filters": ["require_debug_false"],
        },
    },
    "root": {
        "handlers": ["console", "file_general"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file_general"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "file_error", "mail_admins"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console", "file_error"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",  # Set to DEBUG locally to see raw SQL
            "propagate": False,
        },
        # Namespace for all of our own apps. Each app can use
        # logging.getLogger(__name__) and it will resolve to
        # something like "apps.accounts.views" and inherit these
        # handlers via propagation.
        "apps": {
            "handlers": ["console", "file_general", "file_error"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

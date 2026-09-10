"""
WSGI config for the Teacher Marketplace Platform.

Exposes the WSGI callable as a module-level variable named
`application`. Used by Gunicorn/uWSGI in production, and by
Django's `runserver` in development.

Docs: https://docs.djangoproject.com/en/5.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings.development",
)

application = get_wsgi_application()

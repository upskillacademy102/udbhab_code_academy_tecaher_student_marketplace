"""
ASGI config for the Teacher Marketplace Platform.

Exposes the ASGI callable as a module-level variable named
`application`. Used by async servers (Uvicorn, Daphne) and
required if Django Channels is introduced later (e.g. for
real-time notifications in a future phase).

Docs: https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings.development",
)

application = get_asgi_application()

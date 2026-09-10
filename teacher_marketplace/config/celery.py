"""
Celery application configuration for the Teacher Marketplace Platform.

This is the first async task infrastructure in this project - added
specifically to support apps.matching.tasks.expire_lead_assignments,
a scheduled task that must run independently of any user request
(per the spec's explicit "Do not rely on a user opening the
application for expiration" requirement).
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("teacher_marketplace")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

"""
App configuration for the notifications app.

This app owns Notification - email + in-app notifications
triggered synchronously from apps.payments, apps.subscriptions, and
apps.lead_engine via apps.notifications.services.NotificationService.
"""

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    verbose_name = "Notifications"

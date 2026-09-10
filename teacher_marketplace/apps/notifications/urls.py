"""
URL configuration for the notifications app.

Included from config/urls.py at the `api/v1/notifications/`
prefix, so the full paths resolve to:

    GET  /api/v1/notifications/
    POST /api/v1/notifications/mark-read/
"""

from django.urls import path

from apps.notifications.views import MarkNotificationsReadView, NotificationListView

app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path("mark-read/", MarkNotificationsReadView.as_view(), name="mark-read"),
]

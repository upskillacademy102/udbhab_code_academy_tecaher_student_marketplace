"""
Views for the notifications app.

Endpoints (wired up in apps/notifications/urls.py, next file):
    GET  /api/v1/notifications/              -> NotificationListView
    POST /api/v1/notifications/mark-read/     -> MarkNotificationsReadView

Available to ANY authenticated user (not Teacher-restricted like
most of Phase 3) - the Notification model's `user` field is a
generic AUTH_USER_MODEL reference, and while every event in Phase
3's list happens to be teacher-facing today, restricting this
endpoint itself to teachers would be an unnecessary, brittle
assumption baked into the wrong layer (the endpoint should just
show "my own notifications," whoever "I" am).
"""

import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.views import APIView

from apps.core.responses import APIResponse
from apps.notifications.models import Notification
from apps.notifications.serializers import (
    MarkNotificationReadSerializer,
    NotificationSerializer,
)

logger = logging.getLogger("apps.notifications")


@extend_schema(tags=["Notifications"])
class NotificationListView(generics.ListAPIView):
    """
    GET: The authenticated user's own notifications, newest first.
    Supports ?is_read=false to fetch only unread notifications
    (common "notification bell" use case).
    """

    serializer_class = NotificationSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        queryset = Notification.objects.filter(user=self.request.user)
        is_read_param = self.request.query_params.get("is_read")
        if is_read_param is not None:
            is_read = is_read_param.lower() == "true"
            queryset = queryset.filter(is_read=is_read)
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return APIResponse.paginated(
                data=serializer.data,
                pagination_meta={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                    "unread_count": Notification.objects.filter(
                        user=request.user, is_read=False
                    ).count(),
                },
            )
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)


@extend_schema(
    tags=["Notifications"],
    request=MarkNotificationReadSerializer,
    responses={200: OpenApiResponse(description="`data`: {updated_count}.")},
)
class MarkNotificationsReadView(APIView):
    """
    POST: Marks the given notification ids as read, scoped to the
    authenticated user's own notifications only (silently ignores
    any id in the list that doesn't belong to them or doesn't
    exist, rather than erroring on partial-invalid input).
    """

    def post(self, request):
        serializer = MarkNotificationReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_count = Notification.objects.filter(
            id__in=serializer.validated_data["notification_ids"],
            user=request.user,
            is_read=False,
        ).update(is_read=True)

        logger.info(
            "%d notification(s) marked read by %s", updated_count, request.user.email
        )

        return APIResponse.success(
            message=f"{updated_count} notification(s) marked as read."
        )

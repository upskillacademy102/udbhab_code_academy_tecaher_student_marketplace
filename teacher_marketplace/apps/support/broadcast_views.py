"""
"Circulate a message" - the Support-admin side.

    GET  /api/v1/admin/broadcast-messages/   send history          (admin, superadmin; Support-department only)
    POST /api/v1/admin/broadcast-messages/   compose + send        (admin, superadmin; Support-department only)
"""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, serializers
from rest_framework.pagination import PageNumberPagination

from apps.accounts.models import User, UserRole
from apps.core.exceptions.custom_exceptions import ValidationException
from apps.core.responses import APIResponse
from apps.ops.models import AuditCategory
from apps.ops.services import AuditService
from apps.support.broadcast_service import BroadcastService
from apps.support.models import BroadcastMessage
from apps.support.serializers import BroadcastMessageSerializer


class _Pagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class _BroadcastComposeSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=5000)
    via_email = serializers.BooleanField(required=False, default=False)
    via_sms = serializers.BooleanField(required=False, default=False)
    recipient_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False
    )

    def validate(self, attrs):
        if not attrs.get("via_email") and not attrs.get("via_sms"):
            raise serializers.ValidationError(
                "Choose at least one channel: email or SMS."
            )
        return attrs


@extend_schema_view(
    get=extend_schema(
        tags=["Support"],
        summary="Support admin: circulated-message send history",
        responses=BroadcastMessageSerializer,
    ),
    post=extend_schema(
        tags=["Support"],
        summary="Support admin: circulate a message (email and/or SMS)",
        request=_BroadcastComposeSerializer,
        responses=BroadcastMessageSerializer,
    ),
)
class AdminBroadcastMessageListCreateView(generics.ListAPIView):
    serializer_class = BroadcastMessageSerializer
    pagination_class = _Pagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return BroadcastMessage.objects.none()
        return BroadcastMessage.objects.select_related("sent_by").order_by("-created_at")

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page if page is not None else qs, many=True)
        if page is not None:
            return APIResponse.paginated(
                data=serializer.data,
                pagination_meta={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                },
            )
        return APIResponse.success(data=serializer.data)

    def post(self, request, *args, **kwargs):
        serializer = _BroadcastComposeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        recipient_ids = data["recipient_ids"]
        recipients = list(
            User.objects.filter(
                id__in=recipient_ids,
                role__in=[UserRole.STUDENT, UserRole.TEACHER, UserRole.LEARNING_PARTNER],
                is_active=True,
            )
        )
        if len(recipients) != len(set(recipient_ids)):
            raise ValidationException(
                detail="One or more selected recipients aren't valid."
            )

        message = BroadcastService.send(
            request.user,
            subject=data["subject"],
            body=data["body"],
            via_email=data["via_email"],
            via_sms=data["via_sms"],
            recipients=recipients,
        )

        channels = "+".join(
            c for c, on in (("email", message.via_email), ("sms", message.via_sms)) if on
        )
        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="broadcast_message.sent",
            message=(
                f"{request.user.email} circulated '{message.subject}' to "
                f"{message.recipient_count} recipient(s) via {channels}"
            ),
        )
        return APIResponse.created(
            data=BroadcastMessageSerializer(message).data, message="Message sent."
        )

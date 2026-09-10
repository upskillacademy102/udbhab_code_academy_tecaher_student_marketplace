"""
Onboarding video call queue - who's asked for one, and Super Admin's
"assign an Admin + auto-schedule" action.

    GET  /api/v1/admin/onboarding-calls/                       queue (admin, superadmin)
    POST /api/v1/admin/onboarding-calls/{id}/schedule/          assign + schedule (superadmin only)

A teacher requesting the call (``VerificationService._request_video_interview``)
creates the ``OnboardingCallRequest`` row this reads. The actual pass/fail
verdict for the call stays on the existing per-item verify/reject endpoint
(``AdminTeacherVerificationItemView``) - this module only tracks who's
running it and when. ``{id}`` is the Teacher id, matching
``/admin/teacher-profiles/{id}/``.
"""

from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, inline_serializer
from rest_framework import generics, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.trust.models import OnboardingCallRequest


class OnboardingCallRequestSerializer(serializers.ModelSerializer):
    teacher_id = serializers.UUIDField(source="item.teacher_id", read_only=True)
    teacher_name = serializers.CharField(
        source="item.teacher.user.get_full_name", read_only=True
    )
    teacher_email = serializers.EmailField(
        source="item.teacher.user.email", read_only=True
    )
    item_status = serializers.CharField(source="item.status", read_only=True)
    assigned_admin_id = serializers.UUIDField(read_only=True, allow_null=True)
    assigned_admin_name = serializers.SerializerMethodField()
    assigned_admin_email = serializers.CharField(
        source="assigned_admin.email", read_only=True, default=""
    )

    class Meta:
        model = OnboardingCallRequest
        fields = (
            "id",
            "teacher_id",
            "teacher_name",
            "teacher_email",
            "item_status",
            "assigned_admin_id",
            "assigned_admin_name",
            "assigned_admin_email",
            "scheduled_at",
            "created_at",
        )
        read_only_fields = fields

    def get_assigned_admin_name(self, obj) -> str:
        if obj.assigned_admin:
            return obj.assigned_admin.get_full_name() or obj.assigned_admin.email
        return ""


class _Pagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema(
    tags=["Teacher Verification"],
    parameters=[
        OpenApiParameter(
            "status",
            str,
            OpenApiParameter.QUERY,
            description="Pass 'all' to include decided (verified/rejected) calls; "
            "default shows only still-open (submitted) requests.",
        ),
        OpenApiParameter(
            "mine",
            str,
            OpenApiParameter.QUERY,
            description="Pass '1' to show only calls assigned to the current user.",
        ),
    ],
    responses=OnboardingCallRequestSerializer(many=True),
)
class AdminOnboardingCallListView(generics.ListAPIView):
    serializer_class = OnboardingCallRequestSerializer
    pagination_class = _Pagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return OnboardingCallRequest.objects.none()
        qs = OnboardingCallRequest.objects.select_related(
            "item", "item__teacher", "item__teacher__user", "assigned_admin"
        )
        p = self.request.query_params
        if p.get("status") != "all":
            qs = qs.filter(item__status="submitted")
        if p.get("mine") == "1":
            qs = qs.filter(assigned_admin=self.request.user)
        return qs

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


@extend_schema(
    tags=["Teacher Verification"],
    summary="Super Admin: assign an Admin and auto-schedule the call (now + 24h)",
    request=inline_serializer(
        "OnboardingCallSchedule", {"assigned_admin_id": serializers.UUIDField()}
    ),
    responses={200: OpenApiResponse(description="`data`: the updated call request.")},
)
class AdminOnboardingCallScheduleView(APIView):
    """
    Not granted to plain Admin in apps.accounts.api_permissions - left
    unlisted so only Super Admin (the is_allowed() short-circuit) can call
    it, same idiom as the admin_users write actions.
    """

    def post(self, request, id):
        from apps.accounts.models import User, UserRole
        from apps.ops.models import AuditCategory
        from apps.ops.services import AuditService

        call = (
            OnboardingCallRequest.objects.select_related("item__teacher__user")
            .filter(item__teacher_id=id, item__key="video_interview")
            .first()
        )
        if call is None:
            raise ResourceNotFoundException(
                detail="This teacher hasn't requested an onboarding call."
            )

        admin_id = request.data.get("assigned_admin_id")
        admin_user = (
            User.objects.filter(
                id=admin_id,
                role__in=[UserRole.ADMIN, UserRole.SUPERADMIN],
                is_active=True,
            ).first()
            if admin_id
            else None
        )
        if admin_user is None:
            raise ValidationException(
                detail="Choose a valid, active Admin to assign the call to."
            )

        call.assigned_admin = admin_user
        call.scheduled_by = request.user
        call.scheduled_at = timezone.now() + timedelta(hours=24)
        call.save(
            update_fields=["assigned_admin", "scheduled_by", "scheduled_at", "updated_at"]
        )

        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="teacher.onboarding_call.scheduled",
            target=call.item.teacher.user,
            message=(
                f"{request.user.email} assigned {admin_user.email} to call "
                f"{call.item.teacher.user.email}, scheduled for {call.scheduled_at.isoformat()}"
            ),
        )
        return APIResponse.success(
            data=OnboardingCallRequestSerializer(call).data, message="Call scheduled."
        )

"""
Report & block endpoints (Phase 8d), mounted at ``/api/v1/safety/``.

    POST   /safety/report/          -> report another user
    GET    /safety/blocks/          -> my block list
    POST   /safety/blocks/          -> block a user  {user_id}
    DELETE /safety/blocks/{user_id}/ -> unblock

Reports always open a review-queue item. Blocks are always stored; they
only filter search + lead distribution while TRUST_ENABLE_USER_BLOCKING
is on.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.exceptions.custom_exceptions import ResourceNotFoundException
from apps.core.responses import APIResponse
from apps.trust.models import UserBlock, UserReportReason
from apps.trust.services.report_block_service import ReportBlockService


class _ReportSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    reason = serializers.ChoiceField(choices=UserReportReason.choices)
    detail = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class _BlockSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()


def _get_user_or_404(user_id):
    u = User.objects.filter(id=user_id, is_active=True).first()
    if u is None:
        raise ResourceNotFoundException(detail="User not found.")
    return u


@extend_schema(tags=["Safety"])
class ReportUserView(APIView):
    @extend_schema(
        request=_ReportSerializer,
        responses={201: OpenApiResponse(description="Report filed.")},
    )
    def post(self, request):
        s = _ReportSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        reported = _get_user_or_404(s.validated_data["user_id"])
        ReportBlockService.report_user(
            reporter=request.user,
            reported=reported,
            reason=s.validated_data["reason"],
            detail=s.validated_data.get("detail", ""),
            request=request,
        )
        return APIResponse.created(
            data=None, message="Thanks - our team will review this report."
        )


@extend_schema(tags=["Safety"])
class BlockListView(APIView):
    @extend_schema(
        responses={200: OpenApiResponse(description="`data`: blocked user ids.")}
    )
    def get(self, request):
        rows = UserBlock.objects.filter(blocker=request.user).select_related("blocked")
        return APIResponse.success(
            data=[
                {
                    "user_id": str(b.blocked_id),
                    "email": b.blocked.email,
                    "since": b.created_at,
                }
                for b in rows
            ]
        )

    @extend_schema(
        request=_BlockSerializer,
        responses={201: OpenApiResponse(description="User blocked.")},
    )
    def post(self, request):
        s = _BlockSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        blocked = _get_user_or_404(s.validated_data["user_id"])
        ReportBlockService.block_user(
            blocker=request.user, blocked=blocked, request=request
        )
        return APIResponse.created(data=None, message="User blocked.")


@extend_schema(tags=["Safety"], responses={204: None})
class BlockDetailView(APIView):
    def delete(self, request, user_id):
        # Unblock by id directly - don't 404 if the target was deactivated
        # in the meantime; the block row is the only thing that matters.
        ReportBlockService.unblock_user(blocker=request.user, blocked_id=user_id)
        return APIResponse.no_content(message="User unblocked.")

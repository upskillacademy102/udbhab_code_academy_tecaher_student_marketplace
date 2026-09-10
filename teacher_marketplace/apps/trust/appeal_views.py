"""
Suspension-appeal endpoints (mounted at ``/api/v1/appeals/``).

    GET  /appeals/suspension/           -> my suspension + appeal status
    POST /appeals/suspension/           -> file an appeal {message, contact_email?}
    POST /appeals/suspension/withdraw/  -> withdraw my open appeal

Any authenticated role may act on their own account. ``GET`` always
works so the ``/suspended/`` page can render the right state; filing an
appeal needs the account to actually be suspended and
``TRUST_ENABLE_SUSPENSION_APPEALS`` on (enforced in the service).
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.views import APIView

from apps.core.responses import APIResponse
from apps.trust.serializers import SuspensionAppealCreateSerializer
from apps.trust.services.appeal_service import AppealService


@extend_schema(tags=["Appeals"])
class SuspensionAppealView(APIView):
    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                description="`data`: {suspended, appeals_enabled, can_appeal, "
                "support_email, appeal}."
            )
        },
    )
    def get(self, request):
        return APIResponse.success(data=AppealService.status_for(request.user))

    @extend_schema(
        request=SuspensionAppealCreateSerializer,
        responses={201: OpenApiResponse(description="Appeal filed.")},
    )
    def post(self, request):
        s = SuspensionAppealCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        AppealService.submit(
            request.user,
            message=s.validated_data["message"],
            contact_email=s.validated_data.get("contact_email", ""),
            request=request,
        )
        return APIResponse.created(
            data=AppealService.status_for(request.user),
            message="Thanks - our team will review your account.",
        )


@extend_schema(
    tags=["Appeals"],
    request=None,
    responses={200: OpenApiResponse(description="Appeal withdrawn (if one was open).")},
)
class SuspensionAppealWithdrawView(APIView):
    def post(self, request):
        AppealService.withdraw(request.user, request=request)
        return APIResponse.success(
            data=AppealService.status_for(request.user),
            message="Appeal withdrawn.",
        )

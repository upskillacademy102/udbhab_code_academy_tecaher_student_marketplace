"""
Contact-verification endpoints (mounted at ``/api/v1/verify/``).

    POST /verify/email/request/    -> email an OTP to the caller
    POST /verify/email/confirm/    -> {code} -> mark email verified
    POST /verify/mobile/request/   -> SMS an OTP to the caller
    POST /verify/mobile/confirm/   -> {code} -> mark mobile verified
    GET  /verify/status/           -> current verification state

Every authenticated role may verify their own contacts. The codes are
short-lived, single-use, attempt-capped (OTPService) and rate-limited
(OTPRequestThrottle).
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.views import APIView

from apps.core.responses import APIResponse
from apps.core.throttling import OTPRequestThrottle
from apps.trust.models import OTPChannel
from apps.trust.serializers import OTPConfirmSerializer
from apps.trust.services.otp_service import OTPService
from apps.trust.services.trust_service import TrustService

_CODE_SENT = {200: OpenApiResponse(description="Code sent (or silently rate-limited).")}
_VERIFIED = {
    200: OpenApiResponse(description="`data`: the updated verification status.")
}
_STATUS = {
    200: OpenApiResponse(
        description="`data`: {email_verified, mobile_verified, verification_score, is_fully_verified}."
    )
}


def _status_payload(user) -> dict:
    profile = TrustService.get_or_create_profile(user)
    return {
        "email_verified": user.is_email_verified,
        "mobile_verified": user.is_mobile_verified,
        "verification_score": str(profile.verification_score),
        "is_fully_verified": profile.is_fully_verified,
    }


@extend_schema(
    tags=["Verification"],
    summary="My contact-verification status",
    request=None,
    responses=_STATUS,
)
class VerificationStatusView(APIView):
    def get(self, request):
        return APIResponse.success(data=_status_payload(request.user))


class _OTPRequestView(APIView):
    """Base: POST issues a fresh code for ``otp_channel``."""

    otp_channel = None
    throttle_classes = [OTPRequestThrottle]

    def post(self, request):
        OTPService.issue(request.user, channel=self.otp_channel)
        return APIResponse.success(message="Verification code sent.")


class _OTPConfirmView(APIView):
    """Base: POST {code} verifies ``otp_channel``."""

    otp_channel = None

    def post(self, request):
        serializer = OTPConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        OTPService.verify(
            request.user,
            channel=self.otp_channel,
            code=serializer.validated_data["code"],
        )
        return APIResponse.success(
            message="Verified.", data=_status_payload(request.user)
        )


@extend_schema(
    tags=["Verification"],
    summary="Send an email verification code",
    request=None,
    responses=_CODE_SENT,
)
class EmailOTPRequestView(_OTPRequestView):
    otp_channel = OTPChannel.EMAIL


@extend_schema(
    tags=["Verification"],
    summary="Confirm the email verification code",
    request=OTPConfirmSerializer,
    responses=_VERIFIED,
)
class EmailOTPConfirmView(_OTPConfirmView):
    otp_channel = OTPChannel.EMAIL


@extend_schema(
    tags=["Verification"],
    summary="Send an SMS verification code",
    request=None,
    responses=_CODE_SENT,
)
class MobileOTPRequestView(_OTPRequestView):
    otp_channel = OTPChannel.SMS


@extend_schema(
    tags=["Verification"],
    summary="Confirm the SMS verification code",
    request=OTPConfirmSerializer,
    responses=_VERIFIED,
)
class MobileOTPConfirmView(_OTPConfirmView):
    otp_channel = OTPChannel.SMS

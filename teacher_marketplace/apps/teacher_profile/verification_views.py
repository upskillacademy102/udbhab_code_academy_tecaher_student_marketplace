"""
Teacher-facing verification checklist.

    GET  /api/v1/teachers/profile/verification/               progress + items
    POST /api/v1/teachers/profile/verification/{key}/submit/  submit a reviewed item

Reviewed items (``gov_id``, ``selfie_liveness``, ``address_proof``) route
to the configured verification provider; in development they land in the
manual review queue. ``video_interview`` and ``bank_penny_drop`` are not
teacher-submittable here.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.trust.services.verification_service import VerificationService
from apps.utils.validators import validate_image_upload

#: For each reviewed key that takes an uploaded photo, the required
#: multipart field name(s). video_interview needs none (it's a plain
#: "request a call" action); bank_penny_drop isn't submittable at all.
_REQUIRED_FILES = {
    "gov_id": ("front", "back"),
    "address_proof": ("document",),
    "selfie_liveness": ("center", "left", "right", "up", "down"),
}


def _teacher_or_404(request):
    teacher = getattr(request.user, "teacher_profile", None)  # -> apps.teachers.Teacher
    if teacher is None:
        raise ResourceNotFoundException(
            detail="Create your basic Teacher profile first (POST /api/v1/teachers/me/)."
        )
    return teacher


@extend_schema(
    tags=["Teacher Verification"],
    summary="My verification checklist, progress score, and badge",
    request=None,
    responses={
        200: OpenApiResponse(
            description="`data`: {verification_score, progress_percent, is_fully_verified, floor_met, items[]}."
        )
    },
)
class TeacherVerificationView(APIView):
    def get(self, request):
        return APIResponse.success(
            data=VerificationService.snapshot(_teacher_or_404(request))
        )


@extend_schema(
    tags=["Teacher Verification"],
    summary="Submit a reviewed verification item",
    description=(
        "gov_id: multipart 'front' + 'back' photo files. address_proof: "
        "multipart 'document' photo file. selfie_liveness: multipart "
        "'center'/'left'/'right'/'up'/'down' photo files (the guided face-"
        "scan capture). video_interview: empty body - requests a callback."
    ),
    request=inline_serializer(
        "VerificationItemSubmit",
        {
            "full_name": serializers.CharField(required=False),
            "date_of_birth": serializers.DateField(required=False),
            "document_type": serializers.CharField(required=False),
            "front": serializers.ImageField(required=False),
            "back": serializers.ImageField(required=False),
            "document": serializers.ImageField(required=False),
            "center": serializers.ImageField(required=False),
            "left": serializers.ImageField(required=False),
            "right": serializers.ImageField(required=False),
            "up": serializers.ImageField(required=False),
            "down": serializers.ImageField(required=False),
        },
    ),
    responses={
        200: OpenApiResponse(description="`data`: the updated checklist snapshot.")
    },
)
class TeacherVerificationSubmitView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, key):
        teacher = _teacher_or_404(request)

        files = None
        required = _REQUIRED_FILES.get(key)
        if required:
            missing = [name for name in required if name not in request.FILES]
            if missing:
                raise ValidationException(
                    detail=f"Attach a photo for: {', '.join(missing)}."
                )
            files = {name: request.FILES[name] for name in required}
            for name, f in files.items():
                try:
                    validate_image_upload(f)
                except DjangoValidationError as e:
                    raise ValidationException(
                        detail=f"{name}: {'; '.join(e.messages)}"
                    ) from e

        VerificationService.submit_reviewed_item(
            teacher, key, payload=request.data, files=files
        )
        return APIResponse.success(
            data=VerificationService.snapshot(teacher),
            message="Submitted.",
        )

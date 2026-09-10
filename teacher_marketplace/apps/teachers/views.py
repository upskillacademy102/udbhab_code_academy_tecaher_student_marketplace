"""
Views for the teachers app.

Endpoints (wired up in apps/teachers/urls.py, next file):
    GET/POST/PUT/PATCH /api/v1/teachers/me/       -> TeacherProfileView
    GET                /api/v1/teachers/            -> TeacherListView
    GET                /api/v1/teachers/{id}/       -> TeacherDetailView

Phase 1 scope note: TeacherListView/TeacherDetailView provide plain
listing/retrieval only. This is the "students search teachers for
FREE" browsing surface from the project brief - note that at this
phase, the full Teacher profile (including whatever contact-
adjacent fields might exist) is returned as-is, because token-
gated contact-detail unlocking is explicit later-phase business
logic. Phase 1 has no separate "contact details" field on Teacher
at all (see apps/teachers/models.py), so there is nothing to gate
yet regardless.
"""

import logging

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import generics
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.teachers.models import Teacher
from apps.teachers.serializers import TeacherCreateUpdateSerializer, TeacherSerializer

logger = logging.getLogger("apps.teachers")


# ==========================================================
# MY PROFILE (authenticated teacher manages their own profile)
# ==========================================================
@extend_schema(tags=["Teachers"], responses=TeacherSerializer)
class TeacherProfileView(APIView):
    """
    Lets the authenticated Teacher view, create, or update their
    own Teacher profile. Only one Teacher profile per User exists
    (enforced by the OneToOneField on the model), so POST here
    behaves as "create if not exists" rather than allowing
    duplicates - mirrors StudentProfileView's semantics exactly.
    """

    def get_object(self):
        return Teacher.objects.filter(user=self.request.user).first()

    @extend_schema(summary="Get my teacher profile")
    def get(self, request):
        teacher = self.get_object()
        if teacher is None:
            raise ResourceNotFoundException(
                detail="Teacher profile not found. Create one first."
            )
        return APIResponse.success(data=TeacherSerializer(teacher).data)

    @extend_schema(
        summary="Create or update my teacher profile (upsert)",
        request=TeacherCreateUpdateSerializer,
    )
    def post(self, request):
        # Upsert: there is exactly one Teacher per user, so a POST when
        # one already exists applies the submitted data as a partial
        # update rather than silently discarding it. This keeps the
        # frontend correct even when the Teacher row was provisioned as
        # a side effect elsewhere (e.g. first visit to the marketplace
        # profile page).
        existing = self.get_object()
        serializer = TeacherCreateUpdateSerializer(
            existing, data=request.data, partial=existing is not None
        )
        serializer.is_valid(raise_exception=True)
        teacher = (
            serializer.save()
            if existing is not None
            else serializer.save(user=request.user)
        )

        from apps.trust.services.content_scan_service import ContentScanService
        from apps.trust.services.verification_service import recompute_for_user

        ContentScanService.scan_teacher(teacher)
        recompute_for_user(request.user)  # profile_basics may have just flipped

        logger.info(
            "Teacher profile %s for user: %s",
            "updated" if existing is not None else "created",
            request.user.email,
        )

        return APIResponse.success(
            data=TeacherSerializer(teacher).data,
            message="Teacher profile saved.",
            http_status=(
                status.HTTP_200_OK if existing is not None else status.HTTP_201_CREATED
            ),
        )

    @extend_schema(
        summary="Update my teacher profile",
        request=TeacherCreateUpdateSerializer,
    )
    def put(self, request):
        return self._update(request, partial=False)

    @extend_schema(
        summary="Partially update my teacher profile",
        request=TeacherCreateUpdateSerializer,
    )
    def patch(self, request):
        return self._update(request, partial=True)

    def _update(self, request, partial: bool):
        teacher = self.get_object()
        if teacher is None:
            raise ResourceNotFoundException(
                detail="Teacher profile not found. Create one first."
            )

        serializer = TeacherCreateUpdateSerializer(
            teacher, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        from apps.trust.services.content_scan_service import ContentScanService
        from apps.trust.services.verification_service import recompute_for_user

        ContentScanService.scan_teacher(teacher)
        recompute_for_user(request.user)

        logger.info("Teacher profile updated for user: %s", request.user.email)

        return APIResponse.success(
            data=TeacherSerializer(teacher).data,
            message="Teacher profile updated successfully.",
        )


# ==========================================================
# LIST / DETAIL (students browse teachers for FREE)
# ==========================================================
@extend_schema(tags=["Teachers"], summary="List teacher profiles")
class TeacherListView(generics.ListAPIView):
    """
    Plain list endpoint for Teacher profiles - this is the "students
    search teachers for free" surface from the project brief. No
    payment, no token gating: any authenticated user (Student,
    Teacher, Admin) can freely browse this list in Phase 1, matching
    "Students never pay" and "search for FREE" from the project spec.
    """

    queryset = Teacher.objects.select_related("user").all()
    serializer_class = TeacherSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["city", "state", "country", "qualification_level"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)


@extend_schema(tags=["Teachers"], summary="Retrieve a single teacher profile")
class TeacherDetailView(generics.RetrieveAPIView):
    """
    Plain retrieve-by-id endpoint for a single Teacher profile -
    freely viewable, consistent with "students search for free."
    """

    queryset = Teacher.objects.select_related("user").all()
    serializer_class = TeacherSerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)


@extend_schema(
    tags=["Teachers"],
    request=inline_serializer(
        "MyPincodeRequest", {"pincode": drf_serializers.CharField()}
    ),
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Resolved {pincode, city, state, country}.",
        )
    },
)
class MyPincodeView(APIView):
    """
    PATCH: Sets the authenticated teacher's pincode_location, used
    by apps.matching's offline distance matching. Geocodes the
    pincode via PincodeGeocodingService if it hasn't been seen
    before - the teacher only ever provides the pincode string
    itself, never coordinates directly.
    """

    def patch(self, request):
        from apps.matching.services.geocoding_service import PincodeGeocodingService

        teacher = getattr(request.user, "teacher_profile", None)
        if teacher is None:
            raise ResourceNotFoundException(
                detail="You must create your basic Teacher profile first (POST /api/v1/teachers/me/)."
            )

        pincode = request.data.get("pincode")
        if not pincode:
            raise ValidationException(detail="pincode is required.")

        pincode_location = PincodeGeocodingService.get_or_geocode(pincode)
        teacher.pincode_location = pincode_location
        teacher.save(update_fields=["pincode_location"])

        logger.info("Teacher %s set pincode: %s", request.user.email, pincode)

        return APIResponse.success(
            data={
                "pincode": pincode_location.pincode,
                "city": pincode_location.city,
                "state": pincode_location.state,
                "country": pincode_location.country,
            },
            message="Pincode updated successfully.",
        )

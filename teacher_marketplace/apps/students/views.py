"""
Views for the students app.

Endpoints (wired up in apps/students/urls.py, next file):
    GET/POST/PUT/PATCH /api/v1/students/me/       -> StudentProfileView
    GET                /api/v1/students/            -> StudentListView
    GET                /api/v1/students/{id}/       -> StudentDetailView

Phase 1 scope note: StudentListView/StudentDetailView provide
plain, unfiltered-by-business-rules listing and retrieval only.
Actual search/matching (e.g. "find students needing my subject
near me") is explicit business logic reserved for a later phase.
"""

import logging

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import ResourceNotFoundException
from apps.core.responses import APIResponse
from apps.students.models import Student
from apps.students.serializers import StudentCreateUpdateSerializer, StudentSerializer

logger = logging.getLogger("apps.students")


# ==========================================================
# MY PROFILE (authenticated student manages their own profile)
# ==========================================================
@extend_schema(tags=["Students"], responses=StudentSerializer)
class StudentProfileView(APIView):
    """
    Lets the authenticated Student view, create, or update their
    own Student profile. Only one Student profile per User exists
    (enforced by the OneToOneField on the model), so POST here
    behaves as "create if not exists" rather than allowing
    duplicates.
    """

    def get_object(self):
        return Student.objects.filter(user=self.request.user).first()

    @extend_schema(summary="Get my student profile")
    def get(self, request):
        student = self.get_object()
        if student is None:
            raise ResourceNotFoundException(
                detail="Student profile not found. Create one first."
            )
        return APIResponse.success(data=StudentSerializer(student).data)

    @extend_schema(
        summary="Create my student profile",
        request=StudentCreateUpdateSerializer,
    )
    def post(self, request):
        if self.get_object() is not None:
            return APIResponse.success(
                data=StudentSerializer(self.get_object()).data,
                message="Student profile already exists.",
                http_status=status.HTTP_200_OK,
            )

        serializer = StudentCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = serializer.save(user=request.user)

        logger.info("Student profile created for user: %s", request.user.email)

        return APIResponse.created(
            data=StudentSerializer(student).data,
            message="Student profile created successfully.",
        )

    @extend_schema(
        summary="Update my student profile",
        request=StudentCreateUpdateSerializer,
    )
    def put(self, request):
        return self._update(request, partial=False)

    @extend_schema(
        summary="Partially update my student profile",
        request=StudentCreateUpdateSerializer,
    )
    def patch(self, request):
        return self._update(request, partial=True)

    def _update(self, request, partial: bool):
        student = self.get_object()
        if student is None:
            raise ResourceNotFoundException(
                detail="Student profile not found. Create one first."
            )

        serializer = StudentCreateUpdateSerializer(
            student, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        logger.info("Student profile updated for user: %s", request.user.email)

        return APIResponse.success(
            data=StudentSerializer(student).data,
            message="Student profile updated successfully.",
        )


# ==========================================================
# LIST / DETAIL (basic browsing, no matching logic)
# ==========================================================
@extend_schema(tags=["Students"], summary="List student profiles")
class StudentListView(generics.ListAPIView):
    """
    Plain list endpoint for Student profiles. Uses DjangoFilterBackend
    (already configured project-wide in REST_FRAMEWORK settings) with
    a minimal, non-business filterset - just exact-match filtering on
    a couple of descriptive fields. No relevance ranking, no lead-
    matching, no visibility restrictions beyond authentication.
    """

    queryset = Student.objects.select_related("user").all()
    serializer_class = StudentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["city", "state", "country", "education_level"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)


@extend_schema(tags=["Students"], summary="Retrieve a single student profile")
class StudentDetailView(generics.RetrieveAPIView):
    """
    Plain retrieve-by-id endpoint for a single Student profile.
    """

    queryset = Student.objects.select_related("user").all()
    serializer_class = StudentSerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

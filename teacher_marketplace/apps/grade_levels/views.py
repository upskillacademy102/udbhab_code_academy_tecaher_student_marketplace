"""
Views for the grade_levels app.

    GET    /api/v1/grade-levels/          -> GradeLevelListCreateView (list)
    POST   /api/v1/grade-levels/          -> GradeLevelListCreateView (create, admin only)
    GET    /api/v1/grade-levels/{id}/      -> GradeLevelDetailView (retrieve)
    PUT    /api/v1/grade-levels/{id}/      -> GradeLevelDetailView (update, admin only)
    PATCH  /api/v1/grade-levels/{id}/      -> GradeLevelDetailView (partial update, admin only)
    DELETE /api/v1/grade-levels/{id}/      -> GradeLevelDetailView (soft delete, admin only)
"""

import logging

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.filters import SearchFilter

from apps.core.responses import APIResponse
from apps.grade_levels.models import GradeLevel
from apps.grade_levels.serializers import GradeLevelSerializer

logger = logging.getLogger("apps.grade_levels")


@extend_schema(tags=["Grade Levels"])
class GradeLevelListCreateView(generics.ListCreateAPIView):
    """
    GET: List all active, non-deleted grade levels.
    POST: Create a new grade level (Admin/SuperAdmin only).
    """

    queryset = GradeLevel.objects.all()
    serializer_class = GradeLevelSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["is_active"]
    search_fields = ["name"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grade_level = serializer.save()

        logger.info(
            "Grade level created: %s (by %s)", grade_level.name, request.user.email
        )

        return APIResponse.created(
            data=GradeLevelSerializer(grade_level).data,
            message="Grade level created successfully.",
        )


@extend_schema(tags=["Grade Levels"])
class GradeLevelDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET: Retrieve a single grade level.
    PUT/PATCH: Update a grade level (Admin/SuperAdmin only).
    DELETE: Soft-delete a grade level (Admin/SuperAdmin only).
    """

    queryset = GradeLevel.objects.all()
    serializer_class = GradeLevelSerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        grade_level = serializer.save()

        logger.info(
            "Grade level updated: %s (by %s)", grade_level.name, request.user.email
        )

        return APIResponse.success(
            data=GradeLevelSerializer(grade_level).data,
            message="Grade level updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        name = instance.name
        instance.delete()  # soft-delete, per SoftDeleteModel.delete()

        logger.info("Grade level soft-deleted: %s (by %s)", name, request.user.email)

        return APIResponse.no_content(message="Grade level deleted successfully.")

"""
Views for the subjects app.

Endpoints (wired up in apps/subjects/urls.py, next file):
    GET    /api/v1/subjects/          -> SubjectListCreateView (list)
    POST   /api/v1/subjects/          -> SubjectListCreateView (create, admin only)
    GET    /api/v1/subjects/{id}/      -> SubjectDetailView (retrieve)
    PUT    /api/v1/subjects/{id}/      -> SubjectDetailView (update, admin only)
    PATCH  /api/v1/subjects/{id}/      -> SubjectDetailView (partial update, admin only)
    DELETE /api/v1/subjects/{id}/      -> SubjectDetailView (soft delete, admin only)

Design note: List/Retrieve are public (AllowAny) - subject taxonomy
is needed by unauthenticated clients too (e.g. populating a
registration form's subject dropdown, or a public search page).
Only mutations require Admin/SuperAdmin role.
"""

import logging

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.filters import SearchFilter

from apps.core.responses import APIResponse
from apps.subjects.models import Subject
from apps.subjects.serializers import SubjectSerializer

logger = logging.getLogger("apps.subjects")


@extend_schema(tags=["Subjects"])
class SubjectListCreateView(generics.ListCreateAPIView):
    """
    GET: List all active, non-deleted subjects (public).
    POST: Create a new subject (Admin/SuperAdmin only).
    """

    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["is_active"]
    search_fields = ["name", "description"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subject = serializer.save()

        logger.info("Subject created: %s (by %s)", subject.name, request.user.email)

        return APIResponse.created(
            data=SubjectSerializer(subject).data,
            message="Subject created successfully.",
        )


@extend_schema(tags=["Subjects"])
class SubjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET: Retrieve a single subject (public).
    PUT/PATCH: Update a subject (Admin/SuperAdmin only).
    DELETE: Soft-delete a subject (Admin/SuperAdmin only).
    """

    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        subject = serializer.save()

        logger.info("Subject updated: %s (by %s)", subject.name, request.user.email)

        return APIResponse.success(
            data=SubjectSerializer(subject).data,
            message="Subject updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        subject_name = instance.name
        instance.delete()  # soft-delete, per SoftDeleteModel.delete()

        logger.info(
            "Subject soft-deleted: %s (by %s)", subject_name, request.user.email
        )

        return APIResponse.no_content(message="Subject deleted successfully.")

"""
Views for the languages app.

Endpoints (wired up in apps/languages/urls.py, next file):
    GET    /api/v1/languages/          -> LanguageListCreateView (list)
    POST   /api/v1/languages/          -> LanguageListCreateView (create, admin only)
    GET    /api/v1/languages/{id}/      -> LanguageDetailView (retrieve)
    PUT    /api/v1/languages/{id}/      -> LanguageDetailView (update, admin only)
    PATCH  /api/v1/languages/{id}/      -> LanguageDetailView (partial update, admin only)
    DELETE /api/v1/languages/{id}/      -> LanguageDetailView (soft delete, admin only)
"""

import logging

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.filters import SearchFilter

from apps.core.responses import APIResponse
from apps.languages.models import Language
from apps.languages.serializers import LanguageSerializer

logger = logging.getLogger("apps.languages")


@extend_schema(tags=["Languages"])
class LanguageListCreateView(generics.ListCreateAPIView):
    """
    GET: List all active, non-deleted languages (public).
    POST: Create a new language (Admin/SuperAdmin only).
    """

    queryset = Language.objects.all()
    serializer_class = LanguageSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["is_active"]
    search_fields = ["name", "code"]
    # Language is a small, admin-curated reference table (dozens of rows,
    # not thousands) driving a picker that needs every option at once -
    # the project-wide DEFAULT_PAGINATION_CLASS (PAGE_SIZE=20) would
    # silently truncate it, so it's opted out here rather than weakened
    # globally for the genuinely large, user-generated endpoints.
    pagination_class = None

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        language = serializer.save()

        logger.info("Language created: %s (by %s)", language.name, request.user.email)

        return APIResponse.created(
            data=LanguageSerializer(language).data,
            message="Language created successfully.",
        )


@extend_schema(tags=["Languages"])
class LanguageDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET: Retrieve a single language (public).
    PUT/PATCH: Update a language (Admin/SuperAdmin only).
    DELETE: Soft-delete a language (Admin/SuperAdmin only).
    """

    queryset = Language.objects.all()
    serializer_class = LanguageSerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        language = serializer.save()

        logger.info("Language updated: %s (by %s)", language.name, request.user.email)

        return APIResponse.success(
            data=LanguageSerializer(language).data,
            message="Language updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        language_name = instance.name
        instance.delete()  # soft-delete, per SoftDeleteModel.delete()

        logger.info(
            "Language soft-deleted: %s (by %s)", language_name, request.user.email
        )

        return APIResponse.no_content(message="Language deleted successfully.")

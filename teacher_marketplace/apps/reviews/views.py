"""
Views for the reviews app (Phase 8c).

    GET  /api/v1/reviews/                 -> my reviews (student)
    POST /api/v1/reviews/                 -> create a review (student)
    DELETE /api/v1/reviews/{id}/          -> withdraw my review (author)
    GET  /api/v1/teachers/{id}/reviews/    -> a teacher's published reviews

All endpoints refuse to operate unless TRUST_ENABLE_REVIEW_SYSTEM is on.
"""

import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.reviews.models import Review, ReviewStatus
from apps.reviews.serializers import ReviewSerializer, ReviewWriteSerializer
from apps.reviews.services import ReviewIntegrityService, enabled
from apps.teachers.models import Teacher

logger = logging.getLogger("apps.reviews")


def _require_enabled():
    if not enabled():
        raise ResourceNotFoundException(detail="Reviews are not available.")


@extend_schema(tags=["Reviews"])
class MyReviewsView(APIView):
    @extend_schema(responses=ReviewSerializer(many=True))
    def get(self, request):
        _require_enabled()
        qs = Review.objects.filter(author=request.user).select_related("teacher")
        return APIResponse.success(data=ReviewSerializer(qs, many=True).data)

    @extend_schema(
        request=ReviewWriteSerializer,
        responses={201: ReviewSerializer},
        summary="Create a review for a teacher you had a lead with",
    )
    def post(self, request):
        _require_enabled()
        s = ReviewWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        try:
            teacher = Teacher.objects.select_related("user").get(id=data["teacher_id"])
        except Teacher.DoesNotExist:
            raise ResourceNotFoundException(detail="Teacher not found.")

        source_lead = None
        if data.get("lead_id"):
            from apps.lead_engine.models import Lead

            source_lead = Lead.objects.filter(id=data["lead_id"]).first()
            if source_lead is None:
                raise ValidationException(detail="Lead not found.")

        from apps.trust.fingerprint import client_fingerprint

        review = ReviewIntegrityService.create_review(
            author=request.user,
            teacher=teacher,
            rating=data["rating"],
            text=data.get("text", ""),
            source_lead=source_lead,
            fingerprint=client_fingerprint(request),
        )
        return APIResponse.created(
            data=ReviewSerializer(review).data,
            message="Thanks for your review.",
        )


@extend_schema(tags=["Reviews"], responses={204: None})
class ReviewDetailView(APIView):
    def delete(self, request, id):
        _require_enabled()
        review = Review.objects.filter(id=id, author=request.user).first()
        if review is None:
            raise ResourceNotFoundException(detail="Review not found.")
        teacher = review.teacher
        review.delete()
        ReviewIntegrityService.recompute_teacher_rating(teacher)
        return APIResponse.no_content(message="Review withdrawn.")


@extend_schema(
    tags=["Reviews"],
    responses={200: OpenApiResponse(description="Published reviews + rating summary.")},
)
class TeacherReviewsView(APIView):
    def get(self, request, id):
        _require_enabled()
        teacher = Teacher.objects.filter(id=id).first()
        if teacher is None:
            raise ResourceNotFoundException(detail="Teacher not found.")
        qs = Review.objects.filter(
            teacher=teacher, status=ReviewStatus.PUBLISHED
        ).select_related("author")
        return APIResponse.success(
            data={
                "count": qs.count(),
                "average_rating": str(ReviewIntegrityService.average_rating(teacher)),
                "results": ReviewSerializer(qs, many=True).data,
            }
        )

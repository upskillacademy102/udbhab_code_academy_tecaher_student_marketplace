"""
ReviewIntegrityService (Phase 8c).

Enforces the review-integrity rules and keeps ``TeacherProfile.rating`` in
sync with PUBLISHED reviews. Everything is gated on
``TRUST_ENABLE_REVIEW_SYSTEM`` - the endpoints refuse to operate when it's
off, and ``recompute_teacher_rating`` is a no-op, so the rating field stays
admin-managed exactly as before.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone

from apps.core.exceptions.custom_exceptions import (
    PermissionDeniedException,
    ValidationException,
)
from apps.reviews.models import Review, ReviewStatus

logger = logging.getLogger("apps.reviews")

_RING_WINDOW = timedelta(hours=24)
_RING_FINGERPRINT_MAX = 3  # reviews from one client fingerprint in the window
_RING_VELOCITY_MAX = 5  # 5-star reviews a teacher gets in the window


def enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_REVIEW_SYSTEM", False))


def _require_enabled():
    if not enabled():
        raise PermissionDeniedException(
            detail="The review system is not currently available."
        )


class ReviewIntegrityService:
    @staticmethod
    def eligible_leads(author, teacher):
        """
        Leads that establish a real author<->teacher relationship: the
        teacher unlocked one of the author's leads, or accepted its
        assignment.
        """
        from apps.lead_engine.models import Lead, LeadUnlockHistory
        from apps.matching.models import AssignmentStatus, LeadAssignment

        unlocked_lead_ids = LeadUnlockHistory.objects.filter(
            teacher=teacher,
            lead__student_requirement__student=author,
        ).values_list("lead_id", flat=True)

        accepted_lead_ids = LeadAssignment.objects.filter(
            teacher=teacher,
            status=AssignmentStatus.ACCEPTED,
            lead__student_requirement__student=author,
        ).values_list("lead_id", flat=True)

        ids = set(unlocked_lead_ids) | set(accepted_lead_ids)
        return Lead.objects.filter(id__in=ids)

    @staticmethod
    def can_review(author, teacher) -> bool:
        if not enabled():
            return False
        if getattr(teacher, "user_id", None) == getattr(author, "id", None):
            return False
        return ReviewIntegrityService.eligible_leads(author, teacher).exists()

    @staticmethod
    @transaction.atomic
    def create_review(
        *,
        author,
        teacher,
        rating: int,
        text: str = "",
        source_lead=None,
        fingerprint: str = "",
    ) -> Review:
        _require_enabled()

        from apps.trust.services.risk_service import RiskService

        if RiskService.is_suspended(author):
            raise PermissionDeniedException(
                detail="Your account is temporarily suspended and cannot post reviews."
            )

        if not (1 <= int(rating) <= 5):
            raise ValidationException(detail="Rating must be between 1 and 5.")
        if teacher.user_id == author.id:
            raise ValidationException(detail="You cannot review yourself.")

        eligible = ReviewIntegrityService.eligible_leads(author, teacher)
        if source_lead is not None:
            if not eligible.filter(pk=source_lead.pk).exists():
                raise ValidationException(
                    detail="That lead does not connect you with this teacher."
                )
            lead = source_lead
        else:
            lead = eligible.order_by("created_at").first()
            if lead is None:
                raise ValidationException(
                    detail=(
                        "You can only review a teacher after they have taken up "
                        "one of your leads."
                    )
                )

        if Review.objects.filter(author=author, source_lead=lead).exists():
            raise ValidationException(
                detail="You have already reviewed this teacher for this lead."
            )

        status = ReviewStatus.PUBLISHED
        flag_reason = ""

        # Content scan on the review text (Phase 8a).
        from apps.trust.services.content_scan_service import ContentScanService

        cats = ContentScanService.flag_text(
            user=author, surface="review.text", text=text or "", priority=3
        )
        if cats:
            status = ReviewStatus.FLAGGED
            flag_reason = f"Content: {', '.join(cats)}"

        review = Review.objects.create(
            author=author,
            teacher=teacher,
            source_lead=lead,
            rating=int(rating),
            text=(text or "").strip()[:2000],
            status=status,
            flag_reason=flag_reason,
            author_fingerprint=(fingerprint or "")[:64],
        )

        ReviewIntegrityService._detect_ring(review)
        ReviewIntegrityService.recompute_teacher_rating(teacher)
        logger.info(
            "review created: author=%s teacher=%s rating=%d status=%s",
            author.email,
            teacher.id,
            review.rating,
            review.status,
        )
        return review

    @staticmethod
    def _detect_ring(review: Review) -> None:
        since = timezone.now() - _RING_WINDOW
        reasons = []

        if review.author_fingerprint:
            fp_count = Review.objects.filter(
                author_fingerprint=review.author_fingerprint, created_at__gte=since
            ).count()
            if fp_count >= _RING_FINGERPRINT_MAX:
                reasons.append(f"{fp_count} reviews from one device in 24h")

        burst = Review.objects.filter(
            teacher=review.teacher, rating__gte=5, created_at__gte=since
        ).count()
        if burst >= _RING_VELOCITY_MAX:
            reasons.append(f"{burst} 5-star reviews for this teacher in 24h")

        if not reasons:
            return

        Review.objects.filter(pk=review.pk).update(
            status=ReviewStatus.FLAGGED,
            flag_reason=(review.flag_reason + "; " if review.flag_reason else "")
            + "; ".join(reasons),
        )
        review.status = ReviewStatus.FLAGGED
        try:
            from apps.trust.models import ManualReviewKind, RiskSignalKind
            from apps.trust.services.risk_service import RiskService
            from apps.trust.services.trust_service import TrustService

            TrustService.open_review_item(
                kind=ManualReviewKind.CONTENT_FLAG,
                summary=f"Possible rating ring on teacher {review.teacher_id}",
                subject_user=review.author,
                payload={"review_id": str(review.id), "reasons": reasons},
                dedupe_key=f"ratingring:{review.teacher_id}",
                priority=2,
            )
            RiskService.add_signal(
                review.author,
                kind=RiskSignalKind.USER_REPORT,
                weight=15,
                detail="Review flagged by rating-ring detection",
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "ring-detection signalling failed for review %s", review.id
            )

    @staticmethod
    def recompute_teacher_rating(teacher) -> Decimal:
        """
        Recompute `TeacherProfile.rating` from PUBLISHED reviews. Call this
        only on a mutating event (review created / deleted / status changed)
        - NOT on every read - so an existing (legacy / admin-set) rating on a
        teacher who has no reviews yet is left untouched until their first
        review actually lands.
        """
        if not enabled():
            return Decimal("0.00")
        agg = Review.objects.filter(
            teacher=teacher, status=ReviewStatus.PUBLISHED
        ).aggregate(avg=Avg("rating"), n=Count("id"))
        avg = agg["avg"]
        value = (
            Decimal("0.00")
            if avg is None
            else Decimal(str(avg)).quantize(Decimal("0.01"))
        )

        profile = getattr(teacher, "marketplace_profile", None)
        if profile is not None:
            type(profile).objects.filter(pk=profile.pk).update(rating=value)
        return value

    @staticmethod
    def average_rating(teacher) -> Decimal:
        """Read-only average of published reviews (no write)."""
        avg = Review.objects.filter(
            teacher=teacher, status=ReviewStatus.PUBLISHED
        ).aggregate(a=Avg("rating"))["a"]
        return (
            Decimal("0.00")
            if avg is None
            else Decimal(str(avg)).quantize(Decimal("0.01"))
        )

    @staticmethod
    def set_status(review: Review, status: str, *, reason: str = "") -> Review:
        review.status = status
        review.flag_reason = reason or review.flag_reason
        review.save(update_fields=["status", "flag_reason", "updated_at"])
        ReviewIntegrityService.recompute_teacher_rating(review.teacher)
        return review

"""
TrustService - the canonical accessor for a user's TrustProfile plus the
one entry point for opening ManualReviewItems.

``recompute_verification_score`` delegates to ``VerificationService``
(Phase 5) for teachers and stamps ``verification_recomputed_at`` for
everyone else. ``recompute_risk`` delegates to ``RiskService`` (Phase 6),
which sums a user's active ``RiskSignal`` weights into
``TrustProfile.risk_score`` / ``risk_state``. Cross-platform
auto-enforcement of ``risk_state`` is still Phase 9
(``TRUST_ENABLE_RISK_AUTO_ACTIONS``).
"""

from __future__ import annotations

from django.utils import timezone

from apps.trust.models import ManualReviewItem, ManualReviewStatus, TrustProfile


class TrustService:
    @staticmethod
    def get_or_create_profile(user) -> TrustProfile:
        """
        Every user gets a TrustProfile via a post_save signal, but this
        stays the safe accessor for users created before the signal
        existed or via paths that skip signals (bulk_create, fixtures).
        """
        profile, _ = TrustProfile.objects.get_or_create(user=user)
        return profile

    @staticmethod
    def recompute_verification_score(user) -> TrustProfile:
        # Teachers have a real verification checklist that drives the score.
        teacher = getattr(user, "teacher_profile", None)  # -> apps.teachers.Teacher
        if teacher is not None:
            from apps.trust.services.verification_service import VerificationService

            return VerificationService.recompute(teacher)

        profile = TrustService.get_or_create_profile(user)
        profile.verification_recomputed_at = timezone.now()
        profile.save(update_fields=["verification_recomputed_at", "updated_at"])
        return profile

    @staticmethod
    def recompute_risk(user) -> TrustProfile:
        from apps.trust.services.risk_service import RiskService

        return RiskService.recompute(user)

    @staticmethod
    def open_review_item(
        *,
        kind: str,
        summary: str,
        subject_user=None,
        payload: dict | None = None,
        dedupe_key: str = "",
        priority: int = 3,
    ) -> ManualReviewItem:
        """
        Create a review-queue item, or return the existing open one when
        ``dedupe_key`` matches (so a signal that fires repeatedly does not
        flood the queue).
        """
        if dedupe_key:
            existing = ManualReviewItem.objects.filter(
                kind=kind,
                dedupe_key=dedupe_key,
                status__in=[ManualReviewStatus.OPEN, ManualReviewStatus.IN_REVIEW],
            ).first()
            if existing is not None:
                return existing

        return ManualReviewItem.objects.create(
            kind=kind,
            summary=summary[:255],
            subject_user=subject_user,
            payload=payload or {},
            dedupe_key=dedupe_key[:200],
            priority=priority,
        )

    @staticmethod
    def resolve_review_item(
        item: ManualReviewItem, *, by=None, resolution: str = "", dismiss: bool = False
    ) -> ManualReviewItem:
        item.status = (
            ManualReviewStatus.DISMISSED if dismiss else ManualReviewStatus.RESOLVED
        )
        item.resolution = resolution
        item.resolved_by = by
        item.resolved_at = timezone.now()
        item.save(
            update_fields=[
                "status",
                "resolution",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )

        # Clearing a duplicate-account item also clears its DuplicateSignals,
        # so the flagged account is no longer blocked.
        from apps.trust.models import ManualReviewKind

        if item.kind == ManualReviewKind.DUPLICATE_ACCOUNT:
            from apps.trust.services.dedupe_service import DedupeService

            DedupeService.resolve_for_review_item(item)

        # Resolving a suspension-appeal item is the ops decision on the
        # appeal: resolve -> grant (lift the suspension), dismiss -> deny.
        if item.kind == ManualReviewKind.SUSPENSION_APPEAL:
            from apps.trust.services.appeal_service import AppealService

            AppealService.on_review_resolved(
                item, by=by, resolution=resolution, dismissed=dismiss
            )

        return item

"""
ReportBlockService (Phase 8d).

  * ``report_user`` - one user flags another. Always records a UserReport +
    opens a USER_REPORT review item + raises a risk signal on the reported
    user. (No feature flag - a report just creates a queue item.)
  * ``block_user`` / ``unblock_user`` - a personal block list. Always
    stored; only *acts* on search + lead distribution while
    ``TRUST_ENABLE_USER_BLOCKING`` is on (so users can build their list
    before the switch is flipped).
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.trust.models import (
    ManualReviewKind,
    RiskSignalKind,
    UserBlock,
    UserReport,
    UserReportReason,
    UserReportStatus,
)

logger = logging.getLogger("apps.trust.report_block")


class ReportBlockService:
    @staticmethod
    @transaction.atomic
    def report_user(
        *, reporter, reported, reason: str, detail: str = "", request=None
    ) -> UserReport:
        if reporter.id == reported.id:
            raise ValidationException(detail="You cannot report yourself.")
        if reason not in UserReportReason.values:
            raise ValidationException(detail="Unknown report reason.")

        recent = UserReport.objects.filter(
            reporter=reporter, reported=reported, status=UserReportStatus.OPEN
        ).first()
        if recent is not None:
            return recent  # dedupe - one open report per pair

        report = UserReport.objects.create(
            reporter=reporter,
            reported=reported,
            reason=reason,
            detail=(detail or "")[:1000],
        )

        try:
            from apps.ops.models import AuditCategory
            from apps.ops.services import AuditService
            from apps.trust.services.risk_service import RiskService
            from apps.trust.services.trust_service import TrustService

            item = TrustService.open_review_item(
                kind=ManualReviewKind.USER_REPORT,
                summary=f"{reporter.email} reported {reported.email}: {reason}",
                subject_user=reported,
                payload={
                    "report_id": str(report.id),
                    "reason": reason,
                    "detail": detail[:500],
                },
                dedupe_key=f"report:{reported.id}",
                priority=2,
            )
            report.review_item = item
            report.save(update_fields=["review_item", "updated_at"])

            RiskService.add_signal(
                reported,
                kind=RiskSignalKind.USER_REPORT,
                weight=20,
                detail=f"Reported by another user ({reason})",
                payload={"reason": reason},
            )
            AuditService.record(
                action="user_report_filed",
                category=AuditCategory.SECURITY,
                request=request,
                actor=reporter,
                target=reported,
                message=f"Reported for {reason}.",
            )
        except Exception:  # noqa: BLE001
            logger.exception("report_user signalling failed (%s)", report.id)

        logger.info(
            "user report: %s -> %s (%s)", reporter.email, reported.email, reason
        )
        return report

    @staticmethod
    def block_user(*, blocker, blocked, request=None) -> UserBlock:
        if blocker.id == blocked.id:
            raise ValidationException(detail="You cannot block yourself.")
        block, created = UserBlock.objects.get_or_create(
            blocker=blocker, blocked=blocked
        )
        if created:
            try:
                from apps.ops.models import AuditCategory
                from apps.ops.services import AuditService

                AuditService.record(
                    action="user_blocked",
                    category=AuditCategory.SECURITY,
                    request=request,
                    actor=blocker,
                    target=blocked,
                    message="User blocked.",
                )
            except Exception:  # noqa: BLE001
                logger.exception("block audit failed")
        return block

    @staticmethod
    def unblock_user(*, blocker, blocked=None, blocked_id=None) -> None:
        target = blocked_id if blocked_id is not None else blocked
        UserBlock.objects.filter(blocker=blocker, blocked=target).delete()

    @staticmethod
    def blocked_user_ids(user) -> set:
        """Every user id `user` should not see and that should not see `user`."""
        return set(
            UserBlock.objects.filter(blocker=user).values_list("blocked_id", flat=True)
        ) | set(
            UserBlock.objects.filter(blocked=user).values_list("blocker_id", flat=True)
        )

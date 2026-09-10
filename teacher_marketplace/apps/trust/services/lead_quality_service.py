"""
LeadQualityService - teachers grade the leads they unlocked.

Two things happen off the back of a rating:

  * ``_reassess`` (fake OR unreachable): keeps ``lead_quality_score``
    current, and once ``TRUST_LEAD_QUALITY_CORROBORATION`` distinct
    teachers agree, refunds them (flag-gated) and raises a LEAD_QUALITY
    risk signal + review item.

  * ``_reassess_fake_reports`` (fake ONLY): on EVERY fake report, opens or
    updates a FAKE_LEAD_REPORT review-queue item for that student so the
    Super Admin dashboard reflects it immediately, and - unconditionally,
    no feature flag - permanently bans the student when the number of
    DISTINCT teachers reporting fake leads exceeds
    ``settings.FAKE_LEAD_AUTOBAN_WEEKLY`` in the last 7 days or
    ``settings.FAKE_LEAD_AUTOBAN_MONTHLY`` in the last 30, with a hard
    floor of ``FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS`` so a couple of
    teachers can never get a student banned.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.trust.models import (
    AccountSanctionKind,
    AccountSanctionSource,
    LeadQualityRating,
    LeadQualityVerdict,
    ManualReviewKind,
    RiskSignalKind,
)
from apps.trust.services.risk_service import RiskService
from apps.trust.services.trust_service import TrustService

logger = logging.getLogger("apps.trust.lead_quality")

_BAD = (LeadQualityVerdict.FAKE, LeadQualityVerdict.UNREACHABLE)


class LeadQualityService:
    @staticmethod
    @transaction.atomic
    def rate(*, teacher, lead, verdict: str, note: str = "") -> LeadQualityRating:
        from apps.lead_engine.models import LeadUnlockHistory

        if verdict not in LeadQualityVerdict.values:
            raise ValidationException(
                detail="verdict must be genuine, unreachable, or fake."
            )
        if lead.teacher_profile.teacher_id != teacher.id:
            raise ValidationException(detail="This lead is not yours.")
        if not LeadUnlockHistory.objects.filter(teacher=teacher, lead=lead).exists():
            raise ValidationException(
                detail="You can only rate a lead you have unlocked."
            )

        student = lead.student_requirement.student
        rating, _ = LeadQualityRating.objects.update_or_create(
            teacher=teacher,
            lead=lead,
            defaults={"student": student, "verdict": verdict, "note": note[:500]},
        )
        LeadQualityService._reassess(student)
        if verdict == LeadQualityVerdict.FAKE:
            LeadQualityService._reassess_fake_reports(
                student, latest_rating=rating, latest_lead=lead
            )
        return rating

    @staticmethod
    def _reassess(student) -> None:
        bad = LeadQualityRating.objects.filter(student=student, verdict__in=_BAD)
        all_ratings = LeadQualityRating.objects.filter(student=student)
        total = all_ratings.count()
        genuine = total - bad.count()

        # cached lead-quality score (1.0 = clean)
        profile = TrustService.get_or_create_profile(student)
        profile.lead_quality_score = (genuine / total) if total else 1.0
        profile.save(update_fields=["lead_quality_score", "updated_at"])

        distinct_teachers = bad.values("teacher").distinct().count()
        if distinct_teachers < settings.TRUST_LEAD_QUALITY_CORROBORATION:
            return

        # Corroborated: refund the flagging teachers (flag-gated) + risk signal + queue.
        if getattr(settings, "TRUST_ENABLE_LEAD_QUALITY_CLAWBACK", False):
            LeadQualityService._clawback(bad.filter(clawed_back=False))

        RiskService.add_signal(
            student,
            kind=RiskSignalKind.LEAD_QUALITY,
            weight=45,
            detail=f"{distinct_teachers} teachers flagged leads as fake/unreachable",
            payload={"distinct_teachers": distinct_teachers, "bad": bad.count()},
        )
        TrustService.open_review_item(
            kind=ManualReviewKind.LEAD_QUALITY,
            summary=f"{student.email}: {distinct_teachers} teachers report fake/unreachable leads",
            subject_user=student,
            payload={"distinct_teachers": distinct_teachers},
            dedupe_key=f"lq:{student.id}",
            priority=2,
        )

    # ------------------------------------------------------------------
    # Fake-lead reporting -> Super Admin alert + automatic ban
    # ------------------------------------------------------------------
    @staticmethod
    def fake_report_stats(student) -> dict:
        """
        Distinct teachers who have rated any of this student's leads
        ``fake``, over the rolling windows and all-time, plus the total
        number of fake reports. Distinct-by-teacher is the anti-gaming
        property: a teacher who flags five of one student's leads counts
        once.
        """
        now = timezone.now()
        weekly = now - timedelta(days=settings.FAKE_LEAD_REPORT_WEEKLY_WINDOW_DAYS)
        monthly = now - timedelta(days=settings.FAKE_LEAD_REPORT_MONTHLY_WINDOW_DAYS)
        fake = LeadQualityRating.objects.filter(
            student=student, verdict=LeadQualityVerdict.FAKE
        )

        def distinct_teachers(qs):
            return qs.aggregate(n=Count("teacher", distinct=True))["n"] or 0

        return {
            "distinct_teachers_7d": distinct_teachers(fake.filter(updated_at__gte=weekly)),
            "distinct_teachers_30d": distinct_teachers(
                fake.filter(updated_at__gte=monthly)
            ),
            "distinct_teachers_all": distinct_teachers(fake),
            "total_reports": fake.count(),
        }

    @staticmethod
    def _reassess_fake_reports(student, *, latest_rating, latest_lead) -> None:
        stats = LeadQualityService.fake_report_stats(student)

        from apps.trust.services.sanction_service import SanctionService

        already_banned = SanctionService.active_for(student) is not None
        weekly_hit = stats["distinct_teachers_7d"] > settings.FAKE_LEAD_AUTOBAN_WEEKLY
        monthly_hit = stats["distinct_teachers_30d"] > settings.FAKE_LEAD_AUTOBAN_MONTHLY
        floor_met = (
            stats["distinct_teachers_all"]
            >= settings.FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS
        )
        should_ban = (
            not already_banned
            and floor_met
            and (weekly_hit or monthly_hit)
            and student.is_active
        )

        latest = {
            "teacher_email": latest_rating.teacher.user.email,
            "teacher_name": latest_rating.teacher.user.get_full_name(),
            "lead_id": str(latest_lead.id),
            "subject": getattr(
                getattr(latest_lead.student_requirement, "subject", None), "name", ""
            ),
            "note": latest_rating.note,
            "at": timezone.now().isoformat(),
        }
        payload = {
            **stats,
            "student_email": student.email,
            "student_name": student.get_full_name(),
            "latest_report": latest,
            "auto_banned": bool(should_ban or already_banned),
        }

        if should_ban:
            source = (
                AccountSanctionSource.AUTO_FAKE_LEADS_WEEKLY
                if weekly_hit
                else AccountSanctionSource.AUTO_FAKE_LEADS_MONTHLY
            )
            window = "7 days" if weekly_hit else "30 days"
            count = (
                stats["distinct_teachers_7d"]
                if weekly_hit
                else stats["distinct_teachers_30d"]
            )
            reason = (
                f"Automatic ban: {count} different teachers reported this "
                f"student's leads as fake in the last {window}."
            )
            item = LeadQualityService._open_fake_report_item(
                student, payload, priority=1
            )
            try:
                SanctionService.apply(
                    student,
                    kind=AccountSanctionKind.BAN,
                    reason=reason,
                    source=source,
                    review_item=item,
                    payload={"trigger": source, "stats": stats},
                )
            except ValidationException:
                # e.g. a race made the account staff between the check and
                # here - leave the alert, skip the ban.
                logger.exception("auto-ban skipped for %s", student.email)
            item.payload = {**payload, "auto_banned": True}
            item.priority = 1
            item.save(update_fields=["payload", "priority", "updated_at"])
            return

        priority = 3
        if already_banned or stats["distinct_teachers_7d"] >= 5:
            priority = 1
        elif stats["distinct_teachers_all"] >= 3:
            priority = 2
        LeadQualityService._open_fake_report_item(student, payload, priority=priority)

    @staticmethod
    def _open_fake_report_item(student, payload, *, priority):
        """
        Open the student's FAKE_LEAD_REPORT review item, or update the
        existing open one's payload/priority so the dashboard always shows
        the current counts.
        """
        from apps.trust.models import ManualReviewItem, ManualReviewStatus

        summary = (
            f"{student.email}: {payload['distinct_teachers_all']} teacher(s) "
            f"reported fake leads ({payload['total_reports']} report(s))"
        )
        item = ManualReviewItem.objects.filter(
            kind=ManualReviewKind.FAKE_LEAD_REPORT,
            dedupe_key=f"flr:{student.id}",
            status__in=[ManualReviewStatus.OPEN, ManualReviewStatus.IN_REVIEW],
        ).first()
        if item is not None:
            item.summary = summary[:255]
            item.payload = payload
            item.priority = min(item.priority, priority)
            item.save(update_fields=["summary", "payload", "priority", "updated_at"])
            return item

        return TrustService.open_review_item(
            kind=ManualReviewKind.FAKE_LEAD_REPORT,
            summary=summary,
            subject_user=student,
            payload=payload,
            dedupe_key=f"flr:{student.id}",
            priority=priority,
        )

    @staticmethod
    def _clawback(pending_ratings) -> None:
        """
        Refund every teacher who flagged this student's leads.

        The refund always lands in the teacher's PURCHASED (never-expiring)
        balance, whichever bucket the unlock originally came from. Restoring
        a plan-allowance unlock instead would hand back something that may
        expire within days, which is not a refund; crediting the permanent
        bucket is the honest version and costs us the same one unlock.

        This deliberately does NOT filter on is_free_unlock. Under the
        allowance model almost every unlock is an allowance unlock
        (is_free_unlock=True, tokens_deducted=0), so the old
        `is_free_unlock=False, tokens_deducted > 0` filter matched no rows
        and silently refunded nobody - the gate looked enabled and paid out
        nothing.

        Corroboration (TRUST_LEAD_QUALITY_CORROBORATION distinct teachers)
        is already enforced by the caller, which is what stops a single
        teacher converting expiring allowance into permanent balance on
        demand.
        """
        from django.conf import settings

        from apps.lead_engine.models import LeadUnlockHistory
        from apps.wallet.services import WalletService

        for rating in pending_ratings.select_related("teacher", "lead"):
            unlock = LeadUnlockHistory.objects.filter(
                teacher=rating.teacher, lead=rating.lead
            ).first()
            if unlock is not None:
                # An allowance unlock cost 0 tokens but still cost the teacher
                # one unlock, so refund the flat unlock price in that case.
                amount = unlock.tokens_deducted or settings.FIXED_LEAD_UNLOCK_COST
                # A teacher who has only ever spent plan allowance has no
                # Wallet row yet - refund() reads one and would 500. Create
                # it first so the credit lands.
                WalletService.get_or_create_wallet(rating.teacher)
                WalletService.refund(
                    teacher=rating.teacher,
                    amount=amount,
                    description="Refund - lead reported fake / unreachable",
                    reference_id=str(rating.lead_id),
                )
                logger.info(
                    "lead-quality clawback: %d unlock(s) -> %s (lead %s, %s)",
                    amount,
                    rating.teacher.user.email,
                    rating.lead_id,
                    "allowance" if unlock.is_free_unlock else "purchased",
                )
            rating.clawed_back = True
            rating.save(update_fields=["clawed_back", "updated_at"])

"""
ContentScanService (Phase 8a / 8b).

Runs the ``content_classifier`` provider (regex now, ML later) over
user-authored free text - teacher profile fields, verification notes,
review text - looking for off-platform contact / payment info. Hits
create a ``ContentFlag`` + a ``ManualReviewItem`` and, for a teacher
profile, put it in ``moderation_status = HELD`` (hidden from search +
lead distribution while ``TRUST_ENABLE_CONTACT_LEAKAGE_SCAN`` is on).

Everything here is a no-op unless that flag is on, so profile / review
create + edit behave exactly as before by default.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.trust.models import (
    ContentFlag,
    ContentFlagStatus,
    ManualReviewKind,
    RiskSignalKind,
)
from apps.trust.providers import get_provider

logger = logging.getLogger("apps.trust.content_scan")


def enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_CONTACT_LEAKAGE_SCAN", False))


class ContentScanService:
    @staticmethod
    def scan_text(text: str):
        """(clean: bool, categories: list[str], matches: list[str])."""
        result = get_provider("content_classifier").classify(text=text or "")
        if result.ok:
            return True, [], []
        meta = result.metadata or {}
        return False, list(meta.get("categories", [])), list(meta.get("matches", []))

    # ---- teacher profiles ------------------------------------------

    @staticmethod
    def scan_teacher_profile(profile) -> None:
        if not enabled():
            return
        try:
            ContentScanService._scan_teacher_profile(profile)
        except Exception:  # noqa: BLE001 - a scan failure must not break a profile save
            logger.exception("scan_teacher_profile failed for %s", profile.pk)

    @staticmethod
    def scan_teacher(teacher) -> None:
        """
        Scan whatever profile surfaces a teacher has. If they have a
        marketplace profile, that path (which also drives the moderation
        hold) is used; otherwise their Teacher.bio / qualification_detail
        are still scanned for a flag. No-op unless the flag is on.
        """
        if not enabled():
            return
        try:
            profile = getattr(teacher, "marketplace_profile", None)
            if profile is not None:
                ContentScanService._scan_teacher_profile(profile)
                return
            for field in ("bio", "qualification_detail"):
                ContentScanService.flag_text(
                    user=teacher.user,
                    surface=f"teacher.{field}",
                    text=getattr(teacher, field, "") or "",
                    object_ref=str(teacher.pk),
                    priority=2,
                )
        except Exception:  # noqa: BLE001
            logger.exception("scan_teacher failed for %s", teacher.pk)

    @staticmethod
    def _scan_teacher_profile(profile) -> None:
        from apps.teacher_profile.models import ModerationStatus
        from apps.trust.services.risk_service import RiskService
        from apps.trust.services.trust_service import TrustService

        teacher = profile.teacher
        user = teacher.user
        surfaces = {
            "headline": profile.headline or "",
            "bio": getattr(teacher, "bio", "") or "",
            "qualification_detail": getattr(teacher, "qualification_detail", "") or "",
        }

        hits = []
        for field, text in surfaces.items():
            clean, cats, matches = ContentScanService.scan_text(text)
            if not clean:
                hits.append((field, cats, matches))

        open_qs = ContentFlag.objects.filter(
            subject_user=user,
            surface__startswith="teacher_profile.",
            status=ContentFlagStatus.OPEN,
        )

        if not hits:
            # Self-heal: the teacher removed the flagged content.
            healed = open_qs.count()
            if healed:
                for flag in open_qs.select_related("review_item"):
                    flag.status = ContentFlagStatus.RESOLVED
                    flag.resolved_at = timezone.now()
                    flag.save(update_fields=["status", "resolved_at", "updated_at"])
                    if flag.review_item and flag.review_item.status in (
                        "open",
                        "in_review",
                    ):
                        TrustService.resolve_review_item(
                            flag.review_item,
                            resolution="Flagged content removed by the teacher.",
                        )
            if profile.moderation_status == ModerationStatus.HELD:
                type(profile).objects.filter(pk=profile.pk).update(
                    moderation_status=ModerationStatus.CLEAR
                )
                profile.moderation_status = ModerationStatus.CLEAR
                logger.info("content scan: cleared moderation hold for %s", user.email)
            return

        review_item = TrustService.open_review_item(
            kind=ManualReviewKind.CONTENT_FLAG,
            summary=f"Off-platform content in {user.email}'s profile",
            subject_user=user,
            payload={
                "profile_id": str(profile.id),
                "fields": [h[0] for h in hits],
                "categories": sorted({c for h in hits for c in h[1]}),
            },
            dedupe_key=f"content:teacher_profile:{profile.id}",
            priority=2,
        )

        for field, cats, matches in hits:
            surface = f"teacher_profile.{field}"
            flag = open_qs.filter(surface=surface).first()
            if flag is None:
                ContentFlag.objects.create(
                    subject_user=user,
                    surface=surface,
                    object_ref=str(profile.id),
                    categories=cats,
                    excerpt="; ".join(matches)[:500],
                    review_item=review_item,
                )
            else:
                flag.categories = cats
                flag.excerpt = "; ".join(matches)[:500]
                flag.review_item = review_item
                flag.save(
                    update_fields=["categories", "excerpt", "review_item", "updated_at"]
                )

        if profile.moderation_status != ModerationStatus.HELD:
            type(profile).objects.filter(pk=profile.pk).update(
                moderation_status=ModerationStatus.HELD
            )
            profile.moderation_status = ModerationStatus.HELD

        RiskService.add_signal(
            user,
            kind=RiskSignalKind.CONTENT_LEAKAGE,
            weight=25,
            detail="Off-platform contact/payment content in profile",
            payload={"fields": [h[0] for h in hits]},
        )
        logger.warning(
            "content scan: held %s's profile (%s)",
            user.email,
            ", ".join(h[0] for h in hits),
        )

    # ---- generic text (reviews, notes) ---------------------------

    @staticmethod
    def flag_text(
        *, user, surface: str, text: str, object_ref: str = "", priority: int = 3
    ):
        """
        Scan a single piece of text and, on a hit, record a ContentFlag +
        review item. Returns the categories found (empty list = clean).
        No-op unless the flag is on.
        """
        if not enabled():
            return []
        clean, cats, matches = ContentScanService.scan_text(text)
        if clean:
            return []
        try:
            from apps.trust.services.trust_service import TrustService

            review_item = TrustService.open_review_item(
                kind=ManualReviewKind.CONTENT_FLAG,
                summary=f"Off-platform content in {surface} by {getattr(user, 'email', user)}",
                subject_user=user if getattr(user, "pk", None) else None,
                payload={
                    "surface": surface,
                    "object_ref": object_ref,
                    "categories": cats,
                },
                dedupe_key=f"content:{surface}:{object_ref}" if object_ref else "",
                priority=priority,
            )
            ContentFlag.objects.create(
                subject_user=user,
                surface=surface,
                object_ref=object_ref,
                categories=cats,
                excerpt="; ".join(matches)[:500],
                review_item=review_item,
            )
        except Exception:  # noqa: BLE001
            logger.exception("flag_text failed for surface %s", surface)
        return cats

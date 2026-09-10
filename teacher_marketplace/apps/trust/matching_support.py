"""
Hooks the teacher verification score into the matching / search pipeline.

Both are feature-flagged and default OFF, so every call here is a no-op
(byte-for-byte the previous behaviour) until a flag is switched on:

  * ``apply_teacher_gate(qs)`` replaces the plain
    ``.filter(verification_status=VERIFIED)`` on a ``TeacherProfile``
    queryset. OFF -> exactly that. ON (``TRUST_TEACHER_FLOOR_FOR_LEADS``)
    -> the auto-floor predicate (verified email + mobile + a completed
    basic profile), excluding admin-REJECTED teachers.

  * ``ranking_enabled()`` / ``verification_score_map()`` let the ranking
    services fold ``-verification_score`` in as a tiebreak *after*
    relevance and *within* a subscription tier, when
    ``TRUST_VERIFICATION_SCORE_AFFECTS_RANKING`` is on.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings


def floor_enabled() -> bool:
    return bool(getattr(settings, "TRUST_TEACHER_FLOOR_FOR_LEADS", False))


def ranking_enabled() -> bool:
    return bool(getattr(settings, "TRUST_VERIFICATION_SCORE_AFFECTS_RANKING", False))


def moderation_hiding_enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_CONTACT_LEAKAGE_SCAN", False))


def blocking_enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_USER_BLOCKING", False))


def apply_teacher_gate(qs, *, prefix: str = ""):
    from apps.teacher_profile.models import ModerationStatus, VerificationStatus
    from apps.trust.services.verification_service import VerificationService

    p = prefix
    if floor_enabled():
        qs = qs.filter(VerificationService.floor_predicate_q(prefix)).exclude(
            **{f"{p}verification_status": VerificationStatus.REJECTED}
        )
    else:
        qs = qs.filter(**{f"{p}verification_status": VerificationStatus.VERIFIED})

    # Phase 8b: profiles held for off-platform-content review are hidden
    # from search + lead distribution (but not from the teacher themself).
    if moderation_hiding_enabled():
        qs = qs.exclude(**{f"{p}moderation_status": ModerationStatus.HELD})
    return qs


def exclude_blocked_teachers(qs, viewer, *, user_path: str = "teacher__user"):
    """
    Drop TeacherProfiles whose user has blocked, or been blocked by,
    ``viewer`` (Phase 8d). No-op unless ``TRUST_ENABLE_USER_BLOCKING``.
    """
    if not blocking_enabled():
        return qs
    if viewer is None or not getattr(viewer, "is_authenticated", False):
        return qs
    from apps.trust.models import UserBlock

    blocked_ids = set(
        UserBlock.objects.filter(blocker=viewer).values_list("blocked_id", flat=True)
    ) | set(
        UserBlock.objects.filter(blocked=viewer).values_list("blocker_id", flat=True)
    )
    if not blocked_ids:
        return qs
    return qs.exclude(**{f"{user_path}_id__in": blocked_ids})


def verification_score_map(teacher_ids) -> dict:
    """{teacher_id: Decimal verification_score} in one query; missing -> 0.000."""
    from apps.trust.models import TrustProfile

    ids = list(teacher_ids)
    rows = TrustProfile.objects.filter(user__teacher_profile__id__in=ids).values_list(
        "user__teacher_profile__id", "verification_score"
    )
    found = {tid: score for tid, score in rows}
    return {tid: found.get(tid, Decimal("0.000")) for tid in ids}


def risk_penalty_map(teacher_ids) -> dict:
    """
    {teacher_id: int down-rank penalty} for risky teachers. Empty (all 0)
    unless ``TRUST_ENABLE_RISK_AUTO_ACTIONS`` is on - so ranking is
    byte-for-byte unchanged by default.
    """
    if not bool(getattr(settings, "TRUST_ENABLE_RISK_AUTO_ACTIONS", False)):
        return {}
    from apps.trust.models import TrustProfile
    from apps.trust.services.risk_service import RiskService

    ids = list(teacher_ids)
    rows = TrustProfile.objects.filter(user__teacher_profile__id__in=ids).values_list(
        "user__teacher_profile__id", "risk_state"
    )
    return {tid: RiskService.ranking_penalty(state) for tid, state in rows}

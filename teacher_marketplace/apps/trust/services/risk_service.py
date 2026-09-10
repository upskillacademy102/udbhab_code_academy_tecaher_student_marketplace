"""
RiskService - the platform risk aggregator (Phase 6 + Phase 9).

Every negative event records a ``RiskSignal``; ``recompute`` sums the
``weight`` of a user's ACTIVE signals into ``TrustProfile.risk_score``
(0-100) and maps it to ``risk_state``:

    < 20   normal
    20-49  limited    (shadow-limited: requirements held, ranked lower)
    50-79  review     (queued for a human)
    >= 80  suspended  (paid / lead actions blocked)

Phase 9 adds:
  * a ``RISK_ESCALATION`` review item opened/resolved as a user crosses
    the ``review`` line (always, so ops sees it even with auto-actions off);
  * ``is_suspended`` / ``ranking_penalty`` helpers the enforcement gates and
    the matching ranker read - all no-ops unless
    ``TRUST_ENABLE_RISK_AUTO_ACTIONS`` is on.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.trust.models import RiskSignal, RiskState
from apps.trust.services.trust_service import TrustService

_THRESHOLDS = (
    (80, RiskState.SUSPENDED),
    (50, RiskState.REVIEW),
    (20, RiskState.LIMITED),
)

_QUEUEABLE = (RiskState.REVIEW, RiskState.SUSPENDED)


def auto_actions_enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_RISK_AUTO_ACTIONS", False))


class RiskService:
    @staticmethod
    def add_signal(
        user, *, kind, weight=10, detail="", payload=None, expires_at=None, dedupe=True
    ):
        payload = payload or {}
        if dedupe:
            existing = RiskSignal.objects.filter(
                user=user, kind=kind, active=True
            ).first()
            if existing is not None:
                existing.weight = max(existing.weight, int(weight))
                existing.detail = (detail or existing.detail)[:255]
                if payload:
                    existing.payload = payload
                # Only extend/replace the expiry when the caller actually gave
                # one - a later plain re-fire must not silently make a
                # time-boxed signal permanent.
                if expires_at is not None:
                    existing.expires_at = expires_at
                existing.save(
                    update_fields=[
                        "weight",
                        "detail",
                        "payload",
                        "expires_at",
                        "updated_at",
                    ]
                )
                RiskService.recompute(user)
                return existing
        signal = RiskSignal.objects.create(
            user=user,
            kind=kind,
            weight=int(weight),
            detail=detail[:255],
            payload=payload,
            expires_at=expires_at,
        )
        RiskService.recompute(user)
        return signal

    @staticmethod
    def recompute(user):
        now = timezone.now()
        RiskSignal.objects.filter(user=user, active=True, expires_at__lt=now).update(
            active=False
        )
        total = (
            RiskSignal.objects.filter(user=user, active=True).aggregate(
                s=Sum("weight")
            )["s"]
            or 0
        )
        score = min(int(total), 100)
        state = RiskState.NORMAL
        for threshold, mapped in _THRESHOLDS:
            if score >= threshold:
                state = mapped
                break

        profile = TrustService.get_or_create_profile(user)
        previous = profile.risk_state
        profile.risk_score = score
        profile.risk_state = state
        profile.risk_recomputed_at = now
        profile.save(
            update_fields=[
                "risk_score",
                "risk_state",
                "risk_recomputed_at",
                "updated_at",
            ]
        )
        if state != previous:
            RiskService._sync_escalation_item(user, profile, state, score)
        return profile

    @staticmethod
    def _sync_escalation_item(user, profile, state, score) -> None:
        """Open a RISK_ESCALATION review item at review+, resolve it below."""
        try:
            from apps.trust.models import ManualReviewKind, ManualReviewStatus
            from apps.trust.services.trust_service import TrustService as _TS

            if state in _QUEUEABLE:
                _TS.open_review_item(
                    kind=ManualReviewKind.RISK_ESCALATION,
                    summary=f"{user.email}: risk {state} (score {score})",
                    subject_user=user,
                    payload={"risk_score": score, "risk_state": state},
                    dedupe_key=f"risk:{user.id}",
                    priority=1 if state == RiskState.SUSPENDED else 2,
                )
            else:
                from apps.trust.models import ManualReviewItem

                for item in ManualReviewItem.objects.filter(
                    kind=ManualReviewKind.RISK_ESCALATION,
                    dedupe_key=f"risk:{user.id}",
                    status__in=[ManualReviewStatus.OPEN, ManualReviewStatus.IN_REVIEW],
                ):
                    _TS.resolve_review_item(
                        item, resolution=f"Risk fell to {state} (score {score})."
                    )
        except (
            Exception
        ):  # noqa: BLE001 - escalation bookkeeping must not break recompute
            import logging

            logging.getLogger("apps.trust").exception(
                "risk escalation sync failed for %s", user.id
            )

    # ---- read helpers for enforcement -------------------------------

    @staticmethod
    def is_shadow_limited(user) -> bool:
        profile = TrustService.get_or_create_profile(user)
        return profile.risk_state in (
            RiskState.LIMITED,
            RiskState.REVIEW,
            RiskState.SUSPENDED,
        )

    @staticmethod
    def is_suspended(user) -> bool:
        """True only when auto-actions are on AND the user is suspended."""
        if not auto_actions_enabled():
            return False
        profile = TrustService.get_or_create_profile(user)
        return profile.risk_state == RiskState.SUSPENDED

    @staticmethod
    def ranking_penalty(risk_state: str) -> int:
        """
        A small, bounded down-rank factor for risky teachers, applied in the
        matching ranker only when auto-actions are on. Higher = worse.
        """
        if not auto_actions_enabled():
            return 0
        return {
            RiskState.LIMITED: 1,
            RiskState.REVIEW: 2,
            RiskState.SUSPENDED: 3,
        }.get(risk_state, 0)

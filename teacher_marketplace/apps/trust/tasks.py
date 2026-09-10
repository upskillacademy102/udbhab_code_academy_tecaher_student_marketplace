"""Celery tasks for the trust app."""

import logging

from celery import shared_task

logger = logging.getLogger("apps.trust.tasks")


@shared_task(name="apps.trust.tasks.apply_due_sensitive_changes")
def apply_due_sensitive_changes():
    """
    Apply any SCHEDULED email/mobile change whose cooldown has elapsed,
    and expire any change request that was never confirmed. Idempotent -
    safe to run on a short interval (see CELERY_BEAT_SCHEDULE).
    """
    from apps.trust.services.sensitive_change_service import SensitiveChangeService

    applied = SensitiveChangeService.apply_due()
    expired = SensitiveChangeService.expire_stale()
    if applied or expired:
        logger.info(
            "apply_due_sensitive_changes: applied=%d expired=%d", applied, expired
        )
    return {"applied": applied, "expired": expired}


@shared_task(name="apps.trust.tasks.recompute_teacher_verification_scores")
def recompute_teacher_verification_scores(limit=None):
    """
    Nightly safety-net: refresh every teacher's verification checklist +
    cached ``verification_score`` so a profile / subject / availability
    edit that didn't recompute inline is picked up within a day.
    Idempotent.
    """
    from apps.teachers.models import Teacher
    from apps.trust.services.verification_service import VerificationService

    qs = Teacher.objects.select_related("user").order_by("created_at")
    if limit:
        qs = qs[: int(limit)]

    done = 0
    for teacher in qs.iterator():
        try:
            VerificationService.recompute(teacher)
            done += 1
        except Exception:  # noqa: BLE001 - one bad teacher must not stop the sweep
            logger.exception("recompute failed for teacher %s", teacher.id)
    logger.info("recompute_teacher_verification_scores: %d teacher(s)", done)
    return {"recomputed": done}


@shared_task(name="apps.trust.tasks.recompute_risk_scores")
def recompute_risk_scores(limit=None):
    """
    Nightly safety-net (Phase 9): re-run RiskService.recompute for every
    user who has at least one RiskSignal, so expired signals decay and the
    RISK_ESCALATION queue item + risk_state stay accurate even if an inline
    recompute was missed. Idempotent.
    """
    from apps.accounts.models import User
    from apps.trust.models import RiskSignal
    from apps.trust.services.risk_service import RiskService

    user_ids = RiskSignal.objects.values_list("user_id", flat=True).distinct()
    qs = User.objects.filter(id__in=list(user_ids)).order_by("created_at")
    if limit:
        qs = qs[: int(limit)]

    done = 0
    for user in qs.iterator():
        try:
            RiskService.recompute(user)
            done += 1
        except Exception:  # noqa: BLE001
            logger.exception("risk recompute failed for user %s", user.id)
    logger.info("recompute_risk_scores: %d user(s)", done)
    return {"recomputed": done}

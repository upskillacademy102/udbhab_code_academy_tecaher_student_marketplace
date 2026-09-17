"""
Celery tasks for the matching app.

expire_lead_assignments is the scheduled task satisfying Section
28's explicit requirement: expired assignments must move to the
next eligible teacher group WITHOUT depending on any user request
triggering it.

Runs on a periodic schedule via django-celery-beat (configured in
the CELERY_BEAT_SCHEDULE patch below, or equivalently via the
django-celery-beat admin UI once migrations run - both are
supported, DB-driven schedule takes precedence if configured there).
"""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("apps.matching.tasks")


@shared_task(name="apps.matching.tasks.expire_lead_assignments")
def expire_lead_assignments():
    """
    Finds every LeadAssignment still ASSIGNED or VIEWED whose
    expires_at has passed, and expires each one via
    LeadDistributionService.expire_assignment() - which itself
    handles the stage-cascade logic (Section 22/23) atomically per
    assignment.

    Processes assignments ONE AT A TIME (not a bulk .update()) -
    deliberately, since expire_assignment() needs to run its
    stage-cascade check (_maybe_advance_stage) individually per
    lead, not as a single blind bulk status flip. A bulk update
    would correctly mark rows EXPIRED but would silently skip the
    "does this unblock the next tier" logic entirely, breaking
    Section 22's core requirement.

    Returns the count processed, for monitoring/logging visibility
    (Section 18 of the platform's broader spec: monitoring metrics).
    """
    from apps.matching.models import AssignmentStatus, LeadAssignment
    from apps.matching.services.lead_distribution_service import LeadDistributionService

    now = timezone.now()
    expired_ids = list(
        LeadAssignment.objects.filter(
            status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.VIEWED],
            never_expires=False,
            expires_at__lte=now,
        ).values_list("id", flat=True)
    )

    processed_count = 0
    error_count = 0
    for assignment_id in expired_ids:
        try:
            assignment = LeadAssignment.objects.get(id=assignment_id)
            LeadDistributionService.expire_assignment(assignment)
            processed_count += 1
        except (
            Exception
        ) as exc:  # noqa: BLE001 - one bad assignment must not stop the whole batch
            error_count += 1
            logger.error(
                "Failed to expire LeadAssignment %s: %s",
                assignment_id,
                exc,
                exc_info=True,
            )

    logger.info(
        "expire_lead_assignments: processed %d expired assignment(s), %d error(s).",
        processed_count,
        error_count,
    )
    return {"processed": processed_count, "errors": error_count}


@shared_task(name="apps.matching.tasks.reveal_online_lead_tiers")
def reveal_online_lead_tiers():
    """
    Beat-scheduled companion to expire_lead_assignments: brings in
    the next subscription tier for an ONLINE lead on a fixed clock
    (online_tier_window_hours per tier), completely independent of
    whether the current tier's assignment has been unlocked,
    accepted, or rejected - see
    LeadDistributionService.reveal_next_online_stage for the actual
    reveal logic; this task just finds which leads are worth
    checking and calls it per lead.

    Bounded lookback: once every configured tier has had a chance to
    be revealed for a lead, a further check on it is a guaranteed
    no-op, so there's no reason to keep scanning it forever.
    """
    from apps.lead_engine.models import Lead
    from apps.matching.models import LeadAssignment
    from apps.matching.services.config_service import get_config
    from apps.matching.services.lead_distribution_service import (
        LeadDistributionService,
    )
    from apps.teacher_profile.models import TeachingMode

    config = get_config()
    order = config.subscription_priority_order or ["Free"]
    lookback_hours = (
        config.online_tier_window_hours * len(order)
        + config.lead_visibility_window_hours
    )
    cutoff = timezone.now() - timezone.timedelta(hours=lookback_hours)

    lead_ids = list(
        LeadAssignment.objects.filter(
            assignment_stage=1,
            is_direct=False,
            lead__student_requirement__teaching_mode=TeachingMode.ONLINE,
            assigned_at__gte=cutoff,
        )
        .values_list("lead_id", flat=True)
        .distinct()
    )

    revealed_count = 0
    error_count = 0
    for lead_id in lead_ids:
        try:
            lead = Lead.objects.get(id=lead_id)
            revealed_count += len(
                LeadDistributionService.reveal_next_online_stage(lead)
            )
        except Exception as exc:  # noqa: BLE001 - one bad lead must not stop the batch
            error_count += 1
            logger.error(
                "Failed to reveal online tiers for lead %s: %s",
                lead_id,
                exc,
                exc_info=True,
            )

    logger.info(
        "reveal_online_lead_tiers: checked %d lead(s), revealed %d new assignment(s), %d error(s).",
        len(lead_ids),
        revealed_count,
        error_count,
    )
    return {"checked": len(lead_ids), "revealed": revealed_count, "errors": error_count}

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

"""
Celery tasks for the lead engine.

``process_requirement_leads`` is the async replacement for the block of
work that used to run synchronously inside
``StudentRequirementListCreateView.create()``:

    generate_leads_for_requirement()   -> soft Lead + LeadMatchScore rows
    LeadDistributionService.distribute_lead()  -> tiered LeadAssignment offers

Moving it here keeps the requirement POST fast (validate, save, commit,
enqueue, return 202) while the potentially-expensive candidate discovery,
time-overlap math, location matching and tier evaluation happen on a
worker.

Design guarantees
-----------------
* **Commit-safe**: the view enqueues via ``transaction.on_commit`` so a
  worker never sees an uncommitted requirement.
* **Idempotent**: safe to run twice (retry, redelivery, manual re-queue).
  ``generate_leads_for_requirement`` skips teachers that already have a
  Lead and swallows the unique-constraint race; ``distribute_lead`` takes
  a row lock on the requirement and no-ops if any assignment already
  exists. A COMPLETED requirement is skipped outright.
* **Concurrency-safe**: two workers processing the same requirement id
  serialize on ``SELECT ... FOR UPDATE`` of the requirement row inside
  ``distribute_lead``; duplicate Lead inserts are caught per-row.
* **Retry policy**: transient DB errors auto-retry with exponential
  backoff + jitter (capped). Any other exception marks the requirement
  FAILED and stops - business-rule failures must not retry forever.
"""

import logging
import time as _time

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import InterfaceError, OperationalError

logger = logging.getLogger("apps.lead_engine.tasks")

# Errors worth retrying: transient DB/connection blips. Everything else
# is treated as a permanent failure for this requirement.
TRANSIENT_DB_ERRORS = (OperationalError, InterfaceError)


@shared_task(
    bind=True,
    name="apps.lead_engine.tasks.process_requirement_leads",
    autoretry_for=TRANSIENT_DB_ERRORS,
    retry_backoff=5,  # 5s, 10s, 20s, 40s, ...
    retry_backoff_max=300,  # ...capped at 5 minutes
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def process_requirement_leads(self, requirement_id):
    """
    Generate soft leads and run stage-1 tiered distribution for one
    StudentRequirement. Returns a small dict for monitoring; never
    raises for business-rule problems (those mark the requirement
    FAILED and return).
    """
    from apps.lead_engine.models import Lead
    from apps.lead_engine.services import generate_leads_for_requirement
    from apps.matching.services.lead_distribution_service import LeadDistributionService
    from apps.student_requirement.models import (
        LeadDistributionStatus,
        StudentRequirement,
    )

    started = _time.monotonic()

    requirement = (
        StudentRequirement.objects.select_related(
            "subject", "city", "pincode_location", "student"
        )
        .prefetch_related("schedule_preferences", "preferred_languages")
        .filter(id=requirement_id)
        .first()
    )
    if requirement is None:
        # Requirement was deleted between enqueue and execution - a valid
        # outcome, not an error. Nothing to do.
        logger.warning(
            "process_requirement_leads: requirement=%s not found (deleted?) - skipping.",
            requirement_id,
        )
        return {"requirement_id": str(requirement_id), "status": "skipped_not_found"}

    if requirement.lead_distribution_status == LeadDistributionStatus.COMPLETED:
        logger.info(
            "process_requirement_leads: requirement=%s already COMPLETED - idempotent skip.",
            requirement_id,
        )
        return {"requirement_id": str(requirement_id), "status": "already_completed"}

    StudentRequirement.objects.filter(id=requirement_id).update(
        lead_distribution_status=LeadDistributionStatus.PROCESSING
    )

    _backfill_city_centroid(requirement, requirement_id)

    try:
        new_leads = generate_leads_for_requirement(requirement)

        # Distribution is per-requirement and needs a canonical Lead to
        # anchor the LeadAssignment rows. Prefer the top-ranked new lead;
        # on a retry where leads already exist, fall back to the best
        # existing one.
        canonical = (
            new_leads[0]
            if new_leads
            else (
                Lead.objects.filter(student_requirement=requirement)
                .select_related("match_score")
                .order_by("-match_score__match_score", "created_at")
                .first()
            )
        )

        assignments = []
        if canonical is not None:
            assignments = LeadDistributionService.distribute_lead(canonical)

    except TRANSIENT_DB_ERRORS:
        # Let autoretry_for handle the backoff/retry.
        logger.warning(
            "process_requirement_leads: requirement=%s transient DB error, retry %d/%d.",
            requirement_id,
            self.request.retries,
            self.max_retries,
        )
        raise
    except SoftTimeLimitExceeded:
        StudentRequirement.objects.filter(id=requirement_id).update(
            lead_distribution_status=LeadDistributionStatus.FAILED
        )
        logger.error(
            "process_requirement_leads: requirement=%s hit the soft time limit - marked FAILED.",
            requirement_id,
        )
        return {
            "requirement_id": str(requirement_id),
            "status": "failed",
            "error": "soft_time_limit",
        }
    # noqa: BLE001 - deliberate catch-all: business-rule errors must not retry
    except Exception as exc:  # noqa: BLE001
        StudentRequirement.objects.filter(id=requirement_id).update(
            lead_distribution_status=LeadDistributionStatus.FAILED
        )
        logger.error(
            "process_requirement_leads: requirement=%s FAILED (not retried): %s",
            requirement_id,
            exc,
            exc_info=True,
        )
        return {
            "requirement_id": str(requirement_id),
            "status": "failed",
            "error": str(exc),
        }

    total_leads = Lead.objects.filter(student_requirement=requirement).count()
    StudentRequirement.objects.filter(id=requirement_id).update(
        lead_distribution_status=LeadDistributionStatus.COMPLETED
    )

    duration_ms = round((_time.monotonic() - started) * 1000)
    summary = {
        "requirement_id": str(requirement_id),
        "task_id": self.request.id,
        "status": "completed",
        "leads_total": total_leads,
        "new_leads": len(new_leads),
        "stage1_assignments": len(assignments),
        "duration_ms": duration_ms,
    }
    logger.info(
        "process_requirement_leads: requirement=%s task=%s leads_total=%d new_leads=%d "
        "stage1_assignments=%d duration_ms=%d",
        requirement_id,
        self.request.id,
        total_leads,
        len(new_leads),
        len(assignments),
        duration_ms,
    )
    return summary


def _backfill_city_centroid(requirement, requirement_id):
    """
    Fill in ``requirement.pincode_location`` from the city centroid when the
    requirement was created with a city NAME (the create serializer defers
    this - see LocationResolutionService.resolve(defer_city_geocode=True)).

    Strictly best-effort: the centroid only powers optional radius ranking,
    so a slow or unreachable geocoder here must never fail the task. A
    pincode requirement already has its location and skips this.
    """
    if not requirement.city_id or requirement.pincode_location_id is not None:
        return

    from apps.matching.services.geocoding_service import (
        GeocodingError,
        PincodeGeocodingService,
    )
    from apps.student_requirement.models import StudentRequirement

    try:
        centroid = PincodeGeocodingService.get_or_geocode_city(requirement.city)
    except GeocodingError:
        return  # geocoder down - proceed without radius ranking
    except Exception:  # noqa: BLE001 - never fail distribution over a centroid
        logger.warning(
            "process_requirement_leads: city-centroid backfill failed for requirement=%s",
            requirement_id,
            exc_info=True,
        )
        return

    if centroid is not None:
        requirement.pincode_location = centroid
        StudentRequirement.objects.filter(id=requirement_id).update(
            pincode_location=centroid
        )


@shared_task(name="apps.lead_engine.tasks.requeue_stuck_requirement_distributions")
def requeue_stuck_requirement_distributions(stale_minutes: int = 15):
    """
    Safety net for requirements whose distribution never completed - the
    broker was down when the requirement was created, a worker was killed
    mid-task, or the task result was lost. Re-queues anything left in
    PENDING/QUEUED/PROCESSING past ``stale_minutes``.

    process_requirement_leads is idempotent, so re-queuing a requirement
    that actually did finish (COMPLETED) is harmless - but we exclude
    COMPLETED/FAILED here anyway to keep the sweep cheap.
    """
    from django.utils import timezone

    from apps.student_requirement.models import (
        LeadDistributionStatus,
        StudentRequirement,
    )

    cutoff = timezone.now() - timezone.timedelta(minutes=stale_minutes)
    stuck = list(
        StudentRequirement.objects.filter(
            lead_distribution_status__in=[
                LeadDistributionStatus.PENDING,
                LeadDistributionStatus.QUEUED,
                LeadDistributionStatus.PROCESSING,
            ],
            updated_at__lt=cutoff,
        ).values_list("id", flat=True)
    )
    for requirement_id in stuck:
        process_requirement_leads.delay(str(requirement_id))

    if stuck:
        logger.info(
            "requeue_stuck_requirement_distributions: re-queued %d requirement(s).",
            len(stuck),
        )
    return {"requeued": len(stuck)}

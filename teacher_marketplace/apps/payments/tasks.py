"""Celery tasks for the payments app."""

import logging

from celery import shared_task

logger = logging.getLogger("apps.payments.tasks")


@shared_task(name="apps.payments.tasks.reconcile_payments")
def reconcile_payments():
    """
    Daily payment-ledger reconciliation (Phase 7f). Idempotent - each run
    covers the window since the previous run's end. Drift is recorded on a
    ReconciliationRun and raised as a RECONCILIATION review item.
    """
    from apps.payments.reconciliation import ReconciliationService

    run = ReconciliationService.run()
    return {
        "run_id": str(run.id),
        "payments_checked": run.payments_checked,
        "discrepancies": run.discrepancies,
        "ok": run.ok,
    }


@shared_task(name="apps.payments.tasks.release_due_cooldown_holds")
def release_due_cooldown_holds():
    """
    Release new-account cooldown WalletHolds whose window has elapsed
    (Phase 7g). Idempotent - safe to run hourly.
    """
    from apps.payments.cooldown import NewAccountCooldownService

    released = NewAccountCooldownService.release_due_holds()
    return {"released": released}

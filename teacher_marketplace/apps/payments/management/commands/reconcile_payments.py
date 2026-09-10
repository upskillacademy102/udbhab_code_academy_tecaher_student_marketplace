"""
Run a payment-ledger reconciliation pass now (Phase 7f).

Normally runs daily via Celery beat (``apps.payments.tasks.reconcile_payments``);
this command is for an on-demand check or a first backfill.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.payments.reconciliation import ReconciliationService


class Command(BaseCommand):
    help = "Reconcile Payment / WalletTransaction / gateway ledgers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Look back this many days (default: since the last run).",
        )

    def handle(self, *args, **options):
        start = None
        if options["days"]:
            start = timezone.now() - timedelta(days=options["days"])
        run = ReconciliationService.run(window_start=start)
        style = self.style.SUCCESS if run.ok else self.style.ERROR
        self.stdout.write(
            style(
                f"Checked {run.payments_checked} payment(s); "
                f"{run.discrepancies} discrepancy(ies)."
            )
        )

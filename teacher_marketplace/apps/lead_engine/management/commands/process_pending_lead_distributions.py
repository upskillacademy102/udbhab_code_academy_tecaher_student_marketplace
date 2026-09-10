"""
Run the lead generation + distribution task for every StudentRequirement
whose async distribution never completed.

Useful when:
  * the broker/worker was down when requirements were created (they got
    stuck at lead_distribution_status = queued / pending / processing);
  * you just changed matching rules and want to re-evaluate open
    requirements.

`process_requirement_leads` is idempotent, so re-running an already
completed requirement is harmless (this command skips them anyway).

Examples:
    python manage.py process_pending_lead_distributions
    python manage.py process_pending_lead_distributions --include-failed
    python manage.py process_pending_lead_distributions --requirement <uuid>
"""

from django.core.management.base import BaseCommand

from apps.lead_engine.tasks import process_requirement_leads
from apps.student_requirement.models import LeadDistributionStatus, StudentRequirement


class Command(BaseCommand):
    help = "Process StudentRequirements whose lead distribution never completed."

    def add_arguments(self, parser):
        parser.add_argument("--requirement", help="Process a single requirement id.")
        parser.add_argument(
            "--include-failed",
            action="store_true",
            help="Also retry requirements marked FAILED.",
        )

    def handle(self, *args, **options):
        statuses = [
            LeadDistributionStatus.PENDING,
            LeadDistributionStatus.QUEUED,
            LeadDistributionStatus.PROCESSING,
        ]
        if options["include_failed"]:
            statuses.append(LeadDistributionStatus.FAILED)

        qs = StudentRequirement.objects.all()
        if options["requirement"]:
            qs = qs.filter(id=options["requirement"])
        else:
            qs = qs.filter(lead_distribution_status__in=statuses)

        ids = list(qs.values_list("id", flat=True))
        if not ids:
            self.stdout.write(self.style.SUCCESS("Nothing to process."))
            return

        self.stdout.write(f"Processing {len(ids)} requirement(s)...")
        ok = failed = 0
        for rid in ids:
            result = process_requirement_leads.apply(args=[str(rid)]).get()
            status = result.get("status")
            if status in ("completed", "already_completed", "skipped_not_found"):
                ok += 1
                self.stdout.write(
                    f"  {rid}  {status}"
                    + (
                        f"  leads={result.get('leads_total')} "
                        f"stage1={result.get('stage1_assignments')}"
                        if status == "completed"
                        else ""
                    )
                )
            else:
                failed += 1
                self.stdout.write(
                    self.style.WARNING(f"  {rid}  {status}: {result.get('error')}")
                )

        self.stdout.write(self.style.SUCCESS(f"Done. {ok} ok, {failed} failed."))

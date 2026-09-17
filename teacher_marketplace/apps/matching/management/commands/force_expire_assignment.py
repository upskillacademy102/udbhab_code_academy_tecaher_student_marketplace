"""
Manual QA helper: instantly expire one LeadAssignment instead of waiting
out its real offline_response_window_hours (default 24h).

Backdates expires_at into the past, then calls
LeadDistributionService.expire_assignment() for real - the exact same
code path the expire_lead_assignments beat task uses - so the offline
cascade-to-next-nearest-teacher behaviour is genuinely exercised, not
faked around.

Usage:
    python manage.py force_expire_assignment <assignment_id>
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.matching.models import LeadAssignment
from apps.matching.services.lead_distribution_service import LeadDistributionService


class Command(BaseCommand):
    help = "Instantly expire one LeadAssignment for manual QA (no waiting out the real response window)."

    def add_arguments(self, parser):
        parser.add_argument("assignment_id", type=str)

    def handle(self, *args, **options):
        try:
            assignment = LeadAssignment.objects.get(id=options["assignment_id"])
        except LeadAssignment.DoesNotExist as exc:
            raise CommandError(f"No LeadAssignment with id={options['assignment_id']}") from exc

        assignment.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        assignment.save(update_fields=["expires_at"])

        result = LeadDistributionService.expire_assignment(assignment)
        self.stdout.write(
            self.style.SUCCESS(
                f"Assignment {result.id} (teacher {result.teacher_id}) is now {result.status}."
            )
        )

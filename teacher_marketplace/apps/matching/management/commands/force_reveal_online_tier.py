"""
Manual QA helper: reveal the next subscription tier for an ONLINE lead
right now, instead of waiting out its real online_tier_window_hours
(default 8h).

Calls LeadDistributionService.reveal_next_online_stage(lead, force=True) -
the exact same code path the reveal_online_lead_tiers beat task uses -
skipping the time check for exactly one reveal, so a human can step
through Elite -> Professional -> Free one tier at a time.

Usage:
    python manage.py force_reveal_online_tier <lead_id>
"""

from django.core.management.base import BaseCommand, CommandError

from apps.lead_engine.models import Lead
from apps.matching.services.lead_distribution_service import LeadDistributionService


class Command(BaseCommand):
    help = "Reveal the next subscription tier for one ONLINE lead right now, for manual QA."

    def add_arguments(self, parser):
        parser.add_argument("lead_id", type=str)

    def handle(self, *args, **options):
        try:
            lead = Lead.objects.select_related("student_requirement").get(
                id=options["lead_id"]
            )
        except Lead.DoesNotExist as exc:
            raise CommandError(f"No Lead with id={options['lead_id']}") from exc

        revealed = LeadDistributionService.reveal_next_online_stage(lead, force=True)
        if not revealed:
            self.stdout.write(
                self.style.WARNING(
                    "Nothing revealed - either this isn't an ONLINE lead, "
                    "every tier is already offered, or no further teachers are eligible."
                )
            )
            return

        for assignment in revealed:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Stage {assignment.assignment_stage}: revealed to teacher "
                    f"{assignment.teacher_id} (tier {assignment.subscription_tier})."
                )
            )

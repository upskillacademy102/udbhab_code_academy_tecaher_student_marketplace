"""
Recompute every teacher's verification checklist + cached score.

Run this once BEFORE enabling ``TRUST_VERIFICATION_SCORE_AFFECTS_RANKING``
or ``TRUST_TEACHER_FLOOR_FOR_LEADS`` so scores are populated for the
existing teacher base rather than defaulting to 0.
"""

from django.core.management.base import BaseCommand

from apps.teachers.models import Teacher
from apps.trust.services.verification_service import VerificationService


class Command(BaseCommand):
    help = "Recompute all teacher verification scores."

    def handle(self, *args, **options):
        total = Teacher.objects.count()
        done = 0
        for teacher in Teacher.objects.select_related("user").iterator():
            VerificationService.recompute(teacher)
            done += 1
            if done % 100 == 0:
                self.stdout.write(f"  {done}/{total}")
        self.stdout.write(
            self.style.SUCCESS(f"Recomputed {done} teacher verification score(s).")
        )

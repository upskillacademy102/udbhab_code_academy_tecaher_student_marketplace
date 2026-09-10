"""
Seed the reference taxonomy the whole platform depends on.

WHY THIS EXISTS
    Subject and Language are reference data with no fixtures, no data
    migration and no seed path anywhere in the repo — so a fresh database
    starts with an empty taxonomy. That is not just a cosmetic gap: with no
    subjects a teacher cannot tag a profile, a student cannot post a
    requirement, and the matching engine has nothing to match on. The
    landing page's subject/language pickers are driven straight off these
    two tables, so an empty taxonomy also renders an empty picker.

    This command populates the starting set that the frontend displays.
    Super Admins add to it from /super-admin/subjects/ and
    /super-admin/languages/ — this only guarantees a sane floor.

SAFETY
    Idempotent. Uses get_or_create keyed on the unique field (Subject.name,
    Language.code), so re-running changes nothing and never overwrites an
    edit an admin has made. It creates only; it never updates or deletes.
    Rows that already exist are reported as skipped.

USAGE
    python manage.py seed_taxonomy
    python manage.py seed_taxonomy --dry-run    # show what would happen
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.languages.models import Language
from apps.subjects.models import Subject

# The subjects the landing page and registration flow offer. Deliberately
# the same list the frontend shipped as a hard-coded array, so seeding
# produces exactly what users were already being shown — now editable.
SUBJECTS = [
    ("Mathematics", "School and college mathematics, from arithmetic to calculus."),
    ("Physics", "Mechanics, electricity, optics and modern physics."),
    ("Chemistry", "Physical, organic and inorganic chemistry."),
    ("Biology", "Botany, zoology and human biology."),
    ("English", "English literature, grammar and writing."),
    ("Hindi", "Hindi language, literature and grammar."),
    ("Computer Science", "Programming, data structures and computer fundamentals."),
    ("Accountancy", "Financial accounting, book-keeping and analysis."),
    ("Economics", "Micro, macro and Indian economic development."),
    ("Music", "Vocal and instrumental music, Indian and Western."),
    ("Spoken English", "Conversational fluency, pronunciation and confidence."),
    ("Test Prep", "Competitive and entrance exam preparation."),
]

# Medium-of-instruction options. Regional-language teaching is the clearest
# differentiator this marketplace has in Tier-2/Tier-3 markets, so the set
# leads with the languages with the largest tutoring demand in India.
# Codes are ISO 639-1 (Language.save() lowercases them anyway).
LANGUAGES = [
    ("English", "en"),
    ("Hindi", "hi"),
    ("Bengali", "bn"),
    ("Marathi", "mr"),
    ("Telugu", "te"),
    ("Tamil", "ta"),
    ("Gujarati", "gu"),
    ("Urdu", "ur"),
    ("Kannada", "kn"),
    ("Malayalam", "ml"),
    ("Punjabi", "pa"),
    ("Odia", "or"),
]


class Command(BaseCommand):
    help = "Create the starting Subject and Language rows (idempotent, additive only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing anything.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]

        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be written.\n"))

        with transaction.atomic():
            s_made, s_skipped = self._seed_subjects(dry)
            l_made, l_skipped = self._seed_languages(dry)

            if dry:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Subjects:  {s_made} created, {s_skipped} already present "
                f"({Subject.objects.count()} total)"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Languages: {l_made} created, {l_skipped} already present "
                f"({Language.objects.count()} total)"
            )
        )
        if not dry:
            self.stdout.write("")
            self.stdout.write(
                "Manage these at /super-admin/subjects/ and /super-admin/languages/. "
                "The landing page picks up changes within 5 minutes (taxonomy cache)."
            )

    # ------------------------------------------------------------------
    def _seed_subjects(self, dry):
        made = skipped = 0
        for name, description in SUBJECTS:
            if Subject.objects.filter(name=name).exists():
                skipped += 1
                self.stdout.write(f"  = subject exists: {name}")
                continue
            if not dry:
                # slug is derived in Subject.save()
                Subject.objects.create(
                    name=name, description=description, is_active=True
                )
            made += 1
            self.stdout.write(self.style.SUCCESS(f"  + subject: {name}"))
        return made, skipped

    def _seed_languages(self, dry):
        made = skipped = 0
        for name, code in LANGUAGES:
            # `code` is the stable identity; a name can legitimately be
            # re-spelled by an admin, a code should not be.
            if Language.objects.filter(code=code).exists():
                skipped += 1
                self.stdout.write(f"  = language exists: {name} ({code})")
                continue
            if not dry:
                Language.objects.create(name=name, code=code, is_active=True)
            made += 1
            self.stdout.write(self.style.SUCCESS(f"  + language: {name} ({code})"))
        return made, skipped

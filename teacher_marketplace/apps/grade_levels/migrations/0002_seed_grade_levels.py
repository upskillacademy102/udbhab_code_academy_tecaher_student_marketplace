"""
Seed a sensible starting set of grade/class levels, ordered how they'd
naturally appear in a dropdown (school grades first, then higher
education, then catch-alls) rather than alphabetically.

Same idiom as apps.subjects/apps.languages: get_or_create only, never
overwrites a row an admin has already added/edited, and the reverse
migration only removes rows that still exactly match this seed set.
"""

from django.db import migrations

SEED_GRADE_LEVELS = [
    "Nursery",
    "Class 1",
    "Class 2",
    "Class 3",
    "Class 4",
    "Class 5",
    "Class 6",
    "Class 7",
    "Class 8",
    "Class 9",
    "Class 10",
    "Class 11",
    "Class 12",
    "Undergraduate",
    "Postgraduate",
    "Competitive Exam Prep",
    "Adult Learner",
    "Hobby / Other",
]


def seed_grade_levels(apps, schema_editor):
    GradeLevel = apps.get_model("grade_levels", "GradeLevel")
    for i, name in enumerate(SEED_GRADE_LEVELS):
        GradeLevel.objects.get_or_create(
            name=name, defaults={"sort_order": i, "is_active": True}
        )


def unseed_grade_levels(apps, schema_editor):
    GradeLevel = apps.get_model("grade_levels", "GradeLevel")
    GradeLevel.objects.filter(name__in=SEED_GRADE_LEVELS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("grade_levels", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_grade_levels, unseed_grade_levels),
    ]

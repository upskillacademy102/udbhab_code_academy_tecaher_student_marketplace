"""
Flag the existing subjects that are learned as a skill (an instrument,
a martial art, ...) rather than an academic grade, so the sign-up
"What level?" step can offer Novice/Intermediate/Expert for these
instead of Class 1-5 / Undergraduate / ... .

get_or_create-style safety: only flips is_skill_based on rows that
already exist and match by name (case-insensitive); never creates a
row. An admin can flag/unflag any subject at /super-admin/subjects/
regardless - this just seeds a sane starting set.
"""

from django.db import migrations

SKILL_BASED_SUBJECT_NAMES = [
    "Music",
    "Karate",
    "Kung Fu",
]


def seed_skill_based(apps, schema_editor):
    Subject = apps.get_model("subjects", "Subject")
    for name in SKILL_BASED_SUBJECT_NAMES:
        Subject.objects.filter(name__iexact=name).update(is_skill_based=True)


def unseed_skill_based(apps, schema_editor):
    Subject = apps.get_model("subjects", "Subject")
    for name in SKILL_BASED_SUBJECT_NAMES:
        Subject.objects.filter(name__iexact=name).update(is_skill_based=False)


class Migration(migrations.Migration):

    dependencies = [
        ("subjects", "0003_subject_is_skill_based"),
    ]

    operations = [
        migrations.RunPython(seed_skill_based, unseed_skill_based),
    ]

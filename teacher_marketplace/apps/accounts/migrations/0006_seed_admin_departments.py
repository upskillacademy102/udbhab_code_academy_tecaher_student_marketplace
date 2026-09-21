"""
Seed the starter set of Admin departments a Super Admin picks from when
approving an admin-account request. Not exhaustive - a Super Admin can add
more later from the Departments screen; this just seeds a sane starting set
covering money (Finance), the help desk (Support), teacher/ID checks
(Verification), trust & safety (Content Moderation), and growth (Marketing).

get_or_create-style safety: only creates rows that don't already exist by
name (case-insensitive); never duplicates or overwrites an existing one.
"""

from django.db import migrations
from django.utils.text import slugify

DEPARTMENT_NAMES = [
    "Finance",
    "Support",
    "Verification",
    "Content Moderation",
    "Marketing",
]


def seed_departments(apps, schema_editor):
    AdminDepartment = apps.get_model("accounts", "AdminDepartment")
    for name in DEPARTMENT_NAMES:
        if not AdminDepartment.objects.filter(name__iexact=name).exists():
            AdminDepartment.objects.create(name=name, slug=slugify(name))


def unseed_departments(apps, schema_editor):
    AdminDepartment = apps.get_model("accounts", "AdminDepartment")
    AdminDepartment.objects.filter(name__in=DEPARTMENT_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_user_admin_account_name_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_departments, unseed_departments),
    ]

"""
Seed the single, structural "Learning Partner" department. Unlike the
starter departments in 0006 (Finance, Support, ...), this one is not a
cosmetic label a Super Admin might rename or delete - every individual
partner organisation is one admin User inside this exact department (see
apps.accounts.services.admin_account_naming), so the app-level guards in
AdminDepartmentSerializer/AdminDepartmentDetailView refuse to rename or
delete whichever row has is_learning_partner=True.

get_or_create-style safety, same as 0006: never duplicates or overwrites.
"""

from django.db import migrations
from django.utils.text import slugify

DEPARTMENT_NAME = "Learning Partner"


def seed_department(apps, schema_editor):
    AdminDepartment = apps.get_model("accounts", "AdminDepartment")
    existing = AdminDepartment.objects.filter(name__iexact=DEPARTMENT_NAME).first()
    if existing is None:
        AdminDepartment.objects.create(
            name=DEPARTMENT_NAME,
            slug=slugify(DEPARTMENT_NAME),
            is_learning_partner=True,
        )
    elif not existing.is_learning_partner:
        existing.is_learning_partner = True
        existing.save(update_fields=["is_learning_partner"])


def unseed_department(apps, schema_editor):
    AdminDepartment = apps.get_model("accounts", "AdminDepartment")
    AdminDepartment.objects.filter(name__iexact=DEPARTMENT_NAME, admins__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_adminaccountrequest_organization_name_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_department, unseed_department),
    ]

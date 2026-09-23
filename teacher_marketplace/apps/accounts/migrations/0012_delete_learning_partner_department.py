"""
Learning Partner is a role now (0010/0011), not a department - this removes
the magic, protected "Learning Partner" AdminDepartment row and the
is_learning_partner field entirely, so no department dropdown or management
list has to special-case it ever again.

AdminAccountRequest.department / .requested_department are PROTECTed FKs -
any historical row still pointing at the Learning Partner department (from
before this split) would block the delete below, so those are nulled out
first. They're both nullable and, for a Learning Partner request, no
longer mean anything (there is no department to record).

The RemoveField for is_learning_partner itself is a SEPARATE migration
(0013) rather than folded in here: Postgres won't let a DELETE that fires a
referencing table's FK trigger and a same-table ALTER TABLE share one
transaction ("cannot ALTER TABLE ... because it has pending trigger
events") - splitting across migrations puts them in separate transactions.
"""

from django.db import migrations


def clear_refs_and_delete_department(apps, schema_editor):
    AdminDepartment = apps.get_model("accounts", "AdminDepartment")
    AdminAccountRequest = apps.get_model("accounts", "AdminAccountRequest")

    lp_department = AdminDepartment.objects.filter(is_learning_partner=True).first()
    if lp_department is None:
        return

    AdminAccountRequest.objects.filter(department=lp_department).update(department=None)
    AdminAccountRequest.objects.filter(requested_department=lp_department).update(
        requested_department=None
    )
    lp_department.delete()


def reseed_department(apps, schema_editor):
    from django.utils.text import slugify

    AdminDepartment = apps.get_model("accounts", "AdminDepartment")
    if not AdminDepartment.objects.filter(name__iexact="Learning Partner").exists():
        AdminDepartment.objects.create(
            name="Learning Partner",
            slug=slugify("Learning Partner"),
            is_learning_partner=True,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_migrate_learning_partner_admins_to_role"),
    ]

    operations = [
        migrations.RunPython(
            clear_refs_and_delete_department, reseed_department
        ),
    ]

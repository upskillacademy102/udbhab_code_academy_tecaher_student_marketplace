"""
Data migration: move every existing Learning Partner admin (role=admin,
admin_department pointing at the seeded is_learning_partner=True row) onto
the new role=learning_partner, and clear admin_department - a Learning
Partner was never really "in" a department, that was always a workaround.

Runs after 0010 (the role choice already accepts "learning_partner") and
before 0012 (which removes AdminDepartment.is_learning_partner - this
migration is the last thing that still needs to read it).
"""

from django.db import migrations


def migrate_forward(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(
        role="admin", admin_department__is_learning_partner=True
    ).update(role="learning_partner", admin_department=None)


def migrate_backward(apps, schema_editor):
    AdminDepartment = apps.get_model("accounts", "AdminDepartment")
    User = apps.get_model("accounts", "User")
    lp_department = AdminDepartment.objects.filter(
        is_learning_partner=True
    ).first()
    if lp_department is not None:
        User.objects.filter(role="learning_partner").update(
            role="admin", admin_department=lp_department
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_remove_admindepartment_is_learning_partner_and_more"),
    ]

    operations = [
        migrations.RunPython(migrate_forward, migrate_backward),
    ]

# Hand-written (not via makemigrations) to include ONLY the
# AccountSanctionSource choices addition. `makemigrations trust` also
# detects an unrelated, pre-existing drift on TeacherVerificationItem.key
# (a choices change nobody has migrated yet) - that's out of scope here and
# deliberately left alone rather than bundled into this feature's migration.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("trust", "0014_alter_manualreviewitem_kind_accountsanction_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="accountsanction",
            name="source",
            field=models.CharField(
                choices=[
                    ("manual", "Super Admin action"),
                    (
                        "auto_fake_leads_weekly",
                        "Automatic - fake-lead reports (weekly threshold)",
                    ),
                    (
                        "auto_fake_leads_monthly",
                        "Automatic - fake-lead reports (monthly threshold)",
                    ),
                    (
                        "auto_staff_login_bruteforce",
                        "Automatic - brute-force admin/super-admin login attempts",
                    ),
                ],
                db_index=True,
                default="manual",
                max_length=32,
            ),
        ),
    ]

# Separate migration (own transaction) from 0012's delete - see that
# migration's docstring for why Postgres requires the split.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_delete_learning_partner_department"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="admindepartment",
            name="is_learning_partner",
        ),
    ]

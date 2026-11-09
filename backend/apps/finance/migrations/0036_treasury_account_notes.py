from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0035_shareholder_legacy_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankaccount",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="cashaccount",
            name="notes",
            field=models.TextField(blank=True),
        ),
    ]

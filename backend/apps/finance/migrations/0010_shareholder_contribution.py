from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0009_treasurytransaction_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="shareholder",
            name="contribution",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("trips", "0008_clientverificationcorrection")]

    operations = [
        migrations.AlterField(
            model_name="trip",
            name="reference",
            field=models.CharField(max_length=100, unique=True),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quotations', '0002_proforma_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='quotationline',
            name='tax_mode',
            field=models.CharField(choices=[('HT', 'HT'), ('TTC', 'TTC')], default='HT', max_length=3),
        ),
    ]

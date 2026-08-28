from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("trips", "0004_company_stock_statuses"),
    ]

    operations = [
        migrations.AlterField(
            model_name="trip",
            name="status",
            field=models.CharField(
                choices=[
                    ("ASSIGNED", "Assigned"),
                    ("SENT_FOR_LOADING", "Sent for loading"),
                    ("LOADING", "Loading"),
                    ("LOADED", "Loaded"),
                    ("ROAD_TRANSIT", "Road transit"),
                    ("IN_TRANSIT", "In transit"),
                    ("BORDER", "Border"),
                    ("CUSTOMS", "Customs"),
                    ("GOING_TO_COMPANY_STOCK", "Going to company stock"),
                    ("ARRIVED_AT_COMPANY_STOCK", "Arrived at company stock"),
                    ("STOCKED", "Stocked"),
                    ("GOING_TO_CLIENT", "Going to client"),
                    ("ARRIVED_AT_CLIENT", "Arrived at client"),
                    ("QUANTITY_CONTROL", "Quantity control"),
                    ("DELIVERED", "Delivered"),
                    ("COMPLETED", "Completed"),
                    ("BLOCKED", "Blocked"),
                    ("CANCELLED", "Cancelled"),
                ],
                default="ASSIGNED",
                max_length=30,
            ),
        ),
    ]

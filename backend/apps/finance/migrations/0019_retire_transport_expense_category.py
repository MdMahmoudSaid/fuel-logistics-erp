from django.db import migrations


def retire_transport_category(apps, schema_editor):
    """Transport cost only ever flows through the transporter commission
    (TransportPayment / TripCostService), never a manual trip fee. A manual
    "Transport" Expense reduced trip margin but no debt type could pay it,
    so the money vanished with no way to settle it. Retire the category:
    non-system (so it drops out of the trip-fee picker's ?is_system=true
    list) and inactive (so it drops out of the general-expense ?is_active=
    true list and the serializer rejects it). Existing rows keep their
    category string and still render via Expense.get_category_display().
    """
    ExpenseCategory = apps.get_model("finance", "ExpenseCategory")
    ExpenseCategory.objects.filter(code="transport").update(
        is_system=False, is_active=False
    )


def restore_transport_category(apps, schema_editor):
    ExpenseCategory = apps.get_model("finance", "ExpenseCategory")
    ExpenseCategory.objects.filter(code="transport").update(
        is_system=True, is_active=True
    )


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0018_supplierpayment_is_reversed"),
    ]

    operations = [
        migrations.RunPython(retire_transport_category, restore_transport_category),
    ]

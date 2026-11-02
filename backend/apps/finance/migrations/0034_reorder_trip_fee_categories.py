from django.db import migrations

# Trip fees are listed Chargement, Transit frontière, Transit BMK, Douane, Ts
# (codes: loading, road_transit, transit, road, customs). The five keep the
# display_order slots they already occupy; only their order among themselves changes.
NEW_ORDER = ["loading", "road_transit", "transit", "road", "customs"]


def reorder(apps, schema_editor):
    ExpenseCategory = apps.get_model("finance", "ExpenseCategory")
    rows = {c.code: c for c in ExpenseCategory.objects.filter(code__in=NEW_ORDER)}
    slots = sorted(c.display_order for c in rows.values())
    for code, order in zip([c for c in NEW_ORDER if c in rows], slots):
        ExpenseCategory.objects.filter(pk=rows[code].pk).update(display_order=order)


class Migration(migrations.Migration):
    dependencies = [("finance", "0033_manual_profit")]

    operations = [migrations.RunPython(reorder, migrations.RunPython.noop)]

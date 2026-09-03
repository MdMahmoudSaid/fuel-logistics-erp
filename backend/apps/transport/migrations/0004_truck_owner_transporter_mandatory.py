# Bug fix (2026-09-03 recette manuelle): every Truck must be linked to a
# transporter, even when it belongs to the company - seeds a single
# is_internal=True Transporter ("Flotte propre / Interne"), backfills any
# pre-existing COMPANY_OWNED truck (and its trips) left without one, then
# makes Truck.owner_transporter mandatory at the DB level.

import django.db.models.deletion
from django.db import migrations, models


INTERNAL_TRANSPORTER_NAME = "Flotte propre / Interne"


def seed_internal_transporter_and_backfill(apps, schema_editor):
    Transporter = apps.get_model("transport", "Transporter")
    Truck = apps.get_model("transport", "Truck")
    Trip = apps.get_model("trips", "Trip")

    internal, _created = Transporter.objects.get_or_create(
        is_internal=True,
        defaults={"name": INTERNAL_TRANSPORTER_NAME},
    )

    company_owned_trucks_without_transporter = Truck.objects.filter(
        ownership_type="COMPANY_OWNED", owner_transporter__isnull=True
    )
    truck_ids = list(company_owned_trucks_without_transporter.values_list("id", flat=True))
    company_owned_trucks_without_transporter.update(owner_transporter=internal)

    if truck_ids:
        Trip.objects.filter(truck_id__in=truck_ids, transporter__isnull=True).update(
            transporter=internal
        )


def unseed_internal_transporter(apps, schema_editor):
    # Data-loss safe: only removes the seeded row itself, never touches the
    # trucks/trips it was backfilled onto (their owner_transporter/
    # transporter FK would simply dangle, which Django's reverse migration
    # framework already disallows deleting a row still referenced elsewhere
    # - PROTECT on Truck.owner_transporter enforces this at the DB level
    # too, by the time this migration's schema changes are reversed).
    Transporter = apps.get_model("transport", "Transporter")
    Transporter.objects.filter(is_internal=True, name=INTERNAL_TRANSPORTER_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("transport", "0003_truck_is_active"),
        ("trips", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="transporter",
            name="is_internal",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            seed_internal_transporter_and_backfill, unseed_internal_transporter
        ),
        migrations.AlterField(
            model_name="truck",
            name="owner_transporter",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="trucks",
                to="transport.transporter",
            ),
        ),
    ]

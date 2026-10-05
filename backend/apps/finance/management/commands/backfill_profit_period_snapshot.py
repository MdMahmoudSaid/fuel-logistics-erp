"""One-off: rebuild the closure snapshot of the latest CLOSED profit period
closed before snapshots existed (spec 2026-10-05-periodes-independantes,
section 3.5). Idempotent - does nothing once the period has a snapshot.

Only the latest closed period matters: the open period is measured from it.
Trips sold before its closed_at are snapshotted with their CURRENT figures,
so a change made to them between that closure and this backfill is absorbed
(the distributable profit stays exact; only that adjustment row is not
shown).
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from apps.finance.models import ShareholderProfitDistribution
from apps.finance.profit_periods import (
    ZERO,
    general_expenses_paid_between,
    latest_closed_period,
    take_snapshot,
)
from apps.reports.queries.margin_report import MarginReportQuery
from apps.sales.models import Sale


class Command(BaseCommand):
    help = "Reconstitue la photo de la derniere periode cloturee (une seule fois)."

    @transaction.atomic
    def handle(self, *args, **options):
        period = latest_closed_period()
        if period is None:
            self.stdout.write("Aucune periode cloturee : rien a faire.")
            return
        if period.general_expenses_paid_snapshot is not None:
            self.stdout.write(f"Photo deja presente pour {period} : rien a faire.")
            return

        sold_before = set(
            Sale.objects.filter(created_at__lte=period.closed_at).values_list(
                "trip_id", flat=True
            )
        )
        rows = [row for row in MarginReportQuery.run() if row["trip_id"] in sold_before]
        take_snapshot(period, rows)
        period.general_expenses_paid_snapshot = general_expenses_paid_between(
            None, period.end_date
        )
        period.distributed_total_snapshot = (
            ShareholderProfitDistribution.objects.filter(
                status=ShareholderProfitDistribution.Status.VALIDATED,
                validated_at__lte=period.closed_at,
            ).aggregate(total=Sum("total_profit"))["total"]
            or ZERO
        )
        period.save(
            update_fields=[
                "general_expenses_paid_snapshot", "distributed_total_snapshot", "updated_at",
            ]
        )
        self.stdout.write(
            f"Photo reconstituee pour {period} : {len(rows)} trajet(s), "
            f"depenses generales {period.general_expenses_paid_snapshot}, "
            f"repartitions {period.distributed_total_snapshot}."
        )

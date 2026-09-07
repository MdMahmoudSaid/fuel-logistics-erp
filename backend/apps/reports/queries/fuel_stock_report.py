# FuelStockReportQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.4/9.7).
#
# Row-level breakdown behind TheoreticalStockService.get_total_theoretical_stock():
# one row per active supplier order's reliquat, one row per unsold trip's
# loaded quantity, plus a trailing TOTAL row - so the report and the
# service can never silently disagree on the total.

from apps.purchasing.models import SupplierOrder
from apps.purchasing.services import SupplierStockService
from apps.reports.services.stock import TheoreticalStockService
from apps.trips.models import Trip

FIELDS = ["component", "reference", "quantity"]


class FuelStockReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls) -> list[dict]:
        rows = []
        for order in SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED):
            rows.append(
                {
                    "component": "SUPPLIER_RELIQUAT",
                    "reference": order.reference,
                    "quantity": SupplierStockService.get_purchase_reliquat(order),
                }
            )
        # Mirrors TheoreticalStockService.get_loaded_unsold_quantity()'s own
        # filter exactly (a forced Sale-less DELIVERED/COMPLETED trip is past
        # delivery, not loaded-unsold stock) so these rows always sum to the
        # TOTAL row below.
        for trip in Trip.objects.filter(sale__isnull=True).exclude(
            status__in=Trip.NON_OCCUPYING_STATUSES
        ):
            rows.append(
                {
                    "component": "LOADED_UNSOLD",
                    "reference": trip.reference,
                    "quantity": trip.quantity_loaded,
                }
            )
        rows.append(
            {
                "component": "TOTAL",
                "reference": None,
                "quantity": TheoreticalStockService.get_total_theoretical_stock(),
            }
        )
        return rows

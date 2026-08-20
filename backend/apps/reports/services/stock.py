# Theoretical fuel stock engine (docs/PHASE_6_PLAN.md Etape 3;
# ERP_Implementation_Experience_Guide.md Section 9.4/9.5; plan Section 1.B).
#
# There is no physical central warehouse: fuel is either still sitting with
# a supplier (purchased but not yet authorized to leave via a
# CessionLetter) or loaded on a truck that hasn't produced a Sale yet.
# Both components are computed live from their source transactions - never
# cached - so a cancellation or correction anywhere in the chain can never
# leave the reported stock drifted from reality.

from decimal import Decimal

from django.db.models import Sum

from apps.purchasing.models import SupplierOrder
from apps.purchasing.services import SupplierStockService
from apps.trips.models import Trip

ZERO = Decimal("0.00")


class TheoreticalStockService:
    """Owns every theoretical stock computation (guide Section 9.1's "do
    not scatter formulas throughout serializers and dashboard queries"
    applies here just as much as to TripProfitService)."""

    @staticmethod
    def get_supplier_reliquats() -> Decimal:
        """Sum of SupplierStockService.get_purchase_reliquat() across every
        active (CONFIRMED) supplier order - fuel already purchased but not
        yet authorized to leave the supplier via a CessionLetter. DRAFT
        orders are not yet a committed purchase and CANCELLED ones never
        happened, so neither counts as stock."""
        active_orders = SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED)
        return sum(
            (SupplierStockService.get_purchase_reliquat(order) for order in active_orders),
            ZERO,
        )

    @staticmethod
    def get_loaded_unsold_quantity() -> Decimal:
        """Sum of Trip.quantity_loaded for trips that have not yet produced
        a Sale - fuel leaves theoretical stock exactly when the Sale is
        created (plan Section 1.B), not from trip.status alone (guide
        Section 9.5). Cancelled trips never held stock, mirroring the same
        exclusion SupplierStockService already applies to loaded-quantity
        sums."""
        return (
            Trip.objects.filter(sale__isnull=True)
            .exclude(status=Trip.Status.CANCELLED)
            .aggregate(total=Sum("quantity_loaded"))["total"]
            or ZERO
        )

    @classmethod
    def get_total_theoretical_stock(cls) -> Decimal:
        return cls.get_supplier_reliquats() + cls.get_loaded_unsold_quantity()

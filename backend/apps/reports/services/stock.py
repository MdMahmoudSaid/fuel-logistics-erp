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

from apps.core.request_cache import memoize_per_request
from apps.purchasing.models import SupplierOrder
from apps.purchasing.services import SupplierStockService
from apps.trips.models import Trip
from apps.trips.services import TripCostService

ZERO = Decimal("0.00")

# Client request (2026-09-06): a "pipeline" view of where purchased fuel
# sits and what it's worth at each stage, valued differently at each stage
# (see each method's own docstring for why):
#   reliquat fournisseur -> en cours (chargé, pas arrivé) -> stock entreprise
# and, the instant a trip is delivered to a client, it drops out of all
# three - it becomes a customer receivable (already shown elsewhere on the
# dashboard as the customer's outstanding balance), never company stock.


class TheoreticalStockService:
    """Owns every theoretical stock computation (guide Section 9.1's "do
    not scatter formulas throughout serializers and dashboard queries"
    applies here just as much as to TripProfitService)."""

    @staticmethod
    @memoize_per_request
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

    @classmethod
    @memoize_per_request
    def get_supplier_reliquat_value(cls) -> Decimal:
        """Monetary value of get_supplier_reliquats(), each order's own
        remaining reliquat priced at ITS OWN unit_price - never a single
        blended average across a supplier's orders (client decision,
        2026-09-06: two purchases at two different prices must each keep
        their own price for what's left of them)."""
        active_orders = SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED)
        return sum(
            (
                SupplierStockService.get_purchase_reliquat(order) * order.unit_price
                for order in active_orders
            ),
            ZERO,
        ).quantize(Decimal("0.01"))

    @staticmethod
    @memoize_per_request
    def get_loaded_unsold_quantity() -> Decimal:
        """Sum of Trip.quantity_loaded for trips that have not yet produced
        a Sale - fuel leaves theoretical stock exactly when the Sale is
        created (plan Section 1.B), not from trip.status alone (guide
        Section 9.5). Cancelled trips never held stock, mirroring the same
        exclusion SupplierStockService already applies to loaded-quantity
        sums.

        `sale__isnull=True` alone does NOT mean "still company-held fuel": a
        trip forced to DELIVERED/COMPLETED through the raw status bar (which
        skips the delivery control that creates the Sale) has no Sale row yet
        has physically left for the client - so every non-occupying status
        is excluded here too (regression 2026-09-07 recette)."""
        return (
            Trip.objects.filter(sale__isnull=True)
            .exclude(status__in=Trip.NON_OCCUPYING_STATUSES)
            .aggregate(total=Sum("quantity_loaded"))["total"]
            or ZERO
        )

    @staticmethod
    def _in_transit_trips():
        """Loaded, not sold, not cancelled, and not yet arrived at EITHER
        final destination (company stock or client) - client's own
        definition (2026-09-06): "en cours" is every truck currently on the
        road, whatever its destination, until it physically arrives
        somewhere. Once it arrives at the depot it moves to the company-
        stock bucket below; once it's delivered to a client it drops out of
        both (it's now a customer debt, not company-held fuel).

        A delivered/completed trip drops out on its STATUS, not on
        sale__isnull: the normal delivery flow creates a Sale, but a status
        forced straight to DELIVERED/COMPLETED through the raw status bar
        does not - and that trip is just as done (regression 2026-09-07
        recette: a Sale-less forced completion was still counted "en cours",
        inflating the dashboard card by a whole phantom trip)."""
        return Trip.objects.filter(sale__isnull=True).exclude(
            status__in={
                Trip.Status.ARRIVED_AT_COMPANY_STOCK,
                Trip.Status.STOCKED,
                *Trip.NON_OCCUPYING_STATUSES,
            }
        )

    @classmethod
    @memoize_per_request
    def get_in_transit_quantity(cls) -> Decimal:
        return cls._in_transit_trips().aggregate(total=Sum("quantity_loaded"))["total"] or ZERO

    @classmethod
    @memoize_per_request
    def get_in_transit_value(cls) -> Decimal:
        """Valued at the pure fuel purchase price per litre (client
        decision, 2026-09-06) - trip fees incurred so far are deliberately
        excluded here (unlike company stock below): a trip mid-route hasn't
        necessarily accrued its full cost yet, so this stays comparable to
        the reliquat card above rather than a partial, still-moving cost
        basis."""
        return sum(
            (
                trip.quantity_loaded * trip.supplier_order.unit_price
                for trip in cls._in_transit_trips().select_related("supplier_order")
            ),
            ZERO,
        ).quantize(Decimal("0.01"))

    @staticmethod
    def _company_stock_trips():
        """Mirrors DashboardViewSet.summary()'s own `stock_trips` query
        exactly (apps/reports/views/dashboard.py) so the "Stock entreprise"
        quantity card and this value never diverge from two independently
        maintained filters."""
        return Trip.objects.filter(
            sale__isnull=True,
            destination_type=Trip.DestinationType.COMPANY_STOCK,
            status__in=[Trip.Status.ARRIVED_AT_COMPANY_STOCK, Trip.Status.STOCKED],
        )

    @classmethod
    @memoize_per_request
    def get_company_stock_value(cls) -> Decimal:
        """Valued at each trip's full cost basis - purchase price + transport
        + every allocated expense (TripCostService.calculate_trip_cost_basis,
        the same "prix de revient" already used for the sale-below-cost
        guard and the trip margin breakdown) - client decision, 2026-09-06:
        once fuel has physically reached the depot, its value includes
        everything it cost to get it there, unlike the reliquat/en-cours
        cards above which only ever reflect the raw purchase price."""
        return sum(
            (
                TripCostService.calculate_trip_cost_basis(trip)["total_cost"]
                for trip in cls._company_stock_trips().select_related("supplier_order")
            ),
            ZERO,
        ).quantize(Decimal("0.01"))

    @classmethod
    @memoize_per_request
    def get_total_theoretical_stock(cls) -> Decimal:
        return cls.get_supplier_reliquats() + cls.get_loaded_unsold_quantity()

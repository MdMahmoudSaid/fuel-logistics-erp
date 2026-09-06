# MarginReportQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.1/9.7).
#
# One row per trip that has produced a Sale, delegating every cost/profit
# number to TripProfitService.get_cost_breakdown() so this never duplicates
# a cost or margin formula (guide Section 9.1: "do not scatter
# profitability formulas throughout serializers and dashboard queries";
# client modifications plan Task 3: cost breakdown itself delegates to
# TripCostService.calculate_trip_cost_basis).

from decimal import Decimal

from apps.finance.models import Expense
from apps.reports.services.profit import TripProfitService
from apps.trips.models import Trip

ZERO = Decimal("0.00")

FIELDS = [
    "trip_reference",
    "client",
    "product",
    "quantity",
    "quantity_loaded",
    "quantity_invoiced",
    "transporter_loss_quantity",
    "transporter_loss_indemnity",
    "company_absorbed_loss_quantity",
    "company_absorbed_loss_amount",
    "supplier_unit_price",
    "transport_cost",
    "customs_cost",
    "transit_cost",
    "road_transit_cost",
    "border_cost",
    "loading_cost",
    "additional_costs",
    "real_total_cost",
    "unit_cost",
    "unit_selling_price",
    "unit_profit",
    "current_margin",
]

# Categories counted separately (customs_cost, transit_cost,
# road_transit_cost, border_cost, loading_cost) or already represented by a
# non-Expense field (transport_cost comes from TripCostService/
# TransportPayment, not from Expense) - excluded here so additional_costs
# never double-counts them. border_cost/loading_cost split out
# Expense.Category.ROAD/LOADING (design doc 2026-08-26-benefices-associes-
# refinement-design.md: the Benefices page needs "frais frontiere" and
# "frais chargement" as their own line items, matching docs/finances_edit.md).
# Bug fix (2026-09-03 recette manuelle): ROAD_TRANSIT was missing from this
# set, so a "Transit routiere" fee silently fell into additional_costs
# ("Autres frais") instead of getting its own road_transit_cost line.
_EXCLUDED_FROM_ADDITIONAL_COSTS = {
    Expense.Category.CUSTOMS,
    Expense.Category.TRANSIT,
    Expense.Category.ROAD_TRANSIT,
    Expense.Category.TRANSPORT,
    Expense.Category.ROAD,
    Expense.Category.LOADING,
}


class MarginReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, date_from=None, date_to=None) -> list[dict]:
        trips = (
            Trip.objects.filter(sale__isnull=False)
            .select_related("sale", "sale__customer", "product", "supplier_order")
            .order_by("-loading_date", "-id")
        )
        if date_from:
            trips = trips.filter(loading_date__gte=date_from)
        if date_to:
            trips = trips.filter(loading_date__lte=date_to)

        rows = []
        for trip in trips:
            breakdown = TripProfitService.get_cost_breakdown(trip)
            expenses_by_category = breakdown["expenses_by_category"]
            additional_costs = sum(
                (
                    amount
                    for category, amount in expenses_by_category.items()
                    if category not in _EXCLUDED_FROM_ADDITIONAL_COSTS
                ),
                ZERO,
            )
            rows.append(
                {
                    "trip_reference": trip.reference,
                    "client": trip.sale.customer.name,
                    "product": trip.product.name,
                    "quantity": trip.quantity_loaded,
                    "quantity_loaded": breakdown["quantity_loaded"],
                    "quantity_invoiced": breakdown["quantity_invoiced"],
                    "transporter_loss_quantity": breakdown["transporter_loss_quantity"],
                    "transporter_loss_indemnity": breakdown[
                        "transporter_loss_indemnity"
                    ],
                    "company_absorbed_loss_quantity": breakdown[
                        "company_absorbed_loss_quantity"
                    ],
                    "company_absorbed_loss_amount": breakdown[
                        "company_absorbed_loss_amount"
                    ],
                    "supplier_unit_price": trip.supplier_order.unit_price,
                    "transport_cost": breakdown["transport_cost"],
                    "customs_cost": expenses_by_category.get(Expense.Category.CUSTOMS, ZERO),
                    "transit_cost": expenses_by_category.get(
                        Expense.Category.TRANSIT, ZERO
                    ),
                    "road_transit_cost": expenses_by_category.get(
                        Expense.Category.ROAD_TRANSIT, ZERO
                    ),
                    "border_cost": expenses_by_category.get(Expense.Category.ROAD, ZERO),
                    "loading_cost": expenses_by_category.get(Expense.Category.LOADING, ZERO),
                    "additional_costs": additional_costs,
                    "real_total_cost": breakdown["real_total_cost"],
                    "unit_cost": breakdown["unit_cost"],
                    "unit_selling_price": trip.sale.unit_selling_price,
                    "unit_profit": breakdown["unit_profit"],
                    "current_margin": breakdown["margin"],
                }
            )
        return rows

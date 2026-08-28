# Trip profit engine (docs/PHASE_6_PLAN.md Etape 2;
# ERP_Implementation_Experience_Guide.md Section 9.1/9.2/9.3/1.8).
#
# Margin is never stored - every read walks the trip's current related
# records (Sale, TransportPayment, ExpenseAllocation) and recomputes, so a
# belated expense allocated to an already-delivered trip changes the margin
# on the very next read with no manual recompute step (guide Section 9.3).

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum

from apps.finance.models import (
    Expense,
    ExpenseAllocation,
    TransportDeduction,
    TransportPayment,
)
from apps.sales.models import ProductSellingPriceHistory
from apps.trips.models import Trip
from apps.trips.services import TripCostService

ZERO = Decimal("0.00")


class TripProfitService:
    """Owns every trip margin computation (guide Section 9.1: "do not
    scatter profitability formulas throughout serializers and dashboard
    queries")."""

    @staticmethod
    def _fuel_purchase_cost(trip: Trip) -> Decimal:
        return trip.quantity_loaded * trip.supplier_order.unit_price

    @staticmethod
    def _transport_cost(trip: Trip) -> Decimal:
        """Frais Transport Brut: the gross settlement amount, before loss
        deductions or advances (guide Section 1.5: those are separate
        transactions, not a silent reduction of the transport cost)."""
        return (
            TransportPayment.objects.filter(trip=trip).aggregate(total=Sum("base_amount"))[
                "total"
            ]
            or ZERO
        )

    @staticmethod
    def _transporter_loss_quantity(trip: Trip) -> Decimal:
        return (
            TransportDeduction.objects.filter(trip=trip)
            .exclude(status=TransportDeduction.Status.CANCELLED)
            .aggregate(total=Sum("chargeable_quantity"))["total"]
            or ZERO
        )

    @staticmethod
    def _transporter_loss_indemnity(trip: Trip) -> Decimal:
        return (
            TransportDeduction.objects.filter(trip=trip)
            .exclude(status=TransportDeduction.Status.CANCELLED)
            .aggregate(total=Sum("amount"))["total"]
            or ZERO
        )

    @staticmethod
    def _expense_allocations(trip: Trip):
        return ExpenseAllocation.objects.filter(
            content_type=ContentType.objects.get_for_model(Trip), object_id=trip.id
        ).exclude(expense__status=Expense.Status.CANCELLED)

    @classmethod
    def _total_allocated_expenses(cls, trip: Trip) -> Decimal:
        return (
            cls._expense_allocations(trip).aggregate(total=Sum("allocated_amount"))["total"]
            or ZERO
        )

    @classmethod
    def _expected_unit_price(cls, trip: Trip) -> Decimal | None:
        if trip.customer_order_id and trip.customer_order.expected_price is not None:
            return trip.customer_order.expected_price
        history_qs = ProductSellingPriceHistory.objects.filter(product=trip.product)
        if trip.client_id:
            customer_price = history_qs.filter(customer=trip.client).first()
            if customer_price is not None:
                return customer_price.price
        global_price = history_qs.filter(customer__isnull=True).first()
        return global_price.price if global_price is not None else None

    @classmethod
    def calculate_estimated_margin(cls, trip: Trip) -> Decimal:
        """Before completion: planned fuel cost (already fixed at trip
        creation) against a theoretical selling price (guide Section 9.2)."""
        expected_price = cls._expected_unit_price(trip)
        if expected_price is None:
            raise ValueError(
                f"Aucun prix de vente attendu connu pour le trajet {trip.reference} ; "
                "renseignez CustomerOrder.expected_price ou enregistrez d'abord une "
                "entree ProductSellingPriceHistory."
            )
        revenue = trip.quantity_loaded * expected_price
        return (
            revenue
            - cls._fuel_purchase_cost(trip)
            - cls._transport_cost(trip)
            - cls._total_allocated_expenses(trip)
        ).quantize(Decimal("0.01"))

    @classmethod
    def calculate_current_margin(cls, trip: Trip) -> Decimal:
        """Based on the validated delivery and sale price (guide Section
        9.2). Requires a Sale - "Delivered Quantity is Commercial Truth"
        (guide Section 1.4), there is no current margin before that."""
        return cls.get_cost_breakdown(trip)["margin"]

    @classmethod
    def calculate_final_margin(cls, trip: Trip) -> Decimal:
        """Frozen once the trip is closed (guide Section 9.2: "do not call
        a value final if new expenses are still accepted without
        reopening"). Trip.COMPLETED is the only closing state this phase
        defines, so it is the freeze gate until an explicit reopen workflow
        exists."""
        if trip.status != Trip.Status.COMPLETED:
            raise ValueError(
                f"Le trajet {trip.reference} n'est pas COMPLETED ; seul un trajet "
                "cloture a une marge finale."
            )
        return cls.calculate_current_margin(trip)

    @classmethod
    def get_cost_breakdown(cls, trip: Trip) -> dict:
        """Detailed revenue/cost decomposition for a trip's current margin
        (guide Section 9.1's recommended component list).

        The cost side (fuel/transport/expenses/total_cost/unit_cost) is
        sourced from TripCostService.calculate_trip_cost_basis rather than
        re-derived here (client modifications plan Task 3 / guide Section
        5.5: never duplicate a formula across services) - this method adds
        only what TripCostService doesn't know about: revenue and margin,
        which need the trip's Sale."""
        sale = getattr(trip, "sale", None)
        if sale is None:
            raise ValueError(
                f"Le trajet {trip.reference} n'a pas encore de vente ; impossible de "
                "decomposer ses couts."
            )
        cost_basis = TripCostService.calculate_trip_cost_basis(trip)
        revenue = sale.delivered_quantity * sale.unit_selling_price
        transporter_loss_quantity = cls._transporter_loss_quantity(trip)
        transporter_loss_indemnity = cls._transporter_loss_indemnity(trip)
        real_total_cost = cost_basis["total_cost"]
        margin = (
            revenue + transporter_loss_indemnity - real_total_cost
        ).quantize(Decimal("0.01"))
        unit_cost = cost_basis["unit_cost"]
        unit_profit = sale.unit_selling_price - unit_cost
        return {
            "quantity_loaded": trip.quantity_loaded,
            "quantity_invoiced": sale.delivered_quantity,
            "transporter_loss_quantity": transporter_loss_quantity,
            "transporter_loss_indemnity": transporter_loss_indemnity,
            "revenue": revenue,
            "fuel_purchase_cost": cost_basis["fuel_purchase_cost"],
            "transport_cost": cost_basis["transport_cost"],
            "expenses_by_category": cost_basis["expenses_by_category"],
            "total_expenses": cost_basis["total_expenses"],
            "real_total_cost": real_total_cost,
            "margin": margin,
            "unit_cost": unit_cost,
            "unit_profit": unit_profit,
        }

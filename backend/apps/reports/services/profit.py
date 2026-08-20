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

from apps.finance.models import Expense, ExpenseAllocation, TransportPayment
from apps.sales.models import ProductSellingPriceHistory
from apps.trips.models import Trip

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
        sale = getattr(trip, "sale", None)
        if sale is None:
            raise ValueError(
                f"Le trajet {trip.reference} n'a pas encore de vente ; impossible de "
                "calculer sa marge actuelle."
            )
        revenue = sale.delivered_quantity * sale.unit_selling_price
        return (
            revenue
            - cls._fuel_purchase_cost(trip)
            - cls._transport_cost(trip)
            - cls._total_allocated_expenses(trip)
        ).quantize(Decimal("0.01"))

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
        (guide Section 9.1's recommended component list)."""
        sale = getattr(trip, "sale", None)
        if sale is None:
            raise ValueError(
                f"Le trajet {trip.reference} n'a pas encore de vente ; impossible de "
                "decomposer ses couts."
            )
        expenses_by_category: dict[str, Decimal] = {}
        for allocation in cls._expense_allocations(trip).select_related("expense"):
            category = allocation.expense.category
            expenses_by_category[category] = (
                expenses_by_category.get(category, ZERO) + allocation.allocated_amount
            )
        revenue = sale.delivered_quantity * sale.unit_selling_price
        fuel_purchase_cost = cls._fuel_purchase_cost(trip)
        transport_cost = cls._transport_cost(trip)
        total_expenses = sum(expenses_by_category.values(), ZERO)
        margin = (revenue - fuel_purchase_cost - transport_cost - total_expenses).quantize(
            Decimal("0.01")
        )
        return {
            "revenue": revenue,
            "fuel_purchase_cost": fuel_purchase_cost,
            "transport_cost": transport_cost,
            "expenses_by_category": expenses_by_category,
            "total_expenses": total_expenses,
            "margin": margin,
        }

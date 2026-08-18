# Derived CustomerOrder aggregates and status projection (docs/PHASE_3_PLAN.md
# Etape 4 "Mettre a jour dynamiquement le statut de la commande client
# associee" + ERP_Implementation_Experience_Guide.md Section 6.4 / Section 5.5).
#
# assigned/loaded/delivered/remaining quantities are never stored on
# CustomerOrder - they are always computed from the order's Trip rows so
# cancellations and corrections can never cause drift (guide Section 5.1).
# status is likewise never set directly past CONFIRMED:
# TripWorkflowService.transition_trip() calls recompute_status() after every
# trip status change that touches an order.

from decimal import Decimal

from django.db.models import Sum

from apps.sales.models import CustomerOrder

ZERO = Decimal("0.00")

# Trip statuses reached once the truck has physically loaded product for
# this order (LOADED onward). BLOCKED/CANCELLED are intentionally excluded.
_LOADED_ONWARD_STATUSES = {
    "LOADED",
    "IN_TRANSIT",
    "BORDER",
    "CUSTOMS",
    "GOING_TO_CLIENT",
    "ARRIVED_AT_CLIENT",
    "QUANTITY_CONTROL",
    "DELIVERED",
    "COMPLETED",
}
_DELIVERED_STATUSES = {"DELIVERED", "COMPLETED"}

# Statuses recompute_status() is allowed to move an order between. DRAFT
# (not yet confirmed), CLOSED and CANCELLED are manual lifecycle boundaries
# set by a user action, not by trip aggregation, so they're left untouched.
_AUTO_MANAGED_STATUSES = {
    CustomerOrder.Status.CONFIRMED,
    CustomerOrder.Status.PARTIALLY_ASSIGNED,
    CustomerOrder.Status.IN_PROGRESS,
    CustomerOrder.Status.PARTIALLY_DELIVERED,
    CustomerOrder.Status.DELIVERED,
}


class CustomerOrderService:
    @staticmethod
    def get_assigned_quantity(order: CustomerOrder) -> Decimal:
        """Portion of the order already committed to a truck: the sum of
        quantity_loaded for every non-cancelled trip against this order."""
        return order.trips.exclude(status="CANCELLED").aggregate(
            total=Sum("quantity_loaded")
        )["total"] or ZERO

    @staticmethod
    def get_loaded_quantity(order: CustomerOrder) -> Decimal:
        return order.trips.filter(
            status__in=_LOADED_ONWARD_STATUSES
        ).aggregate(total=Sum("quantity_loaded"))["total"] or ZERO

    @staticmethod
    def get_delivered_quantity(order: CustomerOrder) -> Decimal:
        return order.trips.filter(
            status__in=_DELIVERED_STATUSES
        ).aggregate(total=Sum("quantity_loaded"))["total"] or ZERO

    @staticmethod
    def get_remaining_quantity(order: CustomerOrder) -> Decimal:
        return order.quantity_ordered - CustomerOrderService.get_delivered_quantity(
            order
        )

    @staticmethod
    def recompute_status(order: CustomerOrder) -> CustomerOrder:
        """Derive `order.status` from its trips' current state and persist
        it if it changed. No-op for DRAFT/CLOSED/CANCELLED orders (guide
        roadmap: "Status transitions ... derived by a service function, not
        set manually by users" - but only within the auto-managed range)."""
        if order.status not in _AUTO_MANAGED_STATUSES:
            return order

        assigned = CustomerOrderService.get_assigned_quantity(order)
        delivered = CustomerOrderService.get_delivered_quantity(order)

        if delivered >= order.quantity_ordered:
            target = CustomerOrder.Status.DELIVERED
        elif delivered > ZERO:
            target = CustomerOrder.Status.PARTIALLY_DELIVERED
        elif assigned >= order.quantity_ordered:
            target = CustomerOrder.Status.IN_PROGRESS
        elif assigned > ZERO:
            target = CustomerOrder.Status.PARTIALLY_ASSIGNED
        else:
            target = CustomerOrder.Status.CONFIRMED

        if target != order.status:
            order.status = target
            order.save(update_fields=["status", "updated_at"])
        return order

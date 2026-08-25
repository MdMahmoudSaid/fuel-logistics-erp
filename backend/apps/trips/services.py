# Domain services owning truck availability and the Trip state machine
# (docs/PHASE_3_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 6.8-6.11, Section 15).
#
# Availability is derived from active Trip rows, never trusted from a bare
# `Truck.status` field alone (guide Section 6.11: "Avoid manually maintaining
# contradictory values such as truck.status = AVAILABLE / trip.status =
# IN_TRANSIT"). `Truck.status` is still kept in sync for display/filtering
# convenience, but TruckAvailabilityService is the actual source of truth
# used for locking decisions.

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import LossToleranceConfig
from apps.core.reference import generate_monthly_reference
from apps.finance.models import Expense, ExpenseAllocation, TransportDeduction, TransportPayment
from apps.sales.models import Invoice, ProductSellingPriceHistory, Sale
from apps.sales.services import CustomerOrderService
from apps.transport.models import Transporter, Truck
from apps.trips.models import DeliveryControl, Trip, TripStatusHistory


_INVOICE_REFERENCE_PREFIX = "FAC"
_MAX_INVOICE_REFERENCE_ATTEMPTS = 5

_ZERO = Decimal("0.00")


class InvalidTripTransition(ValueError):
    """Raised when a requested Trip status transition isn't allowed."""


class CustomerAlreadySoldError(ValueError):
    """Raised when TripCostService.assign_customer_for_sale() is called on
    a trip that already has a Sale - the customer for a sold trip is fixed
    at delivery time (DeliveryService.record_delivery), never mutated
    after the fact."""


class DeliveryAnomalyConfirmationRequired(ValueError):
    """Raised when received_quantity > loaded_quantity and no authorized
    user has explicitly signed off on the anomaly (plan Section 1.D;
    guide Section 7.3: automatic confirmation must stop, an authorized
    manual confirmation is required)."""


class SellingPriceNotConfigured(ValueError):
    """Raised when a delivery is confirmed but no
    ProductSellingPriceHistory entry (customer-specific or global) exists
    yet for the trip's product, so DeliveryService has no price to suggest
    for the Sale it must create."""


class SaleBelowCostConfirmationRequired(ValueError):
    """Raised when the delivery's unit selling price is below the trip's
    unit cost (TripCostService.calculate_trip_cost_basis) and no confirm_loss
    flag was supplied - a loss-making sale can still be recorded, but only
    once an operator has explicitly acknowledged it (same confirm-then-
    proceed pattern as DeliveryAnomalyConfirmationRequired above)."""


class TruckAvailabilityService:
    @staticmethod
    def is_truck_available(truck_id) -> bool:
        """True if the truck has no trip in a non-terminal, non-delivered
        status (Trip.NON_OCCUPYING_STATUSES)."""
        return not (
            Trip.objects.filter(truck_id=truck_id)
            .exclude(status__in=Trip.NON_OCCUPYING_STATUSES)
            .exists()
        )

    @staticmethod
    def get_active_trip(truck_id):
        """The truck's current in-progress trip, if any (most recent first)."""
        return (
            Trip.objects.filter(truck_id=truck_id)
            .exclude(status__in=Trip.NON_OCCUPYING_STATUSES)
            .order_by("-created_at")
            .first()
        )

    @staticmethod
    def get_available_trucks():
        """QuerySet of trucks with no active trip."""
        active_truck_ids = Trip.objects.exclude(
            status__in=Trip.NON_OCCUPYING_STATUSES
        ).values_list("truck_id", flat=True)
        return Truck.objects.exclude(pk__in=active_truck_ids)


class TransporterAvailabilityService:
    """Same "no trip in a non-terminal, non-delivered status" rule as
    TruckAvailabilityService, applied to Transporter (TripForm's "Afficher
    les camions occupes" toggle filters both pickers together)."""

    @staticmethod
    def get_available_transporters():
        """QuerySet of transporters with no active trip."""
        active_transporter_ids = Trip.objects.exclude(
            status__in=Trip.NON_OCCUPYING_STATUSES
        ).values_list("transporter_id", flat=True)
        return Transporter.objects.exclude(pk__in=active_transporter_ids)


class TripCostService:
    """Owns a trip's cost basis (fuel + transport + allocated expenses) and
    direct-customer assignment (Task 1 of the client modifications plan).

    Deliberately separate from TripProfitService (apps.reports.services.
    profit): that service computes *margin*, which requires a Sale/revenue
    and is unavailable before delivery. A trip's cost basis, by contrast,
    is knowable as soon as it's loaded - callers (later tasks: pricing
    suggestions, company-stock valuation) need it long before any Sale
    exists, so it must not share that precondition.
    """

    @staticmethod
    def _fuel_purchase_cost(trip: Trip) -> Decimal:
        return trip.quantity_loaded * trip.supplier_order.unit_price

    @staticmethod
    def _transport_cost(trip: Trip) -> Decimal:
        return (
            TransportPayment.objects.filter(trip=trip).aggregate(total=Sum("base_amount"))[
                "total"
            ]
            or _ZERO
        )

    @staticmethod
    def _expenses_by_category(trip: Trip) -> dict:
        allocations = (
            ExpenseAllocation.objects.filter(
                content_type=ContentType.objects.get_for_model(Trip), object_id=trip.id
            )
            .exclude(expense__status=Expense.Status.CANCELLED)
            .select_related("expense")
        )
        breakdown: dict[str, Decimal] = {}
        for allocation in allocations:
            category = allocation.expense.category
            breakdown[category] = breakdown.get(category, _ZERO) + allocation.allocated_amount
        return breakdown

    @classmethod
    def calculate_trip_cost_basis(cls, trip: Trip) -> dict:
        """Detailed cost decomposition for `trip`, computed live from its
        related records and never stored (same "recompute on every read"
        convention as TripProfitService.get_cost_breakdown, guide Section
        9.3) - a belated expense allocation changes this on the very next
        read with no manual recompute step.

        Later tasks consume `unit_cost`, `total_cost` and
        `expenses_by_category` by these exact key names - do not rename.
        """
        fuel_purchase_cost = cls._fuel_purchase_cost(trip)
        transport_cost = cls._transport_cost(trip)
        expenses_by_category = cls._expenses_by_category(trip)
        total_expenses = sum(expenses_by_category.values(), _ZERO)
        total_cost = fuel_purchase_cost + transport_cost + total_expenses
        unit_cost = total_cost / trip.quantity_loaded
        return {
            "fuel_purchase_cost": fuel_purchase_cost,
            "transport_cost": transport_cost,
            "expenses_by_category": expenses_by_category,
            "total_expenses": total_expenses,
            "total_cost": total_cost,
            "quantity": trip.quantity_loaded,
            "unit_cost": unit_cost,
        }

    @staticmethod
    @transaction.atomic
    def assign_customer_for_sale(trip_id, customer_id, actor) -> Trip:
        """Attach/replace `trip`'s direct customer (Trip.client), under a
        row lock (same concurrency convention as
        TripWorkflowService.transition_trip, guide Section 15).

        A trip is not required to have a client at creation (plan Global
        Constraints: COMPANY_STOCK is a valid, first-class state) - this is
        how one gets assigned later, e.g. once company stock is earmarked
        for a customer. Rejected once the trip already has a Sale: the
        sold customer is fixed at delivery time and must never be mutated
        after the fact.

        `actor` is accepted (rather than only `trip_id`/`customer_id`) to
        match the actor-carrying signature every other Trip-mutating
        service method in this module uses. Not yet written anywhere -
        reserved for a future audit trail entry (no TripClientHistory model
        exists yet, same situation apps.audit was in for the truck
        force-override log before AuditLog landed).
        """
        trip = Trip.objects.select_for_update().get(pk=trip_id)

        if hasattr(trip, "sale"):
            raise CustomerAlreadySoldError(
                f"Le trajet {trip.reference} a deja une vente enregistree ; "
                "impossible de modifier son client."
            )

        trip.client_id = customer_id
        trip.destination_type = Trip.DestinationType.CUSTOMER
        trip.save(update_fields=["client", "destination_type", "updated_at"])
        return trip


class TripWorkflowService:
    """Owns every Trip.status mutation (docs/PHASE_3_PLAN.md Etape 4;
    guide Section 6.8: "Do not allow arbitrary trip.status = ...; trigger
    domain-side effects; commit atomically.").
    """

    # Forward "happy path" sequence (plan Section 1.C / guide Section 6.9).
    FORWARD_TRANSITIONS = {
        Trip.Status.ASSIGNED: Trip.Status.SENT_FOR_LOADING,
        Trip.Status.SENT_FOR_LOADING: Trip.Status.LOADING,
        Trip.Status.LOADING: Trip.Status.LOADED,
        Trip.Status.LOADED: Trip.Status.IN_TRANSIT,
        Trip.Status.IN_TRANSIT: Trip.Status.BORDER,
        Trip.Status.BORDER: Trip.Status.CUSTOMS,
        Trip.Status.CUSTOMS: Trip.Status.GOING_TO_CLIENT,
        Trip.Status.GOING_TO_CLIENT: Trip.Status.ARRIVED_AT_CLIENT,
        Trip.Status.ARRIVED_AT_CLIENT: Trip.Status.QUANTITY_CONTROL,
        Trip.Status.QUANTITY_CONTROL: Trip.Status.DELIVERED,
        Trip.Status.DELIVERED: Trip.Status.COMPLETED,
    }

    # "Statuts eligibles (avant livraison) -> CANCELLED": every forward-path
    # status up to (but excluding) DELIVERED - once delivered, the trip is
    # commercially real and Phase 3 has no reversal flow yet (guide Section 17
    # favours reversal over silent mutation past that point; that reversal
    # flow is a later phase's job, not this one's).
    CANCELLABLE_FROM = set(FORWARD_TRANSITIONS.keys()) - {Trip.Status.DELIVERED}

    @classmethod
    def get_allowed_targets(cls, trip: Trip) -> set:
        """Valid next statuses for `trip`, given its current status and (for
        BLOCKED) the status it was blocked from."""
        current_status = trip.status
        allowed = set()

        forward = cls.FORWARD_TRANSITIONS.get(current_status)
        if forward:
            allowed.add(forward)

        if current_status in cls.CANCELLABLE_FROM:
            allowed.add(Trip.Status.CANCELLED)

        if current_status == Trip.Status.BLOCKED:
            # "BLOCKED -> statut de retour autorise": resume exactly the
            # status the trip was blocked from, not an arbitrary status.
            resume_status = cls._status_before_blocked(trip)
            if resume_status:
                allowed.add(resume_status)
        elif current_status not in Trip.TERMINAL_STATUSES:
            # "Tout statut initial -> BLOCKED (exceptionnel)".
            allowed.add(Trip.Status.BLOCKED)

        return allowed

    @staticmethod
    def _status_before_blocked(trip: Trip):
        last_block_entry = (
            trip.status_history.filter(new_status=Trip.Status.BLOCKED)
            .order_by("-changed_at", "-id")
            .first()
        )
        return last_block_entry.previous_status if last_block_entry else None

    @classmethod
    @transaction.atomic
    def transition_trip(cls, trip_id, target_status, actor, notes=""):
        """Move `trip_id` to `target_status`, recording history and
        triggering side effects, all under a row lock on the Trip.

        Never call `trip.status = x; trip.save()` directly - every status
        change must go through this method (guide Section 6.8).
        """
        trip = Trip.objects.select_for_update().get(pk=trip_id)
        current_status = trip.status

        if target_status == current_status:
            raise InvalidTripTransition(
                f"Le trajet {trip.reference} est deja au statut {current_status}."
            )

        allowed = cls.get_allowed_targets(trip)
        if target_status not in allowed:
            raise InvalidTripTransition(
                f"Impossible de faire passer le trajet {trip.reference} de "
                f"{current_status} a {target_status}."
            )

        previous_status = trip.status
        trip.status = target_status
        trip.save(update_fields=["status", "updated_at"])

        TripStatusHistory.objects.create(
            trip=trip,
            previous_status=previous_status,
            new_status=target_status,
            changed_by=actor,
            notes=notes,
        )

        if target_status in Trip.TERMINAL_STATUSES:
            # Only release the truck if it has no other active trip - an
            # admin-forced concurrent assignment (plan Section 1.D) can leave
            # a second active trip on the same truck.
            if TruckAvailabilityService.is_truck_available(trip.truck_id):
                Truck.objects.filter(pk=trip.truck_id).update(
                    status=Truck.Status.AVAILABLE
                )

        if trip.customer_order_id:
            CustomerOrderService.recompute_status(trip.customer_order)

        return trip


class DeliveryService:
    """Confirms the delivery/discharge of a Trip: quantity control, loss
    calculation, transporter deduction and the resulting Sale/Invoice, all
    inside one atomic transaction (docs/PHASE_4_PLAN.md Etape 5;
    ERP_Implementation_Experience_Guide.md Section 13's "Confirm Delivery"
    transaction boundary example).
    """

    @staticmethod
    def get_latest_selling_price(product_id, customer_id) -> Decimal | None:
        """Latest applicable price for (product, customer), falling back to
        the latest global (customer=None) price for the product (guide
        Section 7.8: "suggest latest applicable price"), or None if neither
        exists yet. Used both to pre-fill the delivery form's price field
        and, wrapped by `_suggest_selling_price`, to resolve the Sale's
        price when the caller doesn't supply an override."""
        customer_specific = (
            ProductSellingPriceHistory.objects.filter(
                product_id=product_id, customer_id=customer_id
            )
            .order_by("-effective_at", "-id")
            .first()
        )
        if customer_specific:
            return customer_specific.price

        global_price = (
            ProductSellingPriceHistory.objects.filter(
                product_id=product_id, customer__isnull=True
            )
            .order_by("-effective_at", "-id")
            .first()
        )
        return global_price.price if global_price else None

    @staticmethod
    def _suggest_selling_price(product_id, customer_id) -> Decimal:
        price = DeliveryService.get_latest_selling_price(product_id, customer_id)
        if price is not None:
            return price

        raise SellingPriceNotConfigured(
            "Aucun prix de vente configure pour ce produit/client - "
            "ajoutez une entree ProductSellingPriceHistory avant de confirmer la livraison."
        )

    @staticmethod
    @transaction.atomic
    def record_delivery(
        trip_id,
        received_qty: Decimal,
        control_date,
        method,
        controller,
        anomaly_confirmed_by=None,
        document=None,
        notes="",
        unit_selling_price: Decimal | None = None,
        confirm_loss: bool = False,
    ) -> DeliveryControl:
        """Confirm discharge for `trip_id`, under a row lock on the Trip
        (guide Section 15). Creates DeliveryControl, an optional
        TransportDeduction (chargeable loss > 0 only) and the resulting
        Sale + DRAFT Invoice - all or nothing.

        `unit_selling_price`, when given, comes from the delivery form's
        "Prix de vente unitaire" field: it's used directly for the Sale,
        and appended as a new customer-specific ProductSellingPriceHistory
        entry (unless it matches the current latest price already) so the
        next delivery for this product/customer picks it up as the
        suggestion. Left None, the existing latest-price lookup applies and
        still raises SellingPriceNotConfigured if nothing is on file.

        `confirm_loss` (client modifications plan Task 3): when the
        resolved `unit_selling_price` is below the trip's unit cost
        (TripCostService.calculate_trip_cost_basis), the Sale is only
        created once this is explicitly set - otherwise
        SaleBelowCostConfirmationRequired is raised so the caller can warn
        and ask for confirmation before retrying.
        """
        trip = Trip.objects.select_for_update().get(pk=trip_id)

        if received_qty > trip.quantity_loaded and anomaly_confirmed_by is None:
            raise DeliveryAnomalyConfirmationRequired(
                f"La quantite recue ({received_qty} L) depasse la quantite "
                f"chargee ({trip.quantity_loaded} L) pour le trajet "
                f"{trip.reference} ; une confirmation par un utilisateur "
                "autorise (anomaly_confirmed_by) est requise."
            )

        customer = trip.client or (
            trip.customer_order.customer if trip.customer_order_id else None
        )
        if customer is None:
            raise ValueError(
                f"Le trajet {trip.reference} n'a ni client direct ni commande "
                "client - impossible de determiner le client de la vente."
            )

        # Resolve the selling price before mutating anything, so a missing
        # price configuration never leaves a half-confirmed delivery behind.
        if unit_selling_price is not None:
            current_price = DeliveryService.get_latest_selling_price(
                trip.product_id, customer.id
            )
            if current_price != unit_selling_price:
                ProductSellingPriceHistory.objects.create(
                    product=trip.product,
                    customer=customer,
                    price=unit_selling_price,
                    changed_by=controller,
                )
        else:
            unit_selling_price = DeliveryService._suggest_selling_price(
                trip.product_id, customer.id
            )

        tolerance = LossToleranceConfig.get_current_tolerance()

        control = DeliveryControl.objects.create(
            trip=trip,
            loaded_quantity=trip.quantity_loaded,
            received_quantity=received_qty,
            tolerance_quantity=tolerance,
            control_date=control_date,
            controller=controller,
            method=method,
            document=document,
            notes=notes,
            anomaly_confirmed_by=anomaly_confirmed_by,
            anomaly_confirmed_at=timezone.now() if anomaly_confirmed_by else None,
        )

        TripWorkflowService.transition_trip(trip.id, Trip.Status.DELIVERED, controller)

        if control.chargeable_loss_quantity > 0:
            TransportDeduction.objects.create(
                trip=trip,
                transporter=trip.transporter,
                chargeable_quantity=control.chargeable_loss_quantity,
                unit_price=trip.supplier_order.unit_price,
            )

        unit_cost = TripCostService.calculate_trip_cost_basis(trip)["unit_cost"]
        if unit_selling_price < unit_cost and not confirm_loss:
            raise SaleBelowCostConfirmationRequired(
                f"Le prix de vente unitaire ({unit_selling_price}) est inferieur au prix de "
                f"revient ({unit_cost}) pour le trajet {trip.reference} ; renvoyez "
                "confirm_loss=true pour confirmer une vente a perte."
            )

        sale = Sale.objects.create(
            trip=trip,
            customer=customer,
            product=trip.product,
            delivered_quantity=received_qty,
            unit_selling_price=unit_selling_price,
        )

        invoice = None
        for _ in range(_MAX_INVOICE_REFERENCE_ATTEMPTS):
            invoice_number = generate_monthly_reference(
                Invoice, "invoice_number", _INVOICE_REFERENCE_PREFIX
            )
            try:
                with transaction.atomic():
                    invoice = Invoice.objects.create(
                        invoice_number=invoice_number,
                        sale=sale,
                        total_amount=sale.subtotal,
                        issued_date=control_date,
                    )
                break
            except IntegrityError:
                continue
        else:
            raise IntegrityError(
                "Impossible de generer un numero de facture unique apres "
                f"{_MAX_INVOICE_REFERENCE_ATTEMPTS} tentatives."
            )

        return control

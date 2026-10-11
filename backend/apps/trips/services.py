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

import uuid
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.request_cache import memoize_per_request
from apps.core.models import LossToleranceConfig
from apps.core.reference import generate_monthly_reference
from apps.finance.models import Expense, ExpenseAllocation, TransportDeduction, TransportPayment
from apps.sales.models import Invoice, InvoiceCorrection, ProductSellingPriceHistory, Sale
from apps.sales.services import CustomerOrderService, InvoiceService
from apps.transport.models import Transporter, Truck
from apps.trips.models import (
    ClientVerificationCorrection,
    DeliveryControl,
    Trip,
    TripCustomerRefusal,
    TripStatusHistory,
)


_INVOICE_REFERENCE_PREFIX = "FAC"
_MAX_INVOICE_REFERENCE_ATTEMPTS = 5

_ZERO = Decimal("0.00")
_UNIT = Decimal("0.0001")


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
    @memoize_per_request
    def _transport_cost(trip: Trip) -> Decimal:
        return (
            TransportPayment.objects.filter(trip=trip).aggregate(total=Sum("base_amount"))[
                "total"
            ]
            or _ZERO
        )

    @staticmethod
    @memoize_per_request
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
    def prime_cost_bases(cls, trips) -> None:
        """Compute _transport_cost and _expenses_by_category for every trip
        of a list page in two queries (instead of two per trip) and hand
        them to the per-request read cache. Same filters as the two
        helpers above - keep them in step."""
        trips = [
            trip
            for trip in trips
            if trip.pk is not None
            and not (cls._transport_cost.is_cached(trip) and cls._expenses_by_category.is_cached(trip))
        ]
        if not trips:
            return
        ids = [trip.id for trip in trips]
        transport = dict(
            TransportPayment.objects.filter(trip_id__in=ids)
            .values("trip_id")
            .annotate(total=Sum("base_amount"))
            .values_list("trip_id", "total")
        )
        expenses: dict[int, dict[str, Decimal]] = {trip_id: {} for trip_id in ids}
        allocations = (
            ExpenseAllocation.objects.filter(
                content_type=ContentType.objects.get_for_model(Trip), object_id__in=ids
            )
            .exclude(expense__status=Expense.Status.CANCELLED)
            .select_related("expense")
        )
        for allocation in allocations:
            breakdown = expenses[allocation.object_id]
            category = allocation.expense.category
            breakdown[category] = breakdown.get(category, _ZERO) + allocation.allocated_amount
        for trip in trips:
            cls._transport_cost.prime(transport.get(trip.id) or _ZERO, trip)
            cls._expenses_by_category.prime(expenses[trip.id], trip)

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
        unit_expenses = {
            category: (amount / trip.quantity_loaded).quantize(_UNIT)
            for category, amount in expenses_by_category.items()
        }
        unit_components_per_litre = {
            "supplier": trip.supplier_order.unit_price.quantize(_UNIT),
            "commission_transporter": (transport_cost / trip.quantity_loaded).quantize(_UNIT),
            "transit": unit_expenses.get(Expense.Category.TRANSIT, _ZERO).quantize(_UNIT),
            "road_transit": unit_expenses.get(Expense.Category.ROAD_TRANSIT, _ZERO).quantize(_UNIT),
            "border": unit_expenses.get(Expense.Category.ROAD, _ZERO).quantize(_UNIT),
            "customs": unit_expenses.get(Expense.Category.CUSTOMS, _ZERO).quantize(_UNIT),
            "loading": unit_expenses.get(Expense.Category.LOADING, _ZERO).quantize(_UNIT),
        }
        known_expense_categories = {
            Expense.Category.TRANSIT,
            Expense.Category.ROAD_TRANSIT,
            Expense.Category.ROAD,
            Expense.Category.CUSTOMS,
            Expense.Category.LOADING,
        }
        unit_components_per_litre["other"] = sum(
            (
                unit
                for category, unit in unit_expenses.items()
                if category not in known_expense_categories
            ),
            _ZERO,
        ).quantize(_UNIT)
        return {
            "fuel_purchase_cost": fuel_purchase_cost,
            "transport_cost": transport_cost,
            "expenses_by_category": expenses_by_category,
            "total_expenses": total_expenses,
            "total_cost": total_cost,
            "quantity": trip.quantity_loaded,
            "unit_cost": unit_cost,
            "unit_components_per_litre": unit_components_per_litre,
        }

    @classmethod
    def compare_unit_selling_price(cls, trip: Trip, unit_selling_price: Decimal) -> dict:
        unit_cost = cls.calculate_trip_cost_basis(trip)["unit_cost"]
        unit_selling_price = unit_selling_price.quantize(_UNIT)
        unit_result = (unit_selling_price - unit_cost).quantize(_UNIT)
        if unit_result < _ZERO:
            result_type = "loss"
        elif unit_result == _ZERO:
            result_type = "break_even"
        else:
            result_type = "profit"
        return {
            "unit_cost": unit_cost,
            "unit_selling_price": unit_selling_price,
            "unit_result": unit_result,
            "result_type": result_type,
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
        trip.invoice_group = ""
        trip.save(
            update_fields=["client", "destination_type", "invoice_group", "updated_at"]
        )
        return trip


    @staticmethod
    @transaction.atomic
    def assign_customers_group_for_sale(trip_ids, customer_id, actor) -> list:
        """Assign one customer to several trips billed on ONE invoice
        (client request 2026-09-25). Same rules as assign_customer_for_sale
        for every trip; with 2+ trips they also share an `invoice_group`
        token that DeliveryService uses to put their Sales on one invoice."""
        trip_ids = list(dict.fromkeys(trip_ids))
        trips = list(Trip.objects.select_for_update().filter(pk__in=trip_ids).order_by("id"))
        if len(trips) != len(trip_ids):
            raise ValueError("Un ou plusieurs trajets sont introuvables.")
        for trip in trips:
            if hasattr(trip, "sale"):
                raise CustomerAlreadySoldError(
                    f"Le trajet {trip.reference} a deja une vente enregistree ; "
                    "impossible de modifier son client."
                )
        group = str(uuid.uuid4()) if len(trips) > 1 else ""
        for trip in trips:
            trip.client_id = customer_id
            trip.destination_type = Trip.DestinationType.CUSTOMER
            trip.invoice_group = group
            trip.save(
                update_fields=["client", "destination_type", "invoice_group", "updated_at"]
            )
        return trips


class TripCancellationService:
    """Reverses every financial side effect a Trip accumulated, called by
    TripWorkflowService.transition_trip right before a trip is marked
    CANCELLED (bug fix, 2026-09-03 recette manuelle: cancelling a trip used
    to leave its fees/transport debt fully active - see the "Phase 3 has no
    reversal flow yet" note this replaces, below).

    Deliberately does NOT touch `trip.supplier_order`: a SupplierOrder is a
    purchasing document that can supply several trips (its reliquat is
    shared, guide purchasing docs) - it is not owned exclusively by this
    trip, so cancelling one trip must never alter another trip's fuel debt
    or consume/release its advance. Only the two records this trip
    exclusively owns - its allocated Expense fees and its own
    TransportPayment - are reversed here.
    """

    @staticmethod
    @transaction.atomic
    def reverse_trip_financials(trip: Trip, actor) -> None:
        # Imported lazily to avoid a circular import at module load time
        # (apps.finance.services -> apps.reports.queries.margin_report ->
        # apps.reports.services.profit -> apps.trips.services) - same
        # pattern already used by TransportPayment.save() in
        # apps.finance.models for the identical reason.
        from apps.finance.services import (
            ExpensePostingService,
            TransportPaymentCancellationService,
        )

        content_type = ContentType.objects.get_for_model(Trip)
        allocations = (
            ExpenseAllocation.objects.filter(content_type=content_type, object_id=trip.id)
            .select_related("expense")
        )
        seen_expense_ids = set()
        for allocation in allocations:
            expense = allocation.expense
            if expense.id in seen_expense_ids or expense.status == Expense.Status.CANCELLED:
                continue
            seen_expense_ids.add(expense.id)
            if expense.status == Expense.Status.UNPAID:
                # cancel_paid_expense() rejects UNPAID (meant for a direct,
                # single-expense cancel request where "just delete it
                # instead" is the right answer) - here the trip itself is
                # being cancelled, so the unpaid fee must go with it.
                Expense.objects.filter(pk=expense.pk).update(
                    status=Expense.Status.CANCELLED, updated_at=timezone.now()
                )
            else:
                ExpensePostingService.cancel_paid_expense(expense, actor)

        for payment in TransportPayment.objects.filter(trip=trip).exclude(
            status=TransportPayment.Status.CANCELLED
        ):
            TransportPaymentCancellationService.cancel_transport_payment(payment, actor)


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
        Trip.Status.LOADED: Trip.Status.ROAD_TRANSIT,
        Trip.Status.ROAD_TRANSIT: Trip.Status.IN_TRANSIT,
        Trip.Status.IN_TRANSIT: Trip.Status.BORDER,
        Trip.Status.BORDER: Trip.Status.CUSTOMS,
        Trip.Status.CUSTOMS: Trip.Status.ARRIVED_AT_CLIENT,
        # Client correction (2026-09-04 recette): quantity control is no
        # longer a mandatory gate before delivery - a trip is delivered
        # directly from ARRIVED_AT_CLIENT, defaulting to "full quantity
        # received". The QUANTITY_CONTROL entry below stays mapped for any
        # trip that predates this change and is still sitting at that
        # status - it is otherwise unreachable going forward.
        Trip.Status.ARRIVED_AT_CLIENT: Trip.Status.DELIVERED,
        Trip.Status.QUANTITY_CONTROL: Trip.Status.DELIVERED,
        Trip.Status.DELIVERED: Trip.Status.COMPLETED,
        Trip.Status.ARRIVED_AT_COMPANY_STOCK: Trip.Status.STOCKED,
    }

    # "Statuts eligibles (avant livraison) -> CANCELLED": every forward-path
    # status up to (but excluding) DELIVERED - once delivered, the trip is
    # commercially real (has a Sale) and there is still no reversal flow for
    # that (guide Section 17 favours reversal over silent mutation past that
    # point; a post-delivery reversal is a separate, larger feature - Sale/
    # Invoice/stock unwind - not just financial reversal). Every status here
    # is pre-Sale, so TripCancellationService.reverse_trip_financials only
    # ever needs to reverse fees/transport debt, never a Sale.
    CANCELLABLE_FROM = set(FORWARD_TRANSITIONS.keys()) - {Trip.Status.DELIVERED}

    @classmethod
    def _next_step(cls, trip: Trip, status):
        """The single forward status after `status` for this trip, resolving
        the client/stock fork: a trip with neither a client nor a customer
        order leaves CUSTOMS for the company stock instead of a client."""
        has_customer = bool(trip.client_id or trip.customer_order_id)
        if status == Trip.Status.STOCKED:
            return Trip.Status.ARRIVED_AT_CLIENT if has_customer else None
        forward = cls.FORWARD_TRANSITIONS.get(status)
        if forward == Trip.Status.ARRIVED_AT_CLIENT and not has_customer:
            return Trip.Status.ARRIVED_AT_COMPANY_STOCK
        return forward

    @classmethod
    def _skip_path(cls, trip: Trip) -> list:
        """Statuses reachable by moving forward from trip.status, in order.
        Stops before DELIVERED/COMPLETED: those are only ever entered one step
        at a time by their own forms (delivery control, client verification)."""
        path = []
        status = trip.status
        while True:
            status = cls._next_step(trip, status)
            if status is None or status in {Trip.Status.DELIVERED, Trip.Status.COMPLETED}:
                return path
            path.append(status)

    @classmethod
    def get_path_to(cls, trip: Trip, target_status) -> list:
        """Statuses a transition to `target_status` walks through (target
        last); [] when the target isn't allowed from the trip's status."""
        if target_status not in cls.get_allowed_targets(trip):
            return []
        skip_path = cls._skip_path(trip)
        if target_status in skip_path:
            return skip_path[: skip_path.index(target_status) + 1]
        return [target_status]

    @classmethod
    def get_allowed_targets(cls, trip: Trip) -> set:
        """Valid next statuses for `trip`, given its current status and (for
        BLOCKED) the status it was blocked from."""
        current_status = trip.status
        allowed = set()

        forward = cls._next_step(trip, current_status)
        if forward:
            allowed.add(forward)
            allowed.update(cls._skip_path(trip))

        if current_status in cls.CANCELLABLE_FROM:
            allowed.add(Trip.Status.CANCELLED)

        if current_status == Trip.Status.BLOCKED:
            # "BLOCKED -> statut de retour autorise": resume exactly the
            # status the trip was blocked from, not an arbitrary status.
            resume_status = cls._status_before_blocked(trip)
            if resume_status:
                allowed.add(resume_status)
        elif current_status not in Trip.TERMINAL_STATUSES and current_status != Trip.Status.STOCKED:
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
        if not last_block_entry:
            return None
        previous = last_block_entry.previous_status
        return Trip.RETIRED_STATUS_REMAP.get(previous, previous)

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

        path = cls.get_path_to(trip, target_status)
        if not path:
            raise InvalidTripTransition(
                f"Impossible de faire passer le trajet {trip.reference} de "
                f"{current_status} a {target_status}."
            )

        previous_status = trip.status
        trip.status = target_status
        trip.save(update_fields=["status", "updated_at"])

        # One history row per traversed status keeps the audit trail complete
        # when several statuses are skipped in one action; the note rides on
        # the last row (the status the user actually picked).
        step_from = previous_status
        for index, step in enumerate(path):
            TripStatusHistory.objects.create(
                trip=trip,
                previous_status=step_from,
                new_status=step,
                changed_by=actor,
                notes=notes if index == len(path) - 1 else "",
            )
            step_from = step
        trip.traversed_statuses = path

        if target_status == Trip.Status.CANCELLED:
            TripCancellationService.reverse_trip_financials(trip, actor)

        # Bug fix (2026-09-03 recette manuelle): was
        # "TERMINAL_STATUSES or STOCKED" - a second, independent definition
        # of "which statuses free the truck" that had drifted from
        # Trip.NON_OCCUPYING_STATUSES (the one TruckAvailabilityService
        # actually queries against) and incorrectly included STOCKED - a
        # trip's fuel sitting in company stock is not the same as the
        # truck having completed a delivery. Reusing the same set here
        # keeps both in permanent agreement.
        if target_status in Trip.NON_OCCUPYING_STATUSES:
            # Only release the truck if it has no other active trip - an
            # admin-forced concurrent assignment (plan Section 1.D) can leave
            # a second active trip on the same truck.
            if TruckAvailabilityService.is_truck_available(trip.truck_id):
                Truck.objects.filter(pk=trip.truck_id).update(
                    status=Truck.Status.AVAILABLE
                )

        if trip.customer_order_id:
            CustomerOrderService.recompute_status(trip.customer_order)

        # Client request 2026-10-11: a completed trip's invoice is validated
        # (payable) at once instead of lingering as DRAFT.
        if target_status == Trip.Status.COMPLETED:
            sale = Sale.objects.filter(trip=trip).first()
            invoice = sale.billing_invoice if sale else None
            if invoice is not None:
                InvoiceService.validate_if_trips_completed(invoice.id, actor)

        # A cancelled trip no longer holds back its group's invoice: if the
        # other trips were all delivered already, bill them now.
        if target_status == Trip.Status.CANCELLED and trip.invoice_group and trip.client_id:
            DeliveryService.bill_group_if_complete(
                trip.invoice_group, trip.client, issued_date=timezone.localdate()
            )

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
    def _create_invoice(sale: Sale, issued_date, *, extra_sales=()) -> Invoice:
        """Create the DRAFT invoice of `sale` (plus, for a multi-trip
        invoice, the `extra_sales` grouped onto it)."""
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
                        issued_date=issued_date,
                    )
                break
            except IntegrityError:
                continue
        else:
            raise IntegrityError(
                "Impossible de generer un numero de facture unique apres "
                f"{_MAX_INVOICE_REFERENCE_ATTEMPTS} tentatives."
            )
        for extra in extra_sales:
            extra.grouped_invoice = invoice
            extra.save(update_fields=["grouped_invoice", "updated_at"])
        if extra_sales:
            invoice.recompute_total()
        return invoice

    @staticmethod
    def bill_group_if_complete(invoice_group, customer, issued_date):
        """Create the ONE invoice of a multi-trip group once no trip of the
        group is still waiting for its delivery (a cancelled trip no longer
        counts - see TripWorkflowService.transition_trip). Until then the
        delivered trips' Sales simply wait, un-invoiced, so an invoice is
        never created half-complete and grown afterwards."""
        waiting = (
            Trip.objects.filter(invoice_group=invoice_group, sale__isnull=True)
            .exclude(status=Trip.Status.CANCELLED)
            .exists()
        )
        if waiting:
            return None
        unbilled = list(
            Sale.objects.filter(
                trip__invoice_group=invoice_group,
                customer=customer,
                invoice__isnull=True,
                grouped_invoice__isnull=True,
            ).order_by("id")
        )
        if not unbilled:
            return None
        invoice = DeliveryService._create_invoice(
            unbilled[0], issued_date, extra_sales=unbilled[1:]
        )
        # Billed after a trip of the group was cancelled: the remaining
        # trips may all be COMPLETED already.
        return InvoiceService.validate_if_trips_completed(invoice.id, None) or invoice

    @staticmethod
    @transaction.atomic
    def record_delivery(
        trip_id,
        *,
        received_qty: Decimal | None = None,
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

        `received_qty` (client correction, 2026-09-04 recette): optional -
        left None, it defaults to the trip's `quantity_loaded` ("full
        quantity received, zero loss"). A trip now delivers directly from
        ARRIVED_AT_CLIENT without a mandatory QUANTITY_CONTROL step; any
        real-world discrepancy is corrected later via a separate
        post-delivery verification flow, not this method.

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

        if received_qty is None:
            received_qty = trip.quantity_loaded

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

        DeliveryService.sync_transport_shortage_deduction(
            trip=trip,
            received_qty=received_qty,
            unit_selling_price=unit_selling_price,
        )

        price_result = TripCostService.compare_unit_selling_price(trip, unit_selling_price)
        if price_result["result_type"] == "loss" and not confirm_loss:
            raise SaleBelowCostConfirmationRequired(
                f"Le prix de vente unitaire ({unit_selling_price}) est inferieur au prix de "
                f"revient ({price_result['unit_cost']}) pour le trajet {trip.reference} ; renvoyez "
                "confirm_loss=true pour confirmer une vente a perte."
            )

        sale = Sale.objects.create(
            trip=trip,
            customer=customer,
            product=trip.product,
            delivered_quantity=received_qty,
            unit_selling_price=unit_selling_price,
        )

        # Multi-trip invoice: a trip assigned as part of a group is NOT
        # invoiced on its own - the group's single invoice is created only
        # once every trip of the group has been delivered.
        if trip.invoice_group:
            DeliveryService.bill_group_if_complete(
                trip.invoice_group, customer, issued_date=control_date
            )
        else:
            DeliveryService._create_invoice(sale, control_date)

        return control

    @staticmethod
    @transaction.atomic
    def record_client_verification(
        trip_id, received_qty: Decimal, verified_at, actor, notes: str = ""
    ) -> DeliveryControl:
        """Post-delivery client quantity check (client modifications
        2026-09-04): updates the DeliveryControl created at delivery time
        (defaulted to full quantity_loaded) with what the client actually
        reports having received. Spec 2026-09-07: the corrected received
        quantity is now propagated to the Sale + Invoice via
        InvoiceService.adjust_delivered_quantity (DRAFT -> direct edit,
        VALIDATED -> audited InvoiceCorrection, (partially) paid / cancelled
        -> InvoicePaidCorrectionUnsupported, surfaced as a 400 by the view).
        The below-tolerance loss is now reflected by the reduced revenue
        (the invoice bills the received quantity); TripProfitService only
        *exposes* company_absorbed_loss_amount for display, it does not
        subtract it. The loss above tolerance re-syncs the existing
        TransportDeduction mechanism.
        """
        trip = Trip.objects.select_for_update().get(pk=trip_id)
        if trip.status not in (Trip.Status.DELIVERED, Trip.Status.COMPLETED):
            raise ValueError(
                f"Le trajet {trip.reference} doit etre livre ou termine pour "
                "enregistrer une verification client."
            )
        try:
            control = DeliveryControl.objects.select_for_update().get(trip=trip)
        except DeliveryControl.DoesNotExist:
            raise ValueError(
                f"Le trajet {trip.reference} n'a pas de controle de livraison "
                "a corriger."
            )

        # Bug fix (recette corrections 2026-09-05): a trip could previously
        # be verified twice, silently overwriting the client's first
        # declaration with a second free-text submission - a correction
        # after the fact must go through a separate, audited action (not
        # implemented in this pass), never a second call to this endpoint.
        if control.verified_at is not None:
            raise ValueError(
                f"Le trajet {trip.reference} a deja une verification client "
                "enregistree le "
                f"{control.verified_at.isoformat()}."
            )

        control.received_quantity = received_qty
        control.verified_at = verified_at
        control.notes = notes
        control.save(
            update_fields=[
                "received_quantity", "verified_at", "notes",
                "loss_quantity", "chargeable_loss_quantity", "updated_at",
            ]
        )

        sale = getattr(trip, "sale", None)
        # The invoice guard is defensive-only: record_delivery always creates
        # the Invoice, so a Sale without one is not a supported state.
        if sale is not None and sale.billing_invoice is not None:
            # Spec 2026-09-07: the client pays for what actually arrived.
            # Propagate the corrected quantity to the Sale + Invoice (DRAFT
            # -> direct, VALIDATED -> audited, PAID -> refused).
            InvoiceService.adjust_delivered_quantity(
                sale.billing_invoice.id,
                received_qty,
                sale_id=sale.id,
                reason=(
                    "Vérification client : quantité reçue corrigée de "
                    f"{sale.delivered_quantity} L à {received_qty} L"
                ),
                actor=actor,
            )
            sale.refresh_from_db()

        DeliveryService.sync_transport_shortage_deduction(
            trip=trip,
            received_qty=received_qty,
            unit_selling_price=sale.unit_selling_price if sale else Decimal("0.0000"),
        )

        # Feature (client request 2026-09-06): the client verification is
        # the operator's final word on what was actually delivered - close
        # the trip immediately instead of leaving it dangling in DELIVERED
        # until someone remembers to flip the status by hand (which used to
        # let the "Declarer une perte" button linger and invite a second,
        # unrelated declaration). Always closes, regardless of whether the
        # loss is zero, below tolerance, or above it - the client's own
        # instruction: once this quantity is confirmed and saved, the trip
        # is done. Reuses TripWorkflowService.transition_trip() so every
        # side effect of a manual completion (TripStatusHistory row,
        # freeing the truck, CustomerOrder recompute) still happens.
        # No-op if the trip was already manually completed before this
        # verification was recorded (transition_trip's own precondition
        # already lets that case through above).
        if trip.status != Trip.Status.COMPLETED:
            TripWorkflowService.transition_trip(
                trip.id,
                Trip.Status.COMPLETED,
                actor,
                notes="Cloture automatique apres verification client",
            )

        return control

    @staticmethod
    @transaction.atomic
    def correct_client_verification(
        trip_id, received_qty: Decimal, reason: str, actor
    ) -> DeliveryControl:
        """Audited correction of an already-recorded client verification
        (feedback 2026-09-10: the "Declarer une perte" button's wording led
        operators to type the loss instead of the received quantity, with
        no way to fix the mistake afterwards - record_client_verification()
        deliberately refuses a second call, see its docstring). Unlike that
        first call, this one is explicitly a correction: it requires a
        reason, logs a ClientVerificationCorrection row, and is gated behind
        the "validate" permission tier (same bar as an invoice correction)
        rather than the routine "edit" tier.

        Re-propagates to the Sale + Invoice exactly like
        record_client_verification() does (DRAFT -> direct edit, VALIDATED
        -> audited InvoiceCorrection, (partially) paid/cancelled -> raises),
        and re-syncs the TransportDeduction for the new quantity.
        """
        trip = Trip.objects.select_for_update().get(pk=trip_id)
        try:
            control = DeliveryControl.objects.select_for_update().get(trip=trip)
        except DeliveryControl.DoesNotExist:
            raise ValueError(
                f"Le trajet {trip.reference} n'a pas de controle de livraison "
                "a corriger."
            )

        if control.verified_at is None:
            raise ValueError(
                f"Le trajet {trip.reference} n'a pas encore de verification "
                "client enregistree - utilisez d'abord la verification "
                "client, pas sa correction."
            )

        previous_qty = control.received_quantity
        if received_qty == previous_qty:
            return control

        control.received_quantity = received_qty
        control.save(
            update_fields=[
                "received_quantity", "loss_quantity", "chargeable_loss_quantity",
                "updated_at",
            ]
        )

        sale = getattr(trip, "sale", None)
        if sale is not None and sale.billing_invoice is not None:
            InvoiceService.adjust_delivered_quantity(
                sale.billing_invoice.id,
                received_qty,
                sale_id=sale.id,
                reason=reason,
                actor=actor,
            )
            sale.refresh_from_db()

        DeliveryService.sync_transport_shortage_deduction(
            trip=trip,
            received_qty=received_qty,
            unit_selling_price=sale.unit_selling_price if sale else Decimal("0.0000"),
        )

        ClientVerificationCorrection.objects.create(
            trip=trip,
            previous_received_quantity=previous_qty,
            new_received_quantity=received_qty,
            corrected_by=actor,
            reason=reason,
        )

        return control

    @staticmethod
    def sync_transport_shortage_deduction(
        *, trip: Trip, received_qty: Decimal, unit_selling_price: Decimal
    ) -> None:
        # CONFIRMED BUSINESS RULE (client, 2026-09-06) - NOT a bug, do not
        # "fix" this to use trip.supplier_order.unit_price: the chargeable
        # transporter loss is deliberately valued at the customer's sale
        # price (`unit_selling_price`), not the supplier's purchase cost.
        # Example confirmed with the client: 300 L facturables x 900 XOF/L
        # (prix de vente client) = 270,000 XOF. See
        # test_transport_deduction_is_valued_at_customer_sale_price_not_
        # supplier_cost (apps.trips.tests) for the locked-in regression.
        #
        # Bug fix (2026-09-03 recette manuelle): a company-owned truck's
        # trip is now linked to the seeded internal transporter (never
        # None - see Trip.transporter docstring), but it still must never
        # be charged for a shortfall - a chargeable shortfall on it is a
        # plain unrecovered loss (reflected only in the lower delivered
        # quantity), never a TransportDeduction. trip.transporter_id is
        # None is kept as a defensive fallback for any trip that predates
        # this fix.
        if trip.transporter_id is None or trip.transporter.is_internal:
            return

        # Bug fix (recette corrections Task 3, 2026-09-04): this previously
        # charged the transporter for the FULL missing quantity, ignoring
        # tolerance entirely. The loss within tolerance is a company-absorbed
        # cost (never billable), matching DeliveryControl.chargeable_loss_
        # quantity's own tolerance-aware computation - only the loss above
        # tolerance is chargeable here.
        #
        # Bug fix (recette corrections Task 3 review, 2026-09-04): use the
        # tolerance already frozen on this trip's DeliveryControl
        # (tolerance_quantity - "gel historique", see its docstring) rather
        # than re-fetching LossToleranceConfig.get_current_tolerance() live.
        # By the time this method runs - both from record_delivery (right
        # after the DeliveryControl is created) and from
        # record_client_verification (which requires one to already exist) -
        # trip.delivery_control always exists. Fetching live here would let
        # this method's TransportDeduction.chargeable_quantity drift from
        # DeliveryControl.chargeable_loss_quantity if the global default
        # tolerance changes between delivery and a later client verification,
        # breaking the company_absorbed_loss_quantity + chargeable_loss_quantity
        # == total loss invariant.
        tolerance = trip.delivery_control.tolerance_quantity
        missing_quantity = max(
            (trip.quantity_loaded - received_qty) - tolerance, Decimal("0.00")
        ).quantize(Decimal("0.01"))
        deductions = list(
            TransportDeduction.objects.select_for_update().filter(trip=trip).order_by("id")
        )

        if missing_quantity <= _ZERO:
            for deduction in deductions:
                deduction.delete()
            DeliveryService._sync_transport_payment_deductions(trip)
            return

        if deductions:
            deduction = deductions[0]
            deduction.transporter = trip.transporter
            deduction.chargeable_quantity = missing_quantity
            deduction.unit_price = unit_selling_price
            deduction.save(
                update_fields=[
                    "transporter",
                    "chargeable_quantity",
                    "unit_price",
                    "amount",
                    "updated_at",
                ]
            )
            for duplicate in deductions[1:]:
                duplicate.delete()
        else:
            TransportDeduction.objects.create(
                trip=trip,
                transporter=trip.transporter,
                chargeable_quantity=missing_quantity,
                unit_price=unit_selling_price,
            )

        DeliveryService._sync_transport_payment_deductions(trip)

    @staticmethod
    def _sync_transport_payment_deductions(trip: Trip) -> None:
        total_deduction = (
            TransportDeduction.objects.filter(trip=trip).aggregate(total=Sum("amount"))["total"]
            or _ZERO
        )
        for payment in TransportPayment.objects.select_for_update().filter(trip=trip):
            payment.deduction_amount = total_deduction
            payment.save(update_fields=["deduction_amount", "net_amount", "updated_at"])


def _money(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".00", "") + " XOF"


class TripCustomerRefusalService:
    """The customer a trip was assigned to does not want it (client request
    2026-10-11). Two outcomes, both recorded as a TripCustomerRefusal:

    - RETURN_TO_STOCK (only before delivery - no sale, no invoice yet): the
      trip loses its customer and heads for / stays in the company stock;
    - CHANGE_CUSTOMER: the trip is handed to another customer. Once
      delivered, its sale and invoice follow it at the new customer's price,
      so the former customer keeps neither the trip nor any invoice for it:
      his receipts imputed on it come back to him as open credit, which is
      redistributed on his own open debts (no treasury row moves - the cash
      came in once). An invoice that grouped several trips is split: the
      refused trip leaves it for an invoice of its own.
    """

    @staticmethod
    def current_customer(trip: Trip):
        if trip.client_id:
            return trip.client
        return trip.customer_order.customer if trip.customer_order_id else None

    @staticmethod
    def _checked(trip: Trip, action, customer_id):
        """Shared guards: returns (old customer, new customer or None, sale
        or None) or raises ValueError."""
        from apps.customers.models import Customer

        old_customer = TripCustomerRefusalService.current_customer(trip)
        if old_customer is None:
            raise ValueError(f"Le trajet {trip.reference} n'est attribué à aucun client.")
        if trip.status == Trip.Status.CANCELLED:
            raise ValueError(f"Le trajet {trip.reference} est annulé.")
        if trip.status == Trip.Status.BLOCKED:
            raise ValueError(
                f"Le trajet {trip.reference} est bloqué ; débloquez-le avant de traiter le refus."
            )
        sale = Sale.objects.filter(trip=trip).first()
        if action == TripCustomerRefusal.Action.RETURN_TO_STOCK:
            if sale is not None:
                raise ValueError(
                    f"Le trajet {trip.reference} est déjà livré : il ne peut plus revenir au "
                    "stock, seul un changement de client est possible."
                )
            return old_customer, None, None
        if action != TripCustomerRefusal.Action.CHANGE_CUSTOMER:
            raise ValueError("Action de refus inconnue.")
        try:
            new_customer = Customer.objects.get(pk=int(customer_id))
        except (Customer.DoesNotExist, TypeError, ValueError):
            raise ValueError("Choisissez le nouveau client.")
        if new_customer.id == old_customer.id:
            raise ValueError("Choisissez un client différent du client actuel.")
        if not new_customer.is_active:
            raise ValueError(f"Le client {new_customer.name} est inactif.")
        if sale is not None:
            invoice = sale.billing_invoice
            if invoice is not None and invoice.status == Invoice.Status.CANCELLED:
                raise ValueError(f"La facture {invoice.invoice_number} de ce trajet est annulée.")
        return old_customer, new_customer, sale

    @staticmethod
    def _price(value, fallback: Decimal) -> Decimal:
        if value in (None, ""):
            return fallback
        try:
            price = Decimal(str(value)).quantize(_UNIT)
        except (ArithmeticError, ValueError):
            raise ValueError("Le prix de vente unitaire est invalide.")
        if price < 0:
            raise ValueError("Le prix de vente unitaire ne peut pas être négatif.")
        return price

    @staticmethod
    def _paid_on(invoice) -> Decimal:
        if invoice is None:
            return _ZERO
        return (
            invoice.allocations.filter(payment__is_reversed=False).aggregate(t=Sum("amount"))["t"]
            or _ZERO
        )

    @staticmethod
    def preview(trip_id, action, customer_id=None, unit_selling_price=None) -> dict:
        """What refuse() would do, without doing it (balances: positive =
        owed to us) - shown to the operator before he confirms."""
        from apps.finance.services import PaymentAllocationService

        trip = Trip.objects.get(pk=trip_id)
        old_customer, new_customer, sale = TripCustomerRefusalService._checked(
            trip, action, customer_id
        )
        old_balance = PaymentAllocationService.get_customer_outstanding(old_customer)
        result = {
            "trip_reference": trip.reference,
            "action": action,
            "delivered": sale is not None,
            "status_after": TripCustomerRefusalService._status_after(trip, action),
            "invoice_number": None,
            "grouped": False,
            "quantity": None,
            "current_unit_price": None,
            "suggested_unit_price": None,
            "unit_price": None,
            "old_amount": "0.00",
            "new_amount": "0.00",
            "released_payments": "0.00",
            "old_customer": {
                "id": old_customer.id,
                "name": old_customer.name,
                "balance_before": str(old_balance),
                "balance_after": str(old_balance),
            },
            "new_customer": None,
        }
        if new_customer is None:
            return result
        suggested = DeliveryService.get_latest_selling_price(trip.product_id, new_customer.id)
        new_balance = PaymentAllocationService.get_customer_outstanding(new_customer)
        new_side = {
            "id": new_customer.id,
            "name": new_customer.name,
            "balance_before": str(new_balance),
            "balance_after": str(new_balance),
            "credit_applied": "0.00",
        }
        result["new_customer"] = new_side
        result["suggested_unit_price"] = str(suggested) if suggested is not None else None
        if sale is None:
            return result

        invoice = sale.billing_invoice
        price = TripCustomerRefusalService._price(
            unit_selling_price, suggested if suggested is not None else sale.unit_selling_price
        )
        new_amount = (sale.delivered_quantity * price).quantize(Decimal("0.01"))
        old_amount = sale.subtotal if invoice is not None else _ZERO
        group_total_after = (invoice.total_amount - sale.subtotal) if invoice else _ZERO
        released = max(_ZERO, TripCustomerRefusalService._paid_on(invoice) - group_total_after)
        payable = (
            invoice is not None and invoice.status != Invoice.Status.DRAFT
        ) or trip.status == Trip.Status.COMPLETED
        credit = PaymentAllocationService.get_customer_available_credit(new_customer)
        result.update(
            invoice_number=invoice.invoice_number if invoice else None,
            grouped=invoice is not None and len(invoice.all_sales) > 1,
            quantity=str(sale.delivered_quantity),
            current_unit_price=str(sale.unit_selling_price),
            unit_price=str(price),
            old_amount=str(old_amount),
            new_amount=str(new_amount),
            released_payments=str(released),
        )
        result["old_customer"]["balance_after"] = str(old_balance - old_amount)
        new_side["balance_after"] = str(new_balance + new_amount)
        new_side["credit_applied"] = str(min(credit, new_amount) if payable else _ZERO)
        return result

    @staticmethod
    def _status_after(trip: Trip, action) -> str:
        if action == TripCustomerRefusal.Action.RETURN_TO_STOCK and trip.status in (
            Trip.Status.ARRIVED_AT_CLIENT,
            Trip.Status.QUANTITY_CONTROL,
        ):
            return Trip.Status.ARRIVED_AT_COMPANY_STOCK
        return trip.status

    @staticmethod
    @transaction.atomic
    def refuse(trip_id, action, reason, actor, customer_id=None, unit_selling_price=None) -> Trip:
        from apps.finance.services import PaymentAllocationService

        trip = Trip.objects.select_for_update().get(pk=trip_id)
        if not str(reason or "").strip():
            raise ValueError("Le motif du refus est obligatoire.")
        old_customer, new_customer, sale = TripCustomerRefusalService._checked(
            trip, action, customer_id
        )
        old_order = trip.customer_order if trip.customer_order_id else None
        old_group = trip.invoice_group
        refusal = TripCustomerRefusal(
            trip=trip,
            action=action,
            previous_customer=old_customer,
            new_customer=new_customer,
            reason=reason,
            recorded_by=actor,
        )

        if sale is not None:
            TripCustomerRefusalService._move_sale(
                trip, sale, old_customer, new_customer, reason, actor, unit_selling_price, refusal
            )

        if new_customer is None:
            trip.client = None
            trip.customer_order = None
            trip.destination_type = Trip.DestinationType.COMPANY_STOCK
        else:
            trip.client = new_customer
            trip.destination_type = Trip.DestinationType.CUSTOMER
            if old_order is not None and old_order.customer_id != new_customer.id:
                trip.customer_order = None
        trip.invoice_group = ""
        previous_status = trip.status
        trip.status = TripCustomerRefusalService._status_after(trip, action)
        trip.save(
            update_fields=[
                "client", "customer_order", "destination_type", "invoice_group", "status",
                "updated_at",
            ]
        )
        if trip.status != previous_status:
            TripStatusHistory.objects.create(
                trip=trip,
                previous_status=previous_status,
                new_status=trip.status,
                changed_by=actor,
                notes=f"Refus du client {old_customer.name} : retour au stock",
            )
        if old_order is not None and trip.customer_order_id != old_order.id:
            CustomerOrderService.recompute_status(old_order)

        # The trips left in the refused trip's group may now all be
        # delivered: their invoice no longer waits for this one.
        if old_group:
            DeliveryService.bill_group_if_complete(
                old_group, old_customer, issued_date=timezone.localdate()
            )

        PaymentAllocationService.apply_customer_credit_to_open_invoices(old_customer)
        if new_customer is not None:
            PaymentAllocationService.apply_customer_credit_to_open_invoices(new_customer)

        refusal.save()
        return trip

    @staticmethod
    def _move_sale(trip, sale, old_customer, new_customer, reason, actor, unit_price, refusal):
        """Hand a delivered trip's Sale (and its invoice amount) to
        `new_customer`. A single-trip invoice moves as a whole; a grouped
        invoice is split, the refused trip getting an invoice of its own."""
        sale = Sale.objects.select_for_update().get(pk=sale.pk)
        invoice = sale.billing_invoice
        if invoice is not None:
            invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        suggested = DeliveryService.get_latest_selling_price(trip.product_id, new_customer.id)
        price = TripCustomerRefusalService._price(
            unit_price, suggested if suggested is not None else sale.unit_selling_price
        )
        previous_price = sale.unit_selling_price
        refusal.previous_unit_price = previous_price
        refusal.new_unit_price = price

        # The former customer's receipts on the invoice become open credit
        # again; whatever the invoice still needs is re-imputed afterwards.
        released = []
        if invoice is not None:
            released = list(invoice.allocations.filter(payment__is_reversed=False).select_for_update())
        paid = sum((a.amount for a in released), _ZERO)
        for allocation in released:
            allocation.invoice = None
            allocation.save(update_fields=["invoice", "updated_at"])

        grouped = invoice is None or len(invoice.all_sales) > 1
        if invoice is not None and grouped:
            others = [s for s in invoice.all_sales if s.id != sale.id]
            if invoice.sale_id == sale.id:
                successor = others[0]
                successor.grouped_invoice = None
                successor.save(update_fields=["grouped_invoice", "updated_at"])
                invoice.sale = successor
                invoice.save(update_fields=["sale", "updated_at"])
            else:
                sale.grouped_invoice = None
                sale.save(update_fields=["grouped_invoice", "updated_at"])
            invoice.recompute_total()
            TripCustomerRefusalService._reopen(invoice)
            InvoiceCorrection.objects.create(
                invoice=invoice,
                field_name="trip_removed",
                previous_value=trip.reference,
                new_value=new_customer.name[:100],
                corrected_by=actor,
                reason=reason,
            )
            refusal.released_amount = max(_ZERO, paid - invoice.total_amount)
        else:
            refusal.released_amount = paid

        sale.customer = new_customer
        sale.unit_selling_price = price
        sale.save()  # recomputes subtotal

        if grouped:
            # A trip still waiting for its group (no invoice yet) or split
            # off one: it is billed on its own now that it left the group.
            target = DeliveryService._create_invoice(sale, timezone.localdate())
            was_payable = invoice is not None and invoice.status != Invoice.Status.DRAFT
            if was_payable or trip.status == Trip.Status.COMPLETED:
                InvoiceService.validate_invoice(target.id, actor)
        else:
            # Reloaded: `invoice.sale` still holds the pre-move Sale.
            target = Invoice.objects.select_for_update().get(pk=invoice.pk)
            target.recompute_total()
            TripCustomerRefusalService._reopen(target)
        refusal.invoice_number = target.invoice_number

        note = reason
        if refusal.released_amount > _ZERO:
            note = (
                f"{reason}\n(paiements de {old_customer.name} libérés en avance : "
                f"{_money(refusal.released_amount)})"
            )
        InvoiceCorrection.objects.create(
            invoice=target,
            field_name="customer",
            previous_value=old_customer.name[:100],
            new_value=new_customer.name[:100],
            corrected_by=actor,
            reason=note,
        )
        if price != previous_price:
            InvoiceCorrection.objects.create(
                invoice=target,
                field_name="unit_selling_price",
                previous_value=str(previous_price),
                new_value=str(price),
                corrected_by=actor,
                reason=reason,
            )
            if DeliveryService.get_latest_selling_price(trip.product_id, new_customer.id) != price:
                ProductSellingPriceHistory.objects.create(
                    product=trip.product, customer=new_customer, price=price, changed_by=actor
                )

    @staticmethod
    def _reopen(invoice) -> None:
        """A (partly) paid invoice whose receipts were just released is owed
        again in full until credit is re-imputed on it."""
        if invoice.status in (Invoice.Status.PARTIALLY_PAID, Invoice.Status.PAID):
            invoice.status = Invoice.Status.VALIDATED
            invoice.save(update_fields=["status", "updated_at"])

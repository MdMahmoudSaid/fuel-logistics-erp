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

from django.db import transaction

from apps.sales.services import CustomerOrderService
from apps.transport.models import Truck
from apps.trips.models import Trip, TripStatusHistory


class InvalidTripTransition(ValueError):
    """Raised when a requested Trip status transition isn't allowed."""


class TruckAvailabilityService:
    @staticmethod
    def is_truck_available(truck_id) -> bool:
        """True if the truck has no trip in a non-terminal status."""
        return not (
            Trip.objects.filter(truck_id=truck_id)
            .exclude(status__in=Trip.TERMINAL_STATUSES)
            .exists()
        )

    @staticmethod
    def get_active_trip(truck_id):
        """The truck's current in-progress trip, if any (most recent first)."""
        return (
            Trip.objects.filter(truck_id=truck_id)
            .exclude(status__in=Trip.TERMINAL_STATUSES)
            .order_by("-created_at")
            .first()
        )

    @staticmethod
    def get_available_trucks():
        """QuerySet of trucks with no active trip."""
        active_truck_ids = Trip.objects.exclude(
            status__in=Trip.TERMINAL_STATUSES
        ).values_list("truck_id", flat=True)
        return Truck.objects.exclude(pk__in=active_truck_ids)


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
                f"Trip {trip.reference} is already in status {current_status}."
            )

        allowed = cls.get_allowed_targets(trip)
        if target_status not in allowed:
            raise InvalidTripTransition(
                f"Cannot transition trip {trip.reference} from "
                f"{current_status} to {target_status}."
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

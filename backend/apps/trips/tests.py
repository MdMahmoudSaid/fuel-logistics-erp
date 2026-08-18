from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import CustomerOrder
from apps.sales.services import CustomerOrderService
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip, TripStatusHistory
from apps.trips.services import (
    InvalidTripTransition,
    TripWorkflowService,
    TruckAvailabilityService,
)

# Full happy-path sequence starting right after ASSIGNED (the default status
# a newly created Trip already has).
FULL_SEQUENCE_AFTER_ASSIGNED = [
    Trip.Status.SENT_FOR_LOADING,
    Trip.Status.LOADING,
    Trip.Status.LOADED,
    Trip.Status.IN_TRANSIT,
    Trip.Status.BORDER,
    Trip.Status.CUSTOMS,
    Trip.Status.GOING_TO_CLIENT,
    Trip.Status.ARRIVED_AT_CLIENT,
    Trip.Status.QUANTITY_CONTROL,
    Trip.Status.DELIVERED,
    Trip.Status.COMPLETED,
]


def _setup_fixtures(order_suffix="001"):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        email=f"admin-trip-{order_suffix}@example.com",
        password="testpass123",
        role=admin_role,
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    transporter = Transporter.objects.create(name="Trans SA")

    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-TRIP-{order_suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-TRIP-{order_suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("500000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    return {
        "admin_user": admin_user,
        "product": product,
        "supplier": supplier,
        "transporter": transporter,
        "supplier_order": supplier_order,
        "cession": cession,
    }


def _make_truck(code):
    return Truck.objects.create(
        internal_id=code,
        tractor_registration=f"{code}-TRACTOR",
        tanker_registration=f"{code}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )


def _make_trip(
    fx,
    truck,
    reference,
    quantity=Decimal("45000.00"),
    customer_order=None,
    status=Trip.Status.ASSIGNED,
):
    return Trip.objects.create(
        reference=reference,
        truck=truck,
        transporter=fx["transporter"],
        supplier=fx["supplier"],
        supplier_order=fx["supplier_order"],
        cession_letter=fx["cession"],
        product=fx["product"],
        quantity_loaded=quantity,
        customer_order=customer_order,
        loading_date="2026-08-18",
        bl_reference=f"BL-{reference}",
        status=status,
        created_by=fx["admin_user"],
    )


def _advance_to_completed(trip, actor):
    for target in FULL_SEQUENCE_AFTER_ASSIGNED:
        TripWorkflowService.transition_trip(trip.id, target, actor)
    trip.refresh_from_db()
    return trip


@pytest.mark.django_db
def test_trip_quantity_must_be_positive():
    fx = _setup_fixtures("QTY")
    truck = _make_truck("TRK-QTY")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_trip(fx, truck, "TRIP-QTY-001", quantity=Decimal("0.00"))


@pytest.mark.django_db
def test_trip_reference_must_be_unique():
    fx = _setup_fixtures("REF")
    truck_a = _make_truck("TRK-REF-A")
    truck_b = _make_truck("TRK-REF-B")

    _make_trip(fx, truck_a, "TRIP-DUP-001")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_trip(fx, truck_b, "TRIP-DUP-001")


@pytest.mark.django_db
def test_trip_without_customer_order_is_valid_direct_sale():
    fx = _setup_fixtures("DIRECT")
    truck = _make_truck("TRK-DIRECT")

    trip = _make_trip(fx, truck, "TRIP-DIRECT-001", customer_order=None)

    assert trip.customer_order is None
    assert trip.pk is not None


@pytest.mark.django_db
def test_trip_status_history_is_immutable():
    fx = _setup_fixtures("HIST")
    truck = _make_truck("TRK-HIST")
    trip = _make_trip(fx, truck, "TRIP-HIST-001")

    TripWorkflowService.transition_trip(
        trip.id, Trip.Status.SENT_FOR_LOADING, fx["admin_user"], notes="go"
    )
    entry = trip.status_history.get()

    assert entry.previous_status == Trip.Status.ASSIGNED
    assert entry.new_status == Trip.Status.SENT_FOR_LOADING
    assert entry.changed_by_id == fx["admin_user"].id

    entry.notes = "tampered"
    with pytest.raises(ValueError):
        entry.save()

    with pytest.raises(ValueError):
        entry.delete()

    # Confirm nothing was actually persisted despite the attempted edit.
    assert TripStatusHistory.objects.get(pk=entry.pk).notes == "go"


@pytest.mark.django_db
def test_truck_availability_service_tracks_active_trips():
    fx = _setup_fixtures("AVAIL")
    truck = _make_truck("TRK-AVAIL")

    assert TruckAvailabilityService.is_truck_available(truck.id) is True
    assert truck in TruckAvailabilityService.get_available_trucks()

    trip = _make_trip(fx, truck, "TRIP-AVAIL-001")

    assert TruckAvailabilityService.is_truck_available(truck.id) is False
    assert TruckAvailabilityService.get_active_trip(truck.id).id == trip.id
    assert truck not in TruckAvailabilityService.get_available_trucks()


@pytest.mark.django_db
def test_truck_becomes_available_again_after_trip_completes():
    fx = _setup_fixtures("CYCLE")
    truck = _make_truck("TRK-CYCLE")
    trip = _make_trip(fx, truck, "TRIP-CYCLE-001")

    assert TruckAvailabilityService.is_truck_available(truck.id) is False

    _advance_to_completed(trip, fx["admin_user"])
    truck.refresh_from_db()

    assert TruckAvailabilityService.is_truck_available(truck.id) is True
    assert truck.status == Truck.Status.AVAILABLE

    # And the truck can now be reused for a brand-new, independent trip.
    second_trip = _make_trip(fx, truck, "TRIP-CYCLE-002")
    assert second_trip.pk != trip.pk
    assert TruckAvailabilityService.is_truck_available(truck.id) is False


@pytest.mark.django_db
def test_workflow_rejects_skipping_a_status():
    fx = _setup_fixtures("SKIP")
    truck = _make_truck("TRK-SKIP")
    trip = _make_trip(fx, truck, "TRIP-SKIP-001")

    with pytest.raises(InvalidTripTransition):
        TripWorkflowService.transition_trip(
            trip.id, Trip.Status.DELIVERED, fx["admin_user"]
        )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.ASSIGNED


@pytest.mark.django_db
def test_workflow_rejects_transition_once_completed():
    fx = _setup_fixtures("DONE")
    truck = _make_truck("TRK-DONE")
    trip = _make_trip(fx, truck, "TRIP-DONE-001")
    _advance_to_completed(trip, fx["admin_user"])

    with pytest.raises(InvalidTripTransition):
        TripWorkflowService.transition_trip(
            trip.id, Trip.Status.CANCELLED, fx["admin_user"]
        )


@pytest.mark.django_db
def test_workflow_cancel_allowed_before_delivered_only():
    fx = _setup_fixtures("CANCEL")
    truck_a = _make_truck("TRK-CANCEL-A")
    truck_b = _make_truck("TRK-CANCEL-B")

    early_trip = _make_trip(fx, truck_a, "TRIP-CANCEL-EARLY")
    TripWorkflowService.transition_trip(
        early_trip.id, Trip.Status.CANCELLED, fx["admin_user"]
    )
    early_trip.refresh_from_db()
    assert early_trip.status == Trip.Status.CANCELLED
    # Cancelling frees the truck immediately, same as completion.
    assert TruckAvailabilityService.is_truck_available(truck_a.id) is True

    late_trip = _make_trip(fx, truck_b, "TRIP-CANCEL-LATE")
    for target in FULL_SEQUENCE_AFTER_ASSIGNED[:-1]:  # stop at DELIVERED
        TripWorkflowService.transition_trip(late_trip.id, target, fx["admin_user"])
    late_trip.refresh_from_db()
    assert late_trip.status == Trip.Status.DELIVERED

    with pytest.raises(InvalidTripTransition):
        TripWorkflowService.transition_trip(
            late_trip.id, Trip.Status.CANCELLED, fx["admin_user"]
        )


@pytest.mark.django_db
def test_workflow_block_and_resume_returns_to_exact_prior_status():
    fx = _setup_fixtures("BLOCK")
    truck = _make_truck("TRK-BLOCK")
    trip = _make_trip(fx, truck, "TRIP-BLOCK-001")

    TripWorkflowService.transition_trip(
        trip.id, Trip.Status.SENT_FOR_LOADING, fx["admin_user"]
    )
    TripWorkflowService.transition_trip(
        trip.id, Trip.Status.LOADING, fx["admin_user"]
    )
    TripWorkflowService.transition_trip(
        trip.id, Trip.Status.BLOCKED, fx["admin_user"], notes="customs issue"
    )
    trip.refresh_from_db()
    assert trip.status == Trip.Status.BLOCKED

    allowed = TripWorkflowService.get_allowed_targets(trip)
    assert allowed == {Trip.Status.LOADING}

    with pytest.raises(InvalidTripTransition):
        TripWorkflowService.transition_trip(
            trip.id, Trip.Status.DELIVERED, fx["admin_user"]
        )

    TripWorkflowService.transition_trip(
        trip.id, Trip.Status.LOADING, fx["admin_user"], notes="resolved"
    )
    trip.refresh_from_db()
    assert trip.status == Trip.Status.LOADING

    # Normal forward progression still works after resuming.
    TripWorkflowService.transition_trip(
        trip.id, Trip.Status.LOADED, fx["admin_user"]
    )
    trip.refresh_from_db()
    assert trip.status == Trip.Status.LOADED

    history_statuses = list(
        trip.status_history.values_list("previous_status", "new_status")
    )
    assert history_statuses == [
        (Trip.Status.ASSIGNED, Trip.Status.SENT_FOR_LOADING),
        (Trip.Status.SENT_FOR_LOADING, Trip.Status.LOADING),
        (Trip.Status.LOADING, Trip.Status.BLOCKED),
        (Trip.Status.BLOCKED, Trip.Status.LOADING),
        (Trip.Status.LOADING, Trip.Status.LOADED),
    ]


@pytest.mark.django_db
def test_repeated_truck_scenario_450000_litres_two_rounds():
    """Mandatory recette scenario (spec Section 44 / plan Etape 7): a
    450,000 L customer order fulfilled by 6 trucks in a first round
    (270,000 L) and 4 of those same trucks returning for a second round
    (180,000 L). Exercised at the model/service layer since the API
    (serializers/views) is a later block.

    No real concurrency is exercised here (that's covered separately, see
    purchasing's test_concurrency_select_for_update for the locking
    pattern), so this stays on the default django_db transaction-rollback
    wrapper rather than transaction=True - the latter flushes tables
    (including migration-seeded Roles) after the test runs, which starves
    whichever transaction=True test runs next in the same session."""
    fx = _setup_fixtures("450K")
    customer = Customer.objects.create(name="Client X")
    order = CustomerOrder.objects.create(
        customer=customer,
        product=fx["product"],
        quantity_ordered=Decimal("450000.00"),
        status=CustomerOrder.Status.CONFIRMED,
    )

    trucks = [_make_truck(f"TRK-450K-{letter}") for letter in "ABCDEF"]

    round_one_trips = [
        _make_trip(
            fx,
            truck,
            f"TRIP-450K-R1-{truck.internal_id}",
            quantity=Decimal("45000.00"),
            customer_order=order,
        )
        for truck in trucks
    ]

    # Trip creation itself is Etape 5 (TripSerializer), out of scope here -
    # trips are inserted directly via the model manager above, so nothing
    # has told CustomerOrderService a new trip exists yet. Once the creation
    # service lands it will call recompute_status() the same way
    # TripWorkflowService.transition_trip() already does below.
    CustomerOrderService.recompute_status(order)
    order.refresh_from_db()
    assert CustomerOrderService.get_assigned_quantity(order) == Decimal("270000.00")
    assert order.status == CustomerOrder.Status.PARTIALLY_ASSIGNED

    for trip in round_one_trips:
        _advance_to_completed(trip, fx["admin_user"])
        # Truck is free again immediately after its own trip completes.
        assert TruckAvailabilityService.is_truck_available(trip.truck_id) is True

    order.refresh_from_db()
    assert CustomerOrderService.get_delivered_quantity(order) == Decimal("270000.00")
    assert order.status == CustomerOrder.Status.PARTIALLY_DELIVERED

    reused_trucks = trucks[:4]
    round_two_trips = [
        _make_trip(
            fx,
            truck,
            f"TRIP-450K-R2-{truck.internal_id}",
            quantity=Decimal("45000.00"),
            customer_order=order,
        )
        for truck in reused_trucks
    ]

    for trip in round_two_trips:
        _advance_to_completed(trip, fx["admin_user"])

    order.refresh_from_db()
    assert CustomerOrderService.get_delivered_quantity(order) == Decimal("450000.00")
    assert CustomerOrderService.get_remaining_quantity(order) == Decimal("0.00")
    assert order.status == CustomerOrder.Status.DELIVERED

    # Every reused truck now has two fully independent Trip rows.
    for truck in reused_trucks:
        trip_refs = set(Trip.objects.filter(truck=truck).values_list("reference", flat=True))
        assert len(trip_refs) == 2

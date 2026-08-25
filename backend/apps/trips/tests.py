import itertools
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import resolve
from django.utils import timezone
from django.urls.exceptions import Resolver404
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import LossToleranceConfig, Product
from apps.customers.models import Customer
from apps.finance.models import TransportDeduction
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import CustomerOrder, ProductSellingPriceHistory
from apps.sales.services import CustomerOrderService
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import DeliveryControl, Trip, TripStatusHistory
from apps.trips.serializers import TripSerializer, TripStatusHistorySerializer
from apps.trips.services import (
    DeliveryAnomalyConfirmationRequired,
    DeliveryService,
    InvalidTripTransition,
    SellingPriceNotConfigured,
    TransporterAvailabilityService,
    TripWorkflowService,
    TruckAvailabilityService,
)


class _FakeRequest:
    """Minimal stand-in for a DRF Request - serializers only read .user."""

    def __init__(self, user):
        self.user = user

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
        phone=(f"+222{order_suffix}")[:20],
        pin="1234",
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


def _advance_to_quantity_control(trip, actor):
    # Stop right before DELIVERED - the status DeliveryService.record_delivery
    # itself must reach via TripWorkflowService.
    for target in FULL_SEQUENCE_AFTER_ASSIGNED[:-2]:
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
def test_transporter_availability_service_tracks_active_trips():
    fx = _setup_fixtures("TRANS-AVAIL")
    truck = _make_truck("TRK-TRANS-AVAIL")

    assert fx["transporter"] in TransporterAvailabilityService.get_available_transporters()

    _make_trip(fx, truck, "TRIP-TRANS-AVAIL-001")

    assert (
        fx["transporter"] not in TransporterAvailabilityService.get_available_transporters()
    )


@pytest.mark.django_db
def test_api_transporters_available_filter_excludes_busy_transporter():
    fx = _setup_fixtures("TRANS-API")
    truck = _make_truck("TRK-TRANS-API")
    idle_transporter = Transporter.objects.create(name="Idle Transport")
    _make_trip(fx, truck, "TRIP-TRANS-API-001")  # occupies fx["transporter"]

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    response = client.get("/api/transporters/?available=true")
    assert response.status_code == 200
    names = {t["name"] for t in response.data["results"]}
    assert idle_transporter.name in names
    assert fx["transporter"].name not in names

    unfiltered = client.get("/api/transporters/")
    names_unfiltered = {t["name"] for t in unfiltered.data["results"]}
    assert fx["transporter"].name in names_unfiltered


@pytest.mark.django_db
def test_truck_and_transporter_become_available_once_delivered_even_if_not_completed():
    """A DELIVERED trip has physically returned its truck - it must not
    keep blocking a new assignment just because nobody has clicked through
    the administrative DELIVERED -> COMPLETED step yet (regression: real
    data had trips sitting in DELIVERED indefinitely, which emptied the
    transporter picker entirely and never actually freed any truck)."""
    fx = _setup_fixtures("DELIVERED-FREE")
    truck = _make_truck("TRK-DELIVERED-FREE")
    trip = _make_trip(fx, truck, "TRIP-DELIVERED-FREE-001")

    assert TruckAvailabilityService.is_truck_available(truck.id) is False
    assert fx["transporter"] not in TransporterAvailabilityService.get_available_transporters()

    for target in FULL_SEQUENCE_AFTER_ASSIGNED[:-1]:  # stop at DELIVERED
        TripWorkflowService.transition_trip(trip.id, target, fx["admin_user"])
    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED

    assert TruckAvailabilityService.is_truck_available(truck.id) is True
    assert truck in TruckAvailabilityService.get_available_trucks()
    assert fx["transporter"] in TransporterAvailabilityService.get_available_transporters()


@pytest.mark.django_db
def test_api_trucks_available_filter_excludes_only_truly_active_trucks():
    fx = _setup_fixtures("TRUCK-API-AVAIL")
    idle_truck = _make_truck("TRK-API-AVAIL-IDLE")
    busy_truck = _make_truck("TRK-API-AVAIL-BUSY")
    _make_trip(fx, busy_truck, "TRIP-API-AVAIL-001")  # stays ASSIGNED: truly active

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    response = client.get("/api/trucks/?available=true")
    assert response.status_code == 200
    ids = {t["internal_id"] for t in response.data["results"]}
    assert idle_truck.internal_id in ids
    assert busy_truck.internal_id not in ids

    unfiltered = client.get("/api/trucks/")
    ids_unfiltered = {t["internal_id"] for t in unfiltered.data["results"]}
    assert busy_truck.internal_id in ids_unfiltered


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


def _trip_payload(fx, truck, reference, quantity=Decimal("45000.00"), **overrides):
    payload = {
        "reference": reference,
        "truck": truck.id,
        "transporter": fx["transporter"].id,
        "supplier": fx["supplier"].id,
        "supplier_order": fx["supplier_order"].id,
        "cession_letter": fx["cession"].id,
        "product": fx["product"].id,
        "quantity_loaded": quantity,
        "loading_date": "2026-08-18",
        "bl_reference": f"BL-{reference}",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_trip_serializer_rejects_quantity_over_cession_remaining():
    fx = _setup_fixtures("SER-QTY")
    fx["cession"].authorized_quantity = Decimal("45000.00")
    fx["cession"].save(update_fields=["authorized_quantity"])
    truck_a = _make_truck("TRK-SER-QTY-A")
    truck_b = _make_truck("TRK-SER-QTY-B")

    _make_trip(fx, truck_a, "TRIP-SER-QTY-001", quantity=Decimal("40000.00"))

    serializer = TripSerializer(
        data=_trip_payload(fx, truck_b, "TRIP-SER-QTY-002", quantity=Decimal("10000.00")),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert not serializer.is_valid()
    assert "quantity_loaded" in serializer.errors


@pytest.mark.django_db
def test_trip_serializer_accepts_quantity_within_cession_remaining():
    fx = _setup_fixtures("SER-OK")
    fx["cession"].authorized_quantity = Decimal("45000.00")
    fx["cession"].save(update_fields=["authorized_quantity"])
    truck = _make_truck("TRK-SER-OK")

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-SER-OK-001", quantity=Decimal("45000.00")),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert serializer.is_valid(), serializer.errors
    assert "force" not in serializer.validated_data


@pytest.mark.django_db
def test_trip_serializer_rejects_quantity_over_truck_capacity():
    fx = _setup_fixtures("SER-CAP")
    truck = _make_truck("TRK-SER-CAP")  # capacity_litres = 45000.00

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-SER-CAP-001", quantity=Decimal("50000.00")),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert not serializer.is_valid()
    assert "quantity_loaded" in serializer.errors


@pytest.mark.django_db
def test_trip_serializer_accepts_quantity_equal_to_truck_capacity():
    fx = _setup_fixtures("SER-CAP-OK")
    truck = _make_truck("TRK-SER-CAP-OK")  # capacity_litres = 45000.00

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-SER-CAP-OK-001", quantity=Decimal("45000.00")),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_trip_serializer_rejects_active_truck_without_force():
    fx = _setup_fixtures("SER-LOCK")
    truck = _make_truck("TRK-SER-LOCK")
    _make_trip(fx, truck, "TRIP-SER-LOCK-001")

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-SER-LOCK-002"),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert not serializer.is_valid()
    assert "truck" in serializer.errors


@pytest.mark.django_db
def test_trip_serializer_rejects_force_from_non_admin():
    fx = _setup_fixtures("SER-NOADMIN")
    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)
    ops_user = User.objects.create_user(
        phone="+2220000016", pin="1234", role=ops_role
    )
    truck = _make_truck("TRK-SER-NOADMIN")
    _make_trip(fx, truck, "TRIP-SER-NOADMIN-001")

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-SER-NOADMIN-002", force=True),
        context={"request": _FakeRequest(ops_user)},
    )
    assert not serializer.is_valid()
    assert "truck" in serializer.errors


@pytest.mark.django_db
def test_trip_serializer_allows_force_override_by_admin():
    fx = _setup_fixtures("SER-FORCE")
    truck = _make_truck("TRK-SER-FORCE")
    _make_trip(fx, truck, "TRIP-SER-FORCE-001")

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-SER-FORCE-002", force=True),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert serializer.is_valid(), serializer.errors
    assert "force" not in serializer.validated_data


@pytest.mark.django_db
def test_trip_serializer_update_without_truck_change_skips_availability_check():
    fx = _setup_fixtures("SER-UPD")
    truck = _make_truck("TRK-SER-UPD")
    trip = _make_trip(fx, truck, "TRIP-SER-UPD-001")

    # This trip's own truck is (unsurprisingly) "active" right now - editing
    # an unrelated field must not require force=true just because of that.
    serializer = TripSerializer(
        instance=trip,
        data={"notes": "updated notes"},
        partial=True,
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_trip_status_history_serializer_is_fully_read_only():
    fx = _setup_fixtures("SER-HIST")
    truck = _make_truck("TRK-SER-HIST")
    trip = _make_trip(fx, truck, "TRIP-SER-HIST-001")
    TripWorkflowService.transition_trip(
        trip.id, Trip.Status.SENT_FOR_LOADING, fx["admin_user"], notes="go"
    )
    entry = trip.status_history.get()

    serializer = TripStatusHistorySerializer(entry)
    assert serializer.data["new_status"] == Trip.Status.SENT_FOR_LOADING
    assert set(TripStatusHistorySerializer.Meta.read_only_fields) == set(
        TripStatusHistorySerializer.Meta.fields
    )


# ---------------------------------------------------------------------------
# Etape 7: integration/acceptance tests through the actual DRF endpoints
# (views.py / urls.py from Etape 6). The equivalent scenarios already
# exercised at the model/service layer in block 1 stay in place above; these
# confirm the same rules hold end-to-end through HTTP + permissions.
# ---------------------------------------------------------------------------

_FORWARD_SEQUENCE_STATUS_NAMES = [
    "SENT_FOR_LOADING",
    "LOADING",
    "LOADED",
    "IN_TRANSIT",
    "BORDER",
    "CUSTOMS",
    "GOING_TO_CLIENT",
    "ARRIVED_AT_CLIENT",
    "QUANTITY_CONTROL",
    "DELIVERED",
    "COMPLETED",
]


def _api_trip_payload(fx, truck, quantity="45000.00", **overrides):
    payload = {
        "truck": truck.id,
        "transporter": fx["transporter"].id,
        "supplier": fx["supplier"].id,
        "supplier_order": fx["supplier_order"].id,
        "cession_letter": fx["cession"].id,
        "product": fx["product"].id,
        "quantity_loaded": quantity,
        "loading_date": "2026-08-18",
        "bl_reference": f"BL-{truck.internal_id}",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_api_repeated_truck_scenario_450000_litres():
    """Mandatory recette scenario (spec Section 44 / plan Etape 7), this time
    driven entirely through POST /api/trips/, POST /api/trips/{id}/status/
    and GET /api/customer-orders/{id}/ - the model/service-layer version of
    the same scenario is
    test_repeated_truck_scenario_450000_litres_two_rounds above."""
    fx = _setup_fixtures("API-450K")
    fx["cession"].authorized_quantity = Decimal("500000.00")
    fx["cession"].save(update_fields=["authorized_quantity"])
    customer = Customer.objects.create(name="Client API")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    order_response = client.post(
        "/api/customer-orders/",
        {
            "customer": customer.id,
            "product": fx["product"].id,
            "quantity_ordered": "450000.00",
            "status": CustomerOrder.Status.CONFIRMED,
        },
    )
    assert order_response.status_code == 201, order_response.data
    order_id = order_response.data["id"]

    trucks = [_make_truck(f"TRK-API-450K-{letter}") for letter in "ABCDEF"]

    round_one_trip_ids = []
    for truck in trucks:
        response = client.post(
            "/api/trips/",
            _api_trip_payload(
                fx, truck, customer_order=order_id, bl_reference=f"BL-{truck.internal_id}-R1"
            ),
        )
        assert response.status_code == 201, response.data
        assert response.data["reference"].startswith("TRIP-")
        round_one_trip_ids.append(response.data["id"])

    for trip_id in round_one_trip_ids:
        for target in _FORWARD_SEQUENCE_STATUS_NAMES:
            response = client.post(f"/api/trips/{trip_id}/status/", {"new_status": target})
            assert response.status_code == 200, response.data

    order_after_round_one = client.get(f"/api/customer-orders/{order_id}/").data
    assert order_after_round_one["delivered_quantity"] == "270000.00"
    assert order_after_round_one["status"] == "PARTIALLY_DELIVERED"

    reused_trucks = trucks[:4]
    round_two_trip_ids = []
    for truck in reused_trucks:
        response = client.post(
            "/api/trips/",
            _api_trip_payload(
                fx,
                truck,
                customer_order=order_id,
                loading_date="2026-08-19",
                bl_reference=f"BL-{truck.internal_id}-R2",
            ),
        )
        assert response.status_code == 201, response.data
        round_two_trip_ids.append(response.data["id"])

    for trip_id in round_two_trip_ids:
        for target in _FORWARD_SEQUENCE_STATUS_NAMES:
            response = client.post(f"/api/trips/{trip_id}/status/", {"new_status": target})
            assert response.status_code == 200, response.data

    final_order = client.get(f"/api/customer-orders/{order_id}/").data
    assert final_order["delivered_quantity"] == "450000.00"
    assert final_order["remaining_quantity"] == "0.00"
    assert final_order["status"] == "DELIVERED"

    order_trips = client.get(f"/api/customer-orders/{order_id}/trips/").data
    assert len(order_trips) == 10

    for truck in reused_trucks:
        truck_trips = client.get(f"/api/trucks/{truck.id}/trips/").data
        assert len(truck_trips) == 2
        assert len({t["reference"] for t in truck_trips}) == 2


@pytest.mark.django_db
def test_api_truck_lock_rejected_then_admin_force_succeeds():
    fx = _setup_fixtures("API-LOCK")
    truck = _make_truck("TRK-API-LOCK")
    _make_trip(fx, truck, "TRIP-API-LOCK-SEED")  # pre-existing active trip

    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)
    ops_user = User.objects.create_user(
        phone="+2220000017", pin="1234", role=ops_role
    )
    payload = _api_trip_payload(fx, truck, quantity="10000.00")

    ops_client = APIClient()
    ops_client.force_authenticate(ops_user)
    response = ops_client.post("/api/trips/", payload)
    assert response.status_code == 400
    assert "truck" in response.data

    admin_client = APIClient()
    admin_client.force_authenticate(fx["admin_user"])
    response = admin_client.post("/api/trips/", {**payload, "force": True})
    assert response.status_code == 201, response.data


@pytest.mark.django_db
def test_api_bl_reference_is_generated_when_left_blank():
    fx = _setup_fixtures("API-BL-GEN")
    truck = _make_truck("TRK-API-BL-GEN")
    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    response = client.post(
        "/api/trips/", _api_trip_payload(fx, truck, bl_reference="")
    )
    assert response.status_code == 201, response.data
    yyyymm = timezone.now().strftime("%Y%m")
    assert response.data["bl_reference"].startswith(f"BL-{yyyymm}-")


@pytest.mark.django_db
def test_api_bl_reference_provided_by_user_is_kept():
    fx = _setup_fixtures("API-BL-KEEP")
    truck = _make_truck("TRK-API-BL-KEEP")
    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    response = client.post(
        "/api/trips/", _api_trip_payload(fx, truck, bl_reference="BL-PAPIER-777")
    )
    assert response.status_code == 201, response.data
    assert response.data["bl_reference"] == "BL-PAPIER-777"


@pytest.mark.django_db
def test_api_direct_sale_trip_without_customer_order():
    fx = _setup_fixtures("API-DIRECT")
    truck = _make_truck("TRK-API-DIRECT")
    customer = Customer.objects.create(name="Direct Client")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    response = client.post(
        "/api/trips/", _api_trip_payload(fx, truck, quantity="20000.00", client=customer.id)
    )
    assert response.status_code == 201, response.data
    assert response.data["customer_order"] is None
    assert response.data["client"] == customer.id


@pytest.mark.django_db
def test_api_trip_status_history_immutable_no_mutation_endpoint():
    fx = _setup_fixtures("API-HIST")
    truck = _make_truck("TRK-API-HIST")
    trip = _make_trip(fx, truck, "TRIP-API-HIST-001")
    TripWorkflowService.transition_trip(
        trip.id, Trip.Status.SENT_FOR_LOADING, fx["admin_user"]
    )
    entry = trip.status_history.get()

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    history_response = client.get(f"/api/trips/{trip.id}/history/")
    assert history_response.status_code == 200
    assert len(history_response.data) == 1
    assert history_response.data[0]["new_status"] == Trip.Status.SENT_FOR_LOADING

    # No ModelViewSet is registered for TripStatusHistory - it is exposed
    # strictly read-only, nested under a trip (GET /api/trips/{id}/history/).
    # A guessed direct-mutation URL must not resolve to any view at all -
    # confirmed via the resolver directly (rather than a live PATCH request,
    # whose 404 error page rendering hits an unrelated Django/Python 3.14
    # template-context-copy bug in this environment). The real immutability
    # enforcement is at the model level (see test_trip_status_history_is_immutable).
    with pytest.raises(Resolver404):
        resolve(f"/api/trip-status-history/{entry.id}/")

    # Confirm the DB row genuinely never changed either way.
    assert TripStatusHistory.objects.get(pk=entry.pk).notes == ""


@pytest.mark.django_db
def test_api_customer_order_permissions_gate_on_sales_module():
    fx = _setup_fixtures("API-PERM")
    customer = Customer.objects.create(name="Perm Client")
    payload = {
        "customer": customer.id,
        "product": fx["product"].id,
        "quantity_ordered": "10000.00",
    }

    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)
    ops_user = User.objects.create_user(
        phone="+2220000018", pin="1234", role=ops_role
    )

    client = APIClient()
    client.force_authenticate(ops_user)
    # Operations role only has "view" on the sales module.
    response = client.post("/api/customer-orders/", payload)
    assert response.status_code == 403

    client.force_authenticate(fx["admin_user"])
    response = client.post("/api/customer-orders/", payload)
    assert response.status_code == 201, response.data


# ---------------------------------------------------------------------------
# Phase 4 Etape 2/5: DeliveryControl model + DeliveryService (docs/PHASE_4_PLAN.md;
# ERP_Implementation_Experience_Guide.md Section 7.2-7.6, Section 13/15).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delivery_control_computes_loss_and_chargeable_loss_on_save():
    fx = _setup_fixtures("DC-CALC")
    truck = _make_truck("TRK-DC-CALC")
    trip = _make_trip(fx, truck, "TRIP-DC-CALC-001")

    control = DeliveryControl.objects.create(
        trip=trip,
        loaded_quantity=Decimal("45000.00"),
        received_quantity=Decimal("44850.00"),
        tolerance_quantity=Decimal("100.00"),
        control_date="2026-08-18",
        controller=fx["admin_user"],
        method=DeliveryControl.Method.MANUAL_GAUGE,
    )

    assert control.loss_quantity == Decimal("150.00")
    assert control.chargeable_loss_quantity == Decimal("50.00")


@pytest.mark.django_db
def test_delivery_control_requires_positive_loaded_quantity():
    fx = _setup_fixtures("DC-QTY")
    truck = _make_truck("TRK-DC-QTY")
    trip = _make_trip(fx, truck, "TRIP-DC-QTY-001")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DeliveryControl.objects.create(
                trip=trip,
                loaded_quantity=Decimal("0.00"),
                received_quantity=Decimal("0.00"),
                tolerance_quantity=Decimal("100.00"),
                control_date="2026-08-18",
                controller=fx["admin_user"],
                method=DeliveryControl.Method.MANUAL_GAUGE,
            )


def _fixtures_with_customer(suffix):
    fx = _setup_fixtures(suffix)
    fx["customer"] = Customer.objects.create(name=f"Client {suffix}")
    return fx


_delivery_truck_codes = itertools.count(1)


def _deliverable_trip(fx, reference, quantity=Decimal("45000.00")):
    # A short, counter-based code - independent of `reference`'s length -
    # keeps tractor/tanker registration (max_length=30, "-TRACTOR" suffix
    # included) from overflowing regardless of how long the caller's trip
    # reference is.
    truck = _make_truck(f"TRK-DC-{next(_delivery_truck_codes)}")
    trip = _make_trip(fx, truck, reference, quantity=quantity, customer_order=None)
    trip.client = fx["customer"]
    trip.save(update_fields=["client"])
    _advance_to_quantity_control(trip, fx["admin_user"])
    return trip


@pytest.mark.django_db
def test_delivery_service_requires_selling_price_configured():
    fx = _fixtures_with_customer("DS-NOPRICE")
    trip = _deliverable_trip(fx, "TRIP-NOPRICE-001")

    with pytest.raises(SellingPriceNotConfigured):
        DeliveryService.record_delivery(
            trip_id=trip.id,
            received_qty=Decimal("44850.00"),
            control_date="2026-08-18",
            method=DeliveryControl.Method.MANUAL_GAUGE,
            controller=fx["admin_user"],
        )


@pytest.mark.django_db
def test_delivery_service_happy_path_creates_deduction_sale_and_invoice():
    # Mandatory recette scenario (plan Section 4 / Etape 7): 45,000 L loaded,
    # 44,850 L received, 100 L tolerance -> 150 L loss, 50 L chargeable.
    fx = _fixtures_with_customer("DS-HAPPY")
    trip = _deliverable_trip(fx, "TRIP-DS-HAPPY-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"],
        customer=fx["customer"],
        price=Decimal("650.0000"),
        changed_by=fx["admin_user"],
    )
    LossToleranceConfig.objects.create(
        tolerance_litres=Decimal("100.00"), updated_by=fx["admin_user"]
    )

    control = DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("44850.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED

    assert control.loaded_quantity == Decimal("45000.00")
    assert control.received_quantity == Decimal("44850.00")
    assert control.tolerance_quantity == Decimal("100.00")
    assert control.loss_quantity == Decimal("150.00")
    assert control.chargeable_loss_quantity == Decimal("50.00")

    deduction = TransportDeduction.objects.get(trip=trip)
    assert deduction.transporter_id == fx["transporter"].id
    assert deduction.chargeable_quantity == Decimal("50.00")
    assert deduction.unit_price == Decimal("600.0000")  # supplier purchase price
    assert deduction.amount == Decimal("30000.00")
    assert deduction.status == TransportDeduction.Status.DRAFT

    sale = trip.sale
    assert sale.customer_id == fx["customer"].id
    assert sale.delivered_quantity == Decimal("44850.00")  # received, never loaded
    assert sale.unit_selling_price == Decimal("650.0000")
    assert sale.subtotal == Decimal("29152500.00")

    invoice = sale.invoice
    assert invoice.status == "DRAFT"
    assert invoice.total_amount == sale.subtotal
    assert invoice.issued_date.isoformat() == "2026-08-18"


@pytest.mark.django_db
def test_delivery_confirmation_generates_fac_invoice_number():
    fx = _fixtures_with_customer("FAC-FORMAT")
    trip = _deliverable_trip(fx, "TRIP-FAC-FORMAT-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("44850.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )

    invoice = trip.sale.invoice
    yyyymm = timezone.now().strftime("%Y%m")
    assert invoice.invoice_number.startswith(f"FAC-{yyyymm}-")
    assert not invoice.invoice_number.startswith("INV-")


@pytest.mark.django_db
def test_delivery_service_no_deduction_when_loss_within_tolerance():
    fx = _fixtures_with_customer("DS-INTOL")
    trip = _deliverable_trip(fx, "TRIP-DS-INTOL-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("44950.00"),  # 50 L loss, under the 100 L default tolerance
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )

    assert not TransportDeduction.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_delivery_service_blocks_anomaly_without_confirmation():
    fx = _fixtures_with_customer("DS-ANOM")
    trip = _deliverable_trip(fx, "TRIP-DS-ANOM-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    with pytest.raises(DeliveryAnomalyConfirmationRequired):
        DeliveryService.record_delivery(
            trip_id=trip.id,
            received_qty=Decimal("46000.00"),  # more than the 45,000 L loaded
            control_date="2026-08-18",
            method=DeliveryControl.Method.MANUAL_GAUGE,
            controller=fx["admin_user"],
        )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.QUANTITY_CONTROL
    assert not DeliveryControl.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_delivery_service_allows_anomaly_with_explicit_confirmation():
    fx = _fixtures_with_customer("DS-ANOMOK")
    trip = _deliverable_trip(fx, "TRIP-DS-ANOMOK-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    control = DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("46000.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        anomaly_confirmed_by=fx["admin_user"],
    )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED
    assert control.anomaly_confirmed_by_id == fx["admin_user"].id
    assert control.anomaly_confirmed_at is not None
    assert control.loss_quantity == Decimal("-1000.00")
    assert control.chargeable_loss_quantity == Decimal("0.00")
    assert not TransportDeduction.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_delivery_service_freezes_tolerance_used_at_confirmation_time():
    fx = _fixtures_with_customer("DS-FREEZE")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )
    LossToleranceConfig.objects.create(
        tolerance_litres=Decimal("100.00"), updated_by=fx["admin_user"]
    )

    trip_a = _deliverable_trip(fx, "TRIP-DS-FREEZE-A")
    control_a = DeliveryService.record_delivery(
        trip_id=trip_a.id,
        received_qty=Decimal("44850.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )
    assert control_a.tolerance_quantity == Decimal("100.00")

    # The default tolerance changes after trip A was confirmed.
    LossToleranceConfig.objects.create(
        tolerance_litres=Decimal("500.00"), updated_by=fx["admin_user"]
    )

    trip_b = _deliverable_trip(fx, "TRIP-DS-FREEZE-B")
    control_b = DeliveryService.record_delivery(
        trip_id=trip_b.id,
        received_qty=Decimal("44850.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )
    assert control_b.tolerance_quantity == Decimal("500.00")

    # Trip A's historic control must never drift with the new default.
    control_a.refresh_from_db()
    assert control_a.tolerance_quantity == Decimal("100.00")


# ---------------------------------------------------------------------------
# Phase 4 Etape 6/7: POST /api/trips/{id}/delivery-control/ (docs/PHASE_4_PLAN.md;
# guide Section 7.2-7.7, Section 15).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_delivery_control_happy_path_150l_loss_50l_chargeable():
    # Mandatory recette scenario (plan Section 4 / Etape 7 test 1): 45,000 L
    # loaded, 44,850 L received, 100 L tolerance -> 150 L loss, 50 L chargeable.
    fx = _fixtures_with_customer("API-DC-HAPPY")
    trip = _deliverable_trip(fx, "TRIP-API-DC-HAPPY-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.post(
        f"/api/trips/{trip.id}/delivery-control/",
        {
            "received_quantity": "44850.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
        },
    )

    assert response.status_code == 201, response.data
    assert response.data["loaded_quantity"] == "45000.00"
    assert response.data["received_quantity"] == "44850.00"
    assert response.data["loss_quantity"] == "150.00"
    assert response.data["chargeable_loss_quantity"] == "50.00"
    assert response.data["tolerance_quantity"] == "100.00"

    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED


@pytest.mark.django_db
def test_api_delivery_control_anomaly_rejected_422_then_confirmed_succeeds():
    # Mandatory recette scenario (plan Etape 7 test 2): 46,000 L received on
    # 45,000 L loaded -> 422 without a signature, 201 with one.
    fx = _fixtures_with_customer("API-DC-ANOM")
    trip = _deliverable_trip(fx, "TRIP-API-DC-ANOM-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    rejected = client.post(
        f"/api/trips/{trip.id}/delivery-control/",
        {
            "received_quantity": "46000.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
        },
    )
    assert rejected.status_code == 422, rejected.data

    trip.refresh_from_db()
    assert trip.status == Trip.Status.QUANTITY_CONTROL
    assert not DeliveryControl.objects.filter(trip=trip).exists()

    confirmed = client.post(
        f"/api/trips/{trip.id}/delivery-control/",
        {
            "received_quantity": "46000.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
            "anomaly_confirmed_by": fx["admin_user"].id,
        },
    )
    assert confirmed.status_code == 201, confirmed.data
    assert confirmed.data["anomaly_confirmed_by"] == fx["admin_user"].id
    assert confirmed.data["anomaly_confirmed_at"] is not None

    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED


@pytest.mark.django_db
def test_api_delivery_control_missing_price_returns_400():
    fx = _fixtures_with_customer("API-DC-NOPRICE")
    trip = _deliverable_trip(fx, "TRIP-DC-NOPRICE-01")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.post(
        f"/api/trips/{trip.id}/delivery-control/",
        {
            "received_quantity": "44850.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
        },
    )

    assert response.status_code == 400
    trip.refresh_from_db()
    assert trip.status == Trip.Status.QUANTITY_CONTROL


@pytest.mark.django_db
def test_api_delivery_control_denied_without_operations_permission():
    fx = _fixtures_with_customer("API-DC-PERM")
    trip = _deliverable_trip(fx, "TRIP-API-DC-PERM-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    finance_role = Role.objects.get(name=Role.NAME_FINANCE)
    finance_user = User.objects.create_user(
        phone="+2220000019", pin="1234", role=finance_role
    )
    client = APIClient()
    client.force_authenticate(finance_user)

    response = client.post(
        f"/api/trips/{trip.id}/delivery-control/",
        {
            "received_quantity": "44850.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
        },
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_api_invoice_amount_based_on_received_quantity_not_loaded():
    # Mandatory recette scenario (plan Etape 7 test 3 / guide Section 7.7,
    # Section 19): invoiced amount must reflect 44,850 L received, never the
    # 45,000 L originally loaded. Driven fully through the trip lifecycle API
    # (creation + status transitions), unlike the service-level happy-path
    # test above, to confirm the same rule holds end-to-end through HTTP.
    fx = _fixtures_with_customer("API-INV-QTY")
    truck = _make_truck("TRK-API-INV-QTY")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    trip_response = client.post(
        "/api/trips/",
        _api_trip_payload(fx, truck, quantity="45000.00", client=fx["customer"].id),
    )
    assert trip_response.status_code == 201, trip_response.data
    trip_id = trip_response.data["id"]

    for target in _FORWARD_SEQUENCE_STATUS_NAMES[:-2]:  # stop right before DELIVERED
        response = client.post(f"/api/trips/{trip_id}/status/", {"new_status": target})
        assert response.status_code == 200, response.data

    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    delivery_response = client.post(
        f"/api/trips/{trip_id}/delivery-control/",
        {
            "received_quantity": "44850.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
        },
    )
    assert delivery_response.status_code == 201, delivery_response.data

    sales_response = client.get("/api/sales/", {"trip": trip_id})
    assert sales_response.data["count"] == 1
    sale_data = sales_response.data["results"][0]
    assert sale_data["delivered_quantity"] == "44850.00"

    invoices_response = client.get("/api/invoices/", {"sale": sale_data["id"]})
    assert invoices_response.data["count"] == 1
    invoice_data = invoices_response.data["results"][0]
    assert invoice_data["total_amount"] == "29152500.00"  # 44,850 x 650, not 45,000 x 650

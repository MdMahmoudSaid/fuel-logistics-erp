import itertools
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.urls import resolve
from django.utils import timezone
from django.urls.exceptions import Resolver404
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import LossToleranceConfig, Product
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.finance.models import (
    Expense,
    ExpenseAllocation,
    TransportDeduction,
    TransportPayment,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import (
    CustomerOrder,
    Invoice,
    InvoiceCorrection,
    ProductSellingPriceHistory,
    Sale,
)
from apps.sales.services import (
    CustomerOrderService,
    InvoicePaidCorrectionUnsupported,
    InvoiceService,
)
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import DeliveryControl, Trip, TripStatusHistory
from apps.trips.serializers import TripSerializer, TripStatusHistorySerializer
from apps.trips.services import (
    CustomerAlreadySoldError,
    DeliveryAnomalyConfirmationRequired,
    DeliveryService,
    InvalidTripTransition,
    SaleBelowCostConfirmationRequired,
    SellingPriceNotConfigured,
    TransporterAvailabilityService,
    TripCostService,
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
    Trip.Status.ROAD_TRANSIT,
    Trip.Status.IN_TRANSIT,
    Trip.Status.BORDER,
    Trip.Status.CUSTOMS,
    Trip.Status.GOING_TO_CLIENT,
    Trip.Status.ARRIVED_AT_CLIENT,
    # Client correction (2026-09-04 recette): QUANTITY_CONTROL is no longer
    # a mandatory intermediate stop - a trip is delivered directly from
    # ARRIVED_AT_CLIENT (see TripWorkflowService.FORWARD_TRANSITIONS).
    Trip.Status.DELIVERED,
    Trip.Status.COMPLETED,
]

COMPANY_STOCK_SEQUENCE_AFTER_CUSTOMS = [
    Trip.Status.GOING_TO_COMPANY_STOCK,
    Trip.Status.ARRIVED_AT_COMPANY_STOCK,
    Trip.Status.STOCKED,
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


def _make_truck(code, *, owner_transporter=None):
    # Phase 6 (docs/superpowers/specs/2026-09-02-business-corrections-6-
    # phases-design.md): a truck used with an explicit "transporter" in a
    # trip payload must be EXTERNAL (owner_transporter matching) - a
    # COMPANY_OWNED truck (the default here) can never carry one.
    kwargs = {}
    if owner_transporter is not None:
        kwargs["ownership_type"] = Truck.OwnershipType.EXTERNAL
        kwargs["owner_transporter"] = owner_transporter
    return Truck.objects.create(
        internal_id=code,
        tractor_registration=f"{code}-TRACTOR",
        tanker_registration=f"{code}-TANKER",
        capacity_litres=Decimal("45000.00"),
        **kwargs,
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


@pytest.mark.django_db
def test_trip_serializer_includes_cession_letter_proof_documents():
    fx = _setup_fixtures("PROOF")
    truck = _make_truck("TRK-PROOF")
    trip = _make_trip(fx, truck, "TRIP-PROOF-001")
    Document.objects.create(
        file=SimpleUploadedFile(
            "cession-proof.jpg", b"fake-proof-bytes", content_type="image/jpeg"
        ),
        document_type="cession_proof",
        uploaded_by=fx["admin_user"],
        content_type=ContentType.objects.get_for_model(CessionLetter),
        object_id=fx["cession"].id,
    )

    data = TripSerializer(trip).data

    assert data["cession_letter_detail"]["reference"] == fx["cession"].reference
    proof_file = data["cession_letter_detail"]["documents"][0]["file"]
    # Storage appends a random suffix when a same-named file from an earlier
    # test run is still on disk (media/ isn't wiped between runs) - assert on
    # the stem rather than an exact filename match.
    assert "cession-proof" in proof_file and proof_file.endswith(".jpg")


def _advance_to_completed(trip, actor):
    for target in FULL_SEQUENCE_AFTER_ASSIGNED:
        if (
            target == Trip.Status.GOING_TO_CLIENT
            and not trip.client_id
            and not trip.customer_order_id
        ):
            trip.client = Customer.objects.create(name=f"Client {trip.reference}")
            trip.destination_type = Trip.DestinationType.CUSTOMER
            trip.save(update_fields=["client", "destination_type", "updated_at"])
        TripWorkflowService.transition_trip(trip.id, target, actor)
        trip.refresh_from_db()
    trip.refresh_from_db()
    return trip


def _advance_to_arrived_at_client(trip, actor):
    # Stop at ARRIVED_AT_CLIENT - DeliveryService.record_delivery itself
    # transitions on to DELIVERED via TripWorkflowService (client
    # correction, 2026-09-04 recette: no mandatory QUANTITY_CONTROL stop
    # in between anymore).
    for target in FULL_SEQUENCE_AFTER_ASSIGNED[:-2]:
        if (
            target == Trip.Status.GOING_TO_CLIENT
            and not trip.client_id
            and not trip.customer_order_id
        ):
            trip.client = Customer.objects.create(name=f"Client {trip.reference}")
            trip.destination_type = Trip.DestinationType.CUSTOMER
            trip.save(update_fields=["client", "destination_type", "updated_at"])
        TripWorkflowService.transition_trip(trip.id, target, actor)
        trip.refresh_from_db()
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
def test_trip_workflow_requires_road_transit_before_transit():
    fx = _setup_fixtures("ROAD")
    truck = _make_truck("TRK-ROAD")
    trip = _make_trip(fx, truck, "TRIP-ROAD-001", status=Trip.Status.LOADED)

    allowed = TripWorkflowService.get_allowed_targets(trip)

    assert allowed == {Trip.Status.ROAD_TRANSIT, Trip.Status.CANCELLED, Trip.Status.BLOCKED}

    with pytest.raises(InvalidTripTransition):
        TripWorkflowService.transition_trip(trip.id, Trip.Status.IN_TRANSIT, fx["admin_user"])

    TripWorkflowService.transition_trip(trip.id, Trip.Status.ROAD_TRANSIT, fx["admin_user"])
    trip.refresh_from_db()

    assert trip.status == Trip.Status.ROAD_TRANSIT
    assert TripWorkflowService.get_allowed_targets(trip) == {
        Trip.Status.IN_TRANSIT,
        Trip.Status.CANCELLED,
        Trip.Status.BLOCKED,
    }


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
    trip.client = Customer.objects.create(name="Delivered Free Client")
    trip.destination_type = Trip.DestinationType.CUSTOMER
    trip.save(update_fields=["client", "destination_type", "updated_at"])

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
def test_arrived_at_client_can_go_directly_to_delivered():
    # Client correction (2026-09-04 recette): QUANTITY_CONTROL is no longer
    # a mandatory gate between ARRIVED_AT_CLIENT and DELIVERED - a trip can
    # be delivered directly, defaulting to "full quantity received, zero
    # loss" (any real discrepancy is corrected later via a separate
    # post-delivery verification flow, not implemented here).
    fx = _fixtures_with_customer("ARRIVED-DIRECT")
    trip = _deliverable_trip(fx, "TRIP-ARRIVED-DIRECT-001")
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT

    allowed = TripWorkflowService.get_allowed_targets(trip)
    assert Trip.Status.DELIVERED in allowed
    assert Trip.Status.QUANTITY_CONTROL not in allowed


@pytest.mark.django_db
def test_workflow_blocks_client_statuses_without_customer_and_routes_to_company_stock():
    fx = _setup_fixtures("STOCK-WFLOW")
    truck = _make_truck("TRK-STOCK-WFLOW")
    trip = _make_trip(fx, truck, "TRIP-STOCK-WFLOW-001")

    for target in [
        Trip.Status.SENT_FOR_LOADING,
        Trip.Status.LOADING,
        Trip.Status.LOADED,
        Trip.Status.ROAD_TRANSIT,
        Trip.Status.IN_TRANSIT,
        Trip.Status.BORDER,
        Trip.Status.CUSTOMS,
    ]:
        TripWorkflowService.transition_trip(trip.id, target, fx["admin_user"])
    trip.refresh_from_db()

    allowed = TripWorkflowService.get_allowed_targets(trip)
    assert Trip.Status.GOING_TO_CLIENT not in allowed
    assert Trip.Status.ARRIVED_AT_CLIENT not in allowed
    assert Trip.Status.QUANTITY_CONTROL not in allowed
    assert Trip.Status.GOING_TO_COMPANY_STOCK in allowed

    with pytest.raises(InvalidTripTransition):
        TripWorkflowService.transition_trip(
            trip.id, Trip.Status.GOING_TO_CLIENT, fx["admin_user"]
        )

    for target in COMPANY_STOCK_SEQUENCE_AFTER_CUSTOMS:
        TripWorkflowService.transition_trip(trip.id, target, fx["admin_user"])
    trip.refresh_from_db()

    assert trip.status == Trip.Status.STOCKED
    assert trip.destination_type == Trip.DestinationType.COMPANY_STOCK
    assert trip.client_id is None
    assert not Sale.objects.filter(trip=trip).exists()
    # Bug fix (2026-09-03 recette manuelle): STOCKED used to free the
    # truck (Trip.NON_OCCUPYING_STATUSES included it) - the client's rule
    # is that fuel sitting in company stock does not mean the truck has
    # completed a delivery, so it stays occupied until DELIVERED (or a
    # terminal status).
    assert TruckAvailabilityService.is_truck_available(truck.id) is False


@pytest.mark.django_db
def test_new_trip_on_truck_with_existing_stocked_trip_is_rejected_without_force():
    """Bug fix (2026-09-03 recette manuelle): a truck whose only trip has
    reached STOCKED (fuel sitting in company stock) must not be offered
    for a brand-new assignment - it hasn't actually completed a delivery
    yet."""
    fx = _setup_fixtures("STOCK-REJECT")
    truck = _make_truck("TRK-STOCK-REJECT")
    trip = _make_trip(fx, truck, "TRIP-STOCK-REJECT-001")
    for target in [
        Trip.Status.SENT_FOR_LOADING, Trip.Status.LOADING, Trip.Status.LOADED,
        Trip.Status.ROAD_TRANSIT, Trip.Status.IN_TRANSIT, Trip.Status.BORDER,
        Trip.Status.CUSTOMS,
    ]:
        TripWorkflowService.transition_trip(trip.id, target, fx["admin_user"])
    for target in COMPANY_STOCK_SEQUENCE_AFTER_CUSTOMS:
        TripWorkflowService.transition_trip(trip.id, target, fx["admin_user"])
    trip.refresh_from_db()
    assert trip.status == Trip.Status.STOCKED

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-STOCK-REJECT-002"),
        context={"request": _FakeRequest(fx["admin_user"])},
    )

    assert not serializer.is_valid()
    assert "truck" in serializer.errors


@pytest.mark.django_db
def test_new_trip_on_truck_with_delivered_trip_is_allowed():
    fx = _setup_fixtures("DELIVERED-ALLOW")
    truck = _make_truck("TRK-DELIVERED-ALLOW")
    trip = _make_trip(fx, truck, "TRIP-DELIVERED-ALLOW-001")
    trip.client = Customer.objects.create(name="Delivered Allow Client")
    trip.destination_type = Trip.DestinationType.CUSTOMER
    trip.save(update_fields=["client", "destination_type", "updated_at"])
    for target in FULL_SEQUENCE_AFTER_ASSIGNED[:-1]:  # stop at DELIVERED
        TripWorkflowService.transition_trip(trip.id, target, fx["admin_user"])
    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED

    serializer = TripSerializer(
        data=_trip_payload(
            fx, truck, "TRIP-DELIVERED-ALLOW-002", transporter=truck.owner_transporter_id
        ),
        context={"request": _FakeRequest(fx["admin_user"])},
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_new_trip_on_truck_with_cancelled_trip_is_allowed():
    fx = _setup_fixtures("CANCEL-ALLOW")
    truck = _make_truck("TRK-CANCEL-ALLOW")
    trip = _make_trip(fx, truck, "TRIP-CANCEL-ALLOW-001")
    TripWorkflowService.transition_trip(trip.id, Trip.Status.CANCELLED, fx["admin_user"])
    trip.refresh_from_db()
    assert trip.status == Trip.Status.CANCELLED

    serializer = TripSerializer(
        data=_trip_payload(
            fx, truck, "TRIP-CANCEL-ALLOW-002", transporter=truck.owner_transporter_id
        ),
        context={"request": _FakeRequest(fx["admin_user"])},
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_workflow_allows_client_statuses_after_customer_assignment():
    fx = _setup_fixtures("CLIENT-WFLOW")
    truck = _make_truck("TRK-CLIENT-WFLOW")
    trip = _make_trip(fx, truck, "TRIP-CLIENT-WFLOW-001")
    customer = Customer.objects.create(name="Client workflow")

    for target in [
        Trip.Status.SENT_FOR_LOADING,
        Trip.Status.LOADING,
        Trip.Status.LOADED,
        Trip.Status.ROAD_TRANSIT,
        Trip.Status.IN_TRANSIT,
        Trip.Status.BORDER,
        Trip.Status.CUSTOMS,
    ]:
        TripWorkflowService.transition_trip(trip.id, target, fx["admin_user"])

    TripCostService.assign_customer_for_sale(trip.id, customer.id, fx["admin_user"])
    trip.refresh_from_db()

    allowed = TripWorkflowService.get_allowed_targets(trip)
    assert Trip.Status.GOING_TO_CLIENT in allowed
    assert Trip.Status.GOING_TO_COMPANY_STOCK not in allowed


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
    late_trip.client = Customer.objects.create(name="Cancel Late Client")
    late_trip.destination_type = Trip.DestinationType.CUSTOMER
    late_trip.save(update_fields=["client", "destination_type", "updated_at"])
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
    truck = _make_truck("TRK-SER-OK", owner_transporter=fx["transporter"])

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
    truck = _make_truck(
        "TRK-SER-CAP-OK", owner_transporter=fx["transporter"]
    )  # capacity_litres = 45000.00

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
    truck = _make_truck("TRK-SER-FORCE", owner_transporter=fx["transporter"])
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

# Everything the raw status bar (POST /status/) is still allowed to do -
# stops at ARRIVED_AT_CLIENT. DELIVERED/COMPLETED are form-only now (they
# come out of /delivery-control/ and /client-verification/, never a manual
# transition - 2026-09-07 recette), see _drive_trip_through_delivery below.
_FORWARD_SEQUENCE_STATUS_NAMES = [
    "SENT_FOR_LOADING",
    "LOADING",
    "LOADED",
    "ROAD_TRANSIT",
    "IN_TRANSIT",
    "BORDER",
    "CUSTOMS",
    "GOING_TO_CLIENT",
    "ARRIVED_AT_CLIENT",
]


def _drive_trip_through_delivery(client, trip_id):
    """Walk a freshly-created trip all the way to COMPLETED the way the UI
    does: the status bar up to ARRIVED_AT_CLIENT, then the delivery control
    (-> DELIVERED + Sale) and the client verification (-> auto COMPLETED)."""
    for target in _FORWARD_SEQUENCE_STATUS_NAMES:
        response = client.post(f"/api/trips/{trip_id}/status/", {"new_status": target})
        assert response.status_code == 200, response.data

    delivery_response = client.post(
        f"/api/trips/{trip_id}/delivery-control/",
        {
            "received_quantity": "45000.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
            "unit_selling_price": "900.0000",
        },
    )
    assert delivery_response.status_code == 201, delivery_response.data

    verification_response = client.post(
        f"/api/trips/{trip_id}/client-verification/",
        {"received_quantity": "45000.00", "verified_at": "2026-08-18"},
    )
    assert verification_response.status_code == 200, verification_response.data


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

    trucks = [
        _make_truck(f"TRK-API-450K-{letter}", owner_transporter=fx["transporter"])
        for letter in "ABCDEF"
    ]

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
        _drive_trip_through_delivery(client, trip_id)

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
        _drive_trip_through_delivery(client, trip_id)

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
    truck = _make_truck("TRK-API-LOCK", owner_transporter=fx["transporter"])
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
    truck = _make_truck("TRK-API-BL-GEN", owner_transporter=fx["transporter"])
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
    truck = _make_truck("TRK-API-BL-KEEP", owner_transporter=fx["transporter"])
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
    truck = _make_truck("TRK-API-DIRECT", owner_transporter=fx["transporter"])
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
    _advance_to_arrived_at_client(trip, fx["admin_user"])
    return trip


@pytest.mark.django_db
def test_record_delivery_defaults_received_qty_to_loaded_quantity():
    # Client correction (2026-09-04 recette): received_qty is now optional -
    # omitting it defaults to "full quantity received, zero loss" so a
    # direct ARRIVED_AT_CLIENT -> DELIVERED confirmation needs no quantity
    # control step at all.
    fx = _fixtures_with_customer("DS-DEFAULT-QTY")
    trip = _deliverable_trip(fx, "TRIP-DS-DEFAULT-QTY-001")

    control = DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )

    assert control.received_quantity == trip.quantity_loaded
    assert control.loss_quantity == Decimal("0.00")
    assert control.chargeable_loss_quantity == Decimal("0.00")


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
def test_delivery_service_unit_selling_price_override_creates_history_entry():
    # No price on file yet - the override supplied at confirmation time is
    # used for the Sale and appended as the new customer-specific latest
    # price, so the next delivery for this product/customer suggests it.
    fx = _fixtures_with_customer("DS-OVERRIDE")
    trip = _deliverable_trip(fx, "TRIP-DS-OVERRIDE-001")

    control = DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("44850.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("700.0000"),
    )

    assert control.trip_id == trip.id
    assert trip.sale.unit_selling_price == Decimal("700.0000")
    assert ProductSellingPriceHistory.objects.filter(
        product=fx["product"], customer=fx["customer"], price=Decimal("700.0000")
    ).exists()
    assert DeliveryService.get_latest_selling_price(
        fx["product"].id, fx["customer"].id
    ) == Decimal("700.0000")


@pytest.mark.django_db
def test_delivery_service_unit_selling_price_override_matching_existing_skips_duplicate():
    # The form pre-fills the override field from the existing suggestion;
    # submitting it unchanged must not append a redundant history row.
    fx = _fixtures_with_customer("DS-OVERRIDE-NODUP")
    trip = _deliverable_trip(fx, "TRIP-DS-OVERRIDE-NODUP-001")
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
        unit_selling_price=Decimal("650.0000"),
    )

    assert ProductSellingPriceHistory.objects.filter(
        product=fx["product"], customer=fx["customer"]
    ).count() == 1
    assert trip.sale.unit_selling_price == Decimal("650.0000")


@pytest.mark.django_db
def test_delivery_service_happy_path_creates_deduction_sale_and_invoice():
    # Recette corrections Task 3 (2026-09-04): the transporter is only
    # charged for the loss above tolerance (150L loss - 100L tolerance =
    # 50L chargeable), matching DeliveryControl.chargeable_loss_quantity.
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
    assert deduction.unit_price == Decimal("650.0000")
    assert deduction.amount == Decimal("32500.00")
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
def test_transport_deduction_is_valued_at_customer_sale_price_not_supplier_cost():
    """CONFIRMED BUSINESS RULE (client, 2026-09-06) - this is deliberate,
    not a bug: the transporter's chargeable fuel-loss deduction is valued
    at the customer's sale price, never at the supplier's purchase cost.

    Exact client-confirmed example: 300 L facturables x 900 XOF/L (prix de
    vente client) = 270,000 XOF. The supplier's own purchase price is set
    to a very different value (500 XOF/L) here specifically to prove the
    deduction tracks the sale price and NOT it - do not "fix" this test or
    apps.trips.services.DeliveryService.sync_transport_shortage_deduction
    to use trip.supplier_order.unit_price without a new, explicit client
    instruction overriding this one.
    """
    fx = _fixtures_with_customer("DS-SALE-PRICE-RULE")
    fx["supplier_order"].unit_price = Decimal("500.0000")
    fx["supplier_order"].save()
    trip = _deliverable_trip(fx, "TRIP-DS-SALE-PRICE-RULE-001")
    LossToleranceConfig.objects.create(
        tolerance_litres=Decimal("100.00"), updated_by=fx["admin_user"]
    )

    # 400 L short of the 45,000 L loaded; 100 L tolerated -> 300 L chargeable.
    control = DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("44600.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("900.0000"),
    )

    assert control.chargeable_loss_quantity == Decimal("300.00")

    deduction = TransportDeduction.objects.get(trip=trip)
    assert deduction.chargeable_quantity == Decimal("300.00")
    # Valued at the client's sale price (900), not the supplier's cost (500).
    assert deduction.unit_price == Decimal("900.0000")
    assert deduction.amount == Decimal("270000.00")


@pytest.mark.django_db
def test_delivery_service_syncs_transport_deduction_without_duplicates():
    fx = _fixtures_with_customer("DS-DEDUCT-SYNC")
    trip = _deliverable_trip(fx, "TRIP-DS-DEDUCT-SYNC-001")
    payment = TransportPayment.objects.create(
        trip=trip,
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    # Recette corrections Task 3 review (2026-09-04): sync_transport_shortage_
    # deduction now reads the tolerance frozen on trip.delivery_control rather
    # than a live LossToleranceConfig fetch, so a DeliveryControl must exist
    # before calling it directly - deliver with the default full-quantity/
    # zero-loss received_qty (Task 2) purely to create one; the subsequent
    # sync calls below (each with their own received_qty/unit_selling_price)
    # are what's actually under test.
    DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("700.0000"),
    )

    # Recette corrections Task 3 (2026-09-04): missing quantity is charged
    # net of the 100L default tolerance (300L missing -> 200L chargeable,
    # then 400L missing -> 300L chargeable), still updating the same
    # deduction row in place rather than creating a second one.
    DeliveryService.sync_transport_shortage_deduction(
        trip=trip,
        received_qty=Decimal("44700.00"),
        unit_selling_price=Decimal("600.0000"),
    )
    DeliveryService.sync_transport_shortage_deduction(
        trip=trip,
        received_qty=Decimal("44600.00"),
        unit_selling_price=Decimal("610.0000"),
    )

    assert TransportDeduction.objects.filter(trip=trip).count() == 1
    deduction = TransportDeduction.objects.get(trip=trip)
    assert deduction.chargeable_quantity == Decimal("300.00")
    assert deduction.unit_price == Decimal("610.0000")
    assert deduction.amount == Decimal("183000.00")

    payment.refresh_from_db()
    assert payment.deduction_amount == Decimal("183000.00")
    assert payment.net_amount == Decimal("517000.00")

    DeliveryService.sync_transport_shortage_deduction(
        trip=trip,
        received_qty=Decimal("45000.00"),
        unit_selling_price=Decimal("610.0000"),
    )

    assert not TransportDeduction.objects.filter(trip=trip).exists()
    payment.refresh_from_db()
    assert payment.deduction_amount == Decimal("0.00")
    assert payment.net_amount == Decimal("700000.00")


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
def test_delivery_service_does_not_deduct_missing_quantity_within_tolerance():
    # Recette corrections Task 3 (2026-09-04): fixes a pre-existing bug where
    # sync_transport_shortage_deduction charged the transporter for the full
    # missing quantity, ignoring LossToleranceConfig entirely. A loss within
    # tolerance must not create/charge any TransportDeduction.
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
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT
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
# Recette corrections Task 3 (2026-09-04): sync_transport_shortage_deduction
# must respect LossToleranceConfig instead of charging the transporter for
# the full missing quantity, and DeliveryService.record_client_verification
# lets the client report a real post-delivery discrepancy that corrects the
# DeliveryControl created at delivery time (defaulted to full qty/zero loss
# by Task 2) without ever touching Sale.delivered_quantity.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sync_transport_shortage_deduction_respects_tolerance():
    # loss of 80L (<= 100L tolerance): must NOT create/charge a TransportDeduction
    fx = _fixtures_with_customer("SYNC-TOL")
    trip = _deliverable_trip(fx, "TRIP-SYNC-TOL-001")
    LossToleranceConfig.objects.create(
        tolerance_litres=Decimal("100.00"), updated_by=fx["admin_user"]
    )
    # Recette corrections Task 3 review (2026-09-04): sync_transport_shortage_
    # deduction now reads the tolerance frozen on trip.delivery_control, so a
    # DeliveryControl must exist first - deliver at full quantity/zero loss
    # (Task 2's default) purely to freeze the 100L tolerance just configured
    # above; the sync call below (with its own received_qty) is what's tested.
    DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )

    DeliveryService.sync_transport_shortage_deduction(
        trip=trip, received_qty=Decimal("44920.00"), unit_selling_price=Decimal("850.0000")
    )

    assert not TransportDeduction.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_sync_transport_shortage_deduction_charges_only_above_tolerance():
    # loss of 150L: only 50L (150 - 100 tolerance) must be charged
    fx = _fixtures_with_customer("SYNC-OVERTOL")
    trip = _deliverable_trip(fx, "TRIP-SYNC-OVERTOL-001")
    LossToleranceConfig.objects.create(
        tolerance_litres=Decimal("100.00"), updated_by=fx["admin_user"]
    )
    DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )

    DeliveryService.sync_transport_shortage_deduction(
        trip=trip, received_qty=Decimal("44850.00"), unit_selling_price=Decimal("850.0000")
    )

    deduction = TransportDeduction.objects.get(trip=trip)
    assert deduction.chargeable_quantity == Decimal("50.00")


@pytest.mark.django_db
def test_sync_transport_shortage_deduction_no_charge_at_exact_tolerance_boundary():
    # loss of exactly 100L == 100L tolerance: fully absorbed, 0L chargeable -
    # the boundary the pre-fix bug got wrong (it charged the full 100L).
    fx = _fixtures_with_customer("SYNC-EXACTTOL")
    trip = _deliverable_trip(fx, "TRIP-SYNC-EXACTTOL-001")
    LossToleranceConfig.objects.create(
        tolerance_litres=Decimal("100.00"), updated_by=fx["admin_user"]
    )
    DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )

    DeliveryService.sync_transport_shortage_deduction(
        trip=trip, received_qty=Decimal("44900.00"), unit_selling_price=Decimal("850.0000")
    )

    assert not TransportDeduction.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_record_client_verification_80L_loss_company_absorbs():
    fx = _fixtures_with_customer("RCV-80L")
    trip = _deliverable_trip(fx, "TRIP-RCV-80L-001")
    DeliveryService.record_delivery(  # delivered with full qty by default
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )

    control = DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44920.00"),
        verified_at=date.today(), actor=fx["admin_user"], notes="Ecart signale par le client",
    )

    assert control.loss_quantity == Decimal("80.00")
    assert control.chargeable_loss_quantity == Decimal("0.00")
    assert control.company_absorbed_loss_quantity == Decimal("80.00")
    assert not TransportDeduction.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_record_client_verification_150L_loss_splits_company_and_transporter():
    fx = _fixtures_with_customer("RCV-150L")
    trip = _deliverable_trip(fx, "TRIP-RCV-150L-001")
    DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )

    control = DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44850.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )

    assert control.company_absorbed_loss_quantity == Decimal("100.00")
    assert control.chargeable_loss_quantity == Decimal("50.00")
    deduction = TransportDeduction.objects.get(trip=trip)
    assert deduction.chargeable_quantity == Decimal("50.00")


@pytest.mark.django_db
def test_transport_payment_created_after_client_verification_still_nets_the_deduction():
    """Bug fix (annexe au bug recette critique 8bbcd97, 2026-09-06):
    TransportPaymentForm.vue never sends deduction_amount, and
    sync_transport_shortage_deduction (called from record_delivery/
    record_client_verification) only pushes a TransportDeduction's total
    into TransportPayment rows that already exist at that moment - so a
    payment created AFTER the loss is already known (delivery, then client
    verification - the common real order) used to start net_amount at the
    full base_amount forever, silently losing the deduction depending on
    the order of actions. TransportPayment.save() now falls back to the
    trip's live TransportDeduction total whenever the caller leaves
    deduction_amount at its default, so the backend is the reliable source
    regardless of what the frontend sends."""
    fx = _fixtures_with_customer("TPAFTERVER")
    trip = _deliverable_trip(fx, "TRIP-TPAFTERVER-001")
    DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )
    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44850.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )
    deduction = TransportDeduction.objects.get(trip=trip)
    assert deduction.amount == Decimal("42500.00")  # 50L chargeable x 850

    payment = TransportPayment.objects.create(
        trip=trip,
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("5000000.00"),
    )

    assert payment.deduction_amount == deduction.amount
    assert payment.net_amount == Decimal("5000000.00") - deduction.amount


@pytest.mark.django_db
def test_record_client_verification_rejected_when_already_verified():
    """Bug fix (recette corrections 2026-09-05): a second client
    verification on the same trip must be refused - it previously silently
    overwrote the first declaration, letting a loss be declared more than
    once on the same trip."""
    fx = _fixtures_with_customer("RCV-TWICE")
    trip = _deliverable_trip(fx, "TRIP-RCV-TWICE-001")
    DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )
    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44920.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )

    with pytest.raises(ValueError):
        DeliveryService.record_client_verification(
            trip_id=trip.id, received_qty=Decimal("44800.00"),
            verified_at=date.today(), actor=fx["admin_user"],
        )


@pytest.mark.django_db
def test_record_client_verification_rejected_on_cancelled_trip():
    fx = _setup_fixtures("RCV-CANCEL")
    truck = _make_truck("TRK-RCV-CANCEL")
    trip = _make_trip(fx, truck, "TRIP-RCV-CANCEL-001")
    TripWorkflowService.transition_trip(trip.id, Trip.Status.CANCELLED, fx["admin_user"])
    trip.refresh_from_db()

    with pytest.raises(ValueError):
        DeliveryService.record_client_verification(
            trip_id=trip.id, received_qty=Decimal("44000.00"),
            verified_at=date.today(), actor=fx["admin_user"],
        )


# ---------------------------------------------------------------------------
# Client request (2026-09-06): the "Vérification client / Déclarer une
# perte" action must close the trip on its own - it was previously left in
# DELIVERED until someone remembered to change the status by hand, which
# both looked unfinished on every trip list/board and (in the client's own
# words) invited a loss to be "declared" again later. Always closes,
# whatever the loss size - the client verification is the final word on
# what was delivered.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_record_client_verification_auto_completes_the_trip_with_a_loss():
    fx = _fixtures_with_customer("RCV-AUTOCLOSE-LOSS")
    trip = _deliverable_trip(fx, "TRIP-RCV-AUTOCLOSE-LOSS-001")
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"], unit_selling_price=Decimal("850.0000"),
    )
    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED  # sanity check before the fix's effect

    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44920.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.COMPLETED
    history = TripStatusHistory.objects.filter(trip=trip).latest("id")
    assert history.previous_status == Trip.Status.DELIVERED
    assert history.new_status == Trip.Status.COMPLETED
    trip.truck.refresh_from_db()
    assert trip.truck.status == Truck.Status.AVAILABLE


@pytest.mark.django_db
def test_record_client_verification_auto_completes_the_trip_with_zero_loss():
    """The client explicitly asked for this even when the full quantity is
    confirmed received (no loss at all) - not only when there's a loss to
    resolve."""
    fx = _fixtures_with_customer("RCV-AUTOCLOSE-ZERO")
    trip = _deliverable_trip(fx, "TRIP-RCV-AUTOCLOSE-ZERO-001")
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"], unit_selling_price=Decimal("850.0000"),
    )

    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=trip.quantity_loaded,
        verified_at=date.today(), actor=fx["admin_user"],
    )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.COMPLETED


@pytest.mark.django_db
def test_record_client_verification_auto_completes_the_trip_with_loss_above_tolerance():
    """Same 150 L split-loss scenario as
    test_record_client_verification_150L_loss_splits_company_and_transporter
    (above tolerance, chargeable to the transporter) - still closes."""
    fx = _fixtures_with_customer("RCV-AUTOCLOSE-BIG")
    trip = _deliverable_trip(fx, "TRIP-RCV-AUTOCLOSE-BIG-001")
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"], unit_selling_price=Decimal("850.0000"),
    )

    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44850.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.COMPLETED


@pytest.mark.django_db
def test_record_client_verification_does_not_error_when_trip_already_completed():
    """A trip can already be COMPLETED before this runs (the operator
    closed it manually first, then still records the client's figure) -
    the precondition above already allows this; the auto-close must not
    then try to "transition" a trip to the status it's already in."""
    fx = _fixtures_with_customer("RCV-AUTOCLOSE-ALREADY")
    trip = _deliverable_trip(fx, "TRIP-RCV-AUTOCLOSE-ALREADY-001")
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"], unit_selling_price=Decimal("850.0000"),
    )
    TripWorkflowService.transition_trip(trip.id, Trip.Status.COMPLETED, fx["admin_user"])
    history_count_before = TripStatusHistory.objects.filter(trip=trip).count()

    control = DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44920.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.COMPLETED
    assert control.loss_quantity == Decimal("80.00")
    # No extra history row - transition_trip() was never called since the
    # trip was already at the target status.
    assert TripStatusHistory.objects.filter(trip=trip).count() == history_count_before


# ---------------------------------------------------------------------------
# Spec 2026-09-07: record_client_verification propagates the corrected
# received quantity to the Sale + Invoice (Task 3).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_client_verification_reduces_a_draft_invoice_to_the_received_quantity():
    fx = _fixtures_with_customer("CV-DRAFT-INV")
    trip = _deliverable_trip(fx, "TRIP-CV-DRAFT-INV-001")  # quantity_loaded 45000
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("900.0000"), changed_by=fx["admin_user"],
    )
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE, controller=fx["admin_user"],
    )
    trip.refresh_from_db()
    invoice = trip.sale.invoice
    assert invoice.status == Invoice.Status.DRAFT
    assert trip.sale.delivered_quantity == Decimal("45000.00")
    assert invoice.total_amount == Decimal("40500000.00")

    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44800.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )

    trip = Trip.objects.get(pk=trip.id)
    assert trip.sale.delivered_quantity == Decimal("44800.00")
    invoice.refresh_from_db()
    assert invoice.total_amount == Decimal("40320000.00")
    assert InvoiceCorrection.objects.filter(invoice=invoice).count() == 0


@pytest.mark.django_db
def test_customer_ledger_invoice_exposes_loaded_and_received_quantities():
    # Task 8: SaleSerializer (nested as sale_detail in the client ledger)
    # exposes trip.quantity_loaded alongside the now-received
    # delivered_quantity so the ledger UI can show loaded vs received.
    fx = _fixtures_with_customer("CV-LEDGER-QTY")
    trip = _deliverable_trip(fx, "TRIP-CV-LEDGER-QTY-001")  # quantity_loaded 45000
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("900.0000"), changed_by=fx["admin_user"],
    )
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE, controller=fx["admin_user"],
    )
    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44800.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    resp = client.get(f"/api/customers/{fx['customer'].id}/ledger/")

    assert resp.status_code == 200
    sale_detail = resp.data["invoices"][0]["sale_detail"]
    assert sale_detail["quantity_loaded"] == "45000.00"
    assert sale_detail["delivered_quantity"] == "44800.00"


@pytest.mark.django_db
def test_client_verification_on_a_validated_invoice_writes_a_correction_row():
    fx = _fixtures_with_customer("CV-VALID-INV")
    trip = _deliverable_trip(fx, "TRIP-CV-VALID-INV-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("900.0000"), changed_by=fx["admin_user"],
    )
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE, controller=fx["admin_user"],
    )
    trip.refresh_from_db()
    invoice = trip.sale.invoice
    InvoiceService.validate_invoice(invoice.id, fx["admin_user"])

    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44800.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )

    invoice.refresh_from_db()
    assert invoice.total_amount == Decimal("40320000.00")
    correction = InvoiceCorrection.objects.get(invoice=invoice)
    assert correction.field_name == "delivered_quantity"
    assert "Vérification client" in correction.reason


@pytest.mark.django_db
def test_client_verification_is_blocked_when_the_invoice_is_paid():
    fx = _fixtures_with_customer("CV-PAID-INV")
    trip = _deliverable_trip(fx, "TRIP-CV-PAID-INV-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("900.0000"), changed_by=fx["admin_user"],
    )
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE, controller=fx["admin_user"],
    )
    trip.refresh_from_db()
    invoice = trip.sale.invoice
    InvoiceService.validate_invoice(invoice.id, fx["admin_user"])
    Invoice.objects.filter(pk=invoice.id).update(status=Invoice.Status.PAID)

    with pytest.raises(InvoicePaidCorrectionUnsupported):
        DeliveryService.record_client_verification(
            trip_id=trip.id, received_qty=Decimal("44800.00"),
            verified_at=date.today(), actor=fx["admin_user"],
        )

    trip = Trip.objects.get(pk=trip.id)
    assert trip.status == Trip.Status.DELIVERED  # not completed
    assert trip.sale.delivered_quantity == Decimal("45000.00")
    assert DeliveryControl.objects.get(trip=trip).verified_at is None


@pytest.mark.django_db
def test_client_verification_api_returns_400_when_invoice_paid():
    fx = _fixtures_with_customer("CV-PAID-API")
    trip = _deliverable_trip(fx, "TRIP-CV-PAID-API-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("900.0000"), changed_by=fx["admin_user"],
    )
    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    client.post(f"/api/trips/{trip.id}/delivery-control/",
                {"control_date": "2026-08-18", "method": "MANUAL_GAUGE"})
    trip.refresh_from_db()
    invoice = trip.sale.invoice
    InvoiceService.validate_invoice(invoice.id, fx["admin_user"])
    Invoice.objects.filter(pk=invoice.id).update(status=Invoice.Status.PAID)

    resp = client.post(f"/api/trips/{trip.id}/client-verification/",
                       {"received_quantity": "44800.00", "verified_at": "2026-08-18"})
    assert resp.status_code == 400
    assert "encaiss" in resp.data["detail"].lower()


@pytest.mark.django_db
def test_client_verification_with_zero_received_quantity_returns_400():
    # C1 regression: a total-loss verification (received_quantity = 0) used
    # to pass the serializer/form and then hit Sale's
    # CheckConstraint(delivered_quantity__gt=0) -> IntegrityError -> HTTP 500.
    # The InvoiceService guard now rejects it as a plain ValueError -> 400,
    # and record_client_verification's @transaction.atomic rolls everything
    # back.
    fx = _fixtures_with_customer("CV-ZERO-API")
    trip = _deliverable_trip(fx, "TRIP-CV-ZERO-API-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("900.0000"), changed_by=fx["admin_user"],
    )
    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    client.post(f"/api/trips/{trip.id}/delivery-control/",
                {"control_date": "2026-08-18", "method": "MANUAL_GAUGE"})
    trip.refresh_from_db()
    invoice = trip.sale.invoice
    original_qty = trip.sale.delivered_quantity

    resp = client.post(f"/api/trips/{trip.id}/client-verification/",
                       {"received_quantity": "0", "verified_at": "2026-08-18"})

    assert resp.status_code == 400
    assert invoice.invoice_number in resp.data["detail"]

    trip = Trip.objects.get(pk=trip.id)
    assert trip.status == Trip.Status.DELIVERED
    assert trip.sale.delivered_quantity == original_qty
    assert DeliveryControl.objects.get(trip=trip).verified_at is None


# ---------------------------------------------------------------------------
# Recette corrections Task 6 (2026-09-04): POST /api/trips/{id}/client-
# verification/ - thin HTTP wrapper around
# DeliveryService.record_client_verification(), same conventions as the
# delivery-control API tests above.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_client_verification_updates_delivery_control():
    fx = _fixtures_with_customer("API-CV-HAPPY")
    trip = _deliverable_trip(fx, "TRIP-API-CV-HAPPY-001")
    DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.post(
        f"/api/trips/{trip.id}/client-verification/",
        {
            "received_quantity": "44920.00",
            "verified_at": str(date.today()),
            "notes": "Ecart client",
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["received_quantity"] == "44920.00"
    trip.refresh_from_db()
    assert trip.status == Trip.Status.COMPLETED


@pytest.mark.django_db
def test_api_client_verification_rejected_when_already_verified():
    fx = _fixtures_with_customer("API-CV-TWICE")
    trip = _deliverable_trip(fx, "TRIP-API-CV-TWICE-001")
    DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    first = client.post(
        f"/api/trips/{trip.id}/client-verification/",
        {"received_quantity": "44920.00", "verified_at": str(date.today())},
        format="json",
    )
    assert first.status_code == 200, first.data

    second = client.post(
        f"/api/trips/{trip.id}/client-verification/",
        {"received_quantity": "44800.00", "verified_at": str(date.today())},
        format="json",
    )
    assert second.status_code == 400


@pytest.mark.django_db
def test_api_client_verification_rejected_on_non_delivered_trip():
    fx = _fixtures_with_customer("API-CV-REJECT")
    # _deliverable_trip() advances to ARRIVED_AT_CLIENT only - no
    # delivery-control/DELIVERED transition yet, so no DeliveryControl
    # exists to correct.
    trip = _deliverable_trip(fx, "TRIP-API-CV-REJECT-001")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.post(
        f"/api/trips/{trip.id}/client-verification/",
        {"received_quantity": "44000.00", "verified_at": str(date.today())},
        format="json",
    )

    assert response.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Client modifications Task 3: sale-below-cost guard (fuel-only cost basis
# here, 45,000 L @ 600.0000 -> 600.0000 unit cost, no transport/expenses).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delivery_service_blocks_sale_below_cost_without_confirmation():
    fx = _fixtures_with_customer("DS-BELOWCOST")
    trip = _deliverable_trip(fx, "TRIP-DS-BELOWCOST-001")

    with pytest.raises(SaleBelowCostConfirmationRequired):
        DeliveryService.record_delivery(
            trip_id=trip.id,
            received_qty=Decimal("44850.00"),
            control_date="2026-08-18",
            method=DeliveryControl.Method.MANUAL_GAUGE,
            controller=fx["admin_user"],
            unit_selling_price=Decimal("500.0000"),  # below the 600.0000 unit cost
        )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT
    assert not DeliveryControl.objects.filter(trip=trip).exists()
    assert not Sale.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_delivery_service_compares_selling_price_against_full_unit_cost_basis():
    fx = _fixtures_with_customer("DS-FULLCOST")
    fx["supplier_order"].unit_price = Decimal("500.0000")
    fx["supplier_order"].save(update_fields=["unit_price"])

    trip = _deliverable_trip(fx, "TRIP-DS-FULLCOST-001")
    TransportPayment.objects.create(
        trip=trip,
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.PER_LITRE,
        unit_price_per_litre=Decimal("65.0000"),
        base_amount=Decimal("2925000.00"),
    )
    for category, unit_amount in [
        (Expense.Category.TRANSIT, Decimal("10.0000")),
        (Expense.Category.CUSTOMS, Decimal("225.0000")),
    ]:
        expense = Expense.objects.create(
            category=category,
            amount=(unit_amount * trip.quantity_loaded).quantize(Decimal("0.01")),
            calculation_method=Expense.CalculationMethod.PER_LITRE,
            date="2026-08-18",
        )
        ExpenseAllocation.objects.create(
            expense=expense,
            content_type=ContentType.objects.get_for_model(Trip),
            object_id=trip.id,
            allocated_amount=expense.amount,
        )

    basis = TripCostService.calculate_trip_cost_basis(trip)
    assert basis["unit_cost"] == Decimal("800.0000")
    assert basis["unit_components_per_litre"] == {
        "supplier": Decimal("500.0000"),
        "commission_transporter": Decimal("65.0000"),
        "transit": Decimal("10.0000"),
        "road_transit": Decimal("0.0000"),
        "border": Decimal("0.0000"),
        "customs": Decimal("225.0000"),
        "loading": Decimal("0.0000"),
        "other": Decimal("0.0000"),
    }

    assert TripCostService.compare_unit_selling_price(trip, Decimal("790.0000")) == {
        "unit_cost": Decimal("800.0000"),
        "unit_selling_price": Decimal("790.0000"),
        "unit_result": Decimal("-10.0000"),
        "result_type": "loss",
    }
    assert TripCostService.compare_unit_selling_price(trip, Decimal("800.0000"))[
        "result_type"
    ] == "break_even"
    assert TripCostService.compare_unit_selling_price(trip, Decimal("850.0000")) == {
        "unit_cost": Decimal("800.0000"),
        "unit_selling_price": Decimal("850.0000"),
        "unit_result": Decimal("50.0000"),
        "result_type": "profit",
    }

    with pytest.raises(SaleBelowCostConfirmationRequired):
        DeliveryService.record_delivery(
            trip_id=trip.id,
            received_qty=Decimal("44850.00"),
            control_date="2026-08-18",
            method=DeliveryControl.Method.MANUAL_GAUGE,
            controller=fx["admin_user"],
            unit_selling_price=Decimal("790.0000"),
        )


@pytest.mark.django_db
def test_delivery_service_allows_sale_below_cost_with_confirmation_and_margin_is_negative():
    fx = _fixtures_with_customer("DS-BELOWCOST-OK")
    trip = _deliverable_trip(fx, "TRIP-DS-BELOWCOST-OK-001")

    control = DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("44850.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("500.0000"),
        confirm_loss=True,
    )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED
    assert control.trip_id == trip.id
    assert trip.sale.unit_selling_price == Decimal("500.0000")

    from apps.reports.services.profit import TripProfitService

    assert TripProfitService.calculate_current_margin(trip) < 0


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
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT
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
def test_api_delivery_control_below_cost_rejected_422_then_confirmed_succeeds():
    fx = _fixtures_with_customer("API-DC-BELOWCOST")
    trip = _deliverable_trip(fx, "TRIP-API-DC-BELOWCOST-001")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    rejected = client.post(
        f"/api/trips/{trip.id}/delivery-control/",
        {
            "received_quantity": "44850.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
            "unit_selling_price": "500.0000",  # below the 600.0000 fuel-only unit cost
        },
    )
    assert rejected.status_code == 422, rejected.data

    trip.refresh_from_db()
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT
    assert not Sale.objects.filter(trip=trip).exists()

    confirmed = client.post(
        f"/api/trips/{trip.id}/delivery-control/",
        {
            "received_quantity": "44850.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
            "unit_selling_price": "500.0000",
            "confirm_loss": True,
        },
    )
    assert confirmed.status_code == 201, confirmed.data

    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED
    assert trip.sale.unit_selling_price == Decimal("500.0000")


@pytest.mark.django_db
def test_api_suggested_selling_price_returns_latest_or_null():
    fx = _fixtures_with_customer("API-SUGGEST-PRICE")
    trip = _deliverable_trip(fx, "TRIP-API-SUGGEST-PRICE-01")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    empty = client.get(f"/api/trips/{trip.id}/suggested-selling-price/")
    assert empty.status_code == 200
    assert empty.data["price"] is None

    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    filled = client.get(f"/api/trips/{trip.id}/suggested-selling-price/")
    assert filled.status_code == 200
    assert filled.data["price"] == "650.0000"


@pytest.mark.django_db
def test_api_delivery_control_unit_selling_price_override_used_for_sale():
    fx = _fixtures_with_customer("API-DC-OVERRIDE")
    trip = _deliverable_trip(fx, "TRIP-API-DC-OVERRIDE-01")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.post(
        f"/api/trips/{trip.id}/delivery-control/",
        {
            "received_quantity": "44850.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
            "unit_selling_price": "700.0000",
        },
    )

    assert response.status_code == 201, response.data
    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED
    assert trip.sale.unit_selling_price == Decimal("700.0000")
    assert ProductSellingPriceHistory.objects.filter(
        product=fx["product"], customer=fx["customer"], price=Decimal("700.0000")
    ).exists()


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
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT


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
    truck = _make_truck("TRK-API-INV-QTY", owner_transporter=fx["transporter"])

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    trip_response = client.post(
        "/api/trips/",
        _api_trip_payload(fx, truck, quantity="45000.00", client=fx["customer"].id),
    )
    assert trip_response.status_code == 201, trip_response.data
    trip_id = trip_response.data["id"]

    for target in _FORWARD_SEQUENCE_STATUS_NAMES:  # walks up to ARRIVED_AT_CLIENT
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


@pytest.mark.django_db
def test_api_allowed_statuses_after_delivery_control_does_not_offer_delivered_again():
    fx = _fixtures_with_customer("API-DELIV-NEXT")
    trip = _deliverable_trip(fx, "TRIP-API-DELIV-NEXT-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"],
        customer=fx["customer"],
        price=Decimal("650.0000"),
        changed_by=fx["admin_user"],
    )

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    delivery_response = client.post(
        f"/api/trips/{trip.id}/delivery-control/",
        {
            "received_quantity": "44850.00",
            "control_date": "2026-08-18",
            "method": "MANUAL_GAUGE",
        },
    )
    assert delivery_response.status_code == 201, delivery_response.data

    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED

    allowed_response = client.get(f"/api/trips/{trip.id}/allowed-statuses/")

    assert allowed_response.status_code == 200
    # Neither form-only status is ever offered as a manual status-bar choice:
    # DELIVERED is behind, and COMPLETED is only reached via the client
    # verification flow, never a raw transition (2026-09-07 recette).
    assert Trip.Status.DELIVERED not in allowed_response.data["statuses"]
    assert Trip.Status.COMPLETED not in allowed_response.data["statuses"]


@pytest.mark.django_db
def test_api_status_bar_rejects_manual_delivered_and_completed():
    """2026-09-07 recette: the raw status bar (POST /status/) must not be a
    shortcut past the delivery control / client verification - jumping
    straight to DELIVERED or COMPLETED skipped the sale price and the loss
    declaration and left the trip with no Sale."""
    fx = _fixtures_with_customer("API-FORMONLY")
    trip = _deliverable_trip(fx, "TRIP-API-FORMONLY-001")
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    delivered_response = client.post(
        f"/api/trips/{trip.id}/status/", {"new_status": Trip.Status.DELIVERED}
    )
    assert delivered_response.status_code == 400
    assert "controle de livraison" in delivered_response.data["detail"].lower()

    trip.refresh_from_db()
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT

    # Take it to DELIVERED the legitimate way, then check COMPLETED is
    # blocked from the bar too.
    ProductSellingPriceHistory.objects.create(
        product=fx["product"],
        customer=fx["customer"],
        price=Decimal("650.0000"),
        changed_by=fx["admin_user"],
    )
    delivery_response = client.post(
        f"/api/trips/{trip.id}/delivery-control/",
        {"received_quantity": "45000.00", "control_date": "2026-08-18", "method": "MANUAL_GAUGE"},
    )
    assert delivery_response.status_code == 201, delivery_response.data

    completed_response = client.post(
        f"/api/trips/{trip.id}/status/", {"new_status": Trip.Status.COMPLETED}
    )
    assert completed_response.status_code == 400
    assert "verification client" in completed_response.data["detail"].lower()

    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED


@pytest.mark.django_db
def test_api_trip_margin_unavailable_before_sale():
    """TripDetail.vue's profit block: a trip with no Sale yet (i.e. not
    delivered) reports {"available": false} instead of an error."""
    fx = _setup_fixtures("API-MARGIN-NOSALE")
    truck = _make_truck("TRK-MARGIN-NOSALE")
    trip = _make_trip(fx, truck, "TRIP-MARGIN-NOSALE-001")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.get(f"/api/trips/{trip.id}/margin/")

    assert response.status_code == 200
    assert response.data == {"available": False}


@pytest.mark.django_db
def test_api_trip_margin_breakdown_after_delivery():
    """Guide Section 9.1's cost breakdown, end-to-end through the API:
    45,000 L @ 600 fuel cost, no transport payment or expenses recorded,
    44,850 L delivered @ 650 (150 L loss, 100 L tolerance) -> only the 50 L
    above tolerance is charged back to the transporter at selling price
    (recette corrections Task 3 tolerance fix) -> margin = revenue + loss
    indemnity - real loaded cost."""
    fx = _fixtures_with_customer("API-MARGIN-OK")
    trip = _deliverable_trip(fx, "TRIP-API-MARGIN-OK-001")
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

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.get(f"/api/trips/{trip.id}/margin/")

    assert response.status_code == 200
    assert response.data["available"] is True
    # revenue/fuel_purchase_cost aren't quantized in TripProfitService (they
    # multiply a 2dp quantity by a 4dp unit price) - only margin is.
    assert response.data["revenue"] == "29152500.000000"
    assert response.data["quantity_loaded"] == "45000.00"
    assert response.data["quantity_invoiced"] == "44850.00"
    assert response.data["transporter_loss_quantity"] == "50.00"
    assert response.data["transporter_loss_indemnity"] == "32500.00"
    assert response.data["fuel_purchase_cost"] == "27000000.000000"
    assert response.data["transport_cost"] == "0.00"
    assert response.data["total_expenses"] == "0.00"
    assert response.data["real_total_cost"] == "27000000.000000"
    # As of spec 2026-09-07: the 100 L absorbed by the company (150 L loss -
    # 50 L chargeable to the transporter) is NOT subtracted from margin. The
    # invoice reflects the received quantity, so revenue already integrates it;
    # the absorbed loss stays exposed as company_absorbed_loss_amount for display.
    # Margin = 29,152,500 + 32,500 - 27,000,000 = 2,185,000.00.
    assert response.data["company_absorbed_loss_amount"] == "65000.00"
    assert response.data["margin"] == "2185000.00"


# ---------------------------------------------------------------------------
# Task 1 (client modifications plan): Trip.destination_type,
# TripCostService.calculate_trip_cost_basis, and
# TripCostService.assign_customer_for_sale.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_trip_with_no_client_and_no_customer_order_defaults_to_company_stock():
    fx = _setup_fixtures("DEST-STOCK")
    truck = _make_truck("TRK-DEST-STOCK")

    trip = _make_trip(fx, truck, "TRIP-DEST-STOCK-001")

    assert trip.client is None
    assert trip.customer_order is None
    assert trip.destination_type == Trip.DestinationType.COMPANY_STOCK


@pytest.mark.django_db
def test_trip_serializer_normalizes_destination_type_to_company_stock_by_default():
    fx = _setup_fixtures("DEST-DEFAULT")
    truck = _make_truck("TRK-DEST-DEFAULT", owner_transporter=fx["transporter"])

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-DEST-DEFAULT-001"),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["destination_type"] == Trip.DestinationType.COMPANY_STOCK


@pytest.mark.django_db
def test_trip_serializer_normalizes_destination_type_to_customer_when_client_given():
    fx = _setup_fixtures("DEST-CLIENT")
    truck = _make_truck("TRK-DEST-CLIENT", owner_transporter=fx["transporter"])
    customer = Customer.objects.create(name="Dest Client")

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-DEST-CLIENT-001", client=customer.id),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["destination_type"] == Trip.DestinationType.CUSTOMER


@pytest.mark.django_db
def test_trip_serializer_normalizes_destination_type_to_customer_when_customer_order_given():
    fx = _setup_fixtures("DEST-ORDER")
    truck = _make_truck("TRK-DEST-ORDER", owner_transporter=fx["transporter"])
    customer = Customer.objects.create(name="Dest Order Client")
    order = CustomerOrder.objects.create(
        customer=customer,
        product=fx["product"],
        quantity_ordered=Decimal("45000.00"),
    )

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-DEST-ORDER-001", customer_order=order.id),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["destination_type"] == Trip.DestinationType.CUSTOMER


@pytest.mark.django_db
def test_trip_serializer_rejects_client_and_customer_order_for_different_customers():
    fx = _setup_fixtures("DEST-MISMATCH")
    truck = _make_truck("TRK-DEST-MISMATCH", owner_transporter=fx["transporter"])
    customer_a = Customer.objects.create(name="Customer A")
    customer_b = Customer.objects.create(name="Customer B")
    order = CustomerOrder.objects.create(
        customer=customer_b,
        product=fx["product"],
        quantity_ordered=Decimal("45000.00"),
    )

    serializer = TripSerializer(
        data=_trip_payload(
            fx,
            truck,
            "TRIP-DEST-MISMATCH-001",
            client=customer_a.id,
            customer_order=order.id,
        ),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert not serializer.is_valid()
    assert "client" in serializer.errors


@pytest.mark.django_db
def test_trip_serializer_accepts_client_matching_customer_order_customer():
    fx = _setup_fixtures("DEST-MATCH")
    truck = _make_truck("TRK-DEST-MATCH", owner_transporter=fx["transporter"])
    customer = Customer.objects.create(name="Matching Customer")
    order = CustomerOrder.objects.create(
        customer=customer,
        product=fx["product"],
        quantity_ordered=Decimal("45000.00"),
    )

    serializer = TripSerializer(
        data=_trip_payload(
            fx,
            truck,
            "TRIP-DEST-MATCH-001",
            client=customer.id,
            customer_order=order.id,
        ),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["destination_type"] == Trip.DestinationType.CUSTOMER


@pytest.mark.django_db
def test_assign_customer_for_sale_changes_destination_type_before_delivery():
    fx = _setup_fixtures("ASSIGN-PRE")
    truck = _make_truck("TRK-ASSIGN-PRE")
    trip = _make_trip(fx, truck, "TRIP-ASSIGN-PRE-001")
    _advance_to_arrived_at_client(trip, fx["admin_user"])
    customer = Customer.objects.create(name="Assign Client Pre")

    updated = TripCostService.assign_customer_for_sale(trip.id, customer.id, fx["admin_user"])

    assert updated.client_id == customer.id
    assert updated.destination_type == Trip.DestinationType.CUSTOMER
    trip.refresh_from_db()
    assert trip.client_id == customer.id
    assert trip.destination_type == Trip.DestinationType.CUSTOMER


@pytest.mark.django_db
def test_assign_customer_for_sale_rejected_once_sale_exists():
    fx = _fixtures_with_customer("ASSIGN-SOLD")
    trip = _deliverable_trip(fx, "TRIP-ASSIGN-SOLD-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"],
        customer=fx["customer"],
        price=Decimal("650.0000"),
        changed_by=fx["admin_user"],
    )
    DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("44850.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )
    other_customer = Customer.objects.create(name="Other Customer")

    with pytest.raises(CustomerAlreadySoldError):
        TripCostService.assign_customer_for_sale(trip.id, other_customer.id, fx["admin_user"])

    trip.refresh_from_db()
    assert trip.client_id == fx["customer"].id  # unchanged - assignment was rejected


@pytest.mark.django_db
def test_trip_cost_service_calculates_cost_basis_from_fuel_transport_and_expenses():
    fx = _setup_fixtures("COST-SVC")
    truck = _make_truck("TRK-COST-SVC")
    trip = _make_trip(fx, truck, "TRIP-COST-SVC-001", quantity=Decimal("40000.00"))

    TransportPayment.objects.create(
        trip=trip,
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("800000.00"),
    )
    customs_expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("1200000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=customs_expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("1200000.00"),
    )
    # Cancelled expenses must never be counted in the cost basis.
    cancelled_expense = Expense.objects.create(
        category=Expense.Category.OTHER,
        amount=Decimal("999999.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
        status=Expense.Status.CANCELLED,
    )
    ExpenseAllocation.objects.create(
        expense=cancelled_expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("999999.00"),
    )

    basis = TripCostService.calculate_trip_cost_basis(trip)

    assert basis["fuel_purchase_cost"] == Decimal("24000000.000000")  # 40000 x 600
    assert basis["transport_cost"] == Decimal("800000.00")
    assert basis["expenses_by_category"] == {Expense.Category.CUSTOMS: Decimal("1200000.00")}
    assert basis["total_expenses"] == Decimal("1200000.00")
    assert basis["total_cost"] == Decimal("26000000.000000")
    assert basis["quantity"] == Decimal("40000.00")
    assert basis["unit_cost"] == Decimal("650")


@pytest.mark.django_db
def test_api_trip_cost_basis_breaks_down_fuel_transport_and_expenses():
    fx = _setup_fixtures("API-COST-BASIS")
    truck = _make_truck("TRK-API-COST-BASIS")
    trip = _make_trip(fx, truck, "TRIP-API-COST-BASIS-001", quantity=Decimal("40000.00"))

    TransportPayment.objects.create(
        trip=trip,
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("800000.00"),
    )
    customs_expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("1200000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=customs_expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("1200000.00"),
    )
    other_expense = Expense.objects.create(
        category=Expense.Category.OTHER,
        amount=Decimal("300000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=other_expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("300000.00"),
    )
    cancelled_expense = Expense.objects.create(
        category=Expense.Category.OTHER,
        amount=Decimal("999999.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
        status=Expense.Status.CANCELLED,
    )
    ExpenseAllocation.objects.create(
        expense=cancelled_expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("999999.00"),
    )

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.get(f"/api/trips/{trip.id}/cost-basis/")

    assert response.status_code == 200
    assert Decimal(response.data["fuel_purchase_cost"]) == Decimal("24000000.000000")
    assert Decimal(response.data["transport_cost"]) == Decimal("800000.00")
    assert Decimal(response.data["expenses_by_category"]["customs"]) == Decimal("1200000.00")
    assert Decimal(response.data["expenses_by_category"]["other"]) == Decimal("300000.00")
    assert "999999.00" not in str(response.data["expenses_by_category"])
    assert Decimal(response.data["total_cost"]) == Decimal("26300000.000000")
    assert Decimal(response.data["quantity"]) == Decimal("40000.00")
    assert Decimal(response.data["unit_cost"]) == Decimal("657.5")


@pytest.mark.django_db
def test_api_assign_customer_endpoint_sets_client_and_destination_type():
    fx = _setup_fixtures("API-ASSIGN")
    truck = _make_truck("TRK-API-ASSIGN")
    trip = _make_trip(fx, truck, "TRIP-API-ASSIGN-001")
    customer = Customer.objects.create(name="API Assign Client")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.post(
        f"/api/trips/{trip.id}/assign-customer/", {"customer": customer.id}
    )

    assert response.status_code == 200, response.data
    assert response.data["client"] == customer.id
    assert response.data["destination_type"] == Trip.DestinationType.CUSTOMER


@pytest.mark.django_db
def test_api_assign_customer_endpoint_rejected_once_sale_exists():
    fx = _fixtures_with_customer("API-ASSIGN-SOLD")
    trip = _deliverable_trip(fx, "TRIP-API-ASSIGN-SOLD-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"],
        customer=fx["customer"],
        price=Decimal("650.0000"),
        changed_by=fx["admin_user"],
    )
    DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("44850.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )
    other_customer = Customer.objects.create(name="API Other Customer")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.post(
        f"/api/trips/{trip.id}/assign-customer/", {"customer": other_customer.id}
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Phase 6 (docs/superpowers/specs/2026-09-02-business-corrections-6-phases-
# design.md): a truck's ownership_type governs whether its trip needs a
# transporter - EXTERNAL always does (auto-derived from truck.
# owner_transporter), COMPANY_OWNED never does (no artificial "internal
# transporter" row is ever created).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_trip_serializer_auto_derives_transporter_from_external_truck():
    fx = _setup_fixtures("EXT-AUTO")
    truck = _make_truck("TRK-EXT-AUTO", owner_transporter=fx["transporter"])

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-EXT-AUTO-001", **{"transporter": None}),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["transporter"] == fx["transporter"]


@pytest.mark.django_db
def test_trip_serializer_rejects_transporter_mismatched_with_external_truck():
    fx = _setup_fixtures("EXT-MISMATCH")
    other_transporter = Transporter.objects.create(name="Other Transport")
    truck = _make_truck("TRK-EXT-MISMATCH", owner_transporter=fx["transporter"])

    serializer = TripSerializer(
        data=_trip_payload(
            fx, truck, "TRIP-EXT-MISMATCH-001", transporter=other_transporter.id
        ),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert not serializer.is_valid()
    assert "transporter" in serializer.errors


@pytest.mark.django_db
def test_trip_serializer_derives_internal_transporter_for_company_owned_truck():
    """Bug fix (2026-09-03 recette manuelle): reverses the original Phase 6
    behavior (was: transporter forced to None) - a COMPANY_OWNED truck's
    owner_transporter is now always the seeded internal transporter
    (Truck.save()), so the trip derives that, same as any other truck."""
    fx = _setup_fixtures("CO-NULL")
    truck = _make_truck("TRK-CO-NULL")  # COMPANY_OWNED by default

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-CO-NULL-001", **{"transporter": None}),
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["transporter"] == truck.owner_transporter
    assert serializer.validated_data["transporter"].is_internal is True


@pytest.mark.django_db
def test_trip_serializer_rejects_transporter_for_company_owned_truck():
    fx = _setup_fixtures("CO-REJECT")
    truck = _make_truck("TRK-CO-REJECT")

    serializer = TripSerializer(
        data=_trip_payload(fx, truck, "TRIP-CO-REJECT-001"),  # includes transporter
        context={"request": _FakeRequest(fx["admin_user"])},
    )
    assert not serializer.is_valid()
    assert "transporter" in serializer.errors


@pytest.mark.django_db
def test_company_owned_truck_chargeable_loss_creates_no_transport_deduction():
    fx = _fixtures_with_customer("CO-LOSS")
    truck = _make_truck("TRK-CO-LOSS")
    trip = Trip.objects.create(
        reference="TRIP-CO-LOSS-001",
        truck=truck,
        transporter=None,
        supplier=fx["supplier"],
        supplier_order=fx["supplier_order"],
        cession_letter=fx["cession"],
        product=fx["product"],
        quantity_loaded=Decimal("45000.00"),
        client=fx["customer"],
        destination_type=Trip.DestinationType.CUSTOMER,
        loading_date="2026-08-18",
        bl_reference="BL-CO-LOSS-001",
        created_by=fx["admin_user"],
    )
    _advance_to_arrived_at_client(trip, fx["admin_user"])
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
        received_qty=Decimal("44850.00"),  # 150 L short, 50 L chargeable
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )

    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED
    assert control.chargeable_loss_quantity == Decimal("50.00")
    # No transporter to charge - the shortfall is an unrecovered loss, not a
    # transporter debt.
    assert not TransportDeduction.objects.filter(trip=trip).exists()
    assert trip.sale.delivered_quantity == Decimal("44850.00")


@pytest.mark.django_db
def test_transport_payment_rejected_for_company_owned_truck_trip():
    fx = _setup_fixtures("CO-PAYREJECT")
    truck = _make_truck("TRK-CO-PAYREJECT")
    trip = Trip.objects.create(
        reference="TRIP-CO-PAYREJECT-001",
        truck=truck,
        transporter=None,
        supplier=fx["supplier"],
        supplier_order=fx["supplier_order"],
        cession_letter=fx["cession"],
        product=fx["product"],
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference="BL-CO-PAYREJECT-001",
        created_by=fx["admin_user"],
    )

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.post(
        "/api/transport-payments/",
        {
            "trip": trip.id,
            "transporter": fx["transporter"].id,
            "calculation_method": "FIXED",
            "base_amount": "500000.00",
        },
    )

    assert response.status_code == 400
    assert "transporteur externe" in str(response.data)


@pytest.mark.django_db
def test_company_owned_truck_with_derived_internal_transporter_creates_no_chargeable_deduction():
    """Bug fix (2026-09-03 recette manuelle): same guarantee as
    test_company_owned_truck_chargeable_loss_creates_no_transport_deduction,
    but exercising the real path (truck.owner_transporter auto-derived to
    the seeded internal transporter, not a trip created with
    transporter=None directly) - proves the is_internal check in
    DeliveryService.sync_transport_shortage_deduction actually fires."""
    fx = _fixtures_with_customer("CO-INTLOSS")
    truck = _make_truck("TRK-CO-INTLOSS")
    assert truck.owner_transporter.is_internal is True
    trip = Trip.objects.create(
        reference="TRIP-CO-INTLOSS-001",
        truck=truck,
        transporter=truck.owner_transporter,
        supplier=fx["supplier"],
        supplier_order=fx["supplier_order"],
        cession_letter=fx["cession"],
        product=fx["product"],
        quantity_loaded=Decimal("45000.00"),
        client=fx["customer"],
        destination_type=Trip.DestinationType.CUSTOMER,
        loading_date="2026-08-18",
        bl_reference="BL-CO-INTLOSS-001",
        created_by=fx["admin_user"],
    )
    _advance_to_arrived_at_client(trip, fx["admin_user"])
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
        received_qty=Decimal("44850.00"),  # 150 L short, 50 L chargeable
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )

    trip.refresh_from_db()
    assert control.chargeable_loss_quantity == Decimal("50.00")
    assert not TransportDeduction.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_transport_payment_rejected_for_internal_transporter_trip():
    """Same as test_transport_payment_rejected_for_company_owned_truck_trip,
    but the trip's transporter is the real, auto-derived internal one, not
    None - proves TransportPaymentSerializer.validate()'s is_internal check
    fires, not just its trip.transporter_id is None fallback."""
    fx = _setup_fixtures("CO-INTPAYREJECT")
    truck = _make_truck("TRK-CO-INTPAYREJECT")
    trip = Trip.objects.create(
        reference="TRIP-CO-INTPAYREJECT-001",
        truck=truck,
        transporter=truck.owner_transporter,
        supplier=fx["supplier"],
        supplier_order=fx["supplier_order"],
        cession_letter=fx["cession"],
        product=fx["product"],
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference="BL-CO-INTPAYREJECT-001",
        created_by=fx["admin_user"],
    )

    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    response = client.post(
        "/api/transport-payments/",
        {
            "trip": trip.id,
            "transporter": truck.owner_transporter.id,
            "calculation_method": "FIXED",
            "base_amount": "500000.00",
        },
    )

    assert response.status_code == 400
    assert "transporteur externe" in str(response.data)

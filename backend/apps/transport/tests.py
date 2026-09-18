from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.transport.models import Driver, Transporter


@pytest.mark.django_db
def test_transporter_str():
    transporter = Transporter.objects.create(name="Diallo Transport")
    assert str(transporter) == "Diallo Transport"


@pytest.mark.django_db
def test_driver_creation_with_only_name_succeeds():
    driver = Driver.objects.create(name="Ibrahim Kone")
    assert driver.phone == ""
    assert driver.license_number == ""


@pytest.fixture
def ops_client():
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    user = User.objects.create_user(phone="+2220000001", pin="1234", role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_transporter_crud_via_api(ops_client):
    created = ops_client.post("/api/transporters/", {"name": "Diallo Transport"})
    assert created.status_code == 201

    listed = ops_client.get("/api/transporters/")
    assert listed.status_code == 200
    # 1 created here + the seeded is_internal=True "Flotte propre / Interne"
    # row (migration 0004_truck_owner_transporter_mandatory, bug fix
    # 2026-09-03 recette manuelle).
    assert listed.data["count"] == 2

    transporter_id = created.data["id"]
    retrieved = ops_client.get(f"/api/transporters/{transporter_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["name"] == "Diallo Transport"

    updated = ops_client.patch(f"/api/transporters/{transporter_id}/", {"phone": "+223 70 00 00 00"})
    assert updated.status_code == 200
    assert updated.data["phone"] == "+223 70 00 00 00"


@pytest.mark.django_db
def test_driver_crud_via_api_with_only_name(ops_client):
    created = ops_client.post("/api/drivers/", {"name": "Ibrahim Kone"})
    assert created.status_code == 201
    assert created.data["phone"] == ""

    driver_id = created.data["id"]
    retrieved = ops_client.get(f"/api/drivers/{driver_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["name"] == "Ibrahim Kone"

    updated = ops_client.patch(f"/api/drivers/{driver_id}/", {"license_number": "ML-12345"})
    assert updated.status_code == 200
    assert updated.data["license_number"] == "ML-12345"


from apps.transport.models import Truck


@pytest.mark.django_db
def test_truck_defaults_to_available_status():
    truck = Truck.objects.create(
        internal_id="TRK-001",
        tractor_registration="AA-123-SN",
        tanker_registration="BB-456-SN",
        capacity_litres="45000.00",
    )
    assert truck.status == Truck.Status.AVAILABLE
    # Bug fix (2026-09-03 recette manuelle): COMPANY_OWNED (the default
    # ownership_type) auto-assigns the seeded internal transporter on
    # save() rather than staying null - see Truck.save().
    assert truck.owner_transporter.is_internal is True


@pytest.mark.django_db
def test_truck_crud_via_api(ops_client):
    created = ops_client.post(
        "/api/trucks/",
        {
            "internal_id": "TRK-002",
            "tractor_registration": "CC-789-SN",
            "tanker_registration": "DD-012-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "COMPANY_OWNED",
        },
    )
    assert created.status_code == 201
    assert created.data["status"] == "AVAILABLE"

    listed = ops_client.get("/api/trucks/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1

    truck_id = created.data["id"]
    retrieved = ops_client.get(f"/api/trucks/{truck_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["internal_id"] == "TRK-002"

    updated = ops_client.patch(f"/api/trucks/{truck_id}/", {"notes": "Needs tyre check"})
    assert updated.status_code == 200
    assert updated.data["notes"] == "Needs tyre check"


@pytest.mark.django_db
def test_truck_defaults_to_active():
    truck = Truck.objects.create(
        internal_id="TRK-ACTIVE-001",
        tractor_registration="AA-123-SN",
        tanker_registration="BB-456-SN",
        capacity_litres="45000.00",
    )
    assert truck.is_active is True


@pytest.mark.django_db
def test_truck_internal_id_is_generated_when_left_blank(ops_client):
    created = ops_client.post(
        "/api/trucks/",
        {
            "tractor_registration": "EE-111-SN",
            "tanker_registration": "FF-222-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "COMPANY_OWNED",
        },
    )
    assert created.status_code == 201, created.data
    assert created.data["internal_id"].startswith("TRK-")


@pytest.mark.django_db
def test_truck_internal_id_generation_increments_and_skips_legacy_format(ops_client):
    Truck.objects.create(
        internal_id="TRK-0001",
        tractor_registration="GG-333-SN",
        tanker_registration="HH-444-SN",
        capacity_litres="45000.00",
    )
    Truck.objects.create(
        internal_id="LEGACY-CODE-9999",
        tractor_registration="II-555-SN",
        tanker_registration="JJ-666-SN",
        capacity_litres="45000.00",
    )

    created = ops_client.post(
        "/api/trucks/",
        {
            "tractor_registration": "KK-777-SN",
            "tanker_registration": "LL-888-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "COMPANY_OWNED",
        },
    )
    assert created.status_code == 201, created.data
    assert created.data["internal_id"] == "TRK-0002"


@pytest.mark.django_db
def test_truck_provided_internal_id_is_kept(ops_client):
    created = ops_client.post(
        "/api/trucks/",
        {
            "internal_id": "CUSTOM-ID-42",
            "tractor_registration": "MM-999-SN",
            "tanker_registration": "NN-000-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "COMPANY_OWNED",
        },
    )
    assert created.status_code == 201, created.data
    assert created.data["internal_id"] == "CUSTOM-ID-42"


# ---------------------------------------------------------------------------
# Phase 6 (docs/superpowers/specs/2026-09-02-business-corrections-6-phases-
# design.md): an EXTERNAL truck always needs owner_transporter; a
# COMPANY_OWNED truck stays free of one - never an artificial "internal
# transporter" row.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_external_truck_without_owner_transporter_is_rejected(ops_client):
    response = ops_client.post(
        "/api/trucks/",
        {
            "internal_id": "TRK-EXT-001",
            "tractor_registration": "OO-111-SN",
            "tanker_registration": "PP-222-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "EXTERNAL",
        },
    )
    assert response.status_code == 400
    assert "owner_transporter" in response.data


@pytest.mark.django_db
def test_external_truck_with_owner_transporter_is_accepted(ops_client):
    transporter = Transporter.objects.create(name="Diallo Transport")

    response = ops_client.post(
        "/api/trucks/",
        {
            "internal_id": "TRK-EXT-002",
            "tractor_registration": "QQ-333-SN",
            "tanker_registration": "RR-444-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "EXTERNAL",
            "owner_transporter": transporter.id,
        },
    )
    assert response.status_code == 201, response.data
    assert response.data["owner_transporter"] == transporter.id


@pytest.mark.django_db
def test_company_owned_truck_without_owner_transporter_auto_assigns_internal(ops_client):
    """Bug fix (2026-09-03 recette manuelle): reverses the original Phase 6
    rule (was: accepted with owner_transporter left null) - every truck
    must be linked to a transporter now, so a COMPANY_OWNED truck posted
    without one gets the seeded internal transporter instead."""
    response = ops_client.post(
        "/api/trucks/",
        {
            "internal_id": "TRK-CO-001",
            "tractor_registration": "SS-555-SN",
            "tanker_registration": "TT-666-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "COMPANY_OWNED",
        },
    )
    assert response.status_code == 201, response.data
    assert response.data["owner_transporter"] is not None


@pytest.mark.django_db
def test_external_truck_cannot_be_assigned_the_internal_transporter(ops_client):
    """Bug fix (2026-09-03 recette manuelle): the seeded "Flotte propre /
    Interne" transporter stands in for the company's own fleet - assigning
    it to a real EXTERNAL truck would silently hide a real transporter
    relationship, so it's rejected the same way a missing transporter is."""
    internal = Transporter.objects.get(is_internal=True)

    response = ops_client.post(
        "/api/trucks/",
        {
            "internal_id": "TRK-EXT-INTERNAL",
            "tractor_registration": "ZZ-999-SN",
            "tanker_registration": "YY-888-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "EXTERNAL",
            "owner_transporter": internal.id,
        },
    )
    assert response.status_code == 400
    assert "owner_transporter" in response.data


@pytest.mark.django_db
def test_company_owned_truck_with_explicit_external_transporter_is_rejected(ops_client):
    """UI recette fix (2026-09-05): only the reverse (EXTERNAL truck +
    internal transporter) was validated - a COMPANY_OWNED truck explicitly
    given a real external transporter slipped through uncaught."""
    external = Transporter.objects.create(name="Diallo Transport")

    response = ops_client.post(
        "/api/trucks/",
        {
            "internal_id": "TRK-CO-EXT",
            "tractor_registration": "AB-111-SN",
            "tanker_registration": "AB-222-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "COMPANY_OWNED",
            "owner_transporter": external.id,
        },
    )
    assert response.status_code == 400
    assert "owner_transporter" in response.data


@pytest.mark.django_db
def test_switching_truck_to_external_without_transporter_is_rejected(ops_client):
    created = ops_client.post(
        "/api/trucks/",
        {
            "internal_id": "TRK-SWITCH-001",
            "tractor_registration": "UU-777-SN",
            "tanker_registration": "VV-888-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "COMPANY_OWNED",
        },
    )
    assert created.status_code == 201, created.data

    response = ops_client.patch(
        f"/api/trucks/{created.data['id']}/", {"ownership_type": "EXTERNAL"}
    )
    assert response.status_code == 400
    assert "owner_transporter" in response.data


# ---------------------------------------------------------------------------
# UI recette fix (2026-09-05): is_internal is now user-editable, guarded
# so the "at least one internal transporter" invariant Truck.save()/
# TruckSerializer rely on can never break.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_transporter_can_be_created_as_internal(ops_client):
    response = ops_client.post(
        "/api/transporters/", {"name": "Flotte Nord", "is_internal": True}
    )
    assert response.status_code == 201, response.data
    assert response.data["is_internal"] is True


@pytest.mark.django_db
def test_transporter_can_be_toggled_to_internal_when_another_stays_internal(ops_client):
    # The seeded "Flotte propre / Interne" row stays internal - this one
    # can freely become a second internal transporter.
    external = Transporter.objects.create(name="Diallo Transport", is_internal=False)

    response = ops_client.patch(
        f"/api/transporters/{external.id}/", {"is_internal": True}
    )
    assert response.status_code == 200, response.data
    assert response.data["is_internal"] is True


@pytest.mark.django_db
def test_last_internal_transporter_cannot_be_turned_external(ops_client):
    internal = Transporter.objects.get(is_internal=True)

    response = ops_client.patch(
        f"/api/transporters/{internal.id}/", {"is_internal": False}
    )
    assert response.status_code == 400
    assert "is_internal" in response.data


@pytest.mark.django_db
def test_internal_transporter_can_be_turned_external_when_another_stays_internal(ops_client):
    internal = Transporter.objects.get(is_internal=True)
    second_internal = Transporter.objects.create(name="Flotte Sud", is_internal=True)

    response = ops_client.patch(
        f"/api/transporters/{internal.id}/", {"is_internal": False}
    )
    assert response.status_code == 200, response.data
    assert response.data["is_internal"] is False
    second_internal.refresh_from_db()
    assert second_internal.is_internal is True


# ---------------------------------------------------------------------------
# Bug fix (2026-09-18): the Transporteurs list's gross_earned/deductions/
# advances_applied/net_balance columns counted a CANCELLED TransportPayment
# as if it were still owed - same "reads as what's currently true" rule
# already applied to TransporterLedgerService.get_ledger.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_transporter_list_excludes_a_cancelled_commission_from_its_totals(ops_client):
    from apps.finance.models import TransportPayment
    from apps.finance.services import TransportPaymentCancellationService
    from apps.trips.tests import _make_trip, _make_truck, _setup_fixtures

    fx = _setup_fixtures("TRP-LIST-CANCEL")
    transporter = fx["transporter"]

    cancelled_trip = _make_trip(fx, _make_truck("TRK-LIST-CANCEL"), "TRIP-LIST-CANCEL-001")
    cancelled_payment = TransportPayment.objects.create(
        trip=cancelled_trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("2700000.00"), deduction_amount=Decimal("117000.00"),
        status=TransportPayment.Status.PAID,
    )
    TransportPaymentCancellationService.cancel_transport_payment(
        cancelled_payment, fx["admin_user"]
    )

    active_trip = _make_trip(fx, _make_truck("TRK-LIST-ACTIVE"), "TRIP-LIST-ACTIVE-001")
    TransportPayment.objects.create(
        trip=active_trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("500000.00"), deduction_amount=Decimal("20000.00"),
    )

    response = ops_client.get(f"/api/transporters/{transporter.id}/")

    assert response.status_code == 200, response.data
    assert response.data["gross_earned"] == "500000.00"
    assert response.data["deductions"] == "20000.00"
    assert response.data["net_balance"] == "480000.00"

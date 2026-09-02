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
    assert listed.data["count"] == 1

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
    assert truck.owner_transporter is None


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
def test_company_owned_truck_without_owner_transporter_is_accepted(ops_client):
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
    assert response.data["owner_transporter"] is None


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

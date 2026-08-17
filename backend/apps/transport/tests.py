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
    user = User.objects.create_user(email="ops@example.com", password="testpass123", role=role)
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

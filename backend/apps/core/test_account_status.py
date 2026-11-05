"""Customer / supplier / transporter status: active, legacy ("Ancien"),
inactive. Legacy = no longer trading but a balance is still open."""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.customers.models import Customer
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter

PATHS = {
    "customers": Customer,
    "suppliers": Supplier,
    "transporters": Transporter,
}


@pytest.fixture
def admin_client():
    admin = User.objects.create_user(
        phone="+2220000099", pin="1234", role=Role.objects.get(name=Role.NAME_ADMIN)
    )
    client = APIClient()
    client.force_authenticate(admin)
    return client


def _names(response):
    # "-" skips the seeded internal-fleet transporter.
    return sorted(r["name"] for r in response.data["results"] if "-" in r["name"])


@pytest.mark.django_db
@pytest.mark.parametrize("path", list(PATHS))
def test_status_filter_splits_the_three_groups(admin_client, path):
    model = PATHS[path]
    model.objects.create(name="A-active")
    model.objects.create(name="B-legacy", is_active=False, is_legacy=True)
    model.objects.create(name="C-inactive", is_active=False)

    def get(status):
        return _names(admin_client.get(f"/api/{path}/", {"status": status}))

    assert get("active") == ["A-active"]
    assert get("legacy") == ["B-legacy"]
    assert get("inactive") == ["C-inactive"]
    assert get("active,legacy") == ["A-active", "B-legacy"]
    # Legacy is never matched by the existing is_active=true pickers.
    assert _names(admin_client.get(f"/api/{path}/", {"is_active": "true"})) == ["A-active"]


@pytest.mark.django_db
@pytest.mark.parametrize("path", list(PATHS))
def test_legacy_forces_inactive_and_reactivation_clears_legacy(admin_client, path):
    obj = PATHS[path].objects.create(name="X")
    resp = admin_client.patch(f"/api/{path}/{obj.id}/", {"is_legacy": True}, format="json")
    assert resp.status_code == 200
    assert resp.data["is_legacy"] is True and resp.data["is_active"] is False

    resp = admin_client.patch(f"/api/{path}/{obj.id}/", {"is_active": True}, format="json")
    assert resp.status_code == 200
    assert resp.data["is_legacy"] is False and resp.data["is_active"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("path,field", [("customers", "customer"), ("suppliers", "supplier")])
def test_account_with_balance_cannot_be_deactivated_but_settled_one_can(
    admin_client, path, field
):
    from datetime import date

    from apps.finance.models import OpeningDebt

    indebted = PATHS[path].objects.create(name="Open balance")
    recorder = User.objects.get(phone="+2220000099")
    OpeningDebt.objects.create(
        **{field: indebted}, amount="1000.00", date=date.today(), recorded_by=recorder
    )

    resp = admin_client.patch(f"/api/{path}/{indebted.id}/", {"is_active": False}, format="json")
    assert resp.status_code == 400

    resp = admin_client.patch(f"/api/{path}/{indebted.id}/", {"is_legacy": True}, format="json")
    assert resp.status_code == 200

    settled = PATHS[path].objects.create(name="Zero")
    resp = admin_client.patch(f"/api/{path}/{settled.id}/", {"is_active": False}, format="json")
    assert resp.status_code == 200

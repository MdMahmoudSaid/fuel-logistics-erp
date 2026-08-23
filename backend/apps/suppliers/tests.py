import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.suppliers.models import Supplier


@pytest.mark.django_db
def test_supplier_str():
    supplier = Supplier.objects.create(name="Total Senegal", country="Senegal")
    assert str(supplier) == "Total Senegal"


@pytest.mark.django_db
def test_supplier_crud_requires_purchasing_permission():
    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)  # no purchasing:create
    ops_user = User.objects.create_user(phone="+2220000001", pin="1234", role=ops_role)
    client = APIClient()
    client.force_authenticate(ops_user)

    denied = client.post("/api/suppliers/", {"name": "Shell Mali", "country": "Mali"})
    assert denied.status_code == 403

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000002", pin="1234", role=admin_role)
    client.force_authenticate(admin_user)

    created = client.post("/api/suppliers/", {"name": "Shell Mali", "country": "Mali"})
    assert created.status_code == 201

    listed = client.get("/api/suppliers/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1

    supplier_id = created.data["id"]
    retrieved = client.get(f"/api/suppliers/{supplier_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["name"] == "Shell Mali"

    updated = client.patch(f"/api/suppliers/{supplier_id}/", {"country": "Senegal"})
    assert updated.status_code == 200
    assert updated.data["country"] == "Senegal"

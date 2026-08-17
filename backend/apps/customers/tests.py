import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.customers.models import Customer


@pytest.mark.django_db
def test_customer_str():
    customer = Customer.objects.create(name="Garage Moderne", address="Bamako")
    assert str(customer) == "Garage Moderne"


@pytest.mark.django_db
def test_customer_crud_requires_sales_create_permission():
    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)  # sales:view only, no create
    ops_user = User.objects.create_user(email="ops@example.com", password="testpass123", role=ops_role)
    client = APIClient()
    client.force_authenticate(ops_user)

    denied = client.post("/api/customers/", {"name": "Garage Moderne"})
    assert denied.status_code == 403

    listed = client.get("/api/customers/")
    assert listed.status_code == 200  # operations has sales:view

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(email="admin@example.com", password="testpass123", role=admin_role)
    client.force_authenticate(admin_user)

    created = client.post("/api/customers/", {"name": "Garage Moderne"})
    assert created.status_code == 201

    customer_id = created.data["id"]
    retrieved = client.get(f"/api/customers/{customer_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["name"] == "Garage Moderne"

    updated = client.patch(f"/api/customers/{customer_id}/", {"address": "Bamako"})
    assert updated.status_code == 200
    assert updated.data["address"] == "Bamako"

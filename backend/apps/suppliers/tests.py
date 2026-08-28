from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.purchasing.models import SupplierOrder
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


def _admin_client(phone):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone=phone, pin="1234", role=admin_role)
    client = APIClient()
    client.force_authenticate(admin_user)
    return client, admin_user


def _supplier_order(reference, supplier, admin_user, *, status):
    return SupplierOrder.objects.create(
        reference=reference,
        supplier=supplier,
        product=Product.objects.get(code="gasoil"),
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("500.0000"),
        status=status,
        created_by=admin_user,
    )


@pytest.mark.django_db
def test_supplier_detail_totals_only_count_confirmed_orders():
    client, admin_user = _admin_client("+222SUPCONF1")
    supplier = Supplier.objects.create(name="Supplier Confirmed Only")
    _supplier_order("SO-SUP-CONF-1", supplier, admin_user, status=SupplierOrder.Status.CONFIRMED)
    _supplier_order("SO-SUP-CANC-1", supplier, admin_user, status=SupplierOrder.Status.CANCELLED)
    _supplier_order("SO-SUP-DRAFT-1", supplier, admin_user, status=SupplierOrder.Status.DRAFT)

    response = client.get(f"/api/suppliers/{supplier.id}/")

    assert response.status_code == 200
    assert response.data["total_purchased"] == "50000000.00"
    assert response.data["outstanding_balance"] == "50000000.00"
    assert response.data["total_reliquat"] == "100000.00"


@pytest.mark.django_db
def test_supplier_ledger_keeps_draft_and_cancelled_history_but_excludes_them_from_totals():
    client, admin_user = _admin_client("+222SUPCONF2")
    supplier = Supplier.objects.create(name="Supplier Ledger Confirmed Only")
    confirmed = _supplier_order("SO-SUP-CONF-2", supplier, admin_user, status=SupplierOrder.Status.CONFIRMED)
    cancelled = _supplier_order("SO-SUP-CANC-2", supplier, admin_user, status=SupplierOrder.Status.CANCELLED)
    draft = _supplier_order("SO-SUP-DRAFT-2", supplier, admin_user, status=SupplierOrder.Status.DRAFT)

    response = client.get(f"/api/suppliers/{supplier.id}/ledger/")

    assert response.status_code == 200
    assert response.data["total_purchased"] == "50000000.00"
    assert response.data["outstanding_balance"] == "50000000.00"
    assert response.data["reliquat_summary"] == [
        {
            "product_id": confirmed.product_id,
            "product_name": confirmed.product.name,
            "total_reliquat": "100000.00",
        }
    ]
    assert {order["id"] for order in response.data["orders"]} == {
        confirmed.id,
        cancelled.id,
        draft.id,
    }

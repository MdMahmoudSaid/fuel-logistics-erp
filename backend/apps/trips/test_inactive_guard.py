"""Inactive / "Ancien" records: never offered for new business, and never
archived while they still have open work or an open balance."""
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import BankAccount, CashAccount, OpeningDebt
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip
from apps.trips.serializers import TripSerializer
from apps.trips.tests import (
    _FakeRequest,
    _make_trip,
    _make_truck,
    _setup_fixtures,
    _trip_payload,
)


@pytest.fixture
def api():
    admin = User.objects.create_user(
        phone="+2229990001", pin="1234", role=Role.objects.get(name=Role.NAME_ADMIN)
    )
    client = APIClient()
    client.force_authenticate(admin)
    return client


def _deactivate(api, path, obj):
    return api.patch(f"/api/{path}/{obj.id}/", {"is_active": False}, format="json")


# ---- deactivation blocked while there is open work / balance --------------


@pytest.mark.django_db
def test_truck_on_an_active_trip_cannot_be_deactivated_until_the_trip_ends(api):
    fx = _setup_fixtures("G1")
    truck = _make_truck("TRK-G1")
    trip = _make_trip(fx, truck, "TRIP-G1", status=Trip.Status.IN_TRANSIT)

    resp = _deactivate(api, "trucks", truck)
    assert resp.status_code == 400 and "trajet en cours" in str(resp.data)

    trip.status = Trip.Status.COMPLETED
    trip.save(update_fields=["status"])
    assert _deactivate(api, "trucks", truck).status_code == 200


@pytest.mark.django_db
def test_transporter_supplier_customer_on_an_active_trip_cannot_be_deactivated(api):
    fx = _setup_fixtures("G2")
    customer = Customer.objects.create(name="Client G2")
    truck = _make_truck("TRK-G2")
    trip = _make_trip(fx, truck, "TRIP-G2", status=Trip.Status.IN_TRANSIT)
    trip.client = customer
    trip.save(update_fields=["client"])

    for path, obj in [
        ("transporters", fx["transporter"]),
        ("suppliers", fx["supplier"]),
        ("customers", customer),
    ]:
        resp = _deactivate(api, path, obj)
        assert resp.status_code == 400, path
        assert "trajets en cours" in str(resp.data), path
        # "Ancien" stays available for an account that is still being worked.
        assert (
            api.patch(f"/api/{path}/{obj.id}/", {"is_legacy": True}, format="json").status_code
            == 200
        ), path


@pytest.mark.django_db
def test_customer_with_an_open_order_cannot_be_deactivated(api):
    from apps.sales.models import CustomerOrder

    customer = Customer.objects.create(name="Client order")
    CustomerOrder.objects.create(
        customer=customer,
        product=Product.objects.get(code="gasoil"),
        quantity_ordered=Decimal("1000.00"),
        status=CustomerOrder.Status.CONFIRMED,
    )
    resp = _deactivate(api, "customers", customer)
    assert resp.status_code == 400 and "commandes ouvertes" in str(resp.data)


@pytest.mark.django_db
def test_supplier_with_open_balance_cannot_be_deactivated(api):
    supplier = Supplier.objects.create(name="Owed supplier")
    admin = User.objects.get(phone="+2229990001")
    OpeningDebt.objects.create(
        supplier=supplier, amount="500.00", date=date.today(), recorded_by=admin
    )
    assert _deactivate(api, "suppliers", supplier).status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("path,model", [("bank-accounts", BankAccount), ("cash-accounts", CashAccount)])
def test_treasury_account_with_money_cannot_be_deactivated(api, path, model):
    funded = model.objects.create(name="Funded", opening_balance=Decimal("100.00"))
    empty = model.objects.create(name="Empty", opening_balance=Decimal("0.00"))
    assert _deactivate(api, path, funded).status_code == 400
    assert _deactivate(api, path, empty).status_code == 200


# ---- inactive records are never offered ------------------------------------


@pytest.mark.django_db
def test_inactive_truck_and_transporter_are_not_offered_for_a_trip(api):
    active = _make_truck("TRK-ACT")
    inactive = _make_truck("TRK-OFF")
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])
    off_transporter = Transporter.objects.create(name="Off Trans", is_active=False)

    def ids(url, **params):
        return {row["id"] for row in api.get(url, params).data["results"]}

    for params in ({"is_active": "true"}, {"available": "true"}):
        assert active.id in ids("/api/trucks/", **params)
        assert inactive.id not in ids("/api/trucks/", **params)
    assert off_transporter.id not in ids("/api/transporters/", available="true")
    assert off_transporter.id not in ids("/api/transporters/", is_active="true")


@pytest.mark.django_db
def test_trip_cannot_be_created_with_an_inactive_truck_or_legacy_transporter():
    fx = _setup_fixtures("G3")
    truck = _make_truck("TRK-G3", owner_transporter=fx["transporter"])
    truck.is_active = False
    truck.save(update_fields=["is_active"])
    ctx = {"request": _FakeRequest(fx["admin_user"])}

    serializer = TripSerializer(data=_trip_payload(fx, truck, "TRIP-G3-1"), context=ctx)
    assert not serializer.is_valid() and "truck" in serializer.errors

    truck.is_active = True
    truck.save(update_fields=["is_active"])
    fx["transporter"].is_active = False
    fx["transporter"].is_legacy = True
    fx["transporter"].save(update_fields=["is_active", "is_legacy"])
    serializer = TripSerializer(data=_trip_payload(fx, truck, "TRIP-G3-2"), context=ctx)
    assert not serializer.is_valid() and "transporter" in serializer.errors


@pytest.mark.django_db
def test_supplier_order_and_customer_order_refuse_inactive_parties(api):
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Off supplier", is_active=False, is_legacy=True)
    resp = api.post(
        "/api/supplier-orders/",
        {
            "reference": "SO-OFF",
            "supplier": supplier.id,
            "product": product.id,
            "purchase_date": "2026-08-18",
            "quantity_litres": "50000.00",
            "unit_price": "600.0000",
        },
        format="json",
    )
    assert resp.status_code == 400 and "supplier" in resp.data

    customer = Customer.objects.create(name="Off client", is_active=False)
    resp = api.post(
        "/api/customer-orders/",
        {
            "customer": customer.id,
            "product": product.id,
            "quantity_ordered": "1000.00",
        },
        format="json",
    )
    assert resp.status_code == 400 and "customer" in resp.data


@pytest.mark.django_db
def test_transfer_refuses_an_inactive_account(api):
    off = CashAccount.objects.create(name="Off cash", is_active=False)
    on = CashAccount.objects.create(name="On cash", opening_balance=Decimal("1000.00"))
    resp = api.post(
        "/api/treasury-transactions/transfer/",
        {
            "source_account_type": "cash",
            "source_account_id": on.id,
            "dest_account_type": "cash",
            "dest_account_id": off.id,
            "amount": "10.00",
            "date": "2026-11-05",
        },
        format="json",
    )
    assert resp.status_code == 400

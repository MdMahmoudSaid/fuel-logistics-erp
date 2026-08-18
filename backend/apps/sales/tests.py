from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import CustomerOrder
from apps.sales.services import CustomerOrderService
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _setup_fixtures(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        email=f"admin-sales-{suffix}@example.com",
        password="testpass123",
        role=admin_role,
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    transporter = Transporter.objects.create(name="Trans SA")
    customer = Customer.objects.create(name="Client Y")

    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-SALES-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-SALES-{suffix}",
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
        "customer": customer,
        "supplier_order": supplier_order,
        "cession": cession,
    }


def _make_trip(fx, order, reference, quantity, status):
    truck = Truck.objects.create(
        internal_id=f"TRK-{reference}",
        tractor_registration=f"{reference}-TRACTOR",
        tanker_registration=f"{reference}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    return Trip.objects.create(
        reference=reference,
        truck=truck,
        transporter=fx["transporter"],
        supplier=fx["supplier"],
        supplier_order=fx["supplier_order"],
        cession_letter=fx["cession"],
        product=fx["product"],
        quantity_loaded=quantity,
        customer_order=order,
        loading_date="2026-08-18",
        bl_reference=f"BL-{reference}",
        status=status,
        created_by=fx["admin_user"],
    )


@pytest.mark.django_db
def test_customer_order_quantity_must_be_positive():
    fx = _setup_fixtures("QTY")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CustomerOrder.objects.create(
                customer=fx["customer"],
                product=fx["product"],
                quantity_ordered=Decimal("0.00"),
            )


@pytest.mark.django_db
def test_assigned_quantity_excludes_cancelled_trips():
    fx = _setup_fixtures("EXCL")
    order = CustomerOrder.objects.create(
        customer=fx["customer"],
        product=fx["product"],
        quantity_ordered=Decimal("100000.00"),
        status=CustomerOrder.Status.CONFIRMED,
    )

    _make_trip(fx, order, "TRIP-EXCL-KEEP", Decimal("40000.00"), Trip.Status.ASSIGNED)
    _make_trip(
        fx, order, "TRIP-EXCL-CANCELLED", Decimal("40000.00"), Trip.Status.CANCELLED
    )

    assert CustomerOrderService.get_assigned_quantity(order) == Decimal("40000.00")


@pytest.mark.django_db
def test_recompute_status_is_noop_for_manual_lifecycle_states():
    fx = _setup_fixtures("MANUAL")

    for manual_status in (
        CustomerOrder.Status.DRAFT,
        CustomerOrder.Status.CLOSED,
        CustomerOrder.Status.CANCELLED,
    ):
        order = CustomerOrder.objects.create(
            customer=fx["customer"],
            product=fx["product"],
            quantity_ordered=Decimal("100000.00"),
            status=manual_status,
        )
        _make_trip(
            fx,
            order,
            f"TRIP-MANUAL-{manual_status}",
            Decimal("100000.00"),
            Trip.Status.COMPLETED,
        )

        CustomerOrderService.recompute_status(order)
        order.refresh_from_db()
        assert order.status == manual_status


@pytest.mark.django_db
def test_remaining_quantity_tracks_delivered_not_assigned():
    fx = _setup_fixtures("REMAIN")
    order = CustomerOrder.objects.create(
        customer=fx["customer"],
        product=fx["product"],
        quantity_ordered=Decimal("100000.00"),
        status=CustomerOrder.Status.CONFIRMED,
    )

    # Assigned but not yet delivered: remaining should still be the full amount.
    _make_trip(fx, order, "TRIP-REMAIN-001", Decimal("100000.00"), Trip.Status.ASSIGNED)
    assert CustomerOrderService.get_remaining_quantity(order) == Decimal("100000.00")

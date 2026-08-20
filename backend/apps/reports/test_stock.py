# TheoreticalStockService tests (docs/PHASE_6_PLAN.md Etape 3/6;
# ERP_Implementation_Experience_Guide.md Section 9.4/9.5; plan Section 1.B).

from decimal import Decimal

import pytest

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.reports.services.stock import TheoreticalStockService
from apps.sales.models import Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        email=f"admin-stock-{suffix}@example.com", password="testpass123", role=admin_role
    )


def _make_supplier_order(suffix, admin_user, quantity=Decimal("100000.00"), status=SupplierOrder.Status.CONFIRMED):
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    product = Product.objects.get(code="gasoil")
    return SupplierOrder.objects.create(
        reference=f"SO-STOCK-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=quantity,
        unit_price=Decimal("600.0000"),
        status=status,
        created_by=admin_user,
    )


def _make_trip(suffix, admin_user, supplier_order, quantity_loaded, status=Trip.Status.IN_TRANSIT):
    cession = CessionLetter.objects.create(
        reference=f"CL-STOCK-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=quantity_loaded,
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    truck = Truck.objects.create(
        internal_id=f"TRK-STOCK-{suffix}",
        tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    return Trip.objects.create(
        reference=f"TRIP-STOCK-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier_order.supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=supplier_order.product,
        quantity_loaded=quantity_loaded,
        loading_date="2026-08-18",
        bl_reference=f"BL-STOCK-{suffix}",
        status=status,
        created_by=admin_user,
    )


@pytest.mark.django_db
def test_get_supplier_reliquats_sums_active_orders_only():
    admin_user = _make_admin("RELIQUAT")

    confirmed_a = _make_supplier_order("A", admin_user, quantity=Decimal("100000.00"))
    confirmed_b = _make_supplier_order("B", admin_user, quantity=Decimal("50000.00"))
    _make_supplier_order("DRAFT", admin_user, quantity=Decimal("999999.00"), status=SupplierOrder.Status.DRAFT)
    _make_supplier_order(
        "CANCELLED", admin_user, quantity=Decimal("999999.00"), status=SupplierOrder.Status.CANCELLED
    )

    # Partially consume confirmed_a's reliquat with a cession, leave confirmed_b untouched.
    CessionLetter.objects.create(
        reference="CL-STOCK-PARTIAL",
        supplier_order=confirmed_a,
        authorized_quantity=Decimal("30000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )

    # confirmed_a reliquat: 100000 - 30000 = 70000; confirmed_b: 50000 (untouched).
    assert TheoreticalStockService.get_supplier_reliquats() == Decimal("120000.00")


@pytest.mark.django_db
def test_get_loaded_unsold_quantity_excludes_sold_and_cancelled_trips():
    admin_user = _make_admin("UNSOLD")
    order = _make_supplier_order("UNSOLD", admin_user, quantity=Decimal("200000.00"))

    unsold_trip = _make_trip("UNSOLD", admin_user, order, Decimal("45000.00"))

    sold_trip = _make_trip("SOLD", admin_user, order, Decimal("45000.00"), status=Trip.Status.DELIVERED)
    customer = Customer.objects.create(name="Client UNSOLD")
    Sale.objects.create(
        trip=sold_trip,
        customer=customer,
        product=sold_trip.product,
        delivered_quantity=Decimal("44850.00"),
        unit_selling_price=Decimal("650.0000"),
    )

    _make_trip("CANCELLED", admin_user, order, Decimal("45000.00"), status=Trip.Status.CANCELLED)

    assert TheoreticalStockService.get_loaded_unsold_quantity() == unsold_trip.quantity_loaded


@pytest.mark.django_db
def test_get_total_theoretical_stock_sums_both_components():
    admin_user = _make_admin("TOTAL")
    order = _make_supplier_order("TOTAL", admin_user, quantity=Decimal("100000.00"))
    _make_trip("TOTAL", admin_user, order, Decimal("45000.00"))

    # reliquat: 100000 - 45000 (cession consumed by the trip's own cession) = 55000
    # loaded unsold: 45000
    assert TheoreticalStockService.get_supplier_reliquats() == Decimal("55000.00")
    assert TheoreticalStockService.get_loaded_unsold_quantity() == Decimal("45000.00")
    assert TheoreticalStockService.get_total_theoretical_stock() == Decimal("100000.00")


@pytest.mark.django_db
def test_theoretical_stock_reacts_to_purchase_loading_and_sale_lifecycle():
    """Plan Section 4.1 manual recette scenario, exercised as an automated
    test: purchase increases stock, loading moves it between the two
    components without changing the total, and a Sale removes it."""
    admin_user = _make_admin("LIFECYCLE")
    stock_before_purchase = TheoreticalStockService.get_total_theoretical_stock()

    order = _make_supplier_order("LIFECYCLE", admin_user, quantity=Decimal("100000.00"))
    assert (
        TheoreticalStockService.get_total_theoretical_stock()
        == stock_before_purchase + Decimal("100000.00")
    )

    trip = _make_trip("LIFECYCLE", admin_user, order, Decimal("45000.00"))
    assert (
        TheoreticalStockService.get_total_theoretical_stock()
        == stock_before_purchase + Decimal("100000.00")
    )

    customer = Customer.objects.create(name="Client LIFECYCLE")
    Sale.objects.create(
        trip=trip,
        customer=customer,
        product=trip.product,
        delivered_quantity=Decimal("45000.00"),
        unit_selling_price=Decimal("650.0000"),
    )
    assert (
        TheoreticalStockService.get_total_theoretical_stock()
        == stock_before_purchase + Decimal("55000.00")
    )

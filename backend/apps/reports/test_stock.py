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
        phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role
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

    # Bug fix (client business rule, confirmed 2026-09-06): a cession letter
    # alone no longer consumes reliquat - only an actual loading (Trip)
    # does. Partially consume confirmed_a's reliquat by loading 30,000 L
    # against it, leave confirmed_b untouched.
    _make_trip("PARTIAL", admin_user, confirmed_a, Decimal("30000.00"))

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
def test_get_supplier_reliquat_value_prices_each_order_at_its_own_unit_price():
    """Client decision (2026-09-06): two purchases at two different prices
    must each keep their own price for what's left of them - never a
    single blended average across a supplier's orders."""
    admin_user = _make_admin("RELIQVAL")
    cheap = _make_supplier_order("RELIQVAL-CHEAP", admin_user, quantity=Decimal("100000.00"))
    cheap.unit_price = Decimal("500.0000")
    cheap.save(update_fields=["unit_price"])
    pricey = _make_supplier_order("RELIQVAL-PRICEY", admin_user, quantity=Decimal("50000.00"))
    pricey.unit_price = Decimal("700.0000")
    pricey.save(update_fields=["unit_price"])
    # Partially consume the cheap order only - 60,000 L left at 500, all
    # 50,000 L of the pricey one still untouched at 700.
    _make_trip("RELIQVAL", admin_user, cheap, Decimal("40000.00"))

    assert TheoreticalStockService.get_supplier_reliquats() == Decimal("110000.00")
    assert TheoreticalStockService.get_supplier_reliquat_value() == (
        Decimal("60000.00") * Decimal("500.0000") + Decimal("50000.00") * Decimal("700.0000")
    )


@pytest.mark.django_db
def test_in_transit_and_company_stock_split_by_arrival_status():
    """Client's own 3-bucket split (2026-09-06): a loaded trip is "en
    cours" (valued at pure purchase price) until it physically arrives -
    at that point, if headed to company stock, it moves to the stock
    bucket (valued at full cost basis instead)."""
    admin_user = _make_admin("SPLIT")
    order = _make_supplier_order("SPLIT", admin_user, quantity=Decimal("200000.00"))
    order.unit_price = Decimal("600.0000")
    order.save(update_fields=["unit_price"])

    en_route = _make_trip("SPLIT-ENROUTE", admin_user, order, Decimal("45000.00"), status=Trip.Status.ROAD_TRANSIT)
    arrived = _make_trip("SPLIT-ARRIVED", admin_user, order, Decimal("30000.00"), status=Trip.Status.STOCKED)
    _make_trip("SPLIT-CANCELLED", admin_user, order, Decimal("40000.00"), status=Trip.Status.CANCELLED)

    assert TheoreticalStockService.get_in_transit_quantity() == en_route.quantity_loaded
    assert TheoreticalStockService.get_in_transit_value() == Decimal("45000.00") * Decimal("600.0000")
    # No transport/expense allocations on this trip - full cost basis
    # collapses to the raw fuel purchase cost.
    assert TheoreticalStockService.get_company_stock_value() == Decimal("30000.00") * Decimal(
        "600.0000"
    )
    assert arrived.quantity_loaded == Decimal("30000.00")


@pytest.mark.django_db
def test_delivered_trip_counts_in_none_of_the_three_pipeline_buckets():
    """Client's explicit instruction (2026-09-06): the instant a trip is
    delivered to a client it must stop counting anywhere in the pipeline -
    it becomes a customer receivable instead, never company stock or
    en-cours."""
    admin_user = _make_admin("NOBUCKET")
    order = _make_supplier_order("NOBUCKET", admin_user, quantity=Decimal("100000.00"))
    trip = _make_trip("NOBUCKET", admin_user, order, Decimal("45000.00"), status=Trip.Status.DELIVERED)
    customer = Customer.objects.create(name="Client NOBUCKET")
    Sale.objects.create(
        trip=trip, customer=customer, product=trip.product,
        delivered_quantity=Decimal("45000.00"), unit_selling_price=Decimal("650.0000"),
    )

    assert TheoreticalStockService.get_in_transit_quantity() == Decimal("0.00")
    assert TheoreticalStockService.get_in_transit_value() == Decimal("0.00")
    assert TheoreticalStockService.get_company_stock_value() == Decimal("0.00")
    # Only the reliquat still reflects it (55,000 L left of the 100,000 L
    # purchase) - that part of the story doesn't change once delivered.
    assert TheoreticalStockService.get_supplier_reliquats() == Decimal("55000.00")


@pytest.mark.django_db
def test_delivered_or_completed_trip_without_a_sale_is_out_of_the_pipeline_too():
    """Regression (2026-09-07 recette): a trip whose status was forced to
    DELIVERED/COMPLETED through the raw status bar - skipping the delivery
    control that would have created the Sale - has `sale__isnull=True` yet
    is emphatically NOT still "en cours". "Past delivery" is decided by the
    trip status, never by the mere presence of a Sale row, so a forced,
    Sale-less completion must drop out of every pipeline bucket exactly like
    a normal delivered trip does."""
    admin_user = _make_admin("FORCED")
    order = _make_supplier_order("FORCED", admin_user, quantity=Decimal("100000.00"))
    _make_trip("FORCED-DELIV", admin_user, order, Decimal("45000.00"), status=Trip.Status.DELIVERED)
    _make_trip("FORCED-DONE", admin_user, order, Decimal("30000.00"), status=Trip.Status.COMPLETED)

    assert TheoreticalStockService.get_in_transit_quantity() == Decimal("0.00")
    assert TheoreticalStockService.get_in_transit_value() == Decimal("0.00")
    assert TheoreticalStockService.get_loaded_unsold_quantity() == Decimal("0.00")


@pytest.mark.django_db
def test_get_company_stock_value_includes_transport_and_expense_costs():
    """Unlike en-cours, the stock card is valued at full cost basis
    (TripCostService.calculate_trip_cost_basis) - purchase price plus
    whatever transport/expenses have actually been allocated to the trip
    by the time it reaches the depot."""
    from apps.finance.models import TransportPayment
    from apps.transport.models import Transporter

    admin_user = _make_admin("STOCKCOST")
    order = _make_supplier_order("STOCKCOST", admin_user, quantity=Decimal("100000.00"))
    order.unit_price = Decimal("600.0000")
    order.save(update_fields=["unit_price"])
    trip = _make_trip("STOCKCOST", admin_user, order, Decimal("45000.00"), status=Trip.Status.STOCKED)
    TransportPayment.objects.create(
        trip=trip,
        transporter=trip.transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("2000000.00"),
    )

    # fuel: 45000 x 600 = 27,000,000 + transport 2,000,000 = 29,000,000
    assert TheoreticalStockService.get_company_stock_value() == Decimal("29000000.00")


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

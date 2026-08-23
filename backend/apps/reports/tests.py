# TripProfitService tests (docs/PHASE_6_PLAN.md Etape 2/6;
# ERP_Implementation_Experience_Guide.md Section 9.1/9.2/9.3).

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import Expense, ExpenseAllocation, TransportPayment
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.reports.services.profit import TripProfitService
from apps.sales.models import CustomerOrder, Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _make_trip(suffix, customer_order=None, status=Trip.Status.DELIVERED):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone=(f"+222{suffix}")[:20],
        pin="1234",
        role=admin_role,
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    transporter = Transporter.objects.create(name="Trans SA")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-PROFIT-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-PROFIT-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("500000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-PROFIT-{suffix}",
        tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-PROFIT-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=product,
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference=f"BL-PROFIT-{suffix}",
        status=status,
        customer_order=customer_order,
        created_by=admin_user,
    )
    return trip, transporter, admin_user


def _make_delivered_trip_with_sale(suffix):
    trip, transporter, admin_user = _make_trip(suffix)
    customer = Customer.objects.create(name=f"Client {suffix}")
    Sale.objects.create(
        trip=trip,
        customer=customer,
        product=trip.product,
        delivered_quantity=Decimal("44850.00"),
        unit_selling_price=Decimal("650.0000"),
    )
    TransportPayment.objects.create(
        trip=trip,
        transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.NEGOTIATED,
        base_amount=Decimal("1500000.00"),
    )
    return trip, admin_user


@pytest.mark.django_db
def test_current_margin_requires_a_sale():
    trip, _transporter, _admin_user = _make_trip("NOSALE")

    with pytest.raises(ValueError):
        TripProfitService.calculate_current_margin(trip)


@pytest.mark.django_db
def test_current_margin_is_revenue_minus_fuel_cost_and_transport_cost():
    trip, _admin_user = _make_delivered_trip_with_sale("BASE")

    # revenue: 44850.00 * 650.0000 = 29,152,500.00
    # fuel cost: 45000.00 * 600.0000 = 27,000,000.00
    # transport: 1,500,000.00
    # margin: 29,152,500.00 - 27,000,000.00 - 1,500,000.00 = 652,500.00
    assert TripProfitService.calculate_current_margin(trip) == Decimal("652500.00")


@pytest.mark.django_db
def test_current_margin_recalculates_automatically_when_expense_allocated():
    """§33: a belated expense allocated to an already-computed trip must
    reduce the margin on the very next read, with no manual recompute step."""
    trip, admin_user = _make_delivered_trip_with_sale("RECALC")

    margin_before = TripProfitService.calculate_current_margin(trip)

    expense = Expense.objects.create(
        category=Expense.Category.ROAD,
        amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("50000.00"),
    )

    margin_after = TripProfitService.calculate_current_margin(trip)

    assert margin_after == margin_before - Decimal("50000.00")
    assert margin_after == Decimal("602500.00")


@pytest.mark.django_db
def test_current_margin_ignores_cancelled_expense_allocations():
    trip, admin_user = _make_delivered_trip_with_sale("CANCELLED")
    margin_before = TripProfitService.calculate_current_margin(trip)

    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("75000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
        status=Expense.Status.CANCELLED,
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("75000.00"),
    )

    assert TripProfitService.calculate_current_margin(trip) == margin_before


@pytest.mark.django_db
def test_get_cost_breakdown_matches_current_margin_and_splits_expenses_by_category():
    trip, admin_user = _make_delivered_trip_with_sale("BREAKDOWN")
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("50000.00"),
    )

    breakdown = TripProfitService.get_cost_breakdown(trip)

    assert breakdown["revenue"] == Decimal("29152500.00")
    assert breakdown["fuel_purchase_cost"] == Decimal("27000000.00")
    assert breakdown["transport_cost"] == Decimal("1500000.00")
    assert breakdown["expenses_by_category"] == {Expense.Category.CUSTOMS: Decimal("50000.00")}
    assert breakdown["total_expenses"] == Decimal("50000.00")
    assert breakdown["margin"] == TripProfitService.calculate_current_margin(trip)


@pytest.mark.django_db
def test_estimated_margin_uses_customer_order_expected_price_before_sale():
    customer = Customer.objects.create(name="Client EST")
    product = Product.objects.get(code="gasoil")
    order = CustomerOrder.objects.create(
        customer=customer,
        product=product,
        quantity_ordered=Decimal("45000.00"),
        expected_price=Decimal("640.0000"),
    )
    trip, _transporter, _admin_user = _make_trip(
        "EST", customer_order=order, status=Trip.Status.ASSIGNED
    )

    # revenue: 45000.00 * 640.0000 = 28,800,000.00
    # fuel cost: 45000.00 * 600.0000 = 27,000,000.00
    # margin: 1,800,000.00 (no transport/expenses booked yet)
    assert TripProfitService.calculate_estimated_margin(trip) == Decimal("1800000.00")


@pytest.mark.django_db
def test_estimated_margin_requires_a_known_expected_price():
    trip, _transporter, _admin_user = _make_trip("NOEST", status=Trip.Status.ASSIGNED)

    with pytest.raises(ValueError):
        TripProfitService.calculate_estimated_margin(trip)


@pytest.mark.django_db
def test_final_margin_requires_a_completed_trip():
    trip, _admin_user = _make_delivered_trip_with_sale("NOTFINAL")
    assert trip.status == Trip.Status.DELIVERED

    with pytest.raises(ValueError):
        TripProfitService.calculate_final_margin(trip)


@pytest.mark.django_db
def test_final_margin_equals_current_margin_once_trip_is_completed():
    trip, _admin_user = _make_delivered_trip_with_sale("FINAL")
    trip.status = Trip.Status.COMPLETED
    trip.save(update_fields=["status"])

    assert TripProfitService.calculate_final_margin(trip) == Decimal("652500.00")

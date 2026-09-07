# TripProfitService tests (docs/PHASE_6_PLAN.md Etape 2/6;
# ERP_Implementation_Experience_Guide.md Section 9.1/9.2/9.3).

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import (
    Expense,
    ExpenseAllocation,
    TransportDeduction,
    TransportPayment,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.reports.services.profit import TripProfitService
from apps.sales.models import CustomerOrder, Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import DeliveryControl, Trip
from apps.trips.services import DeliveryService


def _make_trip(suffix, customer_order=None, status=Trip.Status.DELIVERED):
    admin_role, _ = Role.objects.get_or_create(
        name=Role.NAME_ADMIN,
        defaults={"permissions": {module: Role.ACTIONS for module in Role.MODULES}},
    )
    admin_user = User.objects.create_user(
        phone=(f"+222{suffix}")[:20],
        pin="1234",
        role=admin_role,
    )
    product, _ = Product.objects.get_or_create(
        code="gasoil",
        defaults={"name": "Gasoil"},
    )
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


def _make_admin(suffix):
    admin_role, _ = Role.objects.get_or_create(
        name=Role.NAME_ADMIN,
        defaults={"permissions": {module: Role.ACTIONS for module in Role.MODULES}},
    )
    return User.objects.create_user(
        phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role
    )


def _deliver_via_services(suffix, admin_user, *, loaded, received, unit_selling_price):
    """Full delivery cycle through the real services (trip pipeline ->
    record_delivery -> record_client_verification), so that Task 3's
    propagation of the corrected received quantity to Sale.delivered_quantity
    + Invoice.total_amount actually runs - unlike _make_delivered_trip_with_sale,
    which builds a Sale with no Invoice and so never triggers it.

    Wraps apps.reports.test_queries._deliver_trip_with_transporter_loss, which
    already does exactly this; that helper fixes quantity_loaded=45000 and
    unit_selling_price=900, so this wrapper only supports those values.
    """
    from apps.reports.test_queries import _deliver_trip_with_transporter_loss

    if loaded != Decimal("45000.00") or unit_selling_price != Decimal("900.0000"):
        raise NotImplementedError(
            "_deliver_via_services only supports loaded=45000 / unit_selling_price=900 "
            "(the values _deliver_trip_with_transporter_loss hardcodes)."
        )
    fx = _deliver_trip_with_transporter_loss(
        suffix, admin_user, received_qty=received, base_amount=Decimal("5000000.00")
    )
    trip = fx["trip"]
    trip.refresh_from_db()
    return trip


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
def test_get_cost_breakdown_returns_unit_cost_and_unit_profit_with_fuel_transport_and_expense():
    """Client modifications Task 3: a trip with supplier cost (fuel), a
    transport fee and a customs expense must return a correct unit_cost/
    unit_profit, sourced from TripCostService.calculate_trip_cost_basis
    rather than a duplicated formula (guide Section 5.5)."""
    trip, admin_user = _make_delivered_trip_with_sale("UNITCOST")
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

    # fuel 45,000 x 600 = 27,000,000 + transport 1,500,000 + customs 50,000
    # = 28,550,000 total cost, over 45,000 L loaded.
    expected_unit_cost = Decimal("28550000.000000") / Decimal("45000.00")
    assert breakdown["unit_cost"] == expected_unit_cost
    assert breakdown["unit_profit"] == Decimal("650.0000") - expected_unit_cost


@pytest.mark.django_db
def test_current_margin_includes_transporter_loss_indemnity():
    """A missing quantity charged back to the transporter is company income:
    customer invoice + transporter indemnity - real loaded-trip cost."""
    trip, transporter, _admin_user = _make_trip("LOSSINDEMNITY")
    trip.supplier_order.unit_price = Decimal("500.0000")
    trip.supplier_order.save(update_fields=["unit_price"])
    customer = Customer.objects.create(name="Client LOSSINDEMNITY")
    Sale.objects.create(
        trip=trip,
        customer=customer,
        product=trip.product,
        delivered_quantity=Decimal("44900.00"),
        unit_selling_price=Decimal("900.0000"),
    )
    TransportPayment.objects.create(
        trip=trip,
        transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.PER_LITRE,
        unit_price_per_litre=Decimal("65.0000"),
        base_amount=Decimal("2925000.00"),
    )
    customs = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("10125000.00"),
        calculation_method=Expense.CalculationMethod.PER_LITRE,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=customs,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("10125000.00"),
    )
    transit = Expense.objects.create(
        category=Expense.Category.TRANSIT,
        amount=Decimal("450000.00"),
        calculation_method=Expense.CalculationMethod.PER_LITRE,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=transit,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("450000.00"),
    )
    TransportDeduction.objects.create(
        trip=trip,
        transporter=transporter,
        chargeable_quantity=Decimal("100.00"),
        unit_price=Decimal("900.0000"),
    )

    breakdown = TripProfitService.get_cost_breakdown(trip)

    assert breakdown["quantity_loaded"] == Decimal("45000.00")
    assert breakdown["quantity_invoiced"] == Decimal("44900.00")
    assert breakdown["transporter_loss_quantity"] == Decimal("100.00")
    assert breakdown["transporter_loss_indemnity"] == Decimal("90000.00")
    assert breakdown["real_total_cost"] == Decimal("36000000.000000")
    assert breakdown["revenue"] == Decimal("40410000.000000")
    assert breakdown["margin"] == Decimal("4500000.00")
    assert TripProfitService.calculate_current_margin(trip) == Decimal("4500000.00")


@pytest.mark.django_db
def test_margin_reflects_absorbed_loss_via_reduced_revenue_not_a_separate_term():
    """Spec 2026-09-07: once the invoice bills the received quantity, the
    tolerance-absorbed loss shows up as a lower revenue - subtracting
    company_absorbed_loss_amount again would double-count it. The amount is
    still exposed for display, just not a formula term."""
    admin_user = _make_admin("ABSORBED2")
    trip = _deliver_via_services(
        "ABSORBED2", admin_user,
        loaded=Decimal("45000.00"), received=Decimal("44920.00"),  # 80 L, all within tolerance
        unit_selling_price=Decimal("900.0000"),
    )
    breakdown = TripProfitService.get_cost_breakdown(trip)

    # A hypothetical no-loss version of the same trip:
    no_loss_margin = (
        Decimal("45000.00") * Decimal("900.0000")
        + Decimal("0.00")  # no transporter indemnity
        - breakdown["real_total_cost"]
    )
    assert breakdown["margin"] == (no_loss_margin - Decimal("80.00") * Decimal("900.0000")).quantize(Decimal("0.01"))
    # still exposed, for the greyed "information" line on the trip screen:
    assert breakdown["company_absorbed_loss_quantity"] == Decimal("80.00")
    assert breakdown["company_absorbed_loss_amount"] == Decimal("72000.00")


@pytest.mark.django_db
def test_margin_breakdown_has_no_company_absorbed_loss_when_no_loss():
    """UI recette bug (2026-09-04): a trip delivered at full quantity (no
    client verification, or a verification confirming zero loss) must
    expose company_absorbed_loss_amount/_quantity as exactly zero, not
    missing - the frontend's "line shown only when > 0" rule depends on
    the field always being present and comparable."""
    trip, _admin_user = _make_delivered_trip_with_sale("NOLOSS")
    breakdown = TripProfitService.get_cost_breakdown(trip)
    assert breakdown["company_absorbed_loss_quantity"] == Decimal("0.00")
    assert breakdown["company_absorbed_loss_amount"] == Decimal("0.00")


@pytest.mark.django_db
def test_margin_breakdown_above_threshold_splits_company_and_transporter_parts():
    """UI recette bug (2026-09-04): a loss above the 100 L tolerance must
    show ONLY the tolerated portion as company_absorbed_loss_* (capped at
    the threshold), with the remainder staying entirely on the transporter
    side (transporter_loss_quantity/transporter_loss_indemnity) - the two
    must never overlap or double-count the same litres."""
    trip, admin_user = _make_delivered_trip_with_sale("ABOVE-THRESHOLD")
    DeliveryControl.objects.create(
        trip=trip,
        loaded_quantity=trip.quantity_loaded,
        received_quantity=trip.quantity_loaded,
        tolerance_quantity=Decimal("100.00"),
        control_date="2026-08-18",
        controller=admin_user,
        method=DeliveryControl.Method.MANUAL_GAUGE,
    )

    DeliveryService.record_client_verification(
        trip_id=trip.id,
        received_qty=Decimal("44850.00"),  # 150 L loss: 100 L tolerated, 50 L chargeable
        verified_at=date.today(),
        actor=admin_user,
    )

    trip = Trip.objects.get(pk=trip.id)
    breakdown = TripProfitService.get_cost_breakdown(trip)
    # Sale.unit_selling_price for this trip is 650.0000.
    assert breakdown["company_absorbed_loss_quantity"] == Decimal("100.00")
    assert breakdown["company_absorbed_loss_amount"] == (
        Decimal("100.00") * Decimal("650.0000")
    ).quantize(Decimal("0.01"))
    assert breakdown["transporter_loss_quantity"] == Decimal("50.00")
    assert breakdown["transporter_loss_indemnity"] == (
        Decimal("50.00") * Decimal("650.0000")
    ).quantize(Decimal("0.01"))


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

"""Closing a profit period never blocks later operations.

Client decision (2026-10-05): a closure only distributes the current profit
and resets the period counters. Everything done afterwards - progressing or
correcting a trip, the client quantity control, a late fee, paying or
amending a debt - must keep working exactly as before periods existed, even
when the trip or debt dates from an already-closed period. The difference
simply flows into the open period (and the next distribution).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.accounts.models import Role, User
from apps.core.models import LossToleranceConfig
from apps.customers.models import Customer
from apps.finance.models import (
    Expense,
    ExpenseAllocation,
    Shareholder,
    TransportDeduction,
    TransportPayment,
)
from apps.finance.services import ShareholderProfitPeriodService
from apps.finance.testing_helpers import seed_net_profit
from apps.purchasing.models import SupplierOrder
from apps.sales.models import Invoice, Sale
from apps.trips.models import DeliveryControl, Trip
from apps.trips.services import DeliveryService
from apps.trips.tests import (
    _deliverable_trip,
    _fixtures_with_customer,
    _make_truck,
    _setup_fixtures,
)

# _make_trip (apps.trips.tests) loads every trip on 2026-08-18.
CLOSED_START = "2026-08-01"
CLOSED_END = "2026-08-31"


def _actor(suffix):
    role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=f"+22272{suffix}"[:20], pin="1234", role=role)


def _close_period(user, start=CLOSED_START, end=CLOSED_END):
    Shareholder.objects.create(name=f"Associe {start}", participation_percent=Decimal("100.00"))
    seed_net_profit(Decimal("0.00"))
    period = ShareholderProfitPeriodService.open_period(start, user)
    return ShareholderProfitPeriodService.close_period(period.id, end, user)


def _make_trip_on(fx, truck, reference, loading_date, quantity=Decimal("45000.00")):
    return Trip.objects.create(
        reference=reference,
        truck=truck,
        transporter=fx["transporter"],
        supplier=fx["supplier"],
        supplier_order=fx["supplier_order"],
        cession_letter=fx["cession"],
        product=fx["product"],
        quantity_loaded=quantity,
        loading_date=loading_date,
        bl_reference=f"BL-{reference}",
        created_by=fx["admin_user"],
    )


@pytest.mark.django_db
def test_client_verification_on_a_trip_from_a_closed_period_applies_loss_split():
    fx = _fixtures_with_customer("SCOPE-RCV")
    LossToleranceConfig.objects.create(
        tolerance_litres=Decimal("70.00"), updated_by=fx["admin_user"]
    )
    trip = _deliverable_trip(fx, "TRIP-SCOPE-RCV-001")
    DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
        unit_selling_price=Decimal("850.0000"),
    )
    _close_period(fx["admin_user"])

    control = DeliveryService.record_client_verification(
        trip_id=trip.id,
        received_qty=Decimal("44800.00"),
        verified_at=date.today(),
        actor=fx["admin_user"],
    )

    assert control.loss_quantity == Decimal("200.00")
    assert control.company_absorbed_loss_quantity == Decimal("70.00")
    assert control.chargeable_loss_quantity == Decimal("130.00")
    assert TransportDeduction.objects.get(trip=trip).chargeable_quantity == Decimal("130.00")
    assert Sale.objects.get(trip=trip).delivered_quantity == Decimal("44800.00")


@pytest.mark.django_db
def test_late_fee_on_a_trip_from_a_closed_period_is_accepted():
    fx = _setup_fixtures("SCOPE-FEE")
    truck = _make_truck("SCOPE-FEE")
    trip = _make_trip_on(fx, truck, "TRIP-SCOPE-FEE", "2026-08-18")
    _close_period(fx["admin_user"])

    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("90000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("90000.00"),
    )

    assert expense.allocations.count() == 1


@pytest.mark.django_db
def test_trip_status_and_quantity_changes_allowed_after_period_closed():
    fx = _setup_fixtures("SCOPE-TRIP")
    truck = _make_truck("SCOPE-TRIP")
    trip = _make_trip_on(fx, truck, "TRIP-SCOPE-TRIP", "2026-08-18")
    _close_period(fx["admin_user"])

    trip.status = Trip.Status.SENT_FOR_LOADING
    trip.quantity_loaded = Decimal("44000.00")
    trip.save()

    trip.refresh_from_db()
    assert trip.status == Trip.Status.SENT_FOR_LOADING
    assert trip.quantity_loaded == Decimal("44000.00")


@pytest.mark.django_db
def test_trip_creation_allowed_with_a_loading_date_in_a_closed_period():
    fx = _setup_fixtures("SCOPE-NEW")
    truck = _make_truck("SCOPE-NEW")
    _close_period(fx["admin_user"])

    trip = _make_trip_on(fx, truck, "TRIP-SCOPE-NEW", "2026-08-18")

    assert trip.pk is not None


@pytest.mark.django_db
def test_expense_amount_update_and_unpaid_deletion_allowed_after_period_closed():
    user = _actor("EXP")
    old = Expense.objects.create(
        category=Expense.Category.OTHER,
        amount=Decimal("500.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-10",
    )
    to_delete = Expense.objects.create(
        category=Expense.Category.OTHER,
        amount=Decimal("100.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-11",
    )
    _close_period(user)

    old.amount = Decimal("999.00")
    old.status = Expense.Status.PAID
    old.save()
    to_delete.delete()

    old.refresh_from_db()
    assert old.amount == Decimal("999.00")
    assert not Expense.objects.filter(pk=to_delete.pk).exists()


@pytest.mark.django_db
def test_sale_and_invoice_changes_allowed_after_period_closed():
    fx = _setup_fixtures("SCOPE-SALE")
    truck = _make_truck("SCOPE-SALE")
    trip = _make_trip_on(fx, truck, "TRIP-SCOPE-SALE", "2026-08-18")
    customer = Customer.objects.create(name="Client scope")
    sale = Sale.objects.create(
        trip=trip,
        customer=customer,
        product=fx["product"],
        delivered_quantity=Decimal("45000.00"),
        unit_selling_price=Decimal("900.0000"),
    )
    invoice = Invoice.objects.create(
        invoice_number="INV-SCOPE-SALE",
        sale=sale,
        total_amount=sale.subtotal,
        issued_date="2026-08-18",
    )
    _close_period(fx["admin_user"])

    sale.unit_selling_price = Decimal("1000.0000")
    sale.save()
    invoice.total_amount = sale.subtotal
    invoice.status = Invoice.Status.VALIDATED
    invoice.save()

    invoice.refresh_from_db()
    assert invoice.total_amount == Decimal("45000000.00")


@pytest.mark.django_db
def test_supplier_order_and_transport_payment_changes_allowed_after_period_closed():
    fx = _setup_fixtures("SCOPE-DEBT")
    order = SupplierOrder.objects.create(
        reference="SO-SCOPE-DEBT",
        supplier=fx["supplier"],
        product=fx["product"],
        purchase_date="2026-08-10",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        created_by=fx["admin_user"],
    )
    truck = _make_truck("SCOPE-DEBT", owner_transporter=fx["transporter"])
    trip = _make_trip_on(fx, truck, "TRIP-SCOPE-DEBT", "2026-08-18")
    payment = TransportPayment.objects.create(
        trip=trip,
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("10000.00"),
    )
    _close_period(fx["admin_user"])

    order.quantity_litres = Decimal("1000.00")
    order.status = SupplierOrder.Status.CONFIRMED
    order.save()
    payment.base_amount = Decimal("20000.00")
    payment.status = TransportPayment.Status.PAID
    payment.save()

    payment.refresh_from_db()
    assert payment.base_amount == Decimal("20000.00")
    assert payment.status == TransportPayment.Status.PAID

# Bug fix (2026-09-03 recette manuelle): cancelling a Trip used to leave
# every fee/transport debt it generated fully active - see
# TripCancellationService.reverse_trip_financials (apps/trips/services.py).

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.customers.models import Customer
from apps.finance.models import (
    AdvanceConsumption,
    BankAccount,
    Expense,
    ExpenseAllocation,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import (
    AdvanceConsumptionService,
    ControlledDebtPaymentService,
    IndirectSettlementService,
)
from apps.trips.models import Trip
from apps.trips.services import TripCostService, TripWorkflowService
from apps.trips.tests import _make_trip, _make_truck, _setup_fixtures


@pytest.mark.django_db
def test_cancel_trip_cancels_unpaid_expense_fee_with_no_treasury_movement():
    fx = _setup_fixtures("CANCELFEE")
    truck = _make_truck("TRK-CANCELFEE")
    trip = _make_trip(fx, truck, "TRIP-CANCELFEE-001")
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=expense.amount,
    )

    TripWorkflowService.transition_trip(trip.id, Trip.Status.CANCELLED, fx["admin_user"])

    expense.refresh_from_db()
    assert expense.status == Expense.Status.CANCELLED
    assert not TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(Expense), source_object_id=expense.id
    ).exists()
    # No longer counted as an active trip fee.
    assert TripCostService.calculate_trip_cost_basis(trip)["expenses_by_category"] == {}


@pytest.mark.django_db
def test_cancel_trip_reverses_treasury_paid_expense_fee():
    fx = _setup_fixtures("CANCELPAIDFEE")
    truck = _make_truck("TRK-CANCELPAIDFEE")
    trip = _make_trip(fx, truck, "TRIP-CANCELPAIDFEE-001")
    bank = BankAccount.objects.create(name="Bank Cancel Fee", opening_balance=Decimal("1000000.00"))
    expense = Expense.objects.create(
        category=Expense.Category.TRANSIT,
        amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=expense.amount,
    )
    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.TRANSIT,
        debt_id=0,
        bank_account_id=bank.id,
        amount=Decimal("50000.00"),
        date="2026-08-19",
        reference="",
        actor=fx["admin_user"],
    )
    bank.refresh_from_db()
    assert bank.current_balance == Decimal("950000.00")
    expense.refresh_from_db()
    assert expense.status == Expense.Status.PAID

    TripWorkflowService.transition_trip(trip.id, Trip.Status.CANCELLED, fx["admin_user"])

    expense.refresh_from_db()
    assert expense.status == Expense.Status.CANCELLED
    bank.refresh_from_db()
    assert bank.current_balance == Decimal("1000000.00")
    reversal = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(Expense),
        source_object_id=expense.id,
        type=TreasuryTransaction.Type.MONEY_IN,
    )
    assert reversal.amount == Decimal("50000.00")
    # No longer an open debt for this bucket.
    assert ControlledDebtPaymentService.describe_expense_group(
        ControlledDebtPaymentService.TRANSIT
    )["remaining_amount"] == Decimal("0.00")


@pytest.mark.django_db
def test_cancel_trip_reverses_indirect_settlement_expense():
    fx = _setup_fixtures("CANCELINDIRECT")
    truck = _make_truck("TRK-CANCELINDIRECT")
    trip = _make_trip(fx, truck, "TRIP-CANCELINDIRECT-001")
    customer = Customer.objects.create(name="Client Cancel Indirect")

    expense, payment, _allocation = IndirectSettlementService.record_indirect_payment(
        customer.id,
        {
            "category": Expense.Category.CUSTOMS,
            "amount": Decimal("75000.00"),
            "date": "2026-08-18",
        },
        fx["admin_user"],
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=expense.amount,
    )
    assert payment.is_reversed is False

    TripWorkflowService.transition_trip(trip.id, Trip.Status.CANCELLED, fx["admin_user"])

    expense.refresh_from_db()
    payment.refresh_from_db()
    assert expense.status == Expense.Status.CANCELLED
    assert payment.is_reversed is True
    # Never fabricates a treasury movement for a payment that never
    # transited through company bank/cash.
    assert not TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(Expense), source_object_id=expense.id
    ).exists()


@pytest.mark.django_db
def test_cancel_trip_cancels_and_reverses_transport_payment():
    fx = _setup_fixtures("CANCELTP")
    truck = _make_truck("TRK-CANCELTP")
    trip = _make_trip(fx, truck, "TRIP-CANCELTP-001")
    bank = BankAccount.objects.create(name="Bank Cancel TP", opening_balance=Decimal("500000.00"))
    payment = TransportPayment.objects.create(
        trip=trip,
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("200000.00"),
    )
    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.TRANSPORTER,
        debt_id=fx["transporter"].id,
        bank_account_id=bank.id,
        amount=Decimal("200000.00"),
        date="2026-08-19",
        reference="",
        actor=fx["admin_user"],
    )
    bank.refresh_from_db()
    assert bank.current_balance == Decimal("300000.00")
    payment.refresh_from_db()
    assert payment.status == TransportPayment.Status.PAID

    TripWorkflowService.transition_trip(trip.id, Trip.Status.CANCELLED, fx["admin_user"])

    payment.refresh_from_db()
    assert payment.status == TransportPayment.Status.CANCELLED
    bank.refresh_from_db()
    assert bank.current_balance == Decimal("500000.00")
    assert ControlledDebtPaymentService.describe_transporter(fx["transporter"])[
        "remaining_amount"
    ] == Decimal("0.00")


@pytest.mark.django_db
def test_cancel_trip_releases_transporter_advance_consumed_by_its_transport_payment():
    fx = _setup_fixtures("CANCELADV")
    truck = _make_truck("TRK-CANCELADV")
    trip = _make_trip(fx, truck, "TRIP-CANCELADV-001")
    advance = TransporterAdvance.objects.create(
        transporter=fx["transporter"], amount=Decimal("100000.00"), date="2026-08-17",
    )
    assert advance.remaining_amount == Decimal("100000.00")

    # consume_for_transport_payment runs unconditionally on save(), before
    # any treasury payment is ever made against this PLANNED payment.
    payment = TransportPayment.objects.create(
        trip=trip,
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("100000.00"),
    )
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("0.00")
    assert AdvanceConsumptionService.get_consumed_amount(payment) == Decimal("100000.00")

    TripWorkflowService.transition_trip(trip.id, Trip.Status.CANCELLED, fx["admin_user"])

    advance.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == TransportPayment.Status.CANCELLED
    assert advance.remaining_amount == Decimal("100000.00")
    assert AdvanceConsumption.objects.filter(
        debt_content_type=ContentType.objects.get_for_model(TransportPayment),
        debt_object_id=payment.id,
        reversed_at__isnull=True,
    ).count() == 0

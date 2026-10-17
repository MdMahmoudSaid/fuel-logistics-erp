"""Figures of the open period are measured from the last closure, never
from a trip's loading date (spec 2026-10-05-periodes-independantes, 3.3/3.4).

Invariant: operational profit - general expenses paid + carried over -
distributions since closure == distributable result.
"""

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.test import APIClient

from apps.customers.models import Customer
from apps.finance.models import (
    CashAccount,
    Expense,
    ExpenseAllocation,
    Shareholder,
    TreasuryTransaction,
)
from apps.finance.profit_periods import general_expenses_paid_between
from apps.finance.services import (
    ShareholderProfitPeriodService,
    ShareholderProfitPreviewService,
)
from apps.reports.queries.margin_report import MarginReportQuery
from apps.reports.queries.sales_report import SalesReportQuery
from apps.sales.models import Sale
from apps.trips.models import Trip
from apps.trips.tests import _make_trip, _make_truck, _setup_fixtures


def _trip(fx, reference):
    return _make_trip(fx, _make_truck(reference[-12:]), reference)


def _sell(fx, trip, unit_price=Decimal("900.0000")):
    return Sale.objects.create(
        trip=trip,
        customer=Customer.objects.get_or_create(name=f"Client {trip.reference}")[0],
        product=fx["product"],
        delivered_quantity=trip.quantity_loaded,
        unit_selling_price=unit_price,
    )


def _close(fx, start="2026-08-01", end="2026-08-31"):
    Shareholder.objects.get_or_create(
        name="Associe periode", defaults={"participation_percent": Decimal("100.00")}
    )
    period = ShareholderProfitPeriodService.open_period(start, fx["admin_user"])
    return ShareholderProfitPeriodService.close_period(period.id, end, fx["admin_user"])


def _current():
    return ShareholderProfitPreviewService.get_preview(
        date_from="2026-09-01", date_to=timezone.localdate(), since_last_closure=True
    )


def _assert_invariant(preview):
    reconstructed = (
        preview["operational_profit"]
        - preview["general_expenses_paid"]
        + preview["carried_over"]
        + preview["brought_forward_profit"]
        - preview["distributions_since_closure"]
    )
    assert reconstructed == preview["distributable_result"]


def _trip_fee(trip, amount):
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=amount,
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=amount,
    )
    return expense


@pytest.mark.django_db
def test_trip_loaded_before_closure_and_sold_after_counts_in_full_in_open_period():
    # The real case (2026-10-05): loaded in the closed period, sold after.
    fx = _setup_fixtures("CUR-REAL")
    trip = _trip(fx, "TRIP-CUR-REAL")
    _close(fx)
    _sell(fx, trip)
    margin = MarginReportQuery.run()[0]["current_margin"]

    rows = MarginReportQuery.run(since_last_closure=True)
    preview = _current()

    assert [(r["trip_reference"], r["is_adjustment"]) for r in rows] == [("TRIP-CUR-REAL", False)]
    assert preview["operational_profit"] == margin
    assert preview["revenue"] == Decimal("40500000.00")
    assert preview["distributable_result"] == margin
    _assert_invariant(preview)


@pytest.mark.django_db
def test_late_fee_on_a_distributed_trip_shows_as_negative_adjustment():
    fx = _setup_fixtures("CUR-FEE")
    trip = _trip(fx, "TRIP-CUR-FEE")
    _sell(fx, trip)
    _close(fx)
    _trip_fee(trip, Decimal("90000.00"))

    rows = MarginReportQuery.run(since_last_closure=True)
    preview = _current()

    assert len(rows) == 1
    assert rows[0]["is_adjustment"] is True
    assert rows[0]["current_margin"] == Decimal("-90000.00")
    assert rows[0]["customs_cost"] == Decimal("90000.00")
    assert rows[0]["revenue"] == Decimal("0.00")
    assert preview["operational_profit"] == Decimal("-90000.00")
    assert preview["distributable_result"] == Decimal("-90000.00")
    _assert_invariant(preview)


@pytest.mark.django_db
def test_unchanged_old_trip_is_not_listed_in_open_period():
    fx = _setup_fixtures("CUR-SAME")
    _sell(fx, _trip(fx, "TRIP-CUR-SAME"))
    _close(fx)

    assert MarginReportQuery.run(since_last_closure=True) == []
    preview = _current()
    assert preview["operational_profit"] == Decimal("0.00")
    _assert_invariant(preview)


@pytest.mark.django_db
def test_deficit_at_closure_is_carried_into_the_open_period():
    fx = _setup_fixtures("CUR-DEFICIT")
    Expense.objects.create(
        category=Expense.Category.RENT,
        amount=Decimal("500000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-05",
        status=Expense.Status.PAID,
    )
    period = _close(fx)
    assert period.net_profit == Decimal("-500000.00")
    assert period.distribution_id is None
    _sell(fx, _trip(fx, "TRIP-CUR-DEFICIT"))

    preview = _current()

    assert preview["carried_over"] == Decimal("-500000.00")
    assert preview["general_expenses_paid"] == Decimal("0.00")
    _assert_invariant(preview)


@pytest.mark.django_db
def test_trip_that_left_the_margin_report_after_closure_shows_negative_adjustment():
    fx = _setup_fixtures("CUR-GONE")
    trip = _trip(fx, "TRIP-CUR-GONE")
    sale = _sell(fx, trip)
    margin = MarginReportQuery.run()[0]["current_margin"]
    _close(fx)
    Sale.objects.filter(pk=sale.pk).delete()

    rows = MarginReportQuery.run(since_last_closure=True)
    preview = _current()

    assert len(rows) == 1
    assert rows[0]["is_adjustment"] is True
    assert rows[0]["current_margin"] == -margin
    _assert_invariant(preview)


@pytest.mark.django_db
def test_reopening_measures_the_open_period_from_the_previous_closure():
    fx = _setup_fixtures("CUR-REOPEN")
    _sell(fx, _trip(fx, "TRIP-CUR-REOPEN"))
    period = _close(fx)

    ShareholderProfitPeriodService.reopen_period(period.id, "Correction necessaire", fx["admin_user"])

    rows = MarginReportQuery.run(since_last_closure=True)
    assert [r["is_adjustment"] for r in rows] == [False]
    _assert_invariant(_current())


@pytest.mark.django_db
def test_without_any_closure_the_open_period_is_the_whole_history():
    fx = _setup_fixtures("CUR-NONE")
    _sell(fx, _trip(fx, "TRIP-CUR-NONE"))

    preview = _current()

    assert preview["operational_profit"] == MarginReportQuery.run()[0]["current_margin"]
    assert preview["carried_over"] == Decimal("0.00")
    _assert_invariant(preview)


@pytest.mark.django_db
def test_date_ranges_rank_trips_by_sale_date_not_loading_date():
    fx = _setup_fixtures("CUR-SALEDATE")
    _sell(fx, _trip(fx, "TRIP-CUR-SALEDATE"))  # loaded 2026-08-18, sold today
    today = timezone.localdate()

    assert MarginReportQuery.run(date_from="2026-08-01", date_to="2026-08-31") == []
    assert len(MarginReportQuery.run(date_from=today, date_to=today)) == 1
    assert SalesReportQuery.run(date_from="2026-08-01", date_to="2026-08-31") == []
    assert len(SalesReportQuery.run(date_from=today, date_to=today)) == 1


@pytest.mark.django_db
def test_general_expense_counts_on_its_payment_date():
    fx = _setup_fixtures("CUR-PAYDATE")
    expense = Expense.objects.create(
        category=Expense.Category.RENT,
        amount=Decimal("1000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-05",
        status=Expense.Status.PAID,
    )
    TreasuryTransaction.objects.create(
        cash_account=CashAccount.objects.create(name="Caisse paydate"),
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("1000.00"),
        date="2026-09-10",
        recorded_by=fx["admin_user"],
        source_content_type=ContentType.objects.get_for_model(Expense),
        source_object_id=expense.id,
    )

    assert general_expenses_paid_between("2026-08-01", "2026-08-31") == Decimal("0.00")
    assert general_expenses_paid_between("2026-09-01", "2026-09-30") == Decimal("1000.00")


@pytest.mark.django_db
def test_benefices_report_and_dashboard_agree_on_current_period():
    fx = _setup_fixtures("CUR-API")
    trip = _trip(fx, "TRIP-CUR-API")
    _close(fx)
    _sell(fx, trip)
    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    report = client.get("/api/reports/margin-report/", {"preset": "period"})
    preview = client.get("/api/shareholders/profit-preview/", {"preset": "period"})
    dashboard = client.get("/api/dashboard/summary/", {"preset": "period"})

    assert report.status_code == preview.status_code == dashboard.status_code == 200
    assert [r["trip_reference"] for r in report.data["rows"]] == ["TRIP-CUR-API"]
    summary = dashboard.data["financial_summary"]
    assert summary["period_revenue"] == preview.data["revenue"] == "40500000.00"
    assert summary["period_accounting_profit"] == preview.data["operational_profit"]
    assert summary["period_paid_expenses"] == preview.data["general_expenses_paid"]
    assert summary["period_net_profit"] == preview.data["net_profit"]

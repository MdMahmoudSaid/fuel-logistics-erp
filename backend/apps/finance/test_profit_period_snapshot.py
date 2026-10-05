"""Snapshot of every sold trip's profit taken when a period closes
(spec 2026-10-05-periodes-independantes-design.md, section 3.2/3.5)."""

from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.customers.models import Customer
from apps.finance.models import Shareholder, ShareholderProfitPeriodTripSnapshot
from apps.finance.services import ShareholderProfitPeriodService
from apps.reports.queries.margin_report import MarginReportQuery
from apps.sales.models import Sale
from apps.trips.tests import _make_trip, _make_truck, _setup_fixtures


def _sold_trip(fx, reference, unit_price=Decimal("900.0000")):
    trip = _make_trip(fx, _make_truck(reference[-12:]), reference)
    Sale.objects.create(
        trip=trip,
        customer=Customer.objects.get_or_create(name=f"Client {reference}")[0],
        product=fx["product"],
        delivered_quantity=trip.quantity_loaded,
        unit_selling_price=unit_price,
    )
    return trip


def _close(fx):
    Shareholder.objects.get_or_create(
        name="Associe photo", defaults={"participation_percent": Decimal("100.00")}
    )
    period = ShareholderProfitPeriodService.open_period("2026-08-01", fx["admin_user"])
    return ShareholderProfitPeriodService.close_period(period.id, "2026-08-31", fx["admin_user"])


@pytest.mark.django_db
def test_closing_a_period_snapshots_every_sold_trip_and_running_totals():
    fx = _setup_fixtures("SNAP-CLOSE")
    trip = _sold_trip(fx, "TRIP-SNAP-CLOSE")
    expected_margin = MarginReportQuery.run()[0]["current_margin"]

    period = _close(fx)

    snapshot = period.trip_snapshots.get()
    assert snapshot.trip_id == trip.id
    assert snapshot.margin == expected_margin
    assert snapshot.data["trip_reference"] == "TRIP-SNAP-CLOSE"
    assert period.general_expenses_paid_snapshot == Decimal("0.00")
    assert period.distributed_total_snapshot == period.net_profit == expected_margin


@pytest.mark.django_db
def test_reopening_a_period_drops_its_snapshot():
    fx = _setup_fixtures("SNAP-REOPEN")
    _sold_trip(fx, "TRIP-SNAP-REOPEN")
    period = _close(fx)

    period = ShareholderProfitPeriodService.reopen_period(
        period.id, "Correction necessaire", fx["admin_user"]
    )

    assert not ShareholderProfitPeriodTripSnapshot.objects.filter(period=period).exists()
    assert period.general_expenses_paid_snapshot is None
    assert period.distributed_total_snapshot is None


@pytest.mark.django_db
def test_backfill_snapshots_only_trips_sold_before_the_last_closure(capsys):
    fx = _setup_fixtures("SNAP-BACKFILL")
    before = _sold_trip(fx, "TRIP-SNAP-BEFORE")
    period = _close(fx)
    # State of a period closed before this feature existed.
    period.trip_snapshots.all().delete()
    period.general_expenses_paid_snapshot = None
    period.distributed_total_snapshot = None
    period.save(update_fields=["general_expenses_paid_snapshot", "distributed_total_snapshot"])
    _sold_trip(fx, "TRIP-SNAP-AFTER")

    call_command("backfill_profit_period_snapshot")
    call_command("backfill_profit_period_snapshot")

    period.refresh_from_db()
    assert list(period.trip_snapshots.values_list("trip_id", flat=True)) == [before.id]
    assert period.general_expenses_paid_snapshot == Decimal("0.00")
    assert period.distributed_total_snapshot == period.net_profit
    assert "deja" in capsys.readouterr().out

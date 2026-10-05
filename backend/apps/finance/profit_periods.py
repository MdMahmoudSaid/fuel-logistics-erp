"""Profit-period bookkeeping shared by closure, the Benefices page and the
dashboard (spec 2026-10-05-periodes-independantes-design.md).

A closure freezes running totals (per-trip margin rows, general expenses
paid, distributions validated). The open period is "now minus that
snapshot": a trip sold after the closure counts in full, and any later
change to an older trip (late fee, client quantity control, correction)
appears as an adjustment row - nothing done after a closure ever depends on
the closed period's dates.
"""

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Max, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.core.request_cache import memoize_per_request
from apps.finance.models import (
    Expense,
    ShareholderProfitDistribution,
    ShareholderProfitPeriod,
    ShareholderProfitPeriodTripSnapshot,
    TreasuryTransaction,
)

ZERO = Decimal("0.00")

# Margin-report row keys that add up across trips - the ones an adjustment
# row carries as "now minus snapshot". Every other key (unit prices,
# labels) keeps its current value.
ADDITIVE_FIELDS = (
    "quantity",
    "quantity_loaded",
    "quantity_invoiced",
    "transporter_loss_quantity",
    "transporter_loss_indemnity",
    "company_absorbed_loss_quantity",
    "company_absorbed_loss_amount",
    "transport_cost",
    "customs_cost",
    "transit_cost",
    "road_transit_cost",
    "border_cost",
    "loading_cost",
    "additional_costs",
    "real_total_cost",
    "current_margin",
    "revenue",
    "supplier_cost",
)


@memoize_per_request
def latest_closed_period():
    return (
        ShareholderProfitPeriod.objects.filter(status=ShareholderProfitPeriod.Status.CLOSED)
        .order_by("-end_date", "-id")
        .first()
    )


def general_expenses_paid():
    """General expenses (no trip allocation) that are PAID - the same
    definition the net profit has always used."""
    return Expense.objects.filter(allocations__isnull=True, status=Expense.Status.PAID)


@memoize_per_request
def general_expenses_paid_total():
    return general_expenses_paid().aggregate(total=Sum("amount"))["total"] or ZERO


def general_expenses_paid_between(date_from=None, date_to=None):
    """Paid general expenses whose PAYMENT falls in the range: the latest
    treasury outflow recorded against the expense, else the customer
    payment of an indirect settlement, else the expense date."""
    expense_type = ContentType.objects.get_for_model(Expense)
    last_outflow = (
        TreasuryTransaction.objects.filter(
            source_content_type=expense_type,
            source_object_id=OuterRef("pk"),
            type=TreasuryTransaction.Type.MONEY_OUT,
        )
        .values("source_object_id")
        .annotate(last=Max("date"))
        .values("last")
    )
    expenses = general_expenses_paid().annotate(
        paid_on=Coalesce(
            Subquery(last_outflow),
            "indirect_settlement_payment__payment_date",
            "date",
        )
    )
    if date_from:
        expenses = expenses.filter(paid_on__gte=date_from)
    if date_to:
        expenses = expenses.filter(paid_on__lte=date_to)
    return expenses.aggregate(total=Sum("amount"))["total"] or ZERO


@memoize_per_request
def validated_distributions_total():
    return (
        ShareholderProfitDistribution.objects.filter(
            status=ShareholderProfitDistribution.Status.VALIDATED
        ).aggregate(total=Sum("total_profit"))["total"]
        or ZERO
    )


def _serialize(row) -> dict:
    return {
        key: (str(value) if isinstance(value, Decimal) else value)
        for key, value in row.items()
    }


def take_snapshot(period, rows) -> None:
    """Replace `period`'s trip snapshot with `rows` (margin-report rows)."""
    period.trip_snapshots.all().delete()
    ShareholderProfitPeriodTripSnapshot.objects.bulk_create(
        [
            ShareholderProfitPeriodTripSnapshot(
                period=period,
                trip_id=row["trip_id"],
                margin=row["current_margin"],
                data=_serialize(row),
            )
            for row in rows
            # A row without trip_id cannot be keyed (only the test helper
            # seed_net_profit produces such synthetic rows).
            if row.get("trip_id")
        ]
    )


def rows_since_last_closure(rows) -> list[dict]:
    """Margin-report rows of the open period: trips sold since the last
    closure in full, plus one adjustment row per older trip whose figures
    moved since that closure (including a trip that disappeared)."""
    period = latest_closed_period()
    if period is None:
        return rows
    snapshots = {snap.trip_id: snap for snap in period.trip_snapshots.all()}
    result = []
    for row in rows:
        snapshot = snapshots.pop(row.get("trip_id"), None)
        if snapshot is None:
            result.append(row)
            continue
        delta = dict(row)
        for key in ADDITIVE_FIELDS:
            delta[key] = Decimal(str(row.get(key, ZERO))) - Decimal(
                str(snapshot.data.get(key, "0"))
            )
        if any(delta[key] != ZERO for key in ADDITIVE_FIELDS):
            delta["is_adjustment"] = True
            result.append(delta)
    for snapshot in snapshots.values():
        removed = dict(snapshot.data)
        for key in ADDITIVE_FIELDS:
            removed[key] = -Decimal(str(snapshot.data.get(key, "0")))
        for key, value in snapshot.data.items():
            if key not in ADDITIVE_FIELDS and isinstance(value, str):
                try:
                    removed[key] = Decimal(value)
                except ArithmeticError:
                    pass
        removed["trip_id"] = snapshot.trip_id
        removed["is_adjustment"] = True
        result.append(removed)
    return result

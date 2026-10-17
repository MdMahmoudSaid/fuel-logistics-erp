# "Situation financiere" (client request 2026-10-17): what the company owns
# against what it owes, and the net result = owned - owed.
#
# Every figure that exists in the Fond de roulement is shown here with the SAME
# value (treasury, customer receivables, the three "Paye : ..." fuel lines,
# supplier / transporter / trip-fee debts at their full amount, what is owed
# to the associates). A purchase on credit is a debt in full AND the fuel it
# covers, so the unsold fuel (and the costs already engaged on trips not sold
# yet) not yet paid for is shown on the asset side as "couvert par les dettes":
# the two cancel in the net result. Booking them once on each side is what
# makes the net result equal the profit: the profit books a trip's costs only
# when the trip is sold.
#
# Goal (client rule): the net result equals the distributable net profit of the
# Benefices page plus the starting funds (shown as a reconciliation, never as a
# liability), at any time. It holds because
#     treasury + receivables + advances + paid unsold fuel/costs
#   - debts of sold goods - customer credit - what is owed to the associates
# is exactly: capital contributions + all-time profit - everything drawn, minus
# what the associates may still draw, plus the starting funds.
#
# Every figure comes from a service that already owns it (the debts / receivables
# reports, the supplier pipeline of the Fond de roulement, the associates'
# balances); nothing is recomputed from raw rows except the unsold-trip costs.

from decimal import Decimal

from django.db.models import F as models_F

from apps.finance.models import (
    BankAccount,
    CashAccount,
    ExpenseAllocation,
    OpeningDebt,
    ShareholderLoan,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import (
    ControlledDebtPaymentService as Debts,
)
from apps.finance.services import (
    ShareholderContributionService,
    ShareholderLedgerService,
    ShareholderProfitPreviewService,
    WorkingCapitalService,
)
from apps.purchasing.models import SupplierOrder
from apps.purchasing.services import SupplierStockService
from apps.reports.queries.debts_summary_report import DebtsSummaryReportQuery
from apps.reports.queries.receivables_summary_report import ReceivablesSummaryReportQuery
from apps.trips.models import Trip

ZERO = Decimal("0.00")

_FEE_KEYS = ("customs", "transit", "road_transit", "border", "loading")


def _line(key, amount, children=None):
    return {"key": key, "amount": amount, "children": children or []}


def _sum_rows(rows, party_type):
    return sum((r["amount"] for r in rows if r["party_type"] == party_type), ZERO)


def _unsold_trip_costs() -> dict:
    """Costs already engaged on the trips that are not sold yet (they are
    booked in the profit only at the sale): per kind, what is still unpaid
    (matched by an open debt, shown nowhere) and what has been paid (an asset
    until the sale)."""
    trips = {
        t.id: t
        for t in Trip.objects.filter(sale__isnull=True).exclude(
            status__in=Trip.NON_OCCUPYING_STATUSES
        )
    }
    unpaid = {"transport": ZERO, **{key: ZERO for key in _FEE_KEYS}}
    paid = ZERO
    if not trips:
        return {"unpaid": unpaid, "paid": paid}

    for payment in TransportPayment.objects.filter(trip_id__in=trips).exclude(
        status=TransportPayment.Status.CANCELLED
    ).select_related("trip", "transporter"):
        described = Debts.describe_transport_payment(payment)
        unpaid["transport"] += max(described["remaining_amount"], ZERO)
        paid += min(described["paid_amount"], described["total_amount"])

    from django.contrib.contenttypes.models import ContentType

    trip_type = ContentType.objects.get_for_model(Trip)
    seen = {}
    for allocation in ExpenseAllocation.objects.filter(
        content_type=trip_type, object_id__in=trips
    ).select_related("expense"):
        expense = allocation.expense
        if expense.status == expense.Status.CANCELLED:
            continue
        if expense.id not in seen:
            seen[expense.id] = Debts.describe_expense(expense)
        described = seen[expense.id]
        if not described["total_amount"]:
            continue
        # An expense split over several trips: each trip carries its share of
        # what is paid and of what remains.
        share = allocation.allocated_amount / described["total_amount"]
        remaining = max(described["remaining_amount"], ZERO) * share
        paid += described["paid_amount"] * share
        fee_key = described["debt_type"]
        if fee_key in _FEE_KEYS:
            unpaid[fee_key] += remaining
    return {"unpaid": unpaid, "paid": paid}


def _treasury_origins(bank_accounts, cash_accounts, starting_funds) -> list[dict]:
    """Net treasury movement per origin (the kind of record that caused it),
    on the accounts counted in the position; internal transfers net to zero
    between two counted accounts and are listed apart."""
    from django.db.models import Case, DecimalField, Q, Sum, Value, When

    movements = TreasuryTransaction.objects.filter(
        Q(bank_account__in=bank_accounts) | Q(cash_account__in=cash_accounts)
    )
    signed = Case(
        When(type=TreasuryTransaction.Type.MONEY_IN, then="amount"),
        default=-1 * models_F("amount"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    grouped = (
        movements.values("is_transfer", "source_content_type__model")
        .annotate(net=Sum(signed))
        .order_by()
    )
    totals: dict[str, Decimal] = {}
    for row in grouped:
        key = "transfer" if row["is_transfer"] else (row["source_content_type__model"] or "manual")
        totals[key] = totals.get(key, ZERO) + row["net"]
    rows = [{"key": "opening_balances", "amount": starting_funds}] + [
        {"key": key, "amount": amount} for key, amount in totals.items() if amount != ZERO
    ]
    return rows


class FinancialPositionService:
    @staticmethod
    def get_position() -> dict:
        bank_accounts = list(BankAccount.objects.filter(is_active=True))
        cash_accounts = list(CashAccount.objects.filter(is_active=True))
        receivables = ReceivablesSummaryReportQuery.run()
        debts = DebtsSummaryReportQuery.run()

        # Fuel: what is paid for and still unsold (same split, same cap as the
        # Fond de roulement's "Paye : ..." lines); the unpaid rest is matched
        # by the supplier debt and shown in neither column.
        pipeline = WorkingCapitalService.get_supplier_pipeline_breakdown()
        paid_stock = pipeline["supplier_company_stock_value"]
        paid_in_transit = pipeline["supplier_in_transit_value"]
        paid_at_supplier = pipeline["supplier_reliquat_value"]
        full_stock = full_in_transit = full_at_supplier = ZERO
        for order in SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED):
            full_stock += SupplierStockService.get_purchase_company_stock_amount(order)
            full_in_transit += SupplierStockService.get_purchase_in_transit_amount(order)
            full_at_supplier += SupplierStockService.get_purchase_reliquat_amount(order)
        # The same three places as the "Paye : ..." lines; the part of each not
        # paid yet is what the supplier debt still finances.
        unpaid_stock = max(full_stock - paid_stock, ZERO)
        unpaid_in_transit = max(full_in_transit - paid_in_transit, ZERO)
        unpaid_at_supplier = max(full_at_supplier - paid_at_supplier, ZERO)
        unpaid_unsold_fuel = unpaid_stock + unpaid_in_transit + unpaid_at_supplier

        costs = _unsold_trip_costs()

        associate_advances = sum(
            (
                loan.cash_outstanding
                for loan in ShareholderLoan.objects.filter(source=ShareholderLoan.Source.COMPANY)
            ),
            ZERO,
        )

        asset_lines = [
            _line("banks", sum((a.current_balance for a in bank_accounts), ZERO), [
                {"label": a.name, "amount": a.current_balance} for a in bank_accounts
            ]),
            _line("cash", sum((a.current_balance for a in cash_accounts), ZERO), [
                {"label": a.name, "amount": a.current_balance} for a in cash_accounts
            ]),
            _line("customer_receivables", _sum_rows(receivables, "customer")),
            _line("supplier_advances", _sum_rows(receivables, "supplier_advance")),
            _line("transporter_advances", _sum_rows(receivables, "transporter_advance")),
            _line("associate_advances", associate_advances),
            _line("unsold_fuel_paid", paid_stock + paid_in_transit + paid_at_supplier, [
                {"key": "company_stock", "amount": paid_stock},
                {"key": "in_transit", "amount": paid_in_transit},
                {"key": "at_supplier", "amount": paid_at_supplier},
            ]),
            _line("unsold_costs_paid", costs["paid"]),
            _line(
                "unsold_unpaid_covered",
                unpaid_unsold_fuel + sum(costs["unpaid"].values(), ZERO),
                [
                    {"key": "unpaid_company_stock", "amount": unpaid_stock},
                    {"key": "unpaid_in_transit", "amount": unpaid_in_transit},
                    {"key": "unpaid_at_supplier", "amount": unpaid_at_supplier},
                    {"key": "unpaid_costs", "amount": sum(costs["unpaid"].values(), ZERO)},
                ],
            ),
        ]

        supplier_total = _sum_rows(debts, "supplier")
        transporter_total = _sum_rows(debts, "transporter")
        fee_children = [
            {"key": key, "amount": _sum_rows(debts, f"fee_{key}")}
            for key in _FEE_KEYS
        ]
        dues = ShareholderLedgerService.get_company_dues()
        # What the company already had when it started using the app: the
        # accounts' opening balances, plus what customers already owed it and
        # minus what it already owed suppliers / transporters ("Nouvelle dette":
        # money that moved before the app, so never a profit nor a cost).
        old_debts = OpeningDebt.objects.filter(cancelled_at__isnull=True)
        starting_funds = (
            sum((a.opening_balance for a in bank_accounts), ZERO)
            + sum((a.opening_balance for a in cash_accounts), ZERO)
            + sum((d.amount for d in old_debts.filter(customer__isnull=False)), ZERO)
            - sum((d.amount for d in old_debts.filter(customer__isnull=True)), ZERO)
        )
        liability_lines = [
            _line("supplier_debts", supplier_total),
            _line("transporter_debts", transporter_total),
            _line("trip_fee_debts", sum((c["amount"] for c in fee_children), ZERO), fee_children),
            _line("customer_credit", _sum_rows(debts, "customer_credit")),
            _line("shareholder_dues", dues["total"], [
                {"label": s["name"], "amount": s["amount"]} for s in dues["shareholders"]
            ]),
        ]

        total_assets = sum((l["amount"] for l in asset_lines), ZERO)
        total_liabilities = sum((l["amount"] for l in liability_lines), ZERO)
        distributable = ShareholderProfitPreviewService.get_preview()["distributable_result"]
        matched = unpaid_unsold_fuel + sum(costs["unpaid"].values(), ZERO)
        working_capital = WorkingCapitalService.get_working_capital()
        return {
            "assets": {"lines": asset_lines, "total": total_assets},
            "liabilities": {"lines": liability_lines, "total": total_liabilities},
            "net_result": total_assets - total_liabilities,
            # Not a liability: the opening balances are already inside the banks /
            # cash lines (and the old debts inside the receivables / debts). They
            # are not profit, so the net result = distributable profit + these.
            "starting_funds": starting_funds,
            # For the record: open debts matched by fuel / costs not sold yet,
            # shown in neither column (reconciles with "Dettes a payer").
            "matched_unsold": matched,
            # Control figure: the net result must always equal the net profit
            # that can be distributed (Benefices page). A non-zero gap would
            # mean a movement this page does not know how to place.
            "distributable_result": distributable,
            "gap": total_assets - total_liabilities - starting_funds - distributable,
            # Where the treasury comes from (net per origin): lets a gap with the
            # distributable profit be traced to the movements behind it.
            "treasury_origins": _treasury_origins(
                bank_accounts,
                cash_accounts,
                sum((a.opening_balance for a in bank_accounts), ZERO)
                + sum((a.opening_balance for a in cash_accounts), ZERO),
            ),
            # The Fond de roulement figure, for the record (it ADDS the open
            # debts to the treasury and the receivables; this page subtracts them).
            "working_capital_total": working_capital["total"],
            # Information only: the capital the associates brought in.
            "capital": ShareholderContributionService.get_total_capital(),
        }

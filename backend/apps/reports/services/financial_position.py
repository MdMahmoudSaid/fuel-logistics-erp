# "Situation financiere" (client request 2026-10-17): what the company owns
# (ce qui est du a l'entreprise) against what it owes (ce qu'elle doit), and the
# net result = owned - owed. A balance-sheet style view, NOT the Fond de
# roulement (which ADDS open debts, see WorkingCapitalService).
#
# No figure is computed here from raw models when a service already owns it:
#   - receivables / advances paid / customer credit / debts per party come from
#     the two summary reports ("Ce qui nous est du" / "Ce que nous devons"), so
#     the page can never disagree with them;
#   - what the company owes its associates comes from
#     ShareholderLedgerService.get_company_dues() (capital not given back +
#     validated profit not withdrawn);
#   - unsold fuel is valued at the purchase price, in FULL (client decision
#     2026-10-17): the supplier debt is booked in full on confirmation, so the
#     fuel it paid for must stand on the other side, whatever has been paid.
#
# Each amount sits on exactly one side once: treasury (banks/cash) is money
# already received; the associates' capital is inside it, which is why their
# dues are subtracted here instead of added (the Fond de roulement shows them
# for information only).

from decimal import Decimal

from apps.finance.models import BankAccount, CashAccount, ShareholderLoan
from apps.finance.services import ShareholderContributionService, ShareholderLedgerService
from apps.purchasing.models import SupplierOrder
from apps.purchasing.services import SupplierStockService
from apps.reports.queries.debts_summary_report import DebtsSummaryReportQuery
from apps.reports.queries.receivables_summary_report import ReceivablesSummaryReportQuery

ZERO = Decimal("0.00")

_FEE_KEYS = ("customs", "transit", "road_transit", "border", "loading")


def _line(key, amount, children=None):
    return {"key": key, "amount": amount, "children": children or []}


def _sum_rows(rows, party_type):
    return sum((r["amount"] for r in rows if r["party_type"] == party_type), ZERO)


class FinancialPositionService:
    @staticmethod
    def get_position() -> dict:
        banks = [(a.name, a.current_balance) for a in BankAccount.objects.filter(is_active=True)]
        cashes = [(a.name, a.current_balance) for a in CashAccount.objects.filter(is_active=True)]

        receivables = ReceivablesSummaryReportQuery.run()
        debts = DebtsSummaryReportQuery.run()

        company_stock = in_transit = reliquat = ZERO
        for order in SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED):
            company_stock += SupplierStockService.get_purchase_company_stock_amount(order)
            in_transit += SupplierStockService.get_purchase_in_transit_amount(order)
            reliquat += SupplierStockService.get_purchase_reliquat_amount(order)
        fuel_stock = company_stock + in_transit + reliquat

        associate_advances = sum(
            (
                loan.cash_outstanding
                for loan in ShareholderLoan.objects.filter(source=ShareholderLoan.Source.COMPANY)
            ),
            ZERO,
        )

        asset_lines = [
            _line("banks", sum((b for _, b in banks), ZERO), [
                {"label": name, "amount": amount} for name, amount in banks
            ]),
            _line("cash", sum((c for _, c in cashes), ZERO), [
                {"label": name, "amount": amount} for name, amount in cashes
            ]),
            _line("customer_receivables", _sum_rows(receivables, "customer")),
            _line("supplier_advances", _sum_rows(receivables, "supplier_advance")),
            _line("transporter_advances", _sum_rows(receivables, "transporter_advance")),
            _line("associate_advances", associate_advances),
            _line("fuel_stock", fuel_stock, [
                {"key": "company_stock", "amount": company_stock},
                {"key": "in_transit", "amount": in_transit},
                {"key": "at_supplier", "amount": reliquat},
            ]),
        ]

        dues = ShareholderLedgerService.get_company_dues()
        fee_children = [
            {"key": key, "amount": _sum_rows(debts, f"fee_{key}")} for key in _FEE_KEYS
        ]
        liability_lines = [
            _line("supplier_debts", _sum_rows(debts, "supplier")),
            _line("transporter_debts", _sum_rows(debts, "transporter")),
            _line("trip_fee_debts", sum((c["amount"] for c in fee_children), ZERO), fee_children),
            _line("customer_credit", _sum_rows(debts, "customer_credit")),
            _line("shareholder_dues", dues["total"], [
                {"label": s["name"], "amount": s["amount"]} for s in dues["shareholders"]
            ]),
        ]

        total_assets = sum((l["amount"] for l in asset_lines), ZERO)
        total_liabilities = sum((l["amount"] for l in liability_lines), ZERO)
        return {
            "assets": {"lines": asset_lines, "total": total_assets},
            "liabilities": {"lines": liability_lines, "total": total_liabilities},
            "net_result": total_assets - total_liabilities,
            # Information only: the capital the associates brought in.
            "capital": ShareholderContributionService.get_total_capital(),
        }

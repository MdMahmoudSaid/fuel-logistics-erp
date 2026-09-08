# ShareholderStatementQuery - "Relevé Actionnaire" (UI pass 2026-08-27:
# Reports page must list a report for Actionnaires/Associés).
#
# Mirrors CustomerStatementQuery/SupplierStatementQuery's shape (one
# chronological ledger with a running balance) but sourced from the four
# event types that move a shareholder's equity (Task 7, client
# modifications plan / apps.finance.services.ShareholderLedgerService):
#   - a ShareholderProfitShare being attributed (credit: it's now theirs)
#   - a ShareholderWithdrawal (debit: cash paid out against that share)
#   - a ShareholderLoan where this shareholder is the lender (credit: an
#     IOU from another shareholder, still their equity)
#   - a ShareholderLoan where this shareholder is the borrower (debit: a
#     liability against their equity)
#
# Loan rows use `remaining_amount` (net of any repayment) rather than the
# original `amount` - there is no separate repayment-event model
# (ShareholderLoan only stores a cumulative amount_repaid), so a partial
# repayment updates this row's amount in place instead of appearing as its
# own ledger line. With that, the final running balance always equals
# ShareholderLedgerService.get_available_balance() for the same shareholder,
# since both are derived from the same rows/formula.

from django.utils.dateparse import parse_date

from apps.finance.models import (
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
)

FIELDS = ["date", "type", "reference", "debit", "credit", "balance"]


def _as_date(value):
    """date_from/date_to arrive as either a "YYYY-MM-DD" string (explicit
    ?from=/&to=) or an already-resolved date (named ?range=), and the rows
    here are merged in Python rather than filtered via the ORM (unlike
    CustomerStatementQuery) - so, same fix as TreasuryStatementQuery,
    always coerce to a real date before comparing against entry["date"]."""
    if value is None or not isinstance(value, str):
        return value
    return parse_date(value)


class ShareholderStatementQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, shareholder_id, date_from=None, date_to=None) -> list[dict]:
        date_from = _as_date(date_from)
        date_to = _as_date(date_to)
        shares = (
            ShareholderProfitShare.objects.filter(shareholder_id=shareholder_id)
            .exclude(distribution__status=ShareholderProfitDistribution.Status.CANCELLED)
            .select_related("distribution")
        )
        withdrawals = ShareholderWithdrawal.objects.filter(shareholder_id=shareholder_id)
        loans_lent = ShareholderLoan.objects.filter(lender_id=shareholder_id)
        loans_borrowed = ShareholderLoan.objects.filter(borrower_id=shareholder_id)

        entries = (
            [
                {
                    "date": share.distribution.period_end,
                    "type": "PROFIT_SHARE",
                    "reference": (
                        f"Distribution {share.distribution.period_start} - "
                        f"{share.distribution.period_end}"
                    ),
                    "debit": None,
                    "credit": share.amount_due,
                    "sort_key": (share.distribution.period_end, 0, share.id),
                }
                for share in shares
            ]
            + [
                {
                    "date": withdrawal.date,
                    "type": "WITHDRAWAL",
                    "reference": f"WD-{withdrawal.id}",
                    "debit": withdrawal.amount,
                    "credit": None,
                    "sort_key": (withdrawal.date, 1, withdrawal.id),
                }
                for withdrawal in withdrawals
            ]
            + [
                {
                    "date": loan.date,
                    "type": "LOAN_GIVEN",
                    "reference": f"LOAN-{loan.id}",
                    "debit": None,
                    "credit": loan.remaining_amount,
                    "sort_key": (loan.date, 2, loan.id),
                }
                for loan in loans_lent
            ]
            + [
                {
                    "date": loan.date,
                    "type": "LOAN_RECEIVED",
                    "reference": f"LOAN-{loan.id}",
                    "debit": loan.remaining_amount,
                    "credit": None,
                    "sort_key": (loan.date, 3, loan.id),
                }
                for loan in loans_borrowed
            ]
        )
        if date_from:
            entries = [entry for entry in entries if entry["date"] >= date_from]
        if date_to:
            entries = [entry for entry in entries if entry["date"] <= date_to]
        entries.sort(key=lambda entry: entry["sort_key"])

        balance = 0
        rows = []
        for entry in entries:
            balance += (entry["credit"] or 0) - (entry["debit"] or 0)
            rows.append(
                {
                    "date": entry["date"],
                    "type": entry["type"],
                    "reference": entry["reference"],
                    "debit": entry["debit"],
                    "credit": entry["credit"],
                    "balance": balance,
                }
            )
        return rows

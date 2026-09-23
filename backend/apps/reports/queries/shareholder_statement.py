# ShareholderStatementQuery - "Relevé Actionnaire" (UI pass 2026-08-27:
# Reports page must list a report for Actionnaires/Associés).
#
# Mirrors CustomerStatementQuery/SupplierStatementQuery's shape (one
# chronological ledger with a running balance) but sourced from the five
# event types that move a shareholder's equity (Task 7 / design doc
# 2026-09-15-capital-associe-retrait-design.md, apps.finance.services
# .ShareholderLedgerService):
#   - a ShareholderProfitShare being attributed (credit: it's now theirs)
#   - a ShareholderContribution (credit: capital they put in, still theirs)
#   - a ShareholderWithdrawal (debit: cash paid out, whatever pool - profit
#     or capital - it was allocated against; see
#     ShareholderWithdrawalAllocation)
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

from apps.finance.models import (
    ShareholderContribution,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
)

from apps.reports.queries.statement_common import opening_balance, statement_rows

FIELDS = ["date", "type", "reference", "debit", "credit", "balance"]


class ShareholderStatementQuery:
    FIELDS = FIELDS
    DIRECTION = -1  # credit - debit: a positive balance is what the company owes the shareholder

    @classmethod
    def _entries(cls, shareholder_id) -> list[dict]:
        # Only VALIDATED distributions are a real engagement to the
        # shareholder (2026-09-08 review): a DRAFT is a preview, a
        # CANCELLED one no longer grants a right - neither belongs in the
        # grand livre associe.
        shares = (
            ShareholderProfitShare.objects.filter(shareholder_id=shareholder_id)
            .filter(distribution__status=ShareholderProfitDistribution.Status.VALIDATED)
            .select_related("distribution")
        )
        contributions = ShareholderContribution.objects.filter(shareholder_id=shareholder_id)
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
                    "date": contribution.date,
                    "type": "CONTRIBUTION",
                    "reference": f"APPORT-{contribution.id}",
                    "debit": None,
                    "credit": contribution.amount,
                    "sort_key": (contribution.date, 0, contribution.id),
                }
                for contribution in contributions
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
        return entries

    @classmethod
    def opening_balance(cls, *, shareholder_id, date_from=None, date_to=None):
        return opening_balance(cls._entries(shareholder_id), date_from=date_from, direction=cls.DIRECTION)

    @classmethod
    def run(cls, *, shareholder_id, date_from=None, date_to=None) -> list[dict]:
        return statement_rows(
            cls._entries(shareholder_id), date_from=date_from, date_to=date_to, direction=cls.DIRECTION
        )

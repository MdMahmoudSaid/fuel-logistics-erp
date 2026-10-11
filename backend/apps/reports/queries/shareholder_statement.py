# ShareholderStatementQuery - "Relevé Actionnaire" (UI pass 2026-08-27:
# Reports page must list a report for Actionnaires/Associés).
#
# Mirrors CustomerStatementQuery/SupplierStatementQuery's shape (one
# chronological ledger with a running balance) but sourced from every event
# that moves a shareholder's equity (Task 7 / design doc
# 2026-09-15-capital-associe-retrait-design.md, apps.finance.services
# .ShareholderLedgerService; advances reworked by the client on 2026-10-11):
#   - a ShareholderProfitShare being attributed (credit: it's now theirs)
#   - a ShareholderContribution (credit: capital they put in, still theirs)
#   - a ShareholderWithdrawal (debit: cash paid out, whatever pool - profit,
#     advance or capital - it was allocated against)
#   - an associate advance he gave (LOAN_GIVEN, debit: part of his balance
#     moved to the borrower) or received (LOAN_RECEIVED, credit: he can
#     withdraw it); each repayment moves it back (LOAN_REPAYMENT debit for
#     the borrower, LOAN_REPAYMENT_RECEIVED credit for the lender)
#   - a company advance (COMPANY_ADVANCE, credit): it credits his balance
#     like a profit share; what he takes from it is a WITHDRAWAL line
#   - its settlement: deducted from a profit share (ADVANCE_DEDUCTION,
#     debit - the share is consumed, the debt repaid), cancelled before
#     ever being withdrawn (ADVANCE_CANCELLED, debit), or repaid into
#     treasury from his own pocket (LOAN_REPAYMENT, amount in both columns:
#     the debt is cleared, his balance does not move)
#
# References name the counterpart (associate or treasury account) so the
# statement reads on its own. A loan's repaid amount from before repayment
# history existed (amount_repaid not covered by any ShareholderLoanRepayment
# row) is netted into the loan line itself. With that, the final running
# balance always equals ShareholderLedgerService.get_available_balance() for
# the same shareholder, since both are derived from the same rows/formula.

from decimal import Decimal

from apps.finance.models import (
    ShareholderContribution,
    ShareholderLoan,
    ShareholderLoanRepayment,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
)

from apps.reports.queries.statement_common import opening_balance, statement_rows

FIELDS = ["date", "type", "reference", "debit", "credit", "balance"]
ZERO = Decimal("0.00")
Method = ShareholderLoanRepayment.Method


def _account_name(obj) -> str | None:
    account = obj.bank_account or obj.cash_account
    return account.name if account else None


def _ref(code: str, *details) -> str:
    return " · ".join([code, *[d for d in details if d]])


def _period(distribution) -> str:
    return f"{distribution.period_start} - {distribution.period_end}"


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
        contributions = ShareholderContribution.objects.filter(
            shareholder_id=shareholder_id
        ).select_related("bank_account", "cash_account")
        withdrawals = ShareholderWithdrawal.objects.filter(
            shareholder_id=shareholder_id
        ).select_related("bank_account", "cash_account")
        repayment_prefetch = (
            "repayments__bank_account", "repayments__cash_account",
            "repayments__profit_share__distribution",
        )
        loans_lent = (
            ShareholderLoan.objects.filter(lender_id=shareholder_id)
            .select_related("borrower")
            .prefetch_related(*repayment_prefetch)
        )
        loans_borrowed = (
            ShareholderLoan.objects.filter(borrower_id=shareholder_id)
            .select_related("lender")
            .prefetch_related(*repayment_prefetch)
        )

        def booked_amount(loan) -> Decimal:
            legacy = loan.amount_repaid - sum((r.amount for r in loan.repayments.all()), ZERO)
            return loan.amount - legacy

        def entry(date, kind, reference, debit, credit, order, row_id):
            return {
                "date": date, "type": kind, "reference": reference,
                "debit": debit, "credit": credit, "sort_key": (date, order, row_id),
            }

        entries = []
        for share in shares:
            entries.append(entry(
                share.distribution.period_end, "PROFIT_SHARE",
                f"Distribution {_period(share.distribution)}",
                None, share.amount_due, 0, share.id,
            ))
        for contribution in contributions:
            entries.append(entry(
                contribution.date, "CONTRIBUTION",
                _ref(f"APPORT-{contribution.id}", _account_name(contribution)),
                None, contribution.amount, 0, contribution.id,
            ))
        for withdrawal in withdrawals:
            entries.append(entry(
                withdrawal.date, "WITHDRAWAL",
                _ref(f"WD-{withdrawal.id}", _account_name(withdrawal)),
                withdrawal.amount, None, 1, withdrawal.id,
            ))

        for loan in loans_lent:
            code = f"AV-{loan.id}"
            entries.append(entry(
                loan.date, "LOAN_GIVEN", _ref(code, loan.borrower.name),
                booked_amount(loan), None, 2, loan.id,
            ))
            for r in loan.repayments.all():
                if r.method == Method.DIRECT:
                    entries.append(entry(
                        r.date, "LOAN_REPAYMENT_RECEIVED", _ref(code, loan.borrower.name),
                        None, r.amount, 4, r.id,
                    ))

        for loan in loans_borrowed:
            code = f"AV-{loan.id}"
            if loan.source == ShareholderLoan.Source.COMPANY:
                # Credits his balance, like a profit share.
                entries.append(entry(
                    loan.date, "COMPANY_ADVANCE", code, None, loan.amount, 3, loan.id,
                ))
            else:
                entries.append(entry(
                    loan.date, "LOAN_RECEIVED", _ref(code, loan.lender.name),
                    None, booked_amount(loan), 3, loan.id,
                ))
            for r in loan.repayments.all():
                if r.method == Method.DIRECT:
                    # Given back to the lender: leaves his balance.
                    entries.append(entry(
                        r.date, "LOAN_REPAYMENT", _ref(code, loan.lender.name),
                        r.amount, None, 4, r.id,
                    ))
                elif r.method == Method.TREASURY:
                    # Repaid to the company in cash: clears part of his
                    # debt, his balance does not move.
                    entries.append(entry(
                        r.date, "LOAN_REPAYMENT", _ref(code, _account_name(r)),
                        r.amount, r.amount, 4, r.id,
                    ))
                elif r.method == Method.PROFIT_SHARE:
                    entries.append(entry(
                        r.date, "ADVANCE_DEDUCTION",
                        _ref(code, f"Distribution {_period(r.profit_share.distribution)}"),
                        r.amount, None, 5, r.id,
                    ))
                elif r.method == Method.CANCEL:
                    entries.append(entry(
                        r.date, "ADVANCE_CANCELLED", code, r.amount, None, 5, r.id,
                    ))
        return entries

    @classmethod
    def opening_balance(cls, *, shareholder_id, date_from=None, date_to=None):
        return opening_balance(cls._entries(shareholder_id), date_from=date_from, direction=cls.DIRECTION)

    @classmethod
    def statement_context(cls, *, shareholder_id, date_from=None, date_to=None) -> dict:
        """Opening balance of the period plus the associate's current
        advance position - the same figures as the cards of his Grand
        livre (client request 2026-10-11)."""
        from apps.finance.services import ShareholderLedgerService

        summary = ShareholderLedgerService.get_shareholder_summary(shareholder_id)
        return {
            "opening_balance": cls.opening_balance(
                shareholder_id=shareholder_id, date_from=date_from, date_to=date_to
            ),
            "company_advance_debt": summary["company_advance_debt"],
            "company_advance_undrawn": summary["company_advance_undrawn"],
            "shareholder_loan_debt": summary["shareholder_loan_debt"],
            "shareholder_loan_receivable": summary["shareholder_loan_receivable"],
            "withdrawable_balance": summary["withdrawable_balance"],
        }

    @classmethod
    def run(cls, *, shareholder_id, date_from=None, date_to=None) -> list[dict]:
        return statement_rows(
            cls._entries(shareholder_id), date_from=date_from, date_to=date_to, direction=cls.DIRECTION
        )

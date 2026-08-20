# TreasuryStatementQuery (docs/PHASE_6_PLAN.md Etape 4: "avec exclusion des
# virements internes TRANSFER"; ERP_Implementation_Experience_Guide.md
# Section 8.10/9.7).
#
# The running balance is accumulated over every transaction on the account,
# transfer legs included - that is the account's real balance
# (BankAccount/CashAccount.current_balance sums all of them too, guide
# Section 8.10). Only the *rows shown* skip transfer legs, so the account's
# statement reads as "external money movements" without ever reporting a
# balance that doesn't match reality.

from decimal import Decimal

from django.utils.dateparse import parse_date

from apps.finance.models import BankAccount, CashAccount, TreasuryTransaction


def _as_date(value):
    """Accepts a date, a "YYYY-MM-DD" string, or None, and always returns a
    real date - date_from/date_to arrive as strings from query params but
    txn.date is a date object, and comparing the two raises TypeError."""
    if value is None or not isinstance(value, str):
        return value
    return parse_date(value)

FIELDS = ["date", "type", "amount", "reference", "balance"]


class TreasuryStatementQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, bank_account_id=None, cash_account_id=None, date_from=None, date_to=None) -> list[dict]:
        date_from = _as_date(date_from)
        date_to = _as_date(date_to)
        transactions = TreasuryTransaction.objects.all()
        if bank_account_id:
            transactions = transactions.filter(bank_account_id=bank_account_id)
            balance = BankAccount.objects.get(pk=bank_account_id).opening_balance
        elif cash_account_id:
            transactions = transactions.filter(cash_account_id=cash_account_id)
            balance = CashAccount.objects.get(pk=cash_account_id).opening_balance
        else:
            balance = Decimal("0.00")
        # Walk the account's *entire* transaction history in order, so the
        # running balance is always correct - date_from/date_to only decide
        # which rows are emitted below, exactly like the transfer exclusion,
        # rather than truncating the balance calculation itself.
        transactions = transactions.order_by("date", "id")

        rows = []
        for txn in transactions:
            signed_amount = (
                txn.amount if txn.type == TreasuryTransaction.Type.MONEY_IN else -txn.amount
            )
            balance += signed_amount
            if txn.is_transfer:
                continue
            if date_from and txn.date < date_from:
                continue
            if date_to and txn.date > date_to:
                continue
            rows.append(
                {
                    "date": txn.date,
                    "type": txn.type,
                    "amount": txn.amount,
                    "reference": txn.reference,
                    "balance": balance,
                }
            )
        return rows

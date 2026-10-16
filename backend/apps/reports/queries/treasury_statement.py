# TreasuryStatementQuery (docs/PHASE_6_PLAN.md Etape 4: "avec exclusion des
# virements internes TRANSFER"; ERP_Implementation_Experience_Guide.md
# Section 8.10/9.7).
#
# The running balance is accumulated over every transaction on the account,
# transfer legs included - that is the account's real balance
# (BankAccount/CashAccount.current_balance sums all of them too, guide
# Section 8.10).
#
# Rows carry a `kind` so the summary can tell them apart (2026-10-16):
#   "opening"  - the account's opening balance as the first line (it is a
#                field on the account, not a TreasuryTransaction); never
#                counted in the period totals, the summary already shows it;
#   "transfer" - an internal transfer leg, now listed with the counterpart
#                account; still excluded from profit/expense reporting and
#                reconciled through `transfers_net`;
#   "movement" - every other movement.

OPENING_LABEL = "Solde d'ouverture"

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

FIELDS = ["date", "type", "account", "amount", "reference", "balance"]


class TreasuryStatementQuery:
    FIELDS = FIELDS

    @staticmethod
    def _load(bank_account_id, cash_account_id, scope=None):
        """(transactions ordered by date/id, account opening balance, date the
        account was opened).

        With no account chosen, `scope` ("bank" or "cash", set by the report
        view from the report type) makes the statement cover every account of
        that kind - never the other kind's money."""
        transactions = TreasuryTransaction.objects.all()
        opened_on = None
        if bank_account_id:
            transactions = transactions.filter(bank_account_id=bank_account_id)
            account = BankAccount.objects.get(pk=bank_account_id)
            balance, opened_on = account.opening_balance, account.created_at.date()
        elif cash_account_id:
            transactions = transactions.filter(cash_account_id=cash_account_id)
            account = CashAccount.objects.get(pk=cash_account_id)
            balance, opened_on = account.opening_balance, account.created_at.date()
        elif scope in ("bank", "cash"):
            model = BankAccount if scope == "bank" else CashAccount
            transactions = transactions.filter(**{f"{scope}_account__isnull": False})
            accounts = list(model.objects.all())
            balance = sum((a.opening_balance for a in accounts), Decimal("0.00"))
            opened_on = min((a.created_at.date() for a in accounts), default=None)
        else:
            balance = Decimal("0.00")
        return (
            transactions.select_related("source_content_type", "bank_account", "cash_account")
            .prefetch_related("source_object")
            .order_by("date", "id"),
            balance,
            opened_on,
        )

    @staticmethod
    def _accounts(bank_account_id, cash_account_id, scope):
        """The accounts a statement covers (same rule as _load)."""
        if bank_account_id:
            return list(BankAccount.objects.filter(pk=bank_account_id))
        if cash_account_id:
            return list(CashAccount.objects.filter(pk=cash_account_id))
        if scope == "bank":
            return list(BankAccount.objects.order_by("id"))
        if scope == "cash":
            return list(CashAccount.objects.order_by("id"))
        return []

    @staticmethod
    def _counterparty(txn) -> str:
        from apps.finance.labels import describe_treasury_transaction

        return describe_treasury_transaction(txn)["counterparty"] or ""

    @staticmethod
    def _signed(txn):
        return txn.amount if txn.type == TreasuryTransaction.Type.MONEY_IN else -txn.amount

    @classmethod
    def run(
        cls, *, bank_account_id=None, cash_account_id=None, date_from=None, date_to=None, scope=None
    ) -> list[dict]:
        date_from = _as_date(date_from)
        date_to = _as_date(date_to)
        # Walk the account's *entire* transaction history in order, so the
        # running balance is always correct - date_from/date_to only decide
        # which rows are emitted below, exactly like the transfer exclusion,
        # rather than truncating the balance calculation itself.
        transactions, balance, _opened_on = cls._load(bank_account_id, cash_account_id, scope)

        rows = []
        # One opening line per account (so the Compte column says which bank /
        # cash desk the money started in), each carried forward to date_from.
        opening_by_account = {
            account.pk: [account, account.opening_balance]
            for account in cls._accounts(bank_account_id, cash_account_id, scope)
        }
        for txn in transactions:
            balance += cls._signed(txn)
            if date_from and txn.date < date_from:
                key = (txn.bank_account_id or txn.cash_account_id)
                if key in opening_by_account:
                    opening_by_account[key][1] += cls._signed(txn)
                continue
            if date_to and txn.date > date_to:
                continue
            reference = txn.reference or cls._counterparty(txn)
            if txn.is_transfer:
                # "Transfert A -> B", keeping the typed reference when there is one.
                counterparty = cls._counterparty(txn)
                reference = f"{counterparty} ({txn.reference})" if counterparty and txn.reference else (
                    counterparty or txn.reference
                )
            account = txn.bank_account or txn.cash_account
            rows.append(
                {
                    "date": txn.date,
                    "type": txn.type,
                    # Which bank / cash desk the movement went in or out of
                    # (the statement can cover every account of the kind).
                    "account": account.name,
                    "amount": txn.amount,
                    # No reference typed (e.g. an associate's withdrawal): say
                    # who the money was for instead of leaving it blank.
                    "reference": reference,
                    "balance": balance,
                    "kind": "transfer" if txn.is_transfer else "movement",
                }
            )
        openings = []
        running = Decimal("0.00")
        for account, amount in opening_by_account.values():
            if not amount:
                continue
            running += amount
            openings.append(
                {
                    "date": date_from or account.created_at.date(),
                    "type": (
                        TreasuryTransaction.Type.MONEY_IN
                        if amount > 0
                        else TreasuryTransaction.Type.MONEY_OUT
                    ),
                    "account": account.name,
                    "amount": abs(amount),
                    "reference": OPENING_LABEL,
                    "balance": running,
                    "kind": "opening",
                }
            )
        rows[0:0] = openings
        return rows

    @classmethod
    def statement_context(
        cls, *, bank_account_id=None, cash_account_id=None, date_from=None, date_to=None, scope=None
    ) -> dict:
        """Reconciliation figures for the summary block (spec section
        Internal transfers): opening + period_in - period_out + transfers_net
        = closing. transfers_net is signed (in +, out -) and covers the
        is_transfer legs run() leaves out of the rows. closing_balance is
        tracked independently (running balance up to date_to), so the
        equation is a real check rather than a tautology."""
        date_from = _as_date(date_from)
        date_to = _as_date(date_to)
        transactions, account_opening, _opened_on = cls._load(bank_account_id, cash_account_id, scope)

        zero = Decimal("0.00")
        opening = closing = account_opening
        period_in = period_out = transfers_net = zero
        for txn in transactions:
            signed = cls._signed(txn)
            if date_from and txn.date < date_from:
                opening += signed
            elif not (date_to and txn.date > date_to):
                if txn.is_transfer:
                    transfers_net += signed
                elif signed > 0:
                    period_in += signed
                else:
                    period_out -= signed
            if not (date_to and txn.date > date_to):
                closing += signed
        return {
            "opening_balance": opening,
            "period_in": period_in,
            "period_out": period_out,
            "transfers_net": transfers_net,
            "closing_balance": closing,
        }

# Shared running-balance logic for the customer/supplier/shareholder
# statements (docs/superpowers/specs/2026-09-23-rapports-document-comptable-
# design.md, section Statements). Each query builds ALL of its entries for the
# entity (unfiltered by date); this module partitions them around the period
# so the opening balance and the running balance come from one code path.

from decimal import Decimal

from django.utils.dateparse import parse_date

ZERO = Decimal("0.00")


def coerce_date(value):
    """date_from/date_to arrive as "YYYY-MM-DD" strings (explicit ?from=/&to=)
    or as already-resolved dates (named ranges)."""
    if value is None or not isinstance(value, str):
        return value
    return parse_date(value)


def _signed(entry, direction):
    return direction * ((entry["debit"] or ZERO) - (entry["credit"] or ZERO))


def opening_balance(entries, *, date_from, direction):
    """Signed sum of every entry dated before date_from (0 without date_from).
    direction=+1: debit - credit (customer/supplier); -1: credit - debit."""
    date_from = coerce_date(date_from)
    if not date_from:
        return ZERO
    return sum((_signed(e, direction) for e in entries if e["date"] < date_from), ZERO)


def statement_rows(entries, *, date_from, date_to, direction):
    """Rows of the period with a running balance starting at the opening
    balance. Row shape: date, type, reference, debit, credit, balance."""
    date_from = coerce_date(date_from)
    date_to = coerce_date(date_to)
    balance = opening_balance(entries, date_from=date_from, direction=direction)
    rows = []
    for entry in sorted(entries, key=lambda e: e["sort_key"]):
        if date_from and entry["date"] < date_from:
            continue
        if date_to and entry["date"] > date_to:
            continue
        balance += _signed(entry, direction)
        row = {
            "date": entry["date"],
            "type": entry["type"],
            "reference": entry["reference"],
            "debit": entry["debit"],
            "credit": entry["credit"],
            "balance": balance,
        }
        if "party" in entry:  # all-parties statement: who the line belongs to
            row["party"] = entry["party"]
        rows.append(row)
    return rows


def entries_of(query_class, party_id, parties) -> list[dict]:
    """The statement entries of one party, or - when no party is picked - of
    every party in `parties` ((id, name) pairs), each tagged with its name:
    the statement then covers the whole book (running balance = total owed)."""
    if party_id not in (None, ""):
        return query_class._entries(party_id)
    return [
        {**entry, "party": name}
        for pk, name in parties
        for entry in query_class._entries(pk)
    ]

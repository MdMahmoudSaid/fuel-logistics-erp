"""The dashboard assembles many indicators that share sub-computations
(working capital, profit preview, margin report, account balances...).
While one GET is served, each of them must hit the database once - an
identical query (same SQL, same parameters) repeated is wasted time."""

import collections
from decimal import Decimal

import pytest
from django.db import connection

from apps.core.test_list_query_counts import _fee, _sold_trip, setup  # noqa: F401
from apps.finance.models import BankAccount, CashAccount, Expense


@pytest.mark.django_db
# The dashboard still re-reads a few small lists (accounts, suppliers,
# shareholders...) from two code paths - one cheap query each, measured at
# 14 on 2026-10-05 (from ~80 before the per-request cache). The budget
# blocks any regression; computations repeated per trip/customer are gone.
@pytest.mark.parametrize(
    "path,allowed",
    [
        ("/api/dashboard/summary/?preset=period", 14),
        ("/api/dashboard/summary/", 14),
        ("/api/shareholders/profit-preview/?preset=period", 3),
        ("/api/shareholder-periods/", 3),
    ],
)
def test_page_never_repeats_an_identical_query(setup, path, allowed):
    fx, client = setup
    BankAccount.objects.create(name="Banque QC", opening_balance=Decimal("1000.00"))
    CashAccount.objects.create(name="Caisse QC")
    for n in range(1, 4):
        _fee(_sold_trip(fx, n), Expense.Category.CUSTOMS, Decimal("1000.00"))
    seen = collections.Counter()

    def wrapper(execute, sql, params, many, context):
        seen[(sql, repr(params))] += 1
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        assert client.get(path).status_code == 200

    repeated = {key[0][:60]: n for key, n in seen.items() if n > 1}
    extra = sum(n - 1 for n in repeated.values())
    assert extra <= allowed, (extra, sorted(repeated.items()))

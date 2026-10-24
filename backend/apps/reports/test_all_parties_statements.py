# A statement/history with no entity picked covers every party (client
# request 2026-10-24) instead of failing with "customer_id manquant".

import pytest

from apps.customers.models import Customer
from apps.finance.models import OpeningDebt
from apps.reports.queries.customer_statement import CustomerStatementQuery
from apps.reports.queries.truck_history import TruckHistoryQuery
from apps.reports.services.report_document import build_report_document
from datetime import date

from apps.reports.test_queries import _make_admin


@pytest.mark.django_db
def test_customer_statement_without_customer_lists_every_customer_with_one_running_balance():
    admin = _make_admin("x")
    a = Customer.objects.create(name="Alpha")
    b = Customer.objects.create(name="Beta")
    OpeningDebt.objects.create(customer=a, amount=100, date=date(2026, 9, 1), reference="A", recorded_by=admin)
    OpeningDebt.objects.create(customer=b, amount=50, date=date(2026, 9, 2), reference="B", recorded_by=admin)

    rows = CustomerStatementQuery.run()

    assert [(r["party"], r["balance"]) for r in rows] == [("Alpha", 100), ("Beta", 150)]
    assert CustomerStatementQuery.run(customer_id=a.id)[0].get("party") is None


@pytest.mark.django_db
def test_document_adds_the_party_column_only_for_an_all_parties_statement():
    admin = _make_admin("x")
    a = Customer.objects.create(name="Alpha")
    OpeningDebt.objects.create(customer=a, amount=100, date=date(2026, 9, 1), reference="A", recorded_by=admin)

    wide = build_report_document("customer-statement", CustomerStatementQuery.run(), {}, "fr")
    single = build_report_document(
        "customer-statement", CustomerStatementQuery.run(customer_id=a.id), {"customer_id": a.id}, "fr"
    )

    assert [c["field"] for c in wide["tables"][0]["columns"]][:2] == ["date", "party"]
    assert "party" not in [c["field"] for c in single["tables"][0]["columns"]]


@pytest.mark.django_db
def test_truck_history_without_truck_does_not_fail():
    assert TruckHistoryQuery.run() == []

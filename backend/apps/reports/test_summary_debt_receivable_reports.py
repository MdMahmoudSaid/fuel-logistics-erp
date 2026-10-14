# "Ce que nous devons" / "Ce qui nous est dû": one line per party, as of today
# (client request 2026-10-14). Every amount must tie to the services behind the
# payment screens; shareholder money never appears.

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.customers.models import Customer
from apps.finance.models import (
    CashAccount, CustomerPayment, OpeningDebt, SupplierAdvance, TransporterAdvance,
)
from apps.finance.services import ControlledDebtPaymentService as Debts
from apps.finance.services import PaymentAllocationService
from apps.reports.queries.debts_summary_report import DebtsSummaryReportQuery
from apps.reports.queries.receivables_summary_report import ReceivablesSummaryReportQuery
from apps.reports.services.report_document import build_report_document
from apps.reports.test_debt_receivable_reports import _fee, _invoice
from apps.reports.test_queries import _make_admin, _make_full_trip
from apps.reports.test_report_pdf import pdf_pages
from apps.reports.services.report_pdf import render_report_pdf
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter

D = Decimal
TODAY = date(2026, 10, 14)


def _document(slug, rows, lang="fr"):
    return build_report_document(slug, rows, {}, lang, generated_on=TODAY)


def _summary(document):
    return {line["key"]: line["value"] for line in document["summary"]}


def _opening(admin, amount, **party):
    return OpeningDebt.objects.create(amount=D(amount), date="2026-09-30", recorded_by=admin, **party)


def _payment(customer, amount, admin):
    return CustomerPayment.objects.create(
        customer=customer, amount=D(amount), payment_date="2026-10-01", method=CustomerPayment.Method.CASH,
        cash_account=CashAccount.objects.get_or_create(name="Caisse resume")[0], recorded_by=admin,
    )


@pytest.mark.django_db
def test_debts_one_line_per_supplier_transporter_and_fee_bucket_tied_to_the_payment_screens():
    admin = _make_admin("DSUM1")
    sahel = Supplier.objects.create(name="SAHEL", country="Mauritanie")
    carrier = Transporter.objects.create(name="Transporteur Un")
    _opening(admin, "31500000.00", supplier=sahel)
    _opening(admin, "4000000.00", supplier=sahel)  # two debts, still ONE line
    _opening(admin, "700000.00", transporter=carrier)
    _fee("customs", amount="900000.00")

    rows = DebtsSummaryReportQuery.run()

    assert rows == [
        {"party_type": "supplier", "party": "SAHEL", "amount": D("35500000.00")},
        {"party_type": "transporter", "party": "Transporteur Un", "amount": D("700000.00")},
        {"party_type": "fee_customs", "party": None, "amount": D("900000.00")},
    ]
    assert rows[0]["amount"] == Debts.describe_supplier(sahel)["remaining_amount"]
    summary = _summary(_document("debts-summary-report", rows))
    assert summary["total_we_owe"] == D("37100000.00") and summary["debt_parties_count"] == 3


@pytest.mark.django_db
def test_debts_are_net_of_a_consumed_advance_and_exclude_a_fully_covered_supplier():
    admin = _make_admin("DSUM2")
    covered = Supplier.objects.create(name="Couvert", country="Mauritanie")
    partly = Supplier.objects.create(name="Partiel", country="Mauritanie")
    cash = CashAccount.objects.create(name="Caisse avances")
    SupplierAdvance.objects.create(supplier=covered, amount=D("5000000.00"), date="2026-09-01",
                                   cash_account=cash, recorded_by=admin)
    SupplierAdvance.objects.create(supplier=partly, amount=D("1000000.00"), date="2026-09-01",
                                   cash_account=cash, recorded_by=admin)
    from apps.finance.services import AdvanceConsumptionService

    for supplier, amount in ((covered, "2000000.00"), (partly, "3000000.00")):
        debt = _opening(admin, amount, supplier=supplier)
        AdvanceConsumptionService.consume_for_opening_debt(debt)

    rows = DebtsSummaryReportQuery.run()

    assert rows == [{"party_type": "supplier", "party": "Partiel", "amount": D("2000000.00")}]


@pytest.mark.django_db
def test_a_customer_who_paid_ahead_is_a_debt_and_never_a_receivable():
    admin = _make_admin("DSUM3")
    lone = Customer.objects.create(name="Client avance")
    _payment(lone, "250000.00", admin)

    assert DebtsSummaryReportQuery.run() == [
        {"party_type": "customer_credit", "party": "Client avance", "amount": D("250000.00")}
    ]
    assert ReceivablesSummaryReportQuery.run() == []


@pytest.mark.django_db
def test_receivables_customers_plus_unconsumed_supplier_and_transporter_advances():
    admin = _make_admin("RSUM1")
    fx = _make_full_trip("RSUM1", admin)
    _invoice(fx, total="1000000.00")
    _payment(fx["customer"], "400000.00", admin)
    owed_by_opening = Customer.objects.create(name="Ancien client")
    _opening(admin, "250000.00", customer=owed_by_opening)
    supplier = Supplier.objects.create(name="Fourn avance", country="Mauritanie")
    carrier = Transporter.objects.create(name="Transp avance")
    cash = CashAccount.objects.create(name="Caisse avances 2")
    SupplierAdvance.objects.create(supplier=supplier, amount=D("800000.00"), date="2026-09-01",
                                   cash_account=cash, recorded_by=admin)
    TransporterAdvance.objects.create(transporter=carrier, amount=D("300000.00"), date="2026-09-01",
                                      cash_account=cash, recorded_by=admin)

    rows = ReceivablesSummaryReportQuery.run()

    assert {(r["party_type"], r["party"]): r["amount"] for r in rows} == {
        ("customer", fx["customer"].name): PaymentAllocationService.get_customer_outstanding(fx["customer"]),
        ("customer", "Ancien client"): D("250000.00"),
        ("supplier_advance", "Fourn avance"): D("800000.00"),
        ("transporter_advance", "Transp avance"): D("300000.00"),
    }
    assert PaymentAllocationService.get_customer_outstanding(fx["customer"]) == D("600000.00")
    assert _summary(_document("receivables-summary-report", rows))["total_owed_to_us"] == D("1950000.00")


@pytest.mark.django_db
def test_supplier_advance_already_consumed_by_a_debt_is_not_counted_twice():
    admin = _make_admin("RSUM2")
    supplier = Supplier.objects.create(name="Fourn consomme", country="Mauritanie")
    SupplierAdvance.objects.create(supplier=supplier, amount=D("1000000.00"), date="2026-09-01",
                                   cash_account=CashAccount.objects.create(name="Caisse c"), recorded_by=admin)
    from apps.finance.services import AdvanceConsumptionService

    AdvanceConsumptionService.consume_for_opening_debt(_opening(admin, "1000000.00", supplier=supplier))

    assert ReceivablesSummaryReportQuery.run() == []
    assert DebtsSummaryReportQuery.run() == []


@pytest.mark.django_db
@pytest.mark.parametrize("lang,debt_title,recv_title", [
    ("fr", "Ce que nous devons (dettes)", "Ce qui nous est dû (créances)"),
    ("en", "What we owe (debts)", "What is owed to us (receivables)"),
    ("ar", "الديون التي علينا (ما علينا للغير)", "الديون التي لنا (ما لنا عند الغير)"),
])
def test_titles_are_explicit_in_each_language(lang, debt_title, recv_title):
    assert _document("debts-summary-report", [], lang)["title"] == debt_title
    assert _document("receivables-summary-report", [], lang)["title"] == recv_title


@pytest.mark.django_db
def test_endpoint_document_and_pdf_work_and_period_is_as_of():
    admin = _make_admin("RSUM3")
    _opening(admin, "31500000.00", supplier=Supplier.objects.create(name="SAHEL", country="Mauritanie"))
    client = APIClient()
    client.force_authenticate(admin)

    for slug in ("debts-summary-report", "receivables-summary-report"):
        payload = client.get(f"/api/reports/{slug}/?document=1&lang=ar").json()
        assert set(payload) == {"report_type", "fields", "rows", "document"}
        assert payload["fields"] == ["party_type", "party", "amount"]
        assert payload["document"]["period"]["mode"] == "as_of"
        pdf = client.get(f"/api/reports/{slug}/?export=pdf&lang=fr")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    rows = client.get("/api/reports/debts-summary-report/").json()["rows"]
    assert rows == [{"party_type": "supplier", "party": "SAHEL", "amount": "31500000.00"}]
    _, pages = pdf_pages(render_report_pdf(_document("debts-summary-report", DebtsSummaryReportQuery.run()),
                                           DebtsSummaryReportQuery.run(), "fr"))
    assert "SAHEL" in pages[0] and "31 500 000" in pages[0]

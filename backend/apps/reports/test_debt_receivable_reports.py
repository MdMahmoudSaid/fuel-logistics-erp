# Trip-fee debt, general debt and general receivable reports (docs/superpowers/
# specs/2026-09-23-rapports-capital-dettes-creances-design.md, sections 3-5):
# every amount must tie to the services behind the payment screens.

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from apps.finance.models import (
    CashAccount,
    Expense,
    ExpenseAllocation,
    SupplierPayment,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import ControlledDebtPaymentService as Debts
from apps.finance.services import WorkingCapitalService
from apps.reports.queries.general_debt_report import GeneralDebtReportQuery
from apps.reports.queries.trip_fee_debt_report import TripFeeDebtReportQuery
from apps.reports.services.report_document import build_report_document
from apps.reports.test_queries import _make_admin, _make_full_trip
from apps.reports.test_report_pdf import pdf_pages

D = Decimal
TODAY = date(2026, 9, 23)
FEE_TYPES = ["customs", "transit", "road_transit", "border", "loading"]
CATEGORY = {"customs": "customs", "transit": "transit", "road_transit": "road_transit",
            "border": "road", "loading": "loading"}


def _client(suffix):
    client = APIClient()
    client.force_authenticate(_make_admin(suffix))
    return client


def _document(slug, rows, params=None, lang="fr"):
    return build_report_document(slug, rows, params or {}, lang, generated_on=TODAY)


def _summary(document):
    return {line["key"]: line["value"] for line in document["summary"]}


def _fee(debt_type, amount="1000000.00", trip=None, **extra):
    expense = Expense.objects.create(
        category=CATEGORY[debt_type], amount=D(amount), calculation_method="MANUAL",
        date=extra.pop("day", date(2026, 9, 1)), **extra,
    )
    if trip is not None:
        ExpenseAllocation.objects.create(
            expense=expense, content_type=ContentType.objects.get_for_model(trip),
            object_id=trip.id, allocated_amount=D(amount),
        )
    return expense


def _pay_fee(expense, amount):
    from apps.accounts.models import User

    actor = User.objects.filter(phone="+222DEBTPAY").first() or _make_admin("DEBTPAY")
    return TreasuryTransaction.objects.create(
        recorded_by=actor, cash_account=CashAccount.objects.get_or_create(name="Caisse dettes")[0],
        type=TreasuryTransaction.Type.MONEY_OUT, amount=D(amount), date=date(2026, 9, 2),
        source_content_type=ContentType.objects.get_for_model(Expense), source_object_id=expense.id,
    )


def _all_fee_debts():
    fx = _make_full_trip("DEBTFEE", _make_admin("DEBTFEE"))
    for index, debt_type in enumerate(FEE_TYPES, start=1):
        _fee(debt_type, amount=f"{index}000000.00", trip=fx["trip"])
    return fx


# ---------------------------------------------------------------------------
# Trip-fee debts
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("fee_type", FEE_TYPES)
def test_each_fee_type_lists_only_its_own_open_debts(fee_type):
    fx = _all_fee_debts()

    rows = TripFeeDebtReportQuery.run(fee_type=fee_type)
    lines = [r for r in rows if r["section"] == "line"]

    assert {r["fee_type"] for r in lines} == {fee_type}
    line = Debts.get_payable_debts(fee_type)[0]["lines"][0]
    assert (lines[0]["total_amount"], lines[0]["remaining_amount"]) == (line["total_amount"], line["remaining_amount"])
    assert lines[0]["trips"] == fx["trip"].reference
    document = _document("trip-fee-debt-report", rows, {"fee_type": fee_type})
    assert document["entity"]["label"] == "Type de frais"
    assert document["period"]["mode"] == "as_of"


@pytest.mark.django_db
@pytest.mark.parametrize("fee_type", ["all", "", None])
def test_all_types_total_matches_the_payment_screens_and_the_dashboard_breakdown(fee_type):
    _all_fee_debts()

    rows = TripFeeDebtReportQuery.run(fee_type=fee_type)
    document = _document("trip-fee-debt-report", rows, {"fee_type": fee_type or ""})
    breakdown = WorkingCapitalService.get_other_debts_breakdown()
    screen_total = sum(Debts.get_payable_debts(t)[0]["remaining_amount"] for t in FEE_TYPES)

    assert _summary(document)["remaining_total"] == screen_total
    assert screen_total == sum(breakdown.values())
    assert document["entity"]["name"] == "Tous"
    recap = {r["fee_type"]: r for r in rows if r["section"] == "type_total"}
    assert set(recap) == set(FEE_TYPES)
    assert recap["customs"]["remaining_amount"] == D("1000000.00") and recap["customs"]["count"] == 1


@pytest.mark.django_db
def test_partially_paid_fee_shows_paid_and_remaining_and_settled_or_customer_paid_fees_are_absent():
    partial = _fee("customs", amount="1000000.00")
    _pay_fee(partial, "400000.00")
    settled = _fee("transit", amount="500000.00", status=Expense.Status.PAID)
    _pay_fee(settled, "500000.00")
    _fee("loading", amount="300000.00", status=Expense.Status.PAID, paid_by_customer_directly=True)

    rows = [r for r in TripFeeDebtReportQuery.run() if r["section"] == "line"]

    assert [(r["fee_type"], r["paid_amount"], r["remaining_amount"]) for r in rows] == [
        ("customs", D("400000.00"), D("600000.00"))
    ]


@pytest.mark.django_db
def test_unknown_fee_type_is_rejected_and_the_endpoint_answers_400():
    with pytest.raises(ValueError):
        TripFeeDebtReportQuery.run(fee_type="rent")

    client = _client("FEE400")

    assert client.get("/api/reports/trip-fee-debt-report/", {"fee_type": "rent"}).status_code == 400
    assert client.get("/api/reports/trip-fee-debt-report/", {"fee_type": ""}).status_code == 200


@pytest.mark.django_db
def test_fee_debt_period_params_are_ignored_and_empty_report_renders():
    plain = TripFeeDebtReportQuery.run()
    assert TripFeeDebtReportQuery.run(date_from=date(2026, 1, 1), date_to=date(2026, 1, 2)) == plain == []

    client = _client("FEEEMPTY")
    text = " ".join(
        "\n".join(pdf_pages(client.get("/api/reports/trip-fee-debt-report/", {"export": "pdf"}).content)[1]).split()
    )
    assert "Dettes de frais de trajet" in text and "Aucune donnée" in text and "Type de frais Tous" in text


@pytest.mark.django_db
def test_fee_debt_endpoint_exports_pdf_in_french_and_arabic_and_keeps_fields_business_only():
    _all_fee_debts()
    client = _client("FEEPDF")

    french = client.get("/api/reports/trip-fee-debt-report/", {"export": "pdf", "fee_type": "customs"})
    arabic = client.get("/api/reports/trip-fee-debt-report/", {"export": "pdf", "lang": "ar"})
    payload = client.get("/api/reports/trip-fee-debt-report/", {"fee_type": "customs"}).json()

    assert french.status_code == arabic.status_code == 200
    assert "Douane" in "\n".join(pdf_pages(french.content)[1])
    assert "section" not in payload["fields"] and payload["rows"][0]["section"] == "line"


# ---------------------------------------------------------------------------
# General debts
# ---------------------------------------------------------------------------


def _transport_payment(fx, trip=None, base="1500000.00", **extra):
    return TransportPayment.objects.create(
        trip=trip or fx["trip"], transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.NEGOTIATED,
        base_amount=D(base), status=TransportPayment.Status.PAYABLE, **extra,
    )


def _supplier_payment(fx, amount, **extra):
    return SupplierPayment.objects.create(
        supplier=fx["supplier"], supplier_order=fx["supplier_order"], amount=D(amount),
        payment_date=date(2026, 9, 2), method="BANK_TRANSFER",
        cash_account=CashAccount.objects.get_or_create(name="Caisse fournisseurs")[0],
        recorded_by=fx["admin_user"], **extra,
    )


def _family(rows, section):
    return [r for r in rows if r["section"] == section]


@pytest.mark.django_db
def test_general_debts_subtotals_equal_the_payment_screen_and_dashboard_figures():
    fx = _make_full_trip("GDEBT", _make_admin("GDEBT"))
    _supplier_payment(fx, "100000000.00")
    _transport_payment(fx)
    for debt_type in FEE_TYPES:
        _fee(debt_type, amount="750000.00", trip=fx["trip"])

    rows = GeneralDebtReportQuery.run()
    summary = _summary(_document("general-debt-report", rows))
    supplier_total = sum(g["remaining_amount"] for g in Debts.get_payable_debts(Debts.SUPPLIER))
    transporter_total = sum(g["remaining_amount"] for g in Debts.get_payable_debts(Debts.TRANSPORTER))
    fee_total = sum(WorkingCapitalService.get_other_debts_breakdown().values())

    assert summary["suppliers_debt_subtotal"] == supplier_total == D("200000000.00")
    assert summary["transporters_debt_subtotal"] == transporter_total == D("1500000.00")
    assert summary["trip_fees_debt_subtotal"] == fee_total == D("3750000.00")
    assert summary["total_debts"] == supplier_total + transporter_total + fee_total
    assert (summary["supplier_lines_count"], summary["transporter_lines_count"], summary["trip_fee_lines_count"]) == (1, 1, 5)
    supplier_line = _family(rows, "supplier")[0]
    assert supplier_line["reference"] == fx["supplier_order"].reference and supplier_line["status"] == "PARTIALLY_PAID"
    assert _family(rows, "transporter")[0]["trip_reference"] == fx["trip"].reference


@pytest.mark.django_db
def test_reversed_supplier_payment_restores_the_debt_and_advances_are_netted_by_the_service():
    fx = _make_full_trip("GDEBTREV", _make_admin("GDEBTREV"))
    _supplier_payment(fx, "50000000.00", is_reversed=True)

    line = _family(GeneralDebtReportQuery.run(), "supplier")[0]

    assert (line["paid_amount"], line["remaining_amount"]) == (D("0.00"), D("300000000.00"))


@pytest.mark.django_db
def test_consumed_supplier_advance_counts_as_paid_on_the_order_line():
    from apps.finance.models import SupplierAdvance
    from apps.core.models import Product
    from apps.purchasing.models import SupplierOrder
    from apps.suppliers.models import Supplier

    admin = _make_admin("GDEBTADV")
    supplier = Supplier.objects.create(name="Fournisseur avance", country="Senegal")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=D("2000000.00"), date="2026-08-17",
        cash_account=CashAccount.objects.create(name="Caisse avance"), recorded_by=admin,
    )
    order = SupplierOrder.objects.create(
        reference="SO-GDEBTADV", supplier=supplier, product=Product.objects.get(code="gasoil"),
        purchase_date="2026-08-18", quantity_litres=D("500000.00"), unit_price=D("600.0000"),
        status=SupplierOrder.Status.CONFIRMED, created_by=admin,
    )

    line = _family(GeneralDebtReportQuery.run(), "supplier")[0]

    assert line["reference"] == order.reference
    assert (line["paid_amount"], line["remaining_amount"]) == (D("2000000.00"), order.total_amount - D("2000000.00"))
    assert line["status"] == "PARTIALLY_PAID"


@pytest.mark.django_db
def test_negative_transporter_line_keeps_its_sign_and_a_non_positive_transporter_is_absent():
    fx = _make_full_trip("GDEBTNEG", _make_admin("GDEBTNEG"))
    other = _make_full_trip("GDEBTNEG2", _make_admin("GDEBTNEG2"))
    _transport_payment(fx, base="1500000.00")
    _transport_payment(fx, trip=other["trip"], base="100000.00", deduction_amount=D("300000.00"))
    lonely = _make_full_trip("GDEBTNEG3", _make_admin("GDEBTNEG3"))
    _transport_payment(lonely, base="100000.00", deduction_amount=D("500000.00"))

    lines = _family(GeneralDebtReportQuery.run(), "transporter")
    summary = _summary(_document("general-debt-report", GeneralDebtReportQuery.run()))

    assert sorted(r["remaining_amount"] for r in lines) == [D("-200000.00"), D("1500000.00")]
    assert {r["transporter"] for r in lines} == {fx["transporter"].name}  # lonely transporter (<= 0) is absent
    assert summary["transporters_debt_subtotal"] == sum(
        g["remaining_amount"] for g in Debts.get_payable_debts(Debts.TRANSPORTER)
    ) == D("1300000.00")


@pytest.mark.django_db
def test_general_debt_empty_report_period_params_and_export_shape():
    assert GeneralDebtReportQuery.run(date_from=date(2026, 1, 1), date_to=date(2026, 2, 1)) == []
    summary = _summary(_document("general-debt-report", []))
    assert summary["total_debts"] == D("0.00")

    fx = _make_full_trip("GDEBTPDF", _make_admin("GDEBTPDF"))
    _transport_payment(fx)
    client = _client("GDEBTPDF2")
    payload = client.get("/api/reports/general-debt-report/", {"document": "1", "from": "2026-01-01", "to": "2026-01-31"}).json()
    pdf = client.get("/api/reports/general-debt-report/", {"export": "pdf", "lang": "ar"})

    assert [t["section"] for t in payload["document"]["tables"]] == ["supplier", "transporter", "trip_fee"]
    assert payload["document"]["period"]["mode"] == "as_of"
    assert "section" not in payload["fields"] and pdf.status_code == 200

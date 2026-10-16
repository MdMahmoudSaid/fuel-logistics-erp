# Report document builder tests (docs/superpowers/specs/2026-09-23-rapports-
# document-comptable-design.md, sections Per-report definitions, Statements,
# D7): header/meta, totals per report family, opening/closing equations,
# cancelled exclusion, empty reports and the label catalog.

import re
from datetime import date
from decimal import Decimal

import pytest

from apps.finance.models import (
    BankAccount,
    CashAccount,
    Expense,
    Shareholder,
    TreasuryTransaction,
)
from apps.purchasing.models import SupplierOrder
from apps.reports.services.report_document import (
    REPORT_SPECS,
    build_report_document,
)
from apps.reports.services.report_labels import LABELS
from apps.reports.test_queries import _make_admin, _make_full_trip
from apps.reports.views.reports import REPORT_REGISTRY
from apps.trips.models import Trip

D = Decimal
ARABIC = re.compile("[؀-ۿ]")
TODAY = date(2026, 9, 23)

LANDSCAPE = {
    "trip-report", "purchase-report", "sales-report", "loss-report", "margin-report",
    "general-expense-report", "trip-fee-debt-report", "general-debt-report",
    "general-receivable-report",
}
ENTITY_PARAM = {
    "customer-statement": "customer_id",
    "supplier-statement": "supplier_id",
    "transporter-statement": "transporter_id",
    "truck-history": "truck_id",
    "bank-statement": "bank_account_id",
    "cash-statement": "cash_account_id",
    "shareholder-statement": "shareholder_id",
}
AS_OF = {"customer-outstanding", "supplier-outstanding", "transporter-outstanding", "fuel-stock"}


def build(slug, rows=None, params=None, lang="fr", **kwargs):
    return build_report_document(
        slug, rows or [], params or {}, lang, generated_on=TODAY, **kwargs
    )


def summary(document):
    return {line["key"]: line for line in document["summary"]}


def all_fields(document):
    return [column["field"] for table in document["tables"] for column in table["columns"]]


# ---------------------------------------------------------------------------
# Header / meta
# ---------------------------------------------------------------------------


def test_registry_and_specs_cover_the_same_reports():
    # The 22-slug cross-check with the frontend selector lives in
    # test_report_slug_completeness.py.
    assert set(REPORT_SPECS) == set(REPORT_REGISTRY)


@pytest.mark.parametrize("slug", sorted(REPORT_REGISTRY))
def test_header_fields_for_every_report_in_french(slug):
    document = build(slug, params={"date_from": "2026-09-01", "date_to": "2026-09-23"})

    assert document["title"] and document["title"] != slug
    assert document["company"]["name"] == "AZUR ÉNERGIE"
    assert document["generated_on"] == "2026-09-23"
    assert document["currency"] == "XOF"
    assert document["lang"] == "fr" and document["direction"] == "ltr"
    assert document["orientation"] == ("landscape" if slug in LANDSCAPE else "portrait")
    assert document["empty_text"] == "Aucune donnée pour la période sélectionnée."
    labels = [c["label"] for t in document["tables"] for c in t["columns"]]
    assert labels and all(label and "_" not in label for label in labels)
    info = {item["key"]: item["value"] for item in document["info"]}
    assert info["generated_on"] == "23/09/2026"
    assert info["currency"] == "XOF"


@pytest.mark.parametrize("slug", sorted(REPORT_REGISTRY))
def test_every_report_builds_in_arabic_english_and_unknown_language(slug):
    arabic = build(slug, lang="ar")
    english = build(slug, lang="en")
    fallback = build(slug, lang="xx")

    assert arabic["direction"] == "rtl" and ARABIC.search(arabic["title"])
    assert ARABIC.search(arabic["empty_text"])
    assert english["direction"] == "ltr" and not ARABIC.search(english["title"])
    assert fallback["lang"] == "fr" and fallback["title"] == build(slug)["title"]
    for document in (arabic, english):
        assert all("_" not in c["label"] for t in document["tables"] for c in t["columns"])


def test_period_modes():
    ranged = build("expense-report", params={"date_from": "2026-09-01", "date_to": "2026-09-23"})
    assert ranged["period"] == {"mode": "range", "from": "2026-09-01", "to": "2026-09-23",
                                "text": "Du 01/09/2026 au 23/09/2026"}
    from_only = build("expense-report", params={"date_from": date(2026, 9, 1)})
    assert from_only["period"]["text"] == "À partir du 01/09/2026"
    to_only = build("expense-report", params={"date_to": "2026-09-23"})
    assert to_only["period"]["text"] == "Jusqu'au 23/09/2026"
    open_period = build("expense-report")
    assert open_period["period"]["mode"] == "open" and open_period["period"]["text"] == "Toutes périodes"
    for slug in AS_OF:
        as_of = build(slug, params={"date_from": "2026-09-01"})
        assert as_of["period"]["mode"] == "as_of"
        assert as_of["period"]["text"] == "Situation au 23/09/2026"


# ---------------------------------------------------------------------------
# Entity names
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_entity_name_for_the_seven_entity_reports_and_optional_filters():
    fx = _make_full_trip("DOCENT", _make_admin("DOCENT"))
    bank = BankAccount.objects.create(name="Bank DOCENT", opening_balance=D("0"))
    cash = CashAccount.objects.create(name="Cash DOCENT")
    shareholder = Shareholder.objects.create(name="Assoc DOCENT", participation_percent=D("100"))
    ids = {
        "customer_id": fx["customer"].id,
        "supplier_id": fx["supplier"].id,
        "transporter_id": fx["transporter"].id,
        "truck_id": fx["truck"].id,
        "bank_account_id": bank.id,
        "cash_account_id": cash.id,
        "shareholder_id": shareholder.id,
    }
    expected = {
        "customer-statement": ("Client", fx["customer"].name),
        "supplier-statement": ("Fournisseur", fx["supplier"].name),
        "transporter-statement": ("Transporteur", fx["transporter"].name),
        "truck-history": ("Camion", fx["truck"].internal_id),
        "bank-statement": ("Compte bancaire", "Bank DOCENT"),
        "cash-statement": ("Caisse", "Cash DOCENT"),
        "shareholder-statement": ("Associé", "Assoc DOCENT"),
    }
    for slug, (label, name) in expected.items():
        document = build(slug, params={ENTITY_PARAM[slug]: ids[ENTITY_PARAM[slug]]})
        assert document["entity"]["label"] == label
        assert name in document["entity"]["name"]
        assert any(item["key"] == "entity" and name in item["value"] for item in document["info"])
    assert fx["truck"].tractor_registration in build(
        "truck-history", params={"truck_id": ids["truck_id"]}
    )["entity"]["name"]

    purchases = build("purchase-report", params={"supplier_id": ids["supplier_id"]})
    assert purchases["entity"] == {"label": "Fournisseur", "name": fx["supplier"].name}
    sales = build("sales-report", params={"customer_id": ids["customer_id"]})
    assert sales["entity"] == {"label": "Client", "name": fx["customer"].name}
    assert build("purchase-report")["entity"] is None and build("expense-report")["entity"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("bad_id", ["999999", "abc", "", None])
def test_unknown_or_malformed_entity_id_never_raises(bad_id):
    document = build("customer-statement", params={"customer_id": bad_id})

    assert document["entity"] is None or document["entity"]["name"] in (None, "")


# ---------------------------------------------------------------------------
# Statements: opening balance, totals, equation
# ---------------------------------------------------------------------------

STATEMENT_ROWS = [
    {"date": date(2026, 9, 2), "type": "INVOICE", "reference": "F1", "debit": D("1000.00"),
     "credit": None, "balance": D("1500.00")},
    {"date": date(2026, 9, 3), "type": "PAYMENT", "reference": "P1", "debit": None,
     "credit": D("300.00"), "balance": D("1200.00")},
]


def test_customer_statement_summary_and_opening_row():
    document = build("customer-statement", STATEMENT_ROWS, statement_context={"opening_balance": D("500.00")})
    lines = summary(document)

    assert document["opening_balance"] == {"label": "Solde antérieur", "value": D("500.00"), "column": "balance"}
    assert [line["key"] for line in document["summary"]] == [
        "opening_balance", "total_debit", "total_credit", "net_movement", "closing_balance",
    ]
    assert lines["total_debit"]["value"] == D("1000.00")
    assert lines["total_credit"]["value"] == D("300.00")
    assert lines["net_movement"]["value"] == D("700.00")
    assert lines["closing_balance"]["value"] == D("1200.00") and lines["closing_balance"]["emphasis"]
    assert "reconciliation_gap" not in lines
    types = {c["field"]: c for c in document["tables"][0]["columns"]}["type"]
    assert types["kind"] == "enum" and types["enum_labels"]["INVOICE"] == "Facture"


def test_shareholder_statement_uses_credit_minus_debit():
    rows = [
        {"date": date(2026, 9, 2), "type": "CONTRIBUTION", "reference": "A1", "debit": None,
         "credit": D("800.00"), "balance": D("1000.00")},
        {"date": date(2026, 9, 3), "type": "WITHDRAWAL", "reference": "W1", "debit": D("300.00"),
         "credit": None, "balance": D("700.00")},
    ]
    lines = summary(build("shareholder-statement", rows, statement_context={"opening_balance": D("200.00")}))

    assert lines["net_movement"]["value"] == D("500.00")
    assert lines["closing_balance"]["value"] == D("700.00")
    assert "reconciliation_gap" not in lines


def test_statement_with_empty_period_keeps_a_nonzero_opening_balance():
    document = build("supplier-statement", [], statement_context={"opening_balance": D("42.00")})
    lines = summary(document)

    assert document["opening_balance"]["value"] == D("42.00")
    assert lines["opening_balance"]["value"] == lines["closing_balance"]["value"] == D("42.00")
    assert lines["total_debit"]["value"] == lines["total_credit"]["value"] == D("0")
    assert document["empty_text"]


def test_statement_gap_line_appears_only_when_rows_do_not_add_up():
    lines = summary(build("customer-statement", STATEMENT_ROWS, statement_context={"opening_balance": D("0.00")}))

    assert lines["reconciliation_gap"]["value"] == D("500.00")  # last balance 1200 vs 0 + 700


def test_treasury_summary_uses_the_signed_reconciliation_equation():
    rows = [
        {"date": date(2026, 9, 5), "type": "MONEY_IN", "amount": D("500.00"), "reference": "", "balance": D("1400.00")},
        {"date": date(2026, 9, 10), "type": "MONEY_OUT", "amount": D("100.00"), "reference": "", "balance": D("1300.00")},
    ]
    context = {"opening_balance": D("900.00"), "transfers_net": D("-30.00"), "closing_balance": D("1270.00"),
               "period_in": D("500.00"), "period_out": D("100.00")}
    document = build("bank-statement", rows, statement_context=context)
    lines = summary(document)

    assert [line["key"] for line in document["summary"]] == [
        "opening_balance", "total_in", "total_out", "internal_transfers", "closing_balance",
    ]
    assert lines["total_in"]["value"] == D("500.00") and lines["total_out"]["value"] == D("100.00")
    assert lines["internal_transfers"]["value"] == D("-30.00")
    assert lines["closing_balance"]["value"] == D("1270.00")
    # The treasury statements list the opening balance as the first table row
    # (an "Entrée" line) rather than as the separate balance-only row.
    assert document["opening_balance"] is None


def test_treasury_summary_leaves_the_opening_and_transfer_lines_out_of_the_period_totals():
    rows = [
        {"date": date(2026, 9, 1), "type": "MONEY_IN", "amount": D("900.00"), "reference": "Solde d'ouverture",
         "balance": D("900.00"), "kind": "opening"},
        {"date": date(2026, 9, 5), "type": "MONEY_IN", "amount": D("500.00"), "reference": "", "balance": D("1400.00"),
         "kind": "movement"},
        {"date": date(2026, 9, 8), "type": "MONEY_OUT", "amount": D("30.00"), "reference": "Transfert A -> B",
         "balance": D("1370.00"), "kind": "transfer"},
        {"date": date(2026, 9, 10), "type": "MONEY_OUT", "amount": D("100.00"), "reference": "", "balance": D("1270.00"),
         "kind": "movement"},
    ]
    context = {"opening_balance": D("900.00"), "transfers_net": D("-30.00"), "closing_balance": D("1270.00")}
    lines = summary(build("bank-statement", rows, statement_context=context))

    assert lines["total_in"]["value"] == D("500.00") and lines["total_out"]["value"] == D("100.00")
    assert "reconciliation_gap" not in lines

    broken = summary(build("cash-statement", rows, statement_context={**context, "closing_balance": D("1300.00")}))
    assert broken["reconciliation_gap"]["value"] == D("30.00")
    zero_transfers = summary(build("cash-statement", [], statement_context={
        "opening_balance": D("10"), "transfers_net": D("0"), "closing_balance": D("10")}))
    assert zero_transfers["internal_transfers"]["value"] == D("0")


@pytest.mark.django_db
def test_treasury_summary_from_the_real_query_context_reconciles_exactly():
    from apps.reports.queries.treasury_statement import TreasuryStatementQuery

    admin = _make_admin("DOCTREAS")
    account = CashAccount.objects.create(name="Cash DOCTREAS", opening_balance=D("100.00"))
    IN, OUT = TreasuryTransaction.Type.MONEY_IN, TreasuryTransaction.Type.MONEY_OUT
    for kind, amount, day, transfer in ((IN, "1000", "2026-08-10", False), (OUT, "200", "2026-08-15", True),
                                        (IN, "500", "2026-09-05", False), (OUT, "50", "2026-09-12", True),
                                        (OUT, "100", "2026-09-10", False)):
        TreasuryTransaction.objects.create(cash_account=account, type=kind, amount=D(amount), date=day,
                                           is_transfer=transfer, recorded_by=admin)
    params = {"cash_account_id": account.id, "date_from": "2026-09-01", "date_to": "2026-09-30"}

    rows = TreasuryStatementQuery.run(**params)
    lines = summary(build("cash-statement", rows, params, statement_context=TreasuryStatementQuery.statement_context(**params)))

    assert "reconciliation_gap" not in lines
    assert (lines["opening_balance"]["value"] + lines["total_in"]["value"] - lines["total_out"]["value"]
            + lines["internal_transfers"]["value"]) == lines["closing_balance"]["value"]


# ---------------------------------------------------------------------------
# Other families
# ---------------------------------------------------------------------------


def test_transporter_statement_is_a_running_balance_statement():
    rows = [
        {"date": date(2026, 9, 1), "type": "SETTLEMENT", "reference": "T1", "debit": D("1400.00"),
         "credit": None, "balance": D("1400.00")},
        {"date": date(2026, 9, 2), "type": "PAYMENT", "reference": "P1", "debit": None,
         "credit": D("400.00"), "balance": D("1000.00")},
    ]
    lines = summary(build("transporter-statement", rows))

    assert lines["total_debit"]["value"] == D("1400.00")
    assert lines["total_credit"]["value"] == D("400.00")
    assert lines["closing_balance"]["value"] == D("1000.00")


def test_sales_and_expense_and_outstanding_totals():
    sales = [{"trip_reference": "T1", "date": date(2026, 9, 1), "customer": "A", "product": "G",
              "delivered_quantity": D("100.5000"), "unit_selling_price": D("650.1234"), "subtotal": D("65337.88")},
             {"trip_reference": "T2", "date": date(2026, 9, 2), "customer": "B", "product": "G",
              "delivered_quantity": D("50"), "unit_selling_price": D("1"), "subtotal": D("50")}]
    lines = summary(build("sales-report", sales))
    assert lines["total_delivered"]["value"] == D("150.5000") and lines["total_subtotal"]["value"] == D("65387.88")

    expenses = [{"date": date(2026, 9, 1), "category": "rent", "amount": D("10.10"), "calculation_method": "FIXED", "status": "PAID"},
                {"date": date(2026, 9, 2), "category": "salary", "amount": D("20.20"), "calculation_method": "MANUAL", "status": "UNPAID"}]
    lines = summary(build("expense-report", expenses))
    assert lines["total_amount"]["value"] == D("30.30") and lines["expenses_count"]["value"] == 2

    for slug, field, count_key in (("customer-outstanding", "customer", "customers_count"),
                                   ("supplier-outstanding", "supplier", "suppliers_count"),
                                   ("transporter-outstanding", "transporter", "transporters_count")):
        lines = summary(build(slug, [{field: "A", "outstanding": D("5.5")}, {field: "B", "outstanding": D("4.5")}]))
        assert lines["total_outstanding"]["value"] == D("10.0") and lines[count_key]["value"] == 2


def test_fuel_stock_total_row_is_bold_and_never_double_counted():
    rows = [{"component": "SUPPLIER_RELIQUAT", "reference": "SO1", "quantity": D("100.00")},
            {"component": "LOADED_UNSOLD", "reference": "T1", "quantity": D("40.00")},
            {"component": "TOTAL", "reference": None, "quantity": D("140.00")}]
    document = build("fuel-stock", rows)
    lines = summary(document)

    assert lines["supplier_reliquat"]["value"] == D("100.00")
    assert lines["loaded_unsold"]["value"] == D("40.00")
    assert lines["total_stock"]["value"] == D("140.00") and lines["total_stock"]["emphasis"]
    assert "reconciliation_gap" not in lines
    assert document["tables"][0]["emphasis"] == {"field": "component", "equals": "TOTAL"}
    assert document["tables"][0]["columns"][0]["enum_labels"]["TOTAL"]

    broken = summary(build("fuel-stock", rows[:2] + [{**rows[2], "quantity": D("150.00")}]))
    assert broken["reconciliation_gap"]["value"] == D("10.00")
    assert summary(build("fuel-stock", []))["total_stock"]["value"] == D("0")


def test_loss_report_totals_and_unverified_rows():
    rows = [{"trip_reference": "T1", "control_date": date(2026, 9, 1), "loaded_quantity": D("1000"),
             "received_quantity": D("990"), "loss_quantity": D("10"), "tolerance_quantity": D("5"),
             "chargeable_loss_quantity": D("5"), "verified_at": None, "notes": None},
            {"trip_reference": "T2", "control_date": date(2026, 9, 2), "loaded_quantity": D("500"),
             "received_quantity": D("500"), "loss_quantity": D("0"), "tolerance_quantity": D("2"),
             "chargeable_loss_quantity": D("0"), "verified_at": None, "notes": "RAS"}]
    lines = summary(build("loss-report", rows))

    assert (lines["total_loaded"]["value"], lines["total_received"]["value"],
            lines["total_loss"]["value"], lines["total_chargeable"]["value"]) == (D("1500"), D("1490"), D("10"), D("5"))


# ---------------------------------------------------------------------------
# D7: CANCELLED rows stay displayed but leave amounts, quantities, margins, counts
# ---------------------------------------------------------------------------


def test_purchase_report_excludes_cancelled_orders_from_totals_and_reports_the_count():
    rows = [{"reference": "SO1", "purchase_date": date(2026, 9, 1), "supplier": "S", "product": "G",
             "quantity_litres": D("100"), "unit_price": D("2"), "total_amount": D("200"), "status": "CONFIRMED"},
            {"reference": "SO2", "purchase_date": date(2026, 9, 2), "supplier": "S", "product": "G",
             "quantity_litres": D("900"), "unit_price": D("2"), "total_amount": D("1800"), "status": "CANCELLED"}]
    document = build("purchase-report", rows)
    lines = summary(document)

    assert lines["orders_count"]["value"] == 1
    assert lines["total_quantity"]["value"] == D("100") and lines["total_amount"]["value"] == D("200")
    assert lines["cancelled_excluded"]["value"] == 1 and lines["cancelled_excluded"]["kind"] == "count"
    assert document["summary"][-1]["key"] == "cancelled_excluded"
    assert summary(build("purchase-report", rows[:1]))["cancelled_excluded"]["value"] == 0


def test_trip_report_and_truck_history_exclude_cancelled_trips_and_skip_none_margins():
    trips = [{"trip_reference": "T1", "loading_date": date(2026, 9, 1), "status": "DELIVERED", "truck": "K1",
              "transporter": "X", "supplier": "S", "product": "G", "quantity_loaded": D("100"), "client": None},
             {"trip_reference": "T2", "loading_date": date(2026, 9, 2), "status": "CANCELLED", "truck": "K1",
              "transporter": "X", "supplier": "S", "product": "G", "quantity_loaded": D("900"), "client": "C"}]
    lines = summary(build("trip-report", trips))
    assert lines["trips_count"]["value"] == 1 and lines["total_quantity"]["value"] == D("100")
    assert lines["cancelled_excluded"]["value"] == 1

    history = [{"trip_reference": "T1", "loading_date": date(2026, 9, 1), "status": "DELIVERED",
                "quantity_loaded": D("100"), "client": None, "current_margin": None},
               {"trip_reference": "T2", "loading_date": date(2026, 9, 2), "status": "COMPLETED",
                "quantity_loaded": D("50"), "client": "C", "current_margin": D("12.50")},
               {"trip_reference": "T3", "loading_date": date(2026, 9, 3), "status": "CANCELLED",
                "quantity_loaded": D("999"), "client": "C", "current_margin": D("777")}]
    lines = summary(build("truck-history", history))
    assert lines["trips_count"]["value"] == 2 and lines["total_quantity"]["value"] == D("150")
    assert lines["margin_total"]["value"] == D("12.50") and lines["cancelled_excluded"]["value"] == 1


@pytest.mark.django_db
def test_margin_report_looks_up_trip_status_to_exclude_cancelled_trips():
    from apps.reports.queries.margin_report import MarginReportQuery

    admin = _make_admin("DOCMARGIN")
    live = _make_full_trip("DOCMARGINA", admin)
    cancelled = _make_full_trip("DOCMARGINB", admin, status=Trip.Status.CANCELLED)
    rows = MarginReportQuery.run()
    document = build("margin-report", rows)
    lines = summary(document)

    references = {row["trip_reference"] for row in rows}
    assert {live["trip"].reference, cancelled["trip"].reference} <= references
    assert lines["cancelled_excluded"]["value"] == 1
    active = [r for r in rows if r["trip_reference"] != cancelled["trip"].reference]
    assert lines["total_quantity_loaded"]["value"] == sum((r["quantity_loaded"] for r in active), D("0"))
    assert lines["total_real_cost"]["value"] == sum((r["real_total_cost"] for r in active), D("0"))
    assert lines["margin_total"]["value"] == sum((r["current_margin"] for r in active), D("0"))


def test_margin_report_is_three_tables_covering_every_field_once():
    from apps.reports.queries.margin_report import FIELDS

    document = build("margin-report")

    assert len(document["tables"]) == 3 and document["orientation"] == "landscape"
    fields = all_fields(document)
    assert set(fields) == set(FIELDS)
    for field in FIELDS:
        expected = 3 if field in ("trip_reference", "client") else 1
        assert fields.count(field) == expected, field
    assert all(table["title"] for table in document["tables"])
    assert all(table["columns"][0]["field"] == "trip_reference" for table in document["tables"])


# ---------------------------------------------------------------------------
# Column kinds, empty reports and the label catalog
# ---------------------------------------------------------------------------


def test_column_kinds_and_alignment():
    document = build("purchase-report")
    columns = {c["field"]: c for c in document["tables"][0]["columns"]}

    assert columns["purchase_date"]["kind"] == "date" and columns["purchase_date"]["align"] == "start"
    assert columns["quantity_litres"]["kind"] == "quantity" and columns["quantity_litres"]["align"] == "end"
    assert columns["unit_price"]["kind"] == "unit_money" and columns["total_amount"]["kind"] == "money"
    assert columns["status"]["kind"] == "status" and columns["status"]["enum_labels"]["CANCELLED"] == "Annulée"
    assert columns["reference"]["kind"] == "ref"
    assert columns["status"]["namespace"] == "purchaseOrderStatus"  # badge colours depend on it
    assert "namespace" not in columns["reference"]


@pytest.mark.parametrize("slug", sorted(REPORT_REGISTRY))
def test_empty_report_keeps_columns_summary_and_empty_text(slug):
    document = build(slug)

    assert document["tables"] and document["summary"]
    for line in document["summary"]:
        if line["kind"] in ("money", "quantity", "count"):
            assert line["value"] is not None


@pytest.mark.parametrize("lang", ["fr", "en", "ar"])
def test_label_catalog_covers_every_enum_value_used_by_a_report(lang):
    from apps.trips.models import Trip as TripModel

    expected = {
        "statementType": ["INVOICE", "PURCHASE", "PAYMENT", "PROFIT_SHARE", "CONTRIBUTION", "WITHDRAWAL",
                          "LOAN_GIVEN", "LOAN_RECEIVED"],
        "transactionType": [v for v, _ in TreasuryTransaction.Type.choices],
        "purchaseOrderStatus": [v for v, _ in SupplierOrder.Status.choices],
        "expenseStatus": [v for v, _ in Expense.Status.choices],
        "expenseCategory": [v for v, _ in Expense.Category.choices],
        "expenseCalcMethod": [v for v, _ in Expense.CalculationMethod.choices],
        "tripStatus": [v for v, _ in TripModel.Status.choices],
        "fuelComponent": ["SUPPLIER_RELIQUAT", "LOADED_UNSOLD", "TOTAL"],
    }
    for namespace, values in expected.items():
        for value in values:
            assert LABELS[lang].get(f"enum.{namespace}.{value}"), (lang, namespace, value)
    # No enum-backed column may point at a namespace the catalog does not know.
    for slug in REPORT_SPECS:
        for table in build(slug, lang=lang)["tables"]:
            for column in table["columns"]:
                if column["kind"] in ("enum", "status"):
                    assert column["enum_labels"] and all(column["enum_labels"].values())


@pytest.mark.parametrize("lang", ["fr", "en", "ar"])
def test_every_summary_and_field_label_exists_in_each_language(lang):
    for slug in REPORT_SPECS:
        document = build(slug, [], statement_context={"opening_balance": D("1"), "transfers_net": D("0"),
                                                      "closing_balance": D("1")}, lang=lang)
        for line in document["summary"]:
            assert line["label"] and not line["label"].startswith("summary."), (slug, line["key"])
        for table in document["tables"]:
            for column in table["columns"]:
                assert not column["label"].startswith("field."), (slug, column["field"])


# --- Framework additions: percent kind, per-table sections, fee_type entity,
# custom expense category labels (spec 2026-09-23-rapports-capital-dettes-
# creances, section "Changements du cadre" / "Libellés des catégories").


def _sectioned_spec(entity=None):
    from apps.reports.services.report_document import ReportSpec, TableSpec

    columns = (("customer", "text"), ("outstanding", "percent"))
    return ReportSpec(
        "portrait",
        (TableSpec(columns, section="a"), TableSpec(columns, section="b")),
        lambda slug, rows, context: [],
        period_mode="as_of",
        entity=entity,
    )


def test_tables_expose_their_section_and_percent_columns_align_right(monkeypatch):
    monkeypatch.setitem(REPORT_SPECS, "customer-outstanding", _sectioned_spec())

    document = build_report_document("customer-outstanding", [], {}, "fr", generated_on=TODAY)

    assert [table["section"] for table in document["tables"]] == ["a", "b"]
    percent = document["tables"][0]["columns"][1]
    assert (percent["kind"], percent["align"]) == ("percent", "end")


def test_existing_tables_have_no_section():
    document = build_report_document("margin-report", [], {}, "fr", generated_on=TODAY)

    assert [table["section"] for table in document["tables"]] == [None, None, None]


@pytest.mark.parametrize(
    "lang,expected",
    [("fr", ("Type de frais", "Douane")), ("en", ("Fee type", "Customs")), ("ar", ("نوع الرسوم", "الجمارك"))],
)
def test_fee_type_entity_is_translated(monkeypatch, lang, expected):
    monkeypatch.setitem(
        REPORT_SPECS, "customer-outstanding", _sectioned_spec(entity=("fee_type", "fee_type"))
    )

    document = build_report_document(
        "customer-outstanding", [], {"fee_type": "customs"}, lang, generated_on=TODAY
    )

    assert (document["entity"]["label"], document["entity"]["name"]) == expected


@pytest.mark.parametrize("params", [{}, {"fee_type": ""}, {"fee_type": "all"}])
def test_fee_type_entity_defaults_to_all(monkeypatch, params):
    monkeypatch.setitem(
        REPORT_SPECS, "customer-outstanding", _sectioned_spec(entity=("fee_type", "fee_type"))
    )

    document = build_report_document("customer-outstanding", [], params, "fr", generated_on=TODAY)

    assert document["entity"]["name"] == "Tous"


@pytest.mark.django_db
def test_custom_expense_category_shows_its_name_never_its_code():
    from apps.finance.models import ExpenseCategory

    ExpenseCategory.objects.create(name="Fournitures de bureau", code="fournitures_bureau")
    rows = [
        {"date": TODAY, "category": "fournitures_bureau", "amount": D("1000.00"),
         "calculation_method": "FIXED", "status": "UNPAID"},
        {"date": TODAY, "category": "rent", "amount": D("500.00"),
         "calculation_method": "FIXED", "status": "PAID"},
    ]

    labels = {
        lang: build_report_document("expense-report", rows, {}, lang, generated_on=TODAY)["tables"][0][
            "columns"
        ][1]["enum_labels"]
        for lang in ("fr", "en", "ar")
    }

    assert all(entry["fournitures_bureau"] == "Fournitures de bureau" for entry in labels.values())
    assert (labels["fr"]["rent"], labels["en"]["rent"]) == ("Loyer", "Rent")
    assert ARABIC.search(labels["ar"]["rent"])

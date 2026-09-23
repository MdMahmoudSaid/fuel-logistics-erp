# Capital report and general-expense report (docs/superpowers/specs/2026-09-23-
# rapports-capital-dettes-creances-design.md, sections 1 and 2): totals that tie
# to the existing services, period behaviour, settlement rules, category labels.

import importlib
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from apps.finance.models import (
    CashAccount,
    Expense,
    ExpenseAllocation,
    ExpenseCategory,
    Shareholder,
    ShareholderContribution,
    TreasuryTransaction,
)
from apps.finance.services import ControlledDebtPaymentService, ShareholderContributionService
from apps.reports.queries.capital_report import CapitalReportQuery
from apps.reports.queries.general_expense_report import GeneralExpenseReportQuery
from apps.reports.services.report_document import build_report_document
from apps.reports.test_queries import _make_admin, _make_full_trip
from apps.reports.test_report_pdf import pdf_pages

D = Decimal
TODAY = date(2026, 9, 23)


def _client(suffix="CAPEXP"):
    client = APIClient()
    client.force_authenticate(_make_admin(suffix))
    return client


def _document(slug, rows, lang="fr", params=None):
    return build_report_document(slug, rows, params or {}, lang, generated_on=TODAY)


def _summary(document):
    return {line["key"]: line["value"] for line in document["summary"]}


# ---------------------------------------------------------------------------
# Capital
# ---------------------------------------------------------------------------


def _capital_fixture():
    admin = _make_admin("CAPFX")
    cash = CashAccount.objects.create(name="Caisse capital")
    alpha = Shareholder.objects.create(
        name="Alpha", participation_percent=D("60"), contribution=D("1000000.00")
    )
    beta = Shareholder.objects.create(
        name="Beta", participation_percent=D("40"), contribution=D("3000000.00"), is_active=False
    )
    for holder, amount, day in [(alpha, "500000.00", date(2026, 1, 10)), (alpha, "250000.00", date(2026, 9, 10))]:
        ShareholderContribution.objects.create(
            shareholder=holder, amount=D(amount), date=day, cash_account=cash,
            reference=f"CT-{day.month}", recorded_by=admin,
        )
    return alpha, beta


@pytest.mark.django_db
def test_capital_total_equals_the_service_and_every_shareholder_is_listed():
    _capital_fixture()

    rows = CapitalReportQuery.run()
    holders = [r for r in rows if r["section"] == "shareholder"]
    document = _document("capital-report", rows)

    assert [r["shareholder"] for r in holders] == ["Alpha", "Beta"]  # inactive one included
    assert sum(r["gross_capital"] for r in holders) == ShareholderContributionService.get_total_capital()
    alpha = holders[0]
    assert (alpha["opening_contribution"], alpha["later_contributions"], alpha["gross_capital"]) == (
        D("1000000.00"), D("750000.00"), D("1750000.00"),
    )
    assert alpha["participation_percent"] == D("60.00")
    assert alpha["capital_percent"] == D("36.84")  # 1 750 000 / 4 750 000
    assert _summary(document)["total_capital"] == ShareholderContributionService.get_total_capital()
    assert document["period"]["mode"] == "open"


@pytest.mark.django_db
def test_capital_period_filters_the_contribution_table_only():
    _capital_fixture()

    everything = CapitalReportQuery.run()
    september = CapitalReportQuery.run(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
    holders = lambda rows: [r for r in rows if r["section"] == "shareholder"]  # noqa: E731
    contributions = lambda rows: [r for r in rows if r["section"] == "contribution"]  # noqa: E731

    assert holders(september) == holders(everything)
    assert len(contributions(everything)) == 2
    assert [(r["date"], r["amount"], r["account"]) for r in contributions(september)] == [
        (date(2026, 9, 10), D("250000.00"), "Caisse capital")
    ]
    document = _document("capital-report", september, params={"date_from": "2026-09-01", "date_to": "2026-09-30"})
    summary = _summary(document)
    assert summary["period_contributions_total"] == D("250000.00") and summary["contributions_count"] == 1
    assert summary["total_capital"] == ShareholderContributionService.get_total_capital()


@pytest.mark.django_db
def test_capital_with_no_shareholder_or_zero_capital_never_divides_by_zero():
    assert CapitalReportQuery.run() == []
    empty = _document("capital-report", [])
    assert _summary(empty)["total_capital"] == D("0.00") and empty["tables"][0]["section"] == "shareholder"

    Shareholder.objects.create(name="Zero", participation_percent=D("10"), contribution=D("0"))
    rows = CapitalReportQuery.run()

    assert rows[0]["capital_percent"] == D("0.00")


@pytest.mark.django_db
def test_capital_pdf_labels_the_two_percentages_apart_and_suffixes_only_money_with_xof():
    _capital_fixture()
    response = _client("CAPPDF").get("/api/reports/capital-report/", {"export": "pdf", "lang": "fr"})

    text = " ".join("\n".join(pdf_pages(response.content)[1]).split())

    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert "Rapport de capital" in text and "AZUR ÉNERGIE" in text
    assert "% de participation" in text and "% du capital" in text
    assert "60,00 % 1 000 000 XOF" in text and "36,84 %" in text
    assert "60,00 % XOF" not in text and "36,84 % XOF" not in text
    assert "Capital total 4 750 000 XOF" in text
    assert "10/01/2026 Alpha 500 000 XOF Caisse capital CT-1" in text  # date/ref/account carry no XOF


@pytest.mark.django_db
def test_capital_document_endpoint_and_arabic_pdf():
    _capital_fixture()
    client = _client("CAPDOC")

    payload = client.get("/api/reports/capital-report/", {"document": "1", "lang": "en"}).json()
    arabic = client.get("/api/reports/capital-report/", {"export": "pdf", "lang": "ar"})

    assert [t["section"] for t in payload["document"]["tables"]] == ["shareholder", "contribution"]
    assert payload["document"]["title"] == "Capital report"
    assert "section" not in payload["fields"] and payload["report_type"] == "capital-report"
    assert arabic.status_code == 200 and arabic.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_capital_hostile_names_do_not_break_the_pdf():
    Shareholder.objects.create(
        name='<img src=x onerror=1> & ' + "x" * 120, participation_percent=D("100"),
        contribution=D("1000.00"),
    )
    response = _client("CAPHOST").get("/api/reports/capital-report/", {"export": "pdf"})

    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert "<img" in "\n".join(pdf_pages(response.content)[1])  # printed as text, not markup


# ---------------------------------------------------------------------------
# General expenses
# ---------------------------------------------------------------------------


def _expense(category="rent", amount="100000.00", day=date(2026, 9, 5), **extra):
    return Expense.objects.create(
        category=category, amount=D(amount), calculation_method=extra.pop("calculation_method", "MANUAL"),
        date=day, **extra,
    )


def _actor():
    from apps.accounts.models import User

    return User.objects.filter(phone="+222EXPPAY").first() or _make_admin("EXPPAY")


def _pay(expense, amount, kind=TreasuryTransaction.Type.MONEY_OUT):
    return TreasuryTransaction.objects.create(
        recorded_by=_actor(),
        cash_account=CashAccount.objects.get_or_create(name="Caisse dépenses")[0], type=kind,
        amount=D(amount), date=date(2026, 9, 6),
        source_content_type=ContentType.objects.get_for_model(Expense), source_object_id=expense.id,
    )


def _expense_rows(**params):
    return [r for r in GeneralExpenseReportQuery.run(**params) if r["section"] == "expense"]


@pytest.mark.django_db
def test_customer_paid_expense_is_fully_paid_without_any_treasury_transaction():
    _expense(status=Expense.Status.PAID, paid_by_customer_directly=True)

    row = _expense_rows()[0]

    assert (row["total_amount"], row["paid_amount"], row["remaining_amount"]) == (D("100000.00"), D("100000.00"), D("0.00"))
    assert not TreasuryTransaction.objects.exists()


@pytest.mark.django_db
def test_bank_paid_and_partially_paid_expenses_use_the_net_treasury_payments():
    paid = _expense(status=Expense.Status.PAID)
    _pay(paid, "100000.00")
    partial = _expense(category="salary", amount="200000.00", status=Expense.Status.PARTIALLY_PAID)
    _pay(partial, "80000.00")
    _pay(partial, "20000.00", TreasuryTransaction.Type.MONEY_IN)  # a refund reduces what was paid
    unpaid = _expense(category="repairs", amount="50000.00")

    by_category = {r["category"]: r for r in _expense_rows()}

    assert by_category["rent"]["remaining_amount"] == D("0.00")
    assert (by_category["salary"]["paid_amount"], by_category["salary"]["remaining_amount"]) == (D("60000.00"), D("140000.00"))
    assert (by_category["repairs"]["paid_amount"], by_category["repairs"]["remaining_amount"]) == (D("0.00"), D("50000.00"))
    assert unpaid.status == Expense.Status.UNPAID


@pytest.mark.django_db
def test_allocated_expense_uses_the_allocated_total_not_the_per_litre_rate():
    fx = _make_full_trip("EXPALLOC", _make_admin("EXPALLOC"))
    expense = _expense(category="administration", amount="50.00", calculation_method="PER_LITRE")
    ExpenseAllocation.objects.create(
        expense=expense, content_type=ContentType.objects.get_for_model(fx["trip"]),
        object_id=fx["trip"].id, allocated_amount=D("2250000.00"),
    )

    row = _expense_rows()[0]

    assert (row["total_amount"], row["remaining_amount"]) == (D("2250000.00"), D("2250000.00"))
    assert row["total_amount"] == ControlledDebtPaymentService.describe_expense(expense)["total_amount"]


@pytest.mark.django_db
def test_cancelled_expense_is_listed_but_leaves_every_total_and_is_counted():
    _expense(status=Expense.Status.PAID, paid_by_customer_directly=True)
    cancelled = _expense(category="salary", amount="900000.00", status=Expense.Status.CANCELLED)
    _pay(cancelled, "900000.00")
    _pay(cancelled, "900000.00", TreasuryTransaction.Type.MONEY_IN)

    rows = GeneralExpenseReportQuery.run()
    document = _document("general-expense-report", rows)
    summary = _summary(document)
    recap = [r for r in rows if r["section"] == "category_total"]

    salary = next(r for r in rows if r["section"] == "expense" and r["category"] == "salary")
    assert salary["status"] == "CANCELLED" and salary["total_amount"] == D("900000.00")
    assert salary["paid_amount"] is None and salary["remaining_amount"] is None
    assert summary["expenses_count"] == 1 and summary["total_amount"] == D("100000.00")
    assert summary["cancelled_excluded"] == 1 and summary["paid_count"] == 1
    assert [r["category"] for r in recap] == ["rent"]  # no line for a cancelled-only category


@pytest.mark.django_db
def test_trip_fee_categories_are_excluded_and_other_categories_included():
    ExpenseCategory.objects.create(name="Fournitures de bureau", code="fournitures_bureau")
    trip_fee = ["customs", "transit", "road_transit", "road", "loading", "transport"]
    for code in trip_fee:
        _expense(category=code)
    general = ["unloading", "import_intention", "fournitures_bureau", "rent"]
    for code in general:
        _expense(category=code)

    assert {r["category"] for r in _expense_rows()} == set(general)


def test_trip_fee_category_codes_match_the_seeded_system_categories():
    migration = importlib.import_module("apps.finance.migrations.0014_expensecategory")

    assert Expense.TRIP_FEE_CATEGORY_CODES == frozenset(migration.SYSTEM_CODES)


@pytest.mark.django_db
def test_main_table_and_category_recap_show_the_same_label_never_the_code():
    ExpenseCategory.objects.create(name="Fournitures de bureau", code="fournitures_bureau")
    _expense(category="fournitures_bureau")
    _expense(category="rent")

    rows = GeneralExpenseReportQuery.run()
    for lang in ("fr", "en", "ar"):
        document = _document("general-expense-report", rows, lang)
        main = document["tables"][0]["columns"][1]
        recap = document["tables"][1]["columns"][0]
        assert main["field"] == recap["field"] == "category"
        assert main["enum_labels"] == recap["enum_labels"]
        assert main["enum_labels"]["fournitures_bureau"] == "Fournitures de bureau"

    text = "\n".join(
        pdf_pages(_client("EXPLABEL").get("/api/reports/general-expense-report/", {"export": "pdf"}).content)[1]
    )
    assert text.count("Fournitures de bureau") == 2 and "fournitures_bureau" not in text


@pytest.mark.django_db
def test_period_filters_lines_and_totals():
    _expense(day=date(2026, 8, 20), amount="1000.00")
    _expense(day=date(2026, 9, 10), amount="2000.00")

    rows = GeneralExpenseReportQuery.run(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
    document = _document("general-expense-report", rows, params={"date_from": "2026-09-01", "date_to": "2026-09-30"})

    assert [r["total_amount"] for r in rows if r["section"] == "expense"] == [D("2000.00")]
    assert _summary(document)["total_amount"] == D("2000.00")
    assert document["period"]["mode"] == "range"


@pytest.mark.django_db
def test_general_expense_empty_report_and_summary_counts_by_status():
    empty = _document("general-expense-report", GeneralExpenseReportQuery.run())
    assert _summary(empty)["expenses_count"] == 0 and _summary(empty)["cancelled_excluded"] == 0

    _expense(status=Expense.Status.PAID, paid_by_customer_directly=True)
    _expense(category="salary", status=Expense.Status.PARTIALLY_PAID)
    _expense(category="repairs")
    summary = _summary(_document("general-expense-report", GeneralExpenseReportQuery.run()))

    assert (summary["paid_count"], summary["partially_paid_count"], summary["unpaid_count"]) == (1, 1, 1)


@pytest.mark.django_db
def test_general_expense_pdf_survives_hostile_and_huge_notes_and_arabic():
    _expense(notes="<b>bold</b> & " + "long " * 300, status=Expense.Status.UNPAID)
    client = _client("EXPHOST")

    french = client.get("/api/reports/general-expense-report/", {"export": "pdf"})
    arabic = client.get("/api/reports/general-expense-report/", {"export": "pdf", "lang": "ar"})

    assert french.status_code == 200 and arabic.status_code == 200
    text = "\n".join(pdf_pages(french.content)[1])
    assert "Rapport des dépenses générales" in text and "<b>bold</b>" in text
    assert "section" not in client.get("/api/reports/general-expense-report/").json()["fields"]

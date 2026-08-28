# Dashboard / Report / Search API tests (docs/PHASE_6_PLAN.md Etape 5;
# ERP_Implementation_Experience_Guide.md Section 9.6/9.7/9.8).

import csv
import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    Shareholder,
    ShareholderLoan,
)
from apps.finance.services import (
    FinancePostingService,
    ShareholderDistributionService,
    ShareholderWithdrawalService,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role
    )


def _make_role_without_reports(suffix):
    return Role.objects.create(name=f"NoReports-{suffix}", permissions={"operations": ["view"]})


def _make_full_trip(suffix, admin_user, status=Trip.Status.DELIVERED, with_sale=True):
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-VIEW-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-VIEW-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("45000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-VIEW-{suffix}",
        tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-VIEW-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=product,
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference=f"BL-VIEW-{suffix}",
        status=status,
        created_by=admin_user,
    )
    customer = Customer.objects.create(name=f"Client {suffix}")
    sale = None
    if with_sale:
        sale = Sale.objects.create(
            trip=trip,
            customer=customer,
            product=product,
            delivered_quantity=Decimal("44850.00"),
            unit_selling_price=Decimal("650.0000"),
        )
    return {"trip": trip, "truck": truck, "customer": customer, "sale": sale, "supplier_order": supplier_order}


# ---------------------------------------------------------------------------
# DashboardViewSet
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_summary_returns_six_sections():
    admin_user = _make_admin("DASH")
    _make_full_trip("DASH", admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/dashboard/summary/")

    assert response.status_code == 200, response.data
    for section in ("operations", "fuel", "sales", "transport", "finance", "profit"):
        assert section in response.data


@pytest.mark.django_db
def test_dashboard_summary_filters_by_explicit_date_range():
    admin_user = _make_admin("DASHRANGE")
    _make_full_trip("DASHRANGE", admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get(
        "/api/dashboard/summary/", {"from": "2020-01-01", "to": "2020-01-02"}
    )

    assert response.status_code == 200, response.data
    assert response.data["operations"]["trips_count"] == 0


@pytest.mark.django_db
def test_dashboard_summary_includes_shareholders_summary_section():
    """Design doc 2026-08-26-benefices-associes-refinement-design.md:
    dashboard shows a summary only - current profit, total withdrawn,
    remaining undistributed, open loans - the Benefices page stays the
    detailed source."""
    admin_user = _make_admin("DASHSH")
    a = Shareholder.objects.create(name="Dash A", participation_percent=Decimal("100"))
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=admin_user,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, admin_user)
    share = distribution.shares.get(shareholder=a)
    cash_account = CashAccount.objects.create(name="Dash Cash", opening_balance=Decimal("100000.00"))
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=a.id,
        profit_share_id=share.id,
        amount=Decimal("30000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=admin_user,
    )
    b = Shareholder.objects.create(name="Dash B", participation_percent=Decimal("0"))
    ShareholderLoan.objects.create(
        borrower=b, lender=a, amount=Decimal("5000.00"), date="2026-08-01"
    )

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/dashboard/summary/")

    assert response.status_code == 200, response.data
    summary = response.data["shareholders_summary"]
    assert summary["total_withdrawn"] == "30000.00"
    assert summary["remaining_undistributed"] == "70000.00"
    assert summary["open_loans_total"] == "5000.00"


@pytest.mark.django_db
def test_dashboard_summary_requires_reports_permission():
    role = _make_role_without_reports("DASH")
    user = User.objects.create_user(phone="+2220000013", pin="1234", role=role)

    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/dashboard/summary/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_summary_includes_debts_customer_and_bank_sections():
    admin_user = _make_admin("DASHDEBT")
    _make_full_trip("DASHDEBT", admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/dashboard/summary/")

    assert response.status_code == 200, response.data
    assert set(response.data["debts"]) >= {
        "total",
        "suppliers",
        "transporters",
        "customs",
        "other",
    }
    assert "total" in response.data["customer_amounts"]
    assert "rows" in response.data["customer_amounts"]
    assert "total" in response.data["bank_amounts"]
    assert "rows" in response.data["bank_amounts"]
    assert "total" in response.data["cash_amounts"]
    assert "rows" in response.data["cash_amounts"]


@pytest.mark.django_db
def test_dashboard_summary_aggregates_customs_and_other_debts_correctly():
    admin_user = _make_admin("DASHEXP")

    Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("1000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2020-01-01",
        status=Expense.Status.UNPAID,
    )
    Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("500.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2020-01-01",
        status=Expense.Status.PARTIALLY_PAID,
    )
    Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("999.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2020-01-01",
        status=Expense.Status.PAID,
    )
    Expense.objects.create(
        category=Expense.Category.RENT,
        amount=Decimal("300.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2020-01-01",
        status=Expense.Status.UNPAID,
    )
    # Transport-category expenses must be excluded from "other" - they are
    # already captured via TransporterOutstandingReportQuery/debts.transporters.
    Expense.objects.create(
        category=Expense.Category.TRANSPORT,
        amount=Decimal("777.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2020-01-01",
        status=Expense.Status.UNPAID,
    )
    Expense.objects.create(
        category=Expense.Category.RENT,
        amount=Decimal("50.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2020-01-01",
        status=Expense.Status.CANCELLED,
    )

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/dashboard/summary/")

    assert response.status_code == 200, response.data
    assert response.data["debts"]["customs"] == "1500.00"
    assert response.data["debts"]["other"] == "300.00"


@pytest.mark.django_db
def test_dashboard_summary_bank_amounts_only_include_active_banks():
    admin_user = _make_admin("DASHBANK")
    BankAccount.objects.create(
        name="Active Bank", opening_balance=Decimal("100.00"), is_active=True
    )
    BankAccount.objects.create(
        name="Closed Bank", opening_balance=Decimal("50.00"), is_active=False
    )

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/dashboard/summary/")

    assert response.status_code == 200, response.data
    bank_names = {row["bank"] for row in response.data["bank_amounts"]["rows"]}
    assert bank_names == {"Active Bank"}
    assert response.data["bank_amounts"]["total"] == "100.00"


@pytest.mark.django_db
def test_dashboard_summary_cash_amounts_only_include_active_cash_accounts():
    admin_user = _make_admin("DASHCASH")
    CashAccount.objects.create(
        name="Active Cash", opening_balance=Decimal("125.00"), is_active=True
    )
    CashAccount.objects.create(
        name="Closed Cash", opening_balance=Decimal("75.00"), is_active=False
    )

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/dashboard/summary/")

    assert response.status_code == 200, response.data
    cash_names = {row["cash_account"] for row in response.data["cash_amounts"]["rows"]}
    assert cash_names == {"Active Cash"}
    assert response.data["cash_amounts"]["total"] == "125.00"


@pytest.mark.django_db
def test_dashboard_summary_debts_customer_and_bank_sections_ignore_date_range():
    admin_user = _make_admin("DASHNODATE")
    Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("1000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2020-01-01",
        status=Expense.Status.UNPAID,
    )
    BankAccount.objects.create(
        name="Old Bank", opening_balance=Decimal("250.00"), is_active=True
    )

    client = APIClient()
    client.force_authenticate(admin_user)
    unfiltered = client.get("/api/dashboard/summary/")
    filtered = client.get(
        "/api/dashboard/summary/", {"from": "2099-01-01", "to": "2099-01-02"}
    )

    assert unfiltered.status_code == 200, unfiltered.data
    assert filtered.status_code == 200, filtered.data
    # Unlike operations/fuel/sales/transport/finance, these three sections
    # are point-in-time "currently outstanding" snapshots and must not be
    # affected by the requested date_from/date_to range.
    assert filtered.data["operations"]["trips_count"] == 0
    assert filtered.data["debts"] == unfiltered.data["debts"]
    assert filtered.data["customer_amounts"] == unfiltered.data["customer_amounts"]
    assert filtered.data["bank_amounts"] == unfiltered.data["bank_amounts"]
    assert filtered.data["cash_amounts"] == unfiltered.data["cash_amounts"]
    assert filtered.data["debts"]["customs"] == "1000.00"
    assert filtered.data["bank_amounts"]["total"] == "250.00"


@pytest.mark.django_db
def test_dashboard_summary_exposes_final_business_sections():
    admin_user = _make_admin("DASHFINAL")
    fx = _make_full_trip(
        "DASHFINAL", admin_user, status=Trip.Status.ARRIVED_AT_COMPANY_STOCK, with_sale=False
    )
    BankAccount.objects.create(name="Bank Recette", opening_balance=Decimal("1000000.00"))
    CashAccount.objects.create(name="Caisse Recette", opening_balance=Decimal("250000.00"))
    payment = CustomerPayment.objects.create(
        customer=fx["customer"],
        amount=Decimal("300000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH,
        cash_account=CashAccount.objects.get(name="Caisse Recette"),
        recorded_by=admin_user,
    )
    FinancePostingService.record_customer_payment_treasury(payment)
    Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-08-18",
        status=Expense.Status.PAID,
    )

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get(
        "/api/dashboard/summary/", {"from": "2026-08-18", "to": "2026-08-18"}
    )

    assert response.status_code == 200, response.data
    financial = response.data["financial_summary"]
    assert financial["period_revenue"] == "0.00"
    assert financial["period_collections"] == "300000.00"
    assert financial["period_paid_expenses"] == "50000.00"
    assert financial["current_treasury_balance"] == "1550000.00"

    company_stock = response.data["company_stock"]
    assert company_stock["total_quantity"] == "45000.00"
    assert company_stock["trips_count"] == 1
    assert company_stock["by_product"] == [{"product": "Gasoil", "quantity": "45000.00"}]
    assert company_stock["trips"][0]["reference"] == fx["trip"].reference
    assert company_stock["trips"][0]["remaining_quantity"] == "45000.00"

    party_balances = response.data["party_balances"]
    assert set(party_balances) >= {"customers", "suppliers", "transporters", "shareholders"}
    assert party_balances["shareholders"]["balance"] == "0.00"

    action_items = response.data["action_items"]
    assert any(item["kind"] == "company_stock_without_customer" for item in action_items)


# ---------------------------------------------------------------------------
# ReportViewSet
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_report_endpoint_returns_json_rows_for_a_known_report_type():
    admin_user = _make_admin("REPJSON")
    fx = _make_full_trip("REPJSON", admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/reports/trip-report/")

    assert response.status_code == 200, response.data
    assert response.data["report_type"] == "trip-report"
    assert any(row["trip_reference"] == fx["trip"].reference for row in response.data["rows"])


@pytest.mark.django_db
def test_report_endpoint_unknown_type_returns_404():
    admin_user = _make_admin("REP404")

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/reports/does-not-exist/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_report_endpoint_passes_query_params_to_the_query_class():
    admin_user = _make_admin("REPFILTER")
    fx = _make_full_trip("REPFILTER", admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/reports/truck-history/", {"truck_id": fx["truck"].id})

    assert response.status_code == 200, response.data
    assert len(response.data["rows"]) == 1
    assert response.data["rows"][0]["trip_reference"] == fx["trip"].reference


@pytest.mark.django_db
def test_report_endpoint_export_csv_returns_a_csv_attachment():
    admin_user = _make_admin("REPCSV")
    _make_full_trip("REPCSV", admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/reports/trip-report/", {"export": "csv"})

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert "attachment" in response["Content-Disposition"]
    reader = csv.reader(io.StringIO(response.content.decode("utf-8-sig")))
    header = next(reader)
    assert header == list(header)  # non-empty, well-formed CSV header
    assert len(header) > 0


@pytest.mark.django_db
def test_report_endpoint_export_xlsx_returns_a_valid_workbook():
    admin_user = _make_admin("REPXLSX")
    _make_full_trip("REPXLSX", admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/reports/trip-report/", {"export": "xlsx"})

    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.active.max_row >= 2  # header + at least one data row


@pytest.mark.django_db
def test_report_endpoint_export_pdf_returns_a_pdf_attachment():
    admin_user = _make_admin("REPPDF")
    _make_full_trip("REPPDF", admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/reports/trip-report/", {"export": "pdf"})

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert "attachment" in response["Content-Disposition"]
    assert response.content.startswith(b"%PDF-")


@pytest.mark.django_db
def test_report_export_requires_export_permission_not_just_view():
    role = Role.objects.create(name="ViewOnlyReports", permissions={"reports": ["view"]})
    user = User.objects.create_user(phone="+2220000014", pin="1234", role=role)

    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/reports/trip-report/", {"export": "csv"})

    assert response.status_code == 403
    # Without the export param, the same view-only role can still read JSON.
    response = client.get("/api/reports/trip-report/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# SearchView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_search_finds_a_truck_with_its_current_trip_enriched():
    admin_user = _make_admin("SEARCH")
    fx = _make_full_trip("SEARCH", admin_user, status=Trip.Status.IN_TRANSIT, with_sale=False)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/search/", {"q": fx["truck"].tractor_registration})

    assert response.status_code == 200, response.data
    assert len(response.data["trucks"]) == 1
    truck_result = response.data["trucks"][0]
    assert truck_result["current_trip"]["reference"] == fx["trip"].reference
    assert truck_result["current_trip"]["status"] == Trip.Status.IN_TRANSIT


@pytest.mark.django_db
def test_search_with_empty_query_returns_empty_categories():
    admin_user = _make_admin("SEARCHEMPTY")

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/search/", {"q": ""})

    assert response.status_code == 200
    assert response.data["trucks"] == []
    assert response.data["customers"] == []

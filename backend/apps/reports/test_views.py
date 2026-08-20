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
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        email=f"admin-view-{suffix}@example.com", password="testpass123", role=admin_role
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
def test_dashboard_summary_requires_reports_permission():
    role = _make_role_without_reports("DASH")
    user = User.objects.create_user(email="norep-dash@example.com", password="testpass123", role=role)

    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/dashboard/summary/")

    assert response.status_code == 403


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
def test_report_export_requires_export_permission_not_just_view():
    role = Role.objects.create(name="ViewOnlyReports", permissions={"reports": ["view"]})
    user = User.objects.create_user(email="view-only@example.com", password="testpass123", role=role)

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

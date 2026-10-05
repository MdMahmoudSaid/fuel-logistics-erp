"""List pages must not run more queries as rows are added (N+1 guard):
the trips, invoices and transport-payment lists load each row's related
records in bulk and embed parties as short identities (name, company),
never their running totals."""

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.customers.models import Customer
from apps.finance.models import TransportPayment
from apps.sales.models import Invoice, Sale
from apps.trips.tests import _make_trip, _make_truck, _setup_fixtures


def _sold_trip(fx, n):
    trip = _make_trip(fx, _make_truck(f"QC-{n:04d}"), f"TRIP-QC-{n:04d}")
    sale = Sale.objects.create(
        trip=trip,
        customer=Customer.objects.get_or_create(name=f"Client QC {n}")[0],
        product=fx["product"],
        delivered_quantity=trip.quantity_loaded,
        unit_selling_price=Decimal("900.0000"),
    )
    TransportPayment.objects.create(
        trip=trip, transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("100000.00"), deduction_amount=Decimal("0.00"),
    )
    Invoice.objects.create(
        invoice_number=f"INV-QC-{n:04d}",
        sale=sale,
        total_amount=sale.subtotal,
        issued_date="2026-08-18",
    )
    return trip


def _queries(client, path):
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(path)
    assert response.status_code == 200
    return len(ctx.captured_queries)


@pytest.fixture
def setup():
    fx = _setup_fixtures("QC")
    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    return fx, client


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path", ["/api/trips/", "/api/invoices/", "/api/sales/", "/api/transport-payments/"]
)
def test_list_query_count_does_not_grow_with_rows(setup, path):
    fx, client = setup
    _sold_trip(fx, 1)
    with_one = _queries(client, path)
    for n in range(2, 6):
        _sold_trip(fx, n)
    with_five = _queries(client, path)

    # A small constant slack is tolerated; one or more queries per extra
    # row (the N+1 pattern) is not.
    assert with_five - with_one <= 4, (with_one, with_five)


@pytest.mark.django_db
def test_trip_list_embeds_parties_as_short_identities(setup):
    fx, client = setup
    _sold_trip(fx, 1)

    row = client.get("/api/trips/").data["results"][0]

    assert set(row["supplier_detail"]) >= {"id", "name", "company_name", "country"}
    assert "total_purchased" not in row["supplier_detail"]
    assert set(row["transporter_detail"]) >= {"id", "name", "company_name", "is_internal"}
    assert "gross_earned" not in row["transporter_detail"]


def _fee(trip, category, amount, status=None):
    from django.contrib.contenttypes.models import ContentType

    from apps.finance.models import Expense, ExpenseAllocation
    from apps.trips.models import Trip

    expense = Expense.objects.create(
        category=category,
        amount=amount,
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
        **({"status": status} if status else {}),
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=amount,
    )


@pytest.mark.django_db
def test_trip_list_figures_equal_the_services_row_by_row(setup):
    from apps.finance.models import Expense, TransportPayment
    from apps.purchasing.services import SupplierStockService
    from apps.trips.models import Trip
    from apps.trips.services import TripCostService

    fx, client = setup
    paid = _sold_trip(fx, 1)
    TransportPayment.objects.create(
        trip=paid, transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("2700000.00"), deduction_amount=Decimal("0.00"),
    )
    _fee(paid, Expense.Category.CUSTOMS, Decimal("90000.00"))
    _fee(paid, Expense.Category.CUSTOMS, Decimal("10000.00"))
    _fee(paid, Expense.Category.TRANSIT, Decimal("45000.00"))
    _fee(paid, Expense.Category.TRANSIT, Decimal("999999.00"), status=Expense.Status.CANCELLED)
    bare = _sold_trip(fx, 2)
    # Same truck loaded twice under the same cession letter.
    from apps.trips.tests import _make_trip
    _make_trip(fx, bare.truck, "TRIP-QC-AGAIN")

    rows = {row["id"]: row for row in client.get("/api/trips/").data["results"]}

    assert len(rows) == 3
    for trip in Trip.objects.all():
        row = rows[trip.id]
        expected_unit_cost = TripCostService.calculate_trip_cost_basis(trip)["unit_cost"]
        assert row["unit_cost"] == f"{expected_unit_cost:.4f}"
        remaining = SupplierStockService.get_cession_remaining(trip.cession_letter)
        assert row["cession_letter_detail"]["remaining_quantity"] == f"{remaining:.2f}"
    assert rows[bare.id]["cession_letter_truck_load_count"] == 2
    assert rows[paid.id]["cession_letter_truck_load_count"] == 1
    assert rows[paid.id]["unit_cost"] != rows[bare.id]["unit_cost"]

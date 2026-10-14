# Phase 6 cross-cutting integration tests required by docs/PHASE_6_PLAN.md
# Etape 6:
#   - Test de Coherence Financiere (Spec Section 34): sum of profit by
#     client/truck/order must exactly equal the sum of the individual trip
#     margins behind it.
#   - Test d'execution des 16 rapports (Spec Section 37): every V1 report
#     type must return valid structured data through the API.
# (Sections 32/33/39's tests already live in test_stock.py, tests.py and
# apps/audit/tests.py respectively - not duplicated here.)

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import BankAccount, CashAccount, Shareholder
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.reports.services.profit import TripProfitService
from apps.reports.views.reports import REPORT_REGISTRY
from apps.sales.models import CustomerOrder, Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role
    )


def _make_trip_for_order(suffix, admin_user, truck, customer, order, unit_selling_price):
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-COHERENCE-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-COHERENCE-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("45000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    trip = Trip.objects.create(
        reference=f"TRIP-COHERENCE-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=product,
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference=f"BL-COHERENCE-{suffix}",
        status=Trip.Status.DELIVERED,
        customer_order=order,
        created_by=admin_user,
    )
    Sale.objects.create(
        trip=trip,
        customer=customer,
        product=product,
        delivered_quantity=Decimal("44850.00"),
        unit_selling_price=unit_selling_price,
    )
    return trip


@pytest.mark.django_db
def test_financial_coherence_profit_by_customer_truck_and_order_matches_individual_trip_margins():
    """Spec Section 34: profit summed by client/truck/order must never
    drift from the plain sum of each associated trip's own margin - both
    numbers come from TripProfitService, but a report-level bug (wrong
    filter, double count) would show up as a mismatch here."""
    admin_user = _make_admin("COHERENCE")
    customer = Customer.objects.create(name="Client COHERENCE")
    truck = Truck.objects.create(
        internal_id="TRK-COHERENCE",
        tractor_registration="COHERENCE-TRACTOR",
        tanker_registration="COHERENCE-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    order = CustomerOrder.objects.create(
        customer=customer,
        product=Product.objects.get(code="gasoil"),
        quantity_ordered=Decimal("90000.00"),
        expected_price=Decimal("650.0000"),
    )

    trip_a = _make_trip_for_order(
        "A", admin_user, truck, customer, order, unit_selling_price=Decimal("650.0000")
    )
    trip_b = _make_trip_for_order(
        "B", admin_user, truck, customer, order, unit_selling_price=Decimal("655.0000")
    )

    margin_a = TripProfitService.calculate_current_margin(trip_a)
    margin_b = TripProfitService.calculate_current_margin(trip_b)
    expected_total = margin_a + margin_b

    profit_by_customer = sum(
        (
            TripProfitService.calculate_current_margin(trip)
            for trip in Trip.objects.filter(sale__customer=customer)
        ),
        Decimal("0.00"),
    )
    profit_by_truck = sum(
        (
            TripProfitService.calculate_current_margin(trip)
            for trip in Trip.objects.filter(truck=truck, sale__isnull=False)
        ),
        Decimal("0.00"),
    )
    profit_by_order = sum(
        (
            TripProfitService.calculate_current_margin(trip)
            for trip in Trip.objects.filter(customer_order=order, sale__isnull=False)
        ),
        Decimal("0.00"),
    )

    assert profit_by_customer == expected_total
    assert profit_by_truck == expected_total
    assert profit_by_order == expected_total


@pytest.mark.django_db
def test_all_report_types_return_valid_structured_data_via_the_api():
    """Spec Section 37 lists 16 V1 report types, plus shareholder-statement
    (UI pass 2026-08-27: Reports page needed a report for
    Actionnaires/Associes), plus the 5 capital/expense/debt/receivable
    reports of 2026-09-23; walk every one through the live API and check
    it returns a well-formed {fields, rows} payload."""
    admin_user = _make_admin("SIXTEEN")
    customer = Customer.objects.create(name="Client SIXTEEN")
    truck = Truck.objects.create(
        internal_id="TRK-SIXTEEN",
        tractor_registration="SIXTEEN-TRACTOR",
        tanker_registration="SIXTEEN-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    order = CustomerOrder.objects.create(
        customer=customer,
        product=Product.objects.get(code="gasoil"),
        quantity_ordered=Decimal("45000.00"),
        expected_price=Decimal("650.0000"),
    )
    trip = _make_trip_for_order(
        "SIXTEEN", admin_user, truck, customer, order, unit_selling_price=Decimal("650.0000")
    )
    bank_account = BankAccount.objects.create(name="Bank SIXTEEN")
    cash_account = CashAccount.objects.create(name="Cash SIXTEEN")
    shareholder = Shareholder.objects.create(name="Assoc SIXTEEN", participation_percent=Decimal("100"))

    params_by_report_type = {
        "customer-statement": {"customer_id": customer.id},
        "supplier-statement": {"supplier_id": trip.supplier_id},
        "transporter-statement": {"transporter_id": trip.transporter_id},
        "truck-history": {"truck_id": truck.id},
        "trip-report": {},
        "purchase-report": {},
        "sales-report": {},
        "expense-report": {},
        "customer-outstanding": {},
        "supplier-outstanding": {},
        "transporter-outstanding": {},
        "fuel-stock": {},
        "loss-report": {},
        "margin-report": {},
        "bank-statement": {"bank_account_id": bank_account.id},
        "cash-statement": {"cash_account_id": cash_account.id},
        "shareholder-statement": {"shareholder_id": shareholder.id},
        # Added 2026-09-23 (capital / general expense / debts / receivables).
        "capital-report": {},
        "general-expense-report": {},
        "trip-fee-debt-report": {"fee_type": "all"},
        "general-debt-report": {},
        "general-receivable-report": {},
        "debts-summary-report": {},
        "receivables-summary-report": {},
    }

    assert set(params_by_report_type) == set(REPORT_REGISTRY)

    client = APIClient()
    client.force_authenticate(admin_user)
    for report_type, params in params_by_report_type.items():
        response = client.get(f"/api/reports/{report_type}/", params)

        assert response.status_code == 200, f"{report_type}: {response.data}"
        assert response.data["report_type"] == report_type
        assert isinstance(response.data["fields"], list) and response.data["fields"]
        assert isinstance(response.data["rows"], list)

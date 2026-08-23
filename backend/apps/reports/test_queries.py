# Report query classes tests (docs/PHASE_6_PLAN.md Etape 4/6;
# ERP_Implementation_Experience_Guide.md Section 9.7).

from decimal import Decimal

import pytest

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import (
    CashAccount,
    CustomerPayment,
    SupplierPayment,
    TransportDeduction,
    TransportPayment,
    TreasuryTransaction,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.reports.queries.customer_statement import CustomerStatementQuery
from apps.reports.queries.fuel_stock_report import FuelStockReportQuery
from apps.reports.queries.loss_report import LossReportQuery
from apps.reports.queries.margin_report import MarginReportQuery
from apps.reports.queries.supplier_statement import SupplierStatementQuery
from apps.reports.queries.transporter_statement import TransporterStatementQuery
from apps.reports.queries.treasury_statement import TreasuryStatementQuery
from apps.reports.queries.trip_report import TripReportQuery
from apps.reports.queries.truck_history import TruckHistoryQuery
from apps.sales.models import Invoice, Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import DeliveryControl, Trip


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role
    )


def _make_full_trip(suffix, admin_user, status=Trip.Status.DELIVERED, with_sale=True):
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-QUERY-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-QUERY-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("45000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-QUERY-{suffix}",
        tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-QUERY-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=product,
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference=f"BL-QUERY-{suffix}",
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
    return {
        "admin_user": admin_user,
        "supplier": supplier,
        "transporter": transporter,
        "supplier_order": supplier_order,
        "truck": truck,
        "trip": trip,
        "customer": customer,
        "sale": sale,
    }


# ---------------------------------------------------------------------------
# CustomerStatementQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_customer_statement_lists_invoices_and_payments_with_running_balance():
    admin_user = _make_admin("CUSTSTMT")
    fx = _make_full_trip("CUSTSTMT", admin_user)
    invoice = Invoice.objects.create(
        invoice_number="INV-QUERY-CUSTSTMT",
        sale=fx["sale"],
        status=Invoice.Status.VALIDATED,
        total_amount=fx["sale"].subtotal,
        issued_date="2026-08-18",
    )
    CustomerPayment.objects.create(
        customer=fx["customer"],
        amount=Decimal("10000000.00"),
        payment_date="2026-08-19",
        method=CustomerPayment.Method.CASH,
        cash_account=CashAccount.objects.create(name="Cash CUSTSTMT"),
        recorded_by=admin_user,
    )

    rows = CustomerStatementQuery.run(customer_id=fx["customer"].id)

    assert [r["type"] for r in rows] == ["INVOICE", "PAYMENT"]
    assert rows[0]["debit"] == invoice.total_amount
    assert rows[0]["credit"] is None
    assert rows[1]["credit"] == Decimal("10000000.00")
    assert rows[-1]["balance"] == invoice.total_amount - Decimal("10000000.00")


# ---------------------------------------------------------------------------
# SupplierStatementQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_supplier_statement_lists_orders_and_payments_with_running_balance():
    admin_user = _make_admin("SUPPSTMT")
    fx = _make_full_trip("SUPPSTMT", admin_user)
    SupplierPayment.objects.create(
        supplier=fx["supplier"],
        amount=Decimal("5000000.00"),
        payment_date="2026-08-19",
        method=SupplierPayment.Method.CASH,
        cash_account=CashAccount.objects.create(name="Cash SUPPSTMT"),
        recorded_by=admin_user,
    )

    rows = SupplierStatementQuery.run(supplier_id=fx["supplier"].id)

    assert [r["type"] for r in rows] == ["PURCHASE", "PAYMENT"]
    assert rows[0]["debit"] == fx["supplier_order"].total_amount
    assert rows[1]["credit"] == Decimal("5000000.00")
    assert rows[-1]["balance"] == fx["supplier_order"].total_amount - Decimal("5000000.00")


# ---------------------------------------------------------------------------
# TransporterStatementQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_transporter_statement_lists_settlements_for_the_transporter():
    admin_user = _make_admin("TRANSSTMT")
    fx = _make_full_trip("TRANSSTMT", admin_user)
    TransportPayment.objects.create(
        trip=fx["trip"],
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.NEGOTIATED,
        base_amount=Decimal("1500000.00"),
        deduction_amount=Decimal("100000.00"),
    )

    rows = TransporterStatementQuery.run(transporter_id=fx["transporter"].id)

    assert len(rows) == 1
    assert rows[0]["trip_reference"] == fx["trip"].reference
    assert rows[0]["base_amount"] == Decimal("1500000.00")
    assert rows[0]["net_amount"] == Decimal("1400000.00")


# ---------------------------------------------------------------------------
# TruckHistoryQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_truck_history_lists_trips_with_margin_when_sold():
    admin_user = _make_admin("TRUCKHIST")
    fx = _make_full_trip("TRUCKHIST", admin_user)

    rows = TruckHistoryQuery.run(truck_id=fx["truck"].id)

    assert len(rows) == 1
    assert rows[0]["trip_reference"] == fx["trip"].reference
    assert rows[0]["current_margin"] is not None


@pytest.mark.django_db
def test_truck_history_margin_is_none_without_a_sale():
    admin_user = _make_admin("TRUCKNOSALE")
    fx = _make_full_trip("TRUCKNOSALE", admin_user, status=Trip.Status.IN_TRANSIT, with_sale=False)

    rows = TruckHistoryQuery.run(truck_id=fx["truck"].id)

    assert rows[0]["current_margin"] is None


# ---------------------------------------------------------------------------
# TripReportQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_trip_report_lists_operational_summary_filtered_by_status():
    admin_user = _make_admin("TRIPREPORT")
    delivered = _make_full_trip("TRIPREPDEL", admin_user, status=Trip.Status.DELIVERED)
    _make_full_trip("TRIPREPTRANSIT", admin_user, status=Trip.Status.IN_TRANSIT, with_sale=False)

    rows = TripReportQuery.run(status=Trip.Status.DELIVERED)

    assert [r["trip_reference"] for r in rows] == [delivered["trip"].reference]


# ---------------------------------------------------------------------------
# FuelStockReportQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_fuel_stock_report_breaks_down_reliquat_and_unsold_plus_total():
    admin_user = _make_admin("STOCKREPORT")
    fx = _make_full_trip("STOCKREPORT", admin_user, status=Trip.Status.IN_TRANSIT, with_sale=False)

    rows = FuelStockReportQuery.run()

    components = {r["component"] for r in rows}
    assert "SUPPLIER_RELIQUAT" in components
    assert "LOADED_UNSOLD" in components
    assert rows[-1]["component"] == "TOTAL"
    reliquat_row = next(r for r in rows if r["reference"] == fx["supplier_order"].reference)
    assert reliquat_row["quantity"] == Decimal("455000.00")  # 500000 - 45000 cession
    unsold_row = next(r for r in rows if r["reference"] == fx["trip"].reference)
    assert unsold_row["quantity"] == Decimal("45000.00")


# ---------------------------------------------------------------------------
# LossReportQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_loss_report_lists_delivery_controls_with_chargeable_loss():
    admin_user = _make_admin("LOSSREPORT")
    fx = _make_full_trip("LOSSREPORT", admin_user)
    control = DeliveryControl.objects.create(
        trip=fx["trip"],
        loaded_quantity=Decimal("45000.00"),
        received_quantity=Decimal("44850.00"),
        tolerance_quantity=Decimal("100.00"),
        control_date="2026-08-18",
        controller=admin_user,
        method=DeliveryControl.Method.MANUAL_GAUGE,
    )

    rows = LossReportQuery.run()

    assert len(rows) == 1
    assert rows[0]["trip_reference"] == fx["trip"].reference
    assert rows[0]["loss_quantity"] == control.loss_quantity
    assert rows[0]["chargeable_loss_quantity"] == control.chargeable_loss_quantity


# ---------------------------------------------------------------------------
# MarginReportQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_margin_report_lists_current_margin_per_sold_trip():
    admin_user = _make_admin("MARGINREPORT")
    fx = _make_full_trip("MARGINREPORT", admin_user)
    _make_full_trip("MARGINNOSALE", admin_user, status=Trip.Status.IN_TRANSIT, with_sale=False)

    rows = MarginReportQuery.run()

    assert len(rows) == 1
    assert rows[0]["trip_reference"] == fx["trip"].reference
    assert rows[0]["client"] == fx["customer"].name
    assert rows[0]["current_margin"] is not None


# ---------------------------------------------------------------------------
# TreasuryStatementQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_treasury_statement_excludes_transfer_legs_but_keeps_correct_balance():
    admin_user = _make_admin("TREASSTMT")
    account = CashAccount.objects.create(name="Cash TREASSTMT", opening_balance=Decimal("0.00"))
    other_account = CashAccount.objects.create(name="Cash TREASSTMT DEST")

    TreasuryTransaction.objects.create(
        cash_account=account,
        type=TreasuryTransaction.Type.MONEY_IN,
        amount=Decimal("1000000.00"),
        date="2026-08-18",
        recorded_by=admin_user,
    )
    # A transfer leg out of `account`: must not appear as its own row, but
    # must still count in the running balance shown on the remaining rows.
    TreasuryTransaction.objects.create(
        cash_account=account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("200000.00"),
        date="2026-08-19",
        is_transfer=True,
        recorded_by=admin_user,
    )
    TreasuryTransaction.objects.create(
        cash_account=account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("150000.00"),
        date="2026-08-20",
        recorded_by=admin_user,
    )

    rows = TreasuryStatementQuery.run(cash_account_id=account.id)

    assert len(rows) == 2  # the transfer leg is excluded from the listed rows
    assert rows[-1]["balance"] == Decimal("650000.00")  # 1,000,000 - 200,000 - 150,000

# The 6 remaining V1 report types from ERP_Specification.md Section 37 not
# already covered by Etape 4's 9 named classes (purchase/sales/expense
# reports, plus the 3 outstanding reports - TreasuryStatementQuery already
# covers "bank statement"/"cash statement" via one parametrised class).
# docs/PHASE_6_PLAN.md Etape 4/6.

from decimal import Decimal

import pytest

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    SupplierAdvance,
    SupplierPayment,
    TransportPayment,
)
from apps.finance.services import ControlledDebtPaymentService
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.reports.queries.customer_outstanding_report import CustomerOutstandingReportQuery
from apps.reports.queries.expense_report import ExpenseReportQuery
from apps.reports.queries.purchase_report import PurchaseReportQuery
from apps.reports.queries.sales_report import SalesReportQuery
from apps.reports.queries.supplier_outstanding_report import SupplierOutstandingReportQuery
from apps.reports.queries.transporter_outstanding_report import TransporterOutstandingReportQuery
from apps.sales.models import Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role
    )


def _make_full_trip(suffix, admin_user, with_sale=True):
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-QUERY2-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-QUERY2-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("45000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-QUERY2-{suffix}",
        tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-QUERY2-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=product,
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference=f"BL-QUERY2-{suffix}",
        status=Trip.Status.DELIVERED,
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
        "trip": trip,
        "customer": customer,
        "sale": sale,
    }


@pytest.mark.django_db
def test_purchase_report_lists_supplier_orders():
    admin_user = _make_admin("PURCHASE")
    fx = _make_full_trip("PURCHASE", admin_user, with_sale=False)

    rows = PurchaseReportQuery.run()

    assert any(r["reference"] == fx["supplier_order"].reference for r in rows)
    row = next(r for r in rows if r["reference"] == fx["supplier_order"].reference)
    assert row["total_amount"] == fx["supplier_order"].total_amount


@pytest.mark.django_db
def test_sales_report_lists_sales():
    admin_user = _make_admin("SALESREPORT")
    fx = _make_full_trip("SALESREPORT", admin_user)

    rows = SalesReportQuery.run()

    assert len(rows) == 1
    assert rows[0]["trip_reference"] == fx["trip"].reference
    assert rows[0]["subtotal"] == fx["sale"].subtotal


@pytest.mark.django_db
def test_expense_report_lists_non_cancelled_expenses():
    Expense.objects.create(
        category=Expense.Category.ROAD,
        amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )
    Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("75000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
        status=Expense.Status.CANCELLED,
    )

    rows = ExpenseReportQuery.run()

    assert len(rows) == 1
    assert rows[0]["category"] == Expense.Category.ROAD


@pytest.mark.django_db
def test_customer_outstanding_report_matches_invoice_minus_payments():
    admin_user = _make_admin("CUSTOUT")
    fx = _make_full_trip("CUSTOUT", admin_user)
    from apps.sales.models import Invoice

    Invoice.objects.create(
        invoice_number="INV-QUERY2-CUSTOUT",
        sale=fx["sale"],
        status=Invoice.Status.VALIDATED,
        total_amount=fx["sale"].subtotal,
        issued_date="2026-08-18",
    )
    CustomerPayment.objects.create(
        customer=fx["customer"],
        amount=Decimal("1000000.00"),
        payment_date="2026-08-19",
        method=CustomerPayment.Method.CASH,
        cash_account=CashAccount.objects.create(name="Cash CUSTOUT"),
        recorded_by=admin_user,
    )

    rows = CustomerOutstandingReportQuery.run()
    row = next(r for r in rows if r["customer"] == fx["customer"].name)
    assert row["outstanding"] == fx["sale"].subtotal - Decimal("1000000.00")


@pytest.mark.django_db
def test_supplier_outstanding_report_matches_purchases_minus_payments():
    admin_user = _make_admin("SUPPOUT")
    fx = _make_full_trip("SUPPOUT", admin_user, with_sale=False)
    # supplier_order must be set: describe_supplier() (the new single source
    # of truth this report is now aligned on) computes remaining per-order,
    # exactly like the real "Nouveau paiement" flow always links its
    # SupplierPayment rows to the order they settle
    # (ControlledDebtPaymentService._record_supplier_payments) - an
    # unlinked/orphan payment is not a real scenario this report needs to
    # net off.
    SupplierPayment.objects.create(
        supplier=fx["supplier"],
        supplier_order=fx["supplier_order"],
        amount=Decimal("2000000.00"),
        payment_date="2026-08-19",
        method=SupplierPayment.Method.CASH,
        cash_account=CashAccount.objects.create(name="Cash SUPPOUT"),
        recorded_by=admin_user,
    )

    rows = SupplierOutstandingReportQuery.run()
    row = next(r for r in rows if r["supplier"] == fx["supplier"].name)
    # Business rule reversal (client request, 2026-09-10): debt is the full
    # confirmed order (500,000 L x 600 = 300,000,000), due immediately on
    # confirmation - independent of how much of it fx["trip"] has loaded.
    assert fx["trip"].quantity_loaded == Decimal("45000.00")
    assert row["outstanding"] == Decimal("300000000.00") - Decimal("2000000.00")


@pytest.mark.django_db
def test_supplier_outstanding_report_only_counts_confirmed_orders():
    admin_user = _make_admin("SUPCONFONLY")
    supplier = Supplier.objects.create(name="Supplier Report Confirmed Only")
    product = Product.objects.get(code="gasoil")
    confirmed_order = SupplierOrder.objects.create(
        reference="SO-QUERY2-SUPCONFONLY-A",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("500.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    SupplierOrder.objects.create(
        reference="SO-QUERY2-SUPCONFONLY-B",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-19",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("500.0000"),
        status=SupplierOrder.Status.CANCELLED,
        created_by=admin_user,
    )
    SupplierOrder.objects.create(
        reference="SO-QUERY2-SUPCONFONLY-C",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-20",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("500.0000"),
        status=SupplierOrder.Status.DRAFT,
        created_by=admin_user,
    )
    # Bug fix (client business rule, confirmed 2026-09-06): debt now needs
    # quantity actually loaded, not just a CONFIRMED status - fully load
    # confirmed_order so this test still exercises what it's actually
    # about (CONFIRMED counted, CANCELLED/DRAFT excluded), unchanged.
    confirmed_cession = CessionLetter.objects.create(
        reference="CL-QUERY2-SUPCONFONLY", supplier_order=confirmed_order,
        authorized_quantity=confirmed_order.quantity_litres, issue_date="2026-08-18",
        created_by=admin_user,
    )
    confirmed_truck = Truck.objects.create(
        internal_id="TRK-QUERY2-SUPCONFONLY", tractor_registration="SUPCONFONLY-TRAC",
        tanker_registration="SUPCONFONLY-TANK", capacity_litres=Decimal("45000.00"),
    )
    Trip.objects.create(
        reference="TRIP-QUERY2-SUPCONFONLY", truck=confirmed_truck,
        transporter=Transporter.objects.create(name="Transporteur SUPCONFONLY"),
        supplier=supplier, supplier_order=confirmed_order, cession_letter=confirmed_cession,
        product=product, quantity_loaded=confirmed_order.quantity_litres,
        loading_date="2026-08-18", bl_reference="BL-QUERY2-SUPCONFONLY", created_by=admin_user,
    )

    rows = SupplierOutstandingReportQuery.run()
    row = next(r for r in rows if r["supplier"] == supplier.name)

    assert row["outstanding"] == confirmed_order.total_amount


@pytest.mark.django_db
def test_supplier_outstanding_report_nets_out_advance_consumption():
    admin_user = _make_admin("SUPOUTADV")
    supplier = Supplier.objects.create(name="Supplier SUPOUTADV", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Cash SUPOUTADV")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("2000000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    order = SupplierOrder.objects.create(
        reference="SO-QUERY2-SUPOUTADV", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 300000000, advance created BEFORE confirmation so it's consumed at confirm time
    # Bug fix (client business rule, confirmed 2026-09-06): fully load the
    # order so its debt equals the full total_amount this test's assertion
    # is built on - this test is about advance-consumption netting, not
    # about the loaded-vs-purchased debt timing rule itself.
    cession = CessionLetter.objects.create(
        reference="CL-QUERY2-SUPOUTADV", supplier_order=order,
        authorized_quantity=order.quantity_litres, issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id="TRK-QUERY2-SUPOUTADV", tractor_registration="SUPOUTADV-TRAC",
        tanker_registration="SUPOUTADV-TANK", capacity_litres=Decimal("45000.00"),
    )
    Trip.objects.create(
        reference="TRIP-QUERY2-SUPOUTADV", truck=truck,
        transporter=Transporter.objects.create(name="Transporteur SUPOUTADV"),
        supplier=supplier, supplier_order=order, cession_letter=cession,
        product=product, quantity_loaded=order.quantity_litres,
        loading_date="2026-08-18", bl_reference="BL-QUERY2-SUPOUTADV", created_by=admin_user,
    )

    rows = SupplierOutstandingReportQuery.run()
    row = next(r for r in rows if r["supplier"] == supplier.name)
    assert row["outstanding"] == order.total_amount - Decimal("2000000.00")


@pytest.mark.django_db
def test_transporter_outstanding_report_sums_unpaid_settlements():
    admin_user = _make_admin("TRANSOUT")
    fx = _make_full_trip("TRANSOUT", admin_user)
    TransportPayment.objects.create(
        trip=fx["trip"],
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.NEGOTIATED,
        base_amount=Decimal("1500000.00"),
        status=TransportPayment.Status.PAYABLE,
    )

    rows = TransporterOutstandingReportQuery.run()
    row = next(r for r in rows if r["transporter"] == fx["transporter"].name)
    assert row["outstanding"] == Decimal("1500000.00")


@pytest.mark.django_db
def test_transporter_outstanding_report_nets_amount_already_paid():
    """Bug fix: "outstanding" must be net_amount minus what was actually
    disbursed via the TreasuryTransaction ledger - the same reste-a-payer
    ControlledDebtPaymentService.describe_transporter shows on the Nouveau
    paiement screen - not the raw settlement total."""
    admin_user = _make_admin("TRANSOUTNET")
    fx = _make_full_trip("TRANSOUTNET", admin_user)
    TransportPayment.objects.create(
        trip=fx["trip"],
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.NEGOTIATED,
        base_amount=Decimal("5670000.00"),
        status=TransportPayment.Status.PAYABLE,
    )
    bank = BankAccount.objects.create(
        name="TransOutNet Bank", opening_balance=Decimal("10000000.00")
    )

    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.TRANSPORTER,
        debt_id=fx["transporter"].id,
        bank_account_id=bank.id,
        amount=Decimal("33000.00"),
        date="2026-08-19",
        reference="TRANSOUTNET-PAY",
        actor=admin_user,
    )

    rows = TransporterOutstandingReportQuery.run()
    row = next(r for r in rows if r["transporter"] == fx["transporter"].name)
    assert row["outstanding"] == Decimal("5637000.00")

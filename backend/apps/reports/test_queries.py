# Report query classes tests (docs/PHASE_6_PLAN.md Etape 4/6;
# ERP_Implementation_Experience_Guide.md Section 9.7).

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ExpenseAllocation,
    Shareholder,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    SupplierPayment,
    TransportDeduction,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import (
    ShareholderContributionService,
    ShareholderDistributionService,
    ShareholderLedgerService,
    ShareholderProfitPreviewService,
    ShareholderWithdrawalService,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.reports.queries.customer_statement import CustomerStatementQuery
from apps.reports.queries.fuel_stock_report import FuelStockReportQuery
from apps.reports.queries.loss_report import LossReportQuery
from apps.reports.queries.margin_report import MarginReportQuery
from apps.reports.queries.shareholder_statement import ShareholderStatementQuery
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


def _allocate_expense(trip, category, amount, suffix, status=Expense.Status.UNPAID):
    expense = Expense.objects.create(
        category=category,
        amount=amount,
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
        status=status,
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=amount,
    )
    return expense


@pytest.mark.django_db
def test_margin_report_row_includes_expanded_cost_breakdown_fields():
    admin_user = _make_admin("MARGINBREAKDOWN")
    fx = _make_full_trip("MARGINBREAKDOWN", admin_user)
    trip = fx["trip"]

    TransportPayment.objects.create(
        trip=trip,
        transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("800000.00"),
    )
    _allocate_expense(trip, Expense.Category.CUSTOMS, Decimal("1200000.00"), "CUST")
    _allocate_expense(trip, Expense.Category.TRANSIT, Decimal("300000.00"), "TRANSIT")
    # Bug fix (2026-09-03 recette manuelle): ROAD_TRANSIT ("Transit
    # routiere") used to fall into additional_costs - it must now get its
    # own road_transit_cost line, same treatment as ROAD/LOADING below.
    _allocate_expense(trip, Expense.Category.ROAD_TRANSIT, Decimal("50000.00"), "ROADTRANSIT")
    _allocate_expense(trip, Expense.Category.ROAD, Decimal("50000.00"), "ROAD")
    _allocate_expense(trip, Expense.Category.LOADING, Decimal("40000.00"), "LOADING")
    _allocate_expense(trip, Expense.Category.OTHER, Decimal("20000.00"), "OTHER")
    # A TRANSPORT-category Expense must never be double-counted against
    # transport_cost (which already comes from TransportPayment above).
    _allocate_expense(trip, Expense.Category.TRANSPORT, Decimal("15000.00"), "TRANSPORTEXP")
    # Cancelled expenses must never be counted.
    _allocate_expense(
        trip,
        Expense.Category.OTHER,
        Decimal("999999.00"),
        "CANCELLED",
        status=Expense.Status.CANCELLED,
    )

    rows = MarginReportQuery.run()
    row = next(r for r in rows if r["trip_reference"] == trip.reference)

    for field in MarginReportQuery.FIELDS:
        assert field in row

    assert row["quantity"] == trip.quantity_loaded
    assert row["supplier_unit_price"] == trip.supplier_order.unit_price
    assert row["transport_cost"] == Decimal("800000.00")
    assert row["customs_cost"] == Decimal("1200000.00")
    assert row["transit_cost"] == Decimal("300000.00")
    assert row["road_transit_cost"] == Decimal("50000.00")
    assert row["border_cost"] == Decimal("50000.00")
    assert row["loading_cost"] == Decimal("40000.00")
    # additional_costs = other only, excluding
    # customs/transit/road_transit/transport/road/loading
    assert row["additional_costs"] == Decimal("20000.00")
    assert row["unit_selling_price"] == trip.sale.unit_selling_price

    from apps.reports.services.profit import TripProfitService

    breakdown = TripProfitService.get_cost_breakdown(trip)
    assert row["unit_cost"] == breakdown["unit_cost"]
    assert row["unit_profit"] == breakdown["unit_profit"]
    assert row["current_margin"] == breakdown["margin"]


@pytest.mark.django_db
def test_margin_report_period_total_equals_sum_of_row_margins():
    admin_user = _make_admin("MARGINPERIOD")
    fx_in_1 = _make_full_trip("MARGINPERIODA", admin_user)
    fx_in_1["trip"].loading_date = "2026-08-05"
    fx_in_1["trip"].save(update_fields=["loading_date"])
    fx_in_2 = _make_full_trip("MARGINPERIODB", admin_user)
    fx_in_2["trip"].loading_date = "2026-08-20"
    fx_in_2["trip"].save(update_fields=["loading_date"])
    fx_out = _make_full_trip("MARGINPERIODC", admin_user)
    fx_out["trip"].loading_date = "2026-07-01"
    fx_out["trip"].save(update_fields=["loading_date"])

    from apps.reports.services.profit import TripProfitService

    expected_total = TripProfitService.get_cost_breakdown(fx_in_1["trip"])["margin"] + (
        TripProfitService.get_cost_breakdown(fx_in_2["trip"])["margin"]
    )

    rows = MarginReportQuery.run(date_from="2026-08-01", date_to="2026-08-31")

    assert {r["trip_reference"] for r in rows} == {
        fx_in_1["trip"].reference,
        fx_in_2["trip"].reference,
    }
    period_total = sum((r["current_margin"] for r in rows), Decimal("0.00"))
    assert period_total == expected_total


# ---------------------------------------------------------------------------
# ShareholderProfitPreviewService (design doc
# 2026-08-26-benefices-associes-refinement-design.md) - lives in
# apps.finance.services but tested here to reuse _make_full_trip rather
# than duplicate its fixture setup; the service itself delegates entirely
# to MarginReportQuery, so these tests exercise that same integration.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_shareholder_profit_preview_matches_margin_report_current_margin_sum():
    admin_user = _make_admin("PREVIEWSUM")
    fx = _make_full_trip("PREVIEWSUM", admin_user)
    a = Shareholder.objects.create(name="Preview A", participation_percent=Decimal("80"))
    b = Shareholder.objects.create(name="Preview B", participation_percent=Decimal("20"))

    preview = ShareholderProfitPreviewService.get_preview()

    expected_total = sum(
        (r["current_margin"] for r in MarginReportQuery.run()), Decimal("0.00")
    )
    assert preview["current_profit"] == expected_total

    shares_by_id = {s["shareholder_id"]: s for s in preview["shareholders"]}
    assert shares_by_id[a.id]["indicative_share"] == (
        expected_total * Decimal("80") / Decimal("100")
    ).quantize(Decimal("0.01"))
    assert shares_by_id[b.id]["indicative_share"] == (
        expected_total * Decimal("20") / Decimal("100")
    ).quantize(Decimal("0.01"))

    # Read-only: no distribution/share rows are created by a preview.
    assert ShareholderProfitDistribution.objects.count() == 0
    # Fixture sanity: the trip really has a sale to margin.
    assert fx["sale"] is not None


# Bug fix (2026-09-03 recette manuelle, page Benefices): with no general
# expenses in the period, net_profit == operational_profit == current_profit,
# so the test above can't tell current_profit-based shares apart from
# net_profit-based ones - this one adds a paid general expense specifically
# to prove indicative_share is computed from net_profit, not the raw
# operational/current profit (850 000 operational - 100 000 dep. generales
# payees = 750 000 net -> repartition must start from 750 000).
@pytest.mark.django_db
def test_shareholder_profit_preview_indicative_share_uses_net_profit_not_operational():
    admin_user = _make_admin("PREVIEWNET")
    fx = _make_full_trip("PREVIEWNET", admin_user)
    shareholder = Shareholder.objects.create(
        name="Preview Net", participation_percent=Decimal("100")
    )

    from apps.reports.services.profit import TripProfitService

    operational_profit = TripProfitService.get_cost_breakdown(fx["trip"])["margin"]
    general_expense_paid = Decimal("100000.00")
    _general_expense(general_expense_paid, "PREVIEWNET", fx["trip"].loading_date)
    expected_net_profit = operational_profit - general_expense_paid

    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["operational_profit"] == operational_profit
    assert preview["net_profit"] == expected_net_profit
    assert preview["net_profit"] != preview["operational_profit"]

    share = next(
        s for s in preview["shareholders"] if s["shareholder_id"] == shareholder.id
    )
    assert share["indicative_share"] == expected_net_profit.quantize(Decimal("0.01"))
    # The old (buggy) basis would have given the operational figure instead.
    assert share["indicative_share"] != operational_profit.quantize(Decimal("0.01"))


@pytest.mark.django_db
def test_shareholder_profit_preview_excludes_inactive_shareholders():
    admin_user = _make_admin("PREVIEWINACT")
    _make_full_trip("PREVIEWINACT", admin_user)
    Shareholder.objects.create(
        name="Inactive Preview", participation_percent=Decimal("50"), is_active=False
    )

    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["shareholders"] == []


@pytest.mark.django_db
def test_shareholder_profit_preview_defaults_to_period_after_last_validated_distribution():
    admin_user = _make_admin("PREVIEWPERIOD")
    fx_old = _make_full_trip("PREVIEWPERIODOLD", admin_user)
    fx_old["trip"].loading_date = "2026-07-10"
    fx_old["trip"].save(update_fields=["loading_date"])
    fx_new = _make_full_trip("PREVIEWPERIODNEW", admin_user)
    fx_new["trip"].loading_date = "2026-08-15"
    fx_new["trip"].save(update_fields=["loading_date"])
    Shareholder.objects.create(name="Preview Period", participation_percent=Decimal("100"))

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("1.00"),
        actor=admin_user,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, admin_user)

    preview = ShareholderProfitPreviewService.get_preview()

    from apps.reports.services.profit import TripProfitService

    expected_total = TripProfitService.get_cost_breakdown(fx_new["trip"])["margin"]
    assert preview["current_profit"] == expected_total

    from datetime import date

    assert preview["period_start"] == date(2026, 8, 1)


# ---------------------------------------------------------------------------
# ShareholderProfitPreviewService.get_preview - operational vs net profit
# (Phase 4, docs/superpowers/specs/2026-09-02-business-corrections-6-phases-
# design.md): operational_profit is the trip-only margin (unchanged
# formula, same as current_profit above); general_expenses_paid sums only
# unallocated (general) Expense rows actually PAID in the period;
# net_profit = operational_profit - general_expenses_paid.
# ---------------------------------------------------------------------------


def _general_expense(amount, suffix, date_, status=Expense.Status.PAID):
    return Expense.objects.create(
        category=Expense.Category.OTHER,
        amount=amount,
        calculation_method=Expense.CalculationMethod.MANUAL,
        date=date_,
        status=status,
    )


@pytest.mark.django_db
def test_net_profit_equals_operational_profit_without_general_expenses():
    admin_user = _make_admin("NETNOEXP")
    _make_full_trip("NETNOEXP", admin_user)

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    assert preview["general_expenses_paid"] == Decimal("0.00")
    assert preview["net_profit"] == preview["operational_profit"]


@pytest.mark.django_db
def test_net_profit_subtracts_general_expense_paid_in_period():
    admin_user = _make_admin("NETWITHEXP")
    _make_full_trip("NETWITHEXP", admin_user)
    _general_expense(Decimal("150000.00"), "NETWITHEXP", "2026-08-20")

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    assert preview["general_expenses_paid"] == Decimal("150000.00")
    assert preview["net_profit"] == preview["operational_profit"] - Decimal("150000.00")


@pytest.mark.django_db
def test_general_expense_outside_period_is_not_counted():
    admin_user = _make_admin("NETOUTPERIOD")
    _make_full_trip("NETOUTPERIOD", admin_user)
    _general_expense(Decimal("150000.00"), "NETOUTPERIOD", "2026-07-01")

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    assert preview["general_expenses_paid"] == Decimal("0.00")
    assert preview["net_profit"] == preview["operational_profit"]


@pytest.mark.django_db
def test_trip_expense_stays_in_operational_profit_and_is_not_double_counted():
    admin_user = _make_admin("NETTRIPEXP")
    fx = _make_full_trip("NETTRIPEXP", admin_user)
    _allocate_expense(
        fx["trip"], Expense.Category.CUSTOMS, Decimal("300000.00"), "NETTRIPEXP"
    )

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    from apps.reports.services.profit import TripProfitService

    expected_margin = TripProfitService.get_cost_breakdown(fx["trip"])["margin"]
    assert preview["operational_profit"] == expected_margin
    assert preview["general_expenses_paid"] == Decimal("0.00")
    assert preview["net_profit"] == expected_margin


@pytest.mark.django_db
def test_general_expenses_paid_ignores_unpaid_and_allocated_expenses():
    admin_user = _make_admin("NETMIX")
    fx = _make_full_trip("NETMIX", admin_user)
    _allocate_expense(fx["trip"], Expense.Category.CUSTOMS, Decimal("300000.00"), "NETMIX")
    _general_expense(Decimal("50000.00"), "NETMIXUNPAID", "2026-08-15", status=Expense.Status.UNPAID)
    paid = _general_expense(Decimal("75000.00"), "NETMIXPAID", "2026-08-16")

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    assert preview["general_expenses_paid"] == paid.amount


@pytest.mark.django_db
def test_profit_after_capital_equals_net_profit_when_no_capital_contributed():
    admin_user = _make_admin("PAC-NOCAP")
    _make_full_trip("PAC-NOCAP", admin_user)
    Shareholder.objects.create(
        name="PAC No Cap", participation_percent=Decimal("100"), contribution=Decimal("0.00")
    )

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    assert preview["total_capital_contributed"] == Decimal("0.00")
    assert preview["profit_after_capital"] == preview["net_profit"]


@pytest.mark.django_db
def test_profit_after_capital_subtracts_total_capital_contributed():
    admin_user = _make_admin("PAC-CAP")
    _make_full_trip("PAC-CAP", admin_user)
    Shareholder.objects.create(
        name="PAC Cap A", participation_percent=Decimal("60"), contribution=Decimal("2000000.00")
    )
    Shareholder.objects.create(
        name="PAC Cap B", participation_percent=Decimal("40"), contribution=Decimal("500000.00")
    )
    bank = BankAccount.objects.create(name="PAC Bank", opening_balance=Decimal("0.00"))
    contributor = Shareholder.objects.create(
        name="PAC Cap C", participation_percent=Decimal("0"), contribution=Decimal("0.00")
    )
    ShareholderContributionService.record_contribution(
        shareholder_id=contributor.id,
        amount=Decimal("1000000.00"),
        date="2026-08-10",
        actor=admin_user,
        attachment=SimpleUploadedFile("proof.jpg", b"fake-bytes", content_type="image/jpeg"),
        bank_account_id=bank.id,
    )

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    assert preview["total_capital_contributed"] == Decimal("3500000.00")
    assert preview["profit_after_capital"] == (
        preview["net_profit"] - Decimal("3500000.00")
    )
    # net_profit itself must stay exactly what it was before capital ever entered the picture.
    assert preview["net_profit"] == preview["operational_profit"]


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


# ---------------------------------------------------------------------------
# ShareholderStatementQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_shareholder_statement_lists_profit_shares_withdrawals_and_loans():
    admin_user = _make_admin("SHRSTMT")
    shareholder = Shareholder.objects.create(name="Assoc SHRSTMT", participation_percent=Decimal("100"))
    other = Shareholder.objects.create(name="Assoc SHRSTMT2", participation_percent=Decimal("0"))
    cash_account = CashAccount.objects.create(
        name="Cash SHRSTMT", opening_balance=Decimal("1000000.00")
    )

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("1000000.00"),
        actor=admin_user,
    )
    share = ShareholderProfitShare.objects.get(distribution=distribution, shareholder=shareholder)
    # Goes through the service (not a raw ShareholderWithdrawal.objects.create)
    # so amount_withdrawn actually syncs onto `share` - that field is only
    # ever written by sync_amount_withdrawn(), which the service calls.
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("300000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=admin_user,
    )
    loan_given = ShareholderLoan.objects.create(
        lender=shareholder, borrower=other, amount=Decimal("50000.00"), date="2026-08-02"
    )
    loan_given.amount_repaid = Decimal("20000.00")
    loan_given.save()

    rows = ShareholderStatementQuery.run(shareholder_id=shareholder.id)

    assert [r["type"] for r in rows] == ["PROFIT_SHARE", "WITHDRAWAL", "LOAN_GIVEN"]
    assert rows[0]["credit"] == Decimal("1000000.00")
    assert rows[1]["debit"] == Decimal("300000.00")
    assert rows[2]["credit"] == Decimal("30000.00")  # 50,000 - 20,000 repaid = remaining_amount
    assert rows[-1]["balance"] == ShareholderLedgerService.get_available_balance(shareholder.id)

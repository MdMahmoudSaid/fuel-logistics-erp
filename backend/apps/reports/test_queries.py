# Report query classes tests (docs/PHASE_6_PLAN.md Etape 4/6;
# ERP_Implementation_Experience_Guide.md Section 9.7).

from datetime import date
from decimal import Decimal

import pytest

from apps.finance.testing_helpers import seed_net_profit
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
    ShareholderContribution,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    SupplierPayment,
    TransportDeduction,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import (
    TreasuryService,
    ControlledDebtPaymentService,
    PaymentAllocationService,
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
from apps.trips.services import DeliveryService, TripWorkflowService
from apps.trips.tests import FULL_SEQUENCE_AFTER_ASSIGNED


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role
    )


def _sold_on(trip, day):
    """Date a test sale on `day` - since 2026-10-05 a trip's profit/revenue
    belongs to its SALE date, so tests that place a trip in a date range
    move its sale there too."""
    from datetime import date as _date, datetime as _datetime, time as _time

    from django.utils import timezone as _tz

    Sale.objects.filter(trip=trip).update(
        created_at=_tz.make_aware(_datetime.combine(_date.fromisoformat(str(day)), _time(12)))
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
        _sold_on(trip, trip.loading_date)
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

    # Running-balance statement (2026-10-11): the settlement, net of its
    # deduction, is what the company owes.
    assert len(rows) == 1
    assert rows[0]["type"] == "SETTLEMENT"
    assert rows[0]["reference"] == fx["trip"].reference
    assert rows[0]["debit"] == Decimal("1400000.00")
    assert rows[0]["balance"] == Decimal("1400000.00")


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
    _sold_on(fx_in_1["trip"], "2026-08-05")
    fx_in_2 = _make_full_trip("MARGINPERIODB", admin_user)
    fx_in_2["trip"].loading_date = "2026-08-20"
    fx_in_2["trip"].save(update_fields=["loading_date"])
    _sold_on(fx_in_2["trip"], "2026-08-20")
    fx_out = _make_full_trip("MARGINPERIODC", admin_user)
    fx_out["trip"].loading_date = "2026-07-01"
    fx_out["trip"].save(update_fields=["loading_date"])
    _sold_on(fx_out["trip"], "2026-07-01")

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

    # Business decision (2026-09-04): indicative_share is distributable_
    # result-based (not current_profit/margin-based) - verified here as a
    # pure percent-split check against the preview's own distributable_
    # result field, since that figure's own correctness (fond de roulement,
    # debts, capital) is already covered by test_working_capital.py.
    shares_by_id = {s["shareholder_id"]: s for s in preview["shareholders"]}
    assert shares_by_id[a.id]["indicative_share"] == (
        preview["distributable_result"] * Decimal("80") / Decimal("100")
    ).quantize(Decimal("0.01"))
    assert shares_by_id[b.id]["indicative_share"] == (
        preview["distributable_result"] * Decimal("20") / Decimal("100")
    ).quantize(Decimal("0.01"))

    # Read-only: no distribution/share rows are created by a preview.
    assert ShareholderProfitDistribution.objects.count() == 0
    # Fixture sanity: the trip really has a sale to margin.
    assert fx["sale"] is not None


# Business decision (2026-09-04, distribution basis change): a
# shareholder's indicative_share must be based on distributable_result -
# NOT net_profit (rentability) and NOT operational_profit. This test proves
# the distinction: with a paid general expense, operational_profit and
# net_profit differ from each other (as before), and - because
# _make_full_trip seeds no treasury/receivables/capital -
# distributable_result is 0 (gross - capital = 0 - 0) regardless of how
# profitable the trip was. indicative_share must therefore be exactly 0,
# not the (nonzero) net_profit or operational_profit figure the old,
# now-reverted basis would have produced.
@pytest.mark.django_db
def test_shareholder_profit_preview_indicative_share_uses_distributable_result():
    admin_user = _make_admin("PREVIEWDIST")
    fx = _make_full_trip("PREVIEWDIST", admin_user)
    shareholder = Shareholder.objects.create(
        name="Preview Dist", participation_percent=Decimal("100")
    )

    from apps.reports.services.profit import TripProfitService

    operational_profit = TripProfitService.get_cost_breakdown(fx["trip"])["margin"]
    general_expense_paid = Decimal("100000.00")
    _general_expense(general_expense_paid, "PREVIEWDIST", fx["trip"].loading_date)
    expected_net_profit = operational_profit - general_expense_paid

    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["operational_profit"] == operational_profit
    assert preview["net_profit"] == expected_net_profit
    assert preview["net_profit"] != preview["operational_profit"]
    assert preview["net_profit"] != Decimal("0.00")  # fixture sanity: the trip is profitable

    # Client decision 2026-09-25: the distributable amount IS the net
    # profit after general expenses. The debts/capital-based figure stays
    # exposed separately (no treasury/receivables/capital seeded -> 0) and
    # no longer drives it.
    assert preview["distributable_result"] == expected_net_profit
    assert preview["result_after_debts_and_capital"] == Decimal("0.00")

    share = next(
        s for s in preview["shareholders"] if s["shareholder_id"] == shareholder.id
    )
    assert share["indicative_share"] == expected_net_profit.quantize(Decimal("0.01"))


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
def test_shareholder_profit_preview_default_is_all_time_minus_validated_distributions():
    """Client request 2026-09-25: with no period, the preview covers every
    trip and subtracts every validated distribution, so what is left to
    distribute falls to zero once everything has been distributed."""
    admin_user = _make_admin("PREVIEWPERIOD")
    fx_old = _make_full_trip("PREVIEWPERIODOLD", admin_user)
    fx_old["trip"].loading_date = "2026-07-10"
    fx_old["trip"].save(update_fields=["loading_date"])
    _sold_on(fx_old["trip"], "2026-07-10")
    fx_new = _make_full_trip("PREVIEWPERIODNEW", admin_user)
    fx_new["trip"].loading_date = "2026-08-15"
    fx_new["trip"].save(update_fields=["loading_date"])
    _sold_on(fx_new["trip"], "2026-08-15")
    Shareholder.objects.create(name="Preview Period", participation_percent=Decimal("100"))

    from apps.reports.services.profit import TripProfitService

    old_margin = TripProfitService.get_cost_breakdown(fx_old["trip"])["margin"]
    new_margin = TripProfitService.get_cost_breakdown(fx_new["trip"])["margin"]

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=old_margin,
        actor=admin_user,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, admin_user)

    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["period_start"] is None
    assert preview["current_profit"] == old_margin + new_margin
    assert preview["already_validated_total"] == old_margin
    assert preview["distributable_result"] == new_margin

    # Distributing the rest empties it.
    rest = ShareholderDistributionService.create_distribution(
        period_start="2026-08-01",
        period_end="2026-08-31",
        total_profit=new_margin,
        actor=admin_user,
    )
    ShareholderDistributionService.validate_distribution(rest.id, admin_user)
    assert ShareholderProfitPreviewService.get_preview()["distributable_result"] == Decimal(
        "0.00"
    )


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
    """Client decision (2026-10-04): net_profit is now the all-time,
    distribution-aware figure (same contract as distributable_result), not
    the period-scoped one - here it still equals operational_profit only
    because this trip is the only data in the whole database, so the
    all-time and period-scoped figures coincide."""
    admin_user = _make_admin("NETNOEXP")
    _make_full_trip("NETNOEXP", admin_user)

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    assert preview["general_expenses_paid"] == Decimal("0.00")
    assert preview["net_profit"] == preview["operational_profit"]


@pytest.mark.django_db
def test_net_profit_subtracts_general_expense_paid_in_period():
    """Same coincidence as above: the expense is the only one in the
    database and falls inside the queried period, so all-time net_profit
    still matches period operational_profit minus that expense."""
    admin_user = _make_admin("NETWITHEXP")
    _make_full_trip("NETWITHEXP", admin_user)
    _general_expense(Decimal("150000.00"), "NETWITHEXP", "2026-08-20")

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    assert preview["general_expenses_paid"] == Decimal("150000.00")
    assert preview["net_profit"] == preview["operational_profit"] - Decimal("150000.00")


@pytest.mark.django_db
def test_new_general_expense_after_full_distribution_makes_available_profit_negative():
    """Closing one profit cycle must not let a later expense disappear.

    Once the full net profit has been validated and credited to shareholders,
    a new paid general expense with no new trip profit belongs to the next
    cycle. The global profit history remains intact, while the amount still
    available for distribution becomes the real negative value.
    """
    admin_user = _make_admin("POSTDISTEXP")
    fx = _make_full_trip("POSTDISTEXP", admin_user)
    Shareholder.objects.create(
        name="Post distribution shareholder",
        participation_percent=Decimal("100.00"),
    )

    from apps.reports.services.profit import TripProfitService

    earned_profit = TripProfitService.get_cost_breakdown(fx["trip"])["margin"]
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-08-01",
        period_end="2026-08-31",
        total_profit=earned_profit,
        actor=admin_user,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, admin_user)

    _general_expense(Decimal("125000.00"), "POSTDISTEXP", "2026-09-01")
    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["all_time_net_profit"] == earned_profit - Decimal("125000.00")
    assert preview["already_validated_total"] == earned_profit
    assert preview["distributable_result"] == Decimal("-125000.00")


@pytest.mark.django_db
def test_net_profit_is_all_time_and_counts_expenses_outside_the_queried_period():
    """Unlike general_expenses_paid (period-scoped), net_profit is the
    all-time undistributed figure, so a general expense dated outside the
    queried period still reduces it - the queried period only changes
    general_expenses_paid/operational_profit, not net_profit."""
    admin_user = _make_admin("NETOUTPERIOD")
    _make_full_trip("NETOUTPERIOD", admin_user)
    _general_expense(Decimal("150000.00"), "NETOUTPERIOD", "2026-07-01")

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    assert preview["general_expenses_paid"] == Decimal("0.00")
    assert preview["net_profit"] == preview["operational_profit"] - Decimal("150000.00")
    assert preview["net_profit"] == preview["distributable_result"]


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
def test_distributable_result_cancels_debts_added_into_total():
    # Client modifications (2026-09-04, third pass - confirmed bug during
    # actual recette testing): working_capital["total"] ADDS open debts
    # (see WorkingCapitalService), and distributable_result subtracts them
    # back out term by term to reach the real distributable amount - so
    # with zero treasury/receivables/capital, distributable_result is zero
    # regardless of how large _make_full_trip's open supplier debt is.
    admin_user = _make_admin("PAC-NOCAP")
    _make_full_trip("PAC-NOCAP", admin_user)
    Shareholder.objects.create(
        name="PAC No Cap", participation_percent=Decimal("100"), contribution=Decimal("0.00")
    )

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to="2026-08-31"
    )

    assert "total_capital_contributed" not in preview
    assert "profit_after_capital" not in preview
    wc = preview["working_capital"]
    assert wc["capital"] == Decimal("0.00")
    assert wc["treasury_available"] == Decimal("0.00")
    assert wc["customer_receivables"] == Decimal("0.00")
    assert wc["gross"] == Decimal("0.00")
    assert wc["supplier_debt_total"] > Decimal("0.00")
    assert wc["total"] == (
        wc["gross"] + wc["supplier_debt_total"] + wc["transporter_debt_total"]
        + wc["other_debts"] + wc["supplier_reliquat_value"]
        + wc["supplier_in_transit_value"] + wc["supplier_company_stock_value"]
    )
    assert preview["result_after_debts_and_capital"] == Decimal("0.00")


@pytest.mark.django_db
def test_distributable_result_formula_term_by_term():
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

    wc = preview["working_capital"]
    # capital = 2,000,000 + 500,000 (opening Shareholder.contribution) +
    # 1,000,000 (posted ShareholderContribution) = 3,500,000.
    assert wc["capital"] == Decimal("3500000.00")
    # The 1,000,000 contribution posted straight into "PAC Bank" - the only
    # treasury account in this scenario.
    assert wc["treasury_available"] == Decimal("1000000.00")
    assert wc["customer_receivables"] == Decimal("0.00")
    # Formula C (docs/superpowers/specs/2026-09-04-recette-corrections-
    # design.md Section 4, third pass - confirmed bug during actual recette
    # testing): total = gross + debts (debts ADDED), distributable =
    # total - debts - capital. The supplier debt _make_full_trip creates is
    # added into wc["total"] and subtracted right back out via
    # supplier_debt_total, so distributable_result reduces to gross - capital.
    assert wc["supplier_debt_total"] > Decimal("0.00")
    assert wc["total"] == (
        wc["gross"] + wc["supplier_debt_total"] + wc["transporter_debt_total"]
        + wc["other_debts"] + wc["supplier_reliquat_value"]
        + wc["supplier_in_transit_value"] + wc["supplier_company_stock_value"]
    )
    expected = (
        wc["total"] - wc["supplier_debt_total"] - wc["transporter_debt_total"]
        - wc["other_debts"] - wc["supplier_reliquat_value"] - wc["capital"]
        - wc["supplier_in_transit_value"] - wc["supplier_company_stock_value"]
    )
    assert preview["result_after_debts_and_capital"] == expected
    assert preview["result_after_debts_and_capital"] == Decimal("-2500000.00")
    # net_profit itself must stay exactly what it was before capital ever
    # entered the picture - distributable_result never feeds it back.
    assert preview["net_profit"] == preview["operational_profit"]


def _deliver_trip_with_transporter_loss(suffix, admin_user, *, received_qty, base_amount):
    """Full delivery cycle through the real services (not _make_full_trip's
    direct-ORM shortcut, which never creates a DeliveryControl at all): trip
    assigned -> delivered (defaults to full quantity_loaded, no mandatory
    quantity control) -> client verification reports `received_qty`,
    splitting any shortfall into a tolerance-absorbed part (company_absorbed_
    loss_quantity) and a transporter-chargeable part (TransportDeduction).

    The TransportPayment is created BEFORE delivery (contractual fee agreed
    at dispatch) so both sync_transport_shortage_deduction call sites
    (record_delivery, record_client_verification) find it and keep
    deduction_amount/net_amount correctly in sync as the loss is discovered -
    the transporter payment sync gap when a payment is created after the
    fact (TransportPaymentForm.vue never sends deduction_amount) is a
    separate, pre-existing issue, out of scope for this bug fix.
    """
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-{suffix}", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("45000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-{suffix}", supplier_order=supplier_order,
        authorized_quantity=Decimal("45000.00"), issue_date="2026-08-18", created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-{suffix}", tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER", capacity_litres=Decimal("45000.00"),
    )
    customer = Customer.objects.create(name=f"Client {suffix}")
    trip = Trip.objects.create(
        reference=f"TRIP-{suffix}", truck=truck, transporter=transporter, supplier=supplier,
        supplier_order=supplier_order, cession_letter=cession, product=product,
        quantity_loaded=Decimal("45000.00"), loading_date="2026-08-18",
        bl_reference=f"BL-{suffix}", client=customer, created_by=admin_user,
    )
    for target in FULL_SEQUENCE_AFTER_ASSIGNED[:-2]:
        TripWorkflowService.transition_trip(trip.id, target, admin_user)
        trip.refresh_from_db()

    transport_payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=base_amount,
    )

    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE, controller=admin_user,
        unit_selling_price=Decimal("900.0000"),
    )
    control = DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=received_qty,
        verified_at=date.today(), actor=admin_user,
    )
    transport_payment.refresh_from_db()
    return {
        "trip": trip,
        "supplier": supplier,
        "transporter": transporter,
        "customer": customer,
        "control": control,
        "transport_payment": transport_payment,
        "invoice": Invoice.objects.get(sale__trip=trip),
    }


def _settle_all_debts_and_collect_customer(fx, admin_user):
    bank = BankAccount.objects.create(name=f"Bank {fx['trip'].reference}", opening_balance=Decimal("0.00"))
    ShareholderContributionService.record_contribution(
        shareholder_id=Shareholder.objects.create(
            name=f"Actionnaire {fx['trip'].reference}", participation_percent=Decimal("100.00")
        ).id,
        amount=Decimal("50000000.00"), date="2026-08-01",
        actor=admin_user, attachment=None, bank_account_id=bank.id,
    )

    supplier_due = ControlledDebtPaymentService.describe_supplier_balance(fx["supplier"])["total_due"]
    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER, debt_id=fx["supplier"].id,
        bank_account_id=bank.id, amount=supplier_due, date="2026-08-19",
        reference=f"PAY-SUP-{fx['trip'].reference}", actor=admin_user,
    )
    transporter_due = ControlledDebtPaymentService.describe_transporter_balance(
        fx["transporter"]
    )["total_due"]
    if transporter_due > Decimal("0.00"):
        ControlledDebtPaymentService.record_payment(
            debt_type=ControlledDebtPaymentService.TRANSPORTER, debt_id=fx["transporter"].id,
            bank_account_id=bank.id, amount=transporter_due, date="2026-08-19",
            reference=f"PAY-TRANS-{fx['trip'].reference}", actor=admin_user,
        )

    from apps.finance.services import FinancePostingService

    outstanding = PaymentAllocationService.get_customer_outstanding(fx["customer"])
    payment = CustomerPayment.objects.create(
        customer=fx["customer"], amount=outstanding, payment_date="2026-08-19",
        method=CustomerPayment.Method.BANK_TRANSFER, destination=CustomerPayment.Destination.BANK,
        bank_account=bank, recorded_by=admin_user,
    )
    PaymentAllocationService.allocate_payment(
        payment.id, [{"invoice_id": fx["invoice"].id, "amount": outstanding}]
    )
    FinancePostingService.record_customer_payment_treasury(payment)


@pytest.mark.django_db
def test_distributable_result_equals_net_profit_after_full_settlement_with_transporter_loss():
    """Mandated regression (client rule): a transporter-chargeable delivery
    loss must never leave a surplus in distributable_result once every debt
    is paid and every receivable is collected - the two independently
    computed figures (distributable_result, treasury-based; net_profit,
    margin-based) must reconcile exactly.

    Spec 2026-09-07: the invoice now bills the received quantity, so the
    tolerance-absorbed loss shows up as reduced revenue on the margin side
    and as reduced treasury/receivables on the distributable side. NEITHER
    formula needs a company_absorbed_loss correction term any more, and the
    two figures still meet exactly once every debt is settled and the
    customer has fully paid. The trip margin formula itself is untouched.
    """
    admin_user = _make_admin("DISTREC")
    # 400L short of 45,000L loaded: 100L tolerance-absorbed (default
    # LossToleranceConfig) + 300L transporter-chargeable @ 900.0000 XOF/L =
    # 270,000 XOF indemnisation perte transporteur, matching the bug report.
    fx = _deliver_trip_with_transporter_loss(
        "DISTREC", admin_user,
        received_qty=Decimal("44600.00"), base_amount=Decimal("5000000.00"),
    )
    assert fx["control"].company_absorbed_loss_quantity == Decimal("100.00")
    assert fx["control"].chargeable_loss_quantity == Decimal("300.00")
    from apps.reports.services.profit import TripProfitService

    breakdown = TripProfitService.get_cost_breakdown(fx["trip"])
    assert breakdown["transporter_loss_indemnity"] == Decimal("270000.00")
    assert breakdown["company_absorbed_loss_amount"] == Decimal("90000.00")

    _settle_all_debts_and_collect_customer(fx, admin_user)

    assert ControlledDebtPaymentService.describe_supplier_balance(fx["supplier"])["total_due"] == Decimal("0.00")
    assert ControlledDebtPaymentService.describe_transporter_balance(fx["transporter"])["total_due"] == Decimal("0.00")
    assert PaymentAllocationService.get_customer_outstanding(fx["customer"]) == Decimal("0.00")

    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["distributable_result"] == preview["net_profit"]


@pytest.mark.django_db
def test_distributable_result_no_longer_subtracts_company_absorbed_loss():
    """Spec 2026-09-07: the client now pays the received quantity, so the
    lower treasury already reflects the absorbed loss - distributable_result
    is a clean treasury/debts/capital figure with no separate loss term."""
    admin_user = _make_admin("DISTNOLOSS")
    fx = _deliver_trip_with_transporter_loss(
        "DISTNOLOSS", admin_user,
        received_qty=Decimal("44600.00"), base_amount=Decimal("5000000.00"),
    )
    from apps.reports.services.profit import TripProfitService
    breakdown = TripProfitService.get_cost_breakdown(fx["trip"])
    assert breakdown["company_absorbed_loss_amount"] == Decimal("90000.00")  # still exposed

    _settle_all_debts_and_collect_customer(fx, admin_user)
    preview = ShareholderProfitPreviewService.get_preview()

    wc = preview["working_capital"]
    assert Decimal(str(preview["distributable_result"])) == (
        wc["total"] - wc["supplier_debt_total"] - wc["transporter_debt_total"]
        - wc["other_debts"] - wc["supplier_reliquat_value"] - wc["capital"]
        - wc["supplier_in_transit_value"] - wc["supplier_company_stock_value"]
    )
    # the key is still there, just not a term:
    assert "total_company_absorbed_loss" in preview


@pytest.mark.django_db
def test_transporter_loss_indemnity_stays_visible_and_is_not_double_counted():
    """Second half of the mandated regression: the indemnisation perte
    transporteur line must stay visible in the trip's cost/profit breakdown
    (never hidden to "fix" the surplus), and must be counted exactly once -
    isolated here with zero tolerance-absorbed loss (received_qty exactly
    quantity_loaded - chargeable_loss, no shortfall inside tolerance) so
    company_absorbed_loss_amount can't mask a double count of the indemnity
    itself.
    """
    admin_user = _make_admin("INDVIS")
    fx = _deliver_trip_with_transporter_loss(
        "INDVIS", admin_user,
        # 400L short: 100L tolerance-absorbed + 300L chargeable @ 900.0000 =
        # 270,000 XOF indemnity - company_absorbed_loss_amount (90,000) is
        # nonzero too here, but is exercised on its own in the first test.
        received_qty=Decimal("44600.00"), base_amount=Decimal("5000000.00"),
    )

    from apps.reports.services.profit import TripProfitService

    breakdown = TripProfitService.get_cost_breakdown(fx["trip"])
    assert breakdown["transporter_loss_indemnity"] == Decimal("270000.00")
    rows = MarginReportQuery.run()
    row = next(r for r in rows if r["trip_reference"] == fx["trip"].reference)
    assert row["transporter_loss_indemnity"] == Decimal("270000.00")

    # Counted once in margin (credited back into revenue) and once as a
    # reduced net_amount owed to the transporter (TransportPayment.
    # deduction_amount) - never a third time anywhere else.
    assert fx["transport_payment"].deduction_amount == Decimal("270000.00")
    assert fx["transport_payment"].net_amount == Decimal("4730000.00")

    _settle_all_debts_and_collect_customer(fx, admin_user)

    preview = ShareholderProfitPreviewService.get_preview()
    assert preview["distributable_result"] == preview["net_profit"]


# ---------------------------------------------------------------------------
# TreasuryStatementQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_treasury_statement_lists_transfer_legs_and_keeps_correct_balance():
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
    # An internal transfer: both legs exist, the one on `account` is listed
    # as its own row (kind "transfer") and counts in the running balance.
    TreasuryService.record_transfer(
        source_account_type="cash",
        source_account_id=account.id,
        dest_account_type="cash",
        dest_account_id=other_account.id,
        amount=Decimal("200000.00"),
        date="2026-08-19",
        reference="",
        user=admin_user,
    )
    TreasuryTransaction.objects.create(
        cash_account=account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("150000.00"),
        date="2026-08-20",
        recorded_by=admin_user,
    )

    rows = TreasuryStatementQuery.run(cash_account_id=account.id)

    assert [r["kind"] for r in rows] == ["movement", "transfer", "movement"]
    assert rows[1]["type"] == "MONEY_OUT"
    assert rows[1]["reference"] == "Transfert Cash TREASSTMT -> Cash TREASSTMT DEST"
    assert rows[-1]["balance"] == Decimal("650000.00")  # 1,000,000 - 200,000 - 150,000


@pytest.mark.django_db
def test_treasury_statement_starts_with_the_opening_balance_as_an_entry():
    admin_user = _make_admin("TREASOPEN")
    account = BankAccount.objects.create(name="Bank TREASOPEN", opening_balance=Decimal("500000.00"))
    TreasuryTransaction.objects.create(
        bank_account=account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("120000.00"),
        date="2026-08-20",
        recorded_by=admin_user,
    )

    rows = TreasuryStatementQuery.run(bank_account_id=account.id)

    assert [r["kind"] for r in rows] == ["opening", "movement"]
    assert rows[0]["type"] == "MONEY_IN"
    assert rows[0]["amount"] == Decimal("500000.00")
    assert rows[0]["balance"] == Decimal("500000.00")
    assert rows[0]["reference"] == "Solde d'ouverture"
    assert rows[1]["balance"] == Decimal("380000.00")

    # A zero opening balance adds no line; a period starting after history
    # opens on the balance carried forward at date_from.
    empty = BankAccount.objects.create(name="Bank TREASOPEN0")
    assert TreasuryStatementQuery.run(bank_account_id=empty.id) == []
    carried = TreasuryStatementQuery.run(bank_account_id=account.id, date_from="2026-08-21")
    assert [r["kind"] for r in carried] == ["opening"]
    assert carried[0]["amount"] == Decimal("380000.00")


@pytest.mark.django_db
def test_statement_without_an_account_covers_only_that_kind_of_account():
    from rest_framework.test import APIClient

    admin_user = _make_admin("TREASSCOPE")
    bank_a = BankAccount.objects.create(name="Bank A SCOPE", opening_balance=Decimal("1000.00"))
    bank_b = BankAccount.objects.create(name="Bank B SCOPE", opening_balance=Decimal("500.00"))
    cash = CashAccount.objects.create(name="Cash SCOPE", opening_balance=Decimal("70.00"))
    TreasuryTransaction.objects.create(
        bank_account=bank_a, type=TreasuryTransaction.Type.MONEY_IN, amount=Decimal("100.00"),
        date="2026-08-20", reference="R1", recorded_by=admin_user,
    )
    TreasuryTransaction.objects.create(
        cash_account=cash, type=TreasuryTransaction.Type.MONEY_OUT, amount=Decimal("20.00"),
        date="2026-08-21", recorded_by=admin_user,
    )

    bank_rows = TreasuryStatementQuery.run(scope="bank")
    cash_rows = TreasuryStatementQuery.run(scope="cash")

    # Banks only: opening 1500 (both banks) then the one bank movement; no cash money.
    assert [r["kind"] for r in bank_rows] == ["opening", "movement"]
    assert bank_rows[0]["amount"] == Decimal("1500.00")
    assert bank_rows[1]["account"] == "Bank A SCOPE"
    assert bank_rows[1]["reference"] == "R1"
    assert bank_rows[0]["account"] == ""  # the opening line sums every bank
    assert cash_rows[1]["account"] == "Cash SCOPE"
    assert bank_rows[-1]["balance"] == Decimal("1600.00")
    # Cash only: opening 70 then the 20 out.
    assert cash_rows[0]["amount"] == Decimal("70.00")
    assert cash_rows[-1]["balance"] == Decimal("50.00")
    context = TreasuryStatementQuery.statement_context(scope="bank")
    assert context["opening_balance"] == Decimal("1500.00")
    assert context["closing_balance"] == Decimal("1600.00")

    # Through the API, the report type alone decides the scope.
    client = APIClient()
    client.force_authenticate(admin_user)
    api_bank = client.get("/api/reports/bank-statement/").json()["rows"]
    api_cash = client.get("/api/reports/cash-statement/").json()["rows"]
    assert api_bank[-1]["balance"] == "1600.00"
    assert api_cash[-1]["balance"] == "50.00"


# ---------------------------------------------------------------------------
# ShareholderStatementQuery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_shareholder_statement_lists_profit_shares_withdrawals_and_loans():
    admin_user = _make_admin("SHRSTMT")
    seed_net_profit()
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
    ShareholderDistributionService.validate_distribution(distribution.id, admin_user)
    share = ShareholderProfitShare.objects.get(distribution=distribution, shareholder=shareholder)
    # Goes through the service (not a raw ShareholderWithdrawal.objects.create)
    # so amount_withdrawn actually syncs onto `share` - that field is only
    # ever written by sync_amount_withdrawn(), which the service calls.
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
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
    assert rows[2]["debit"] == Decimal("30000.00")  # 50,000 lent - 20,000 given back
    assert rows[-1]["balance"] == ShareholderLedgerService.get_available_balance(shareholder.id)


@pytest.mark.django_db
def test_shareholder_statement_includes_capital_contribution_and_stays_balanced():
    admin_user = _make_admin("SHRSTMTCAP")
    seed_net_profit()
    shareholder = Shareholder.objects.create(name="Assoc SHRSTMTCAP", participation_percent=Decimal("100"))
    bank = BankAccount.objects.create(name="Bank SHRSTMTCAP", opening_balance=Decimal("0.00"))
    cash_account = CashAccount.objects.create(
        name="Cash SHRSTMTCAP", opening_balance=Decimal("1000000.00")
    )

    ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("500000.00"), date="2026-06-01",
        bank_account=bank, recorded_by=admin_user,
    )
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("100000.00"), actor=admin_user,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, admin_user)
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id, amount=Decimal("150000.00"), date="2026-08-01",
        cash_account_id=cash_account.id, actor=admin_user,
    )

    rows = ShareholderStatementQuery.run(shareholder_id=shareholder.id)

    assert [r["type"] for r in rows] == ["CONTRIBUTION", "PROFIT_SHARE", "WITHDRAWAL"]
    assert rows[0]["credit"] == Decimal("500000.00")
    assert rows[-1]["balance"] == ShareholderLedgerService.get_available_balance(shareholder.id)


@pytest.mark.django_db
def test_shareholder_statement_excludes_cancelled_distribution_shares():
    admin_user = _make_admin("SHRSTMTCANCEL")
    seed_net_profit()
    shareholder = Shareholder.objects.create(
        name="Assoc SHRSTMTCANCEL", participation_percent=Decimal("100")
    )
    CashAccount.objects.create(name="SHRSTMTCANCEL Till", opening_balance=Decimal("1000000.00"))

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("500000.00"),
        actor=admin_user,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, admin_user)
    assert ShareholderStatementQuery.run(shareholder_id=shareholder.id) != []

    ShareholderDistributionService.cancel_distribution(distribution.id, admin_user)

    rows = ShareholderStatementQuery.run(shareholder_id=shareholder.id)

    assert rows == []
    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("0.00")


@pytest.mark.django_db
def test_shareholder_statement_excludes_draft_distribution_shares():
    """2026-09-08 review, point 1: a DRAFT distribution's share is a
    preview only - it must not appear in the grand livre associe."""
    admin_user = _make_admin("SHRSTMTDRAFT")
    seed_net_profit()
    shareholder = Shareholder.objects.create(
        name="Assoc SHRSTMTDRAFT", participation_percent=Decimal("100")
    )
    CashAccount.objects.create(name="SHRSTMTDRAFT Till", opening_balance=Decimal("1000000.00"))

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("500000.00"),
        actor=admin_user,
    )

    assert ShareholderStatementQuery.run(shareholder_id=shareholder.id) == []

    ShareholderDistributionService.validate_distribution(distribution.id, admin_user)

    assert ShareholderStatementQuery.run(shareholder_id=shareholder.id) != []


# ---------------------------------------------------------------------------
# Statement opening balance (docs/superpowers/specs/2026-09-23-rapports-
# document-comptable-design.md, section Statements): the running balance of a
# partial period starts from the balance of the full history before date_from.
# ---------------------------------------------------------------------------


def _customer_history(suffix):
    admin_user = _make_admin(suffix)
    fx = _make_full_trip(suffix, admin_user)
    invoice = Invoice.objects.create(
        invoice_number=f"INV-QUERY-{suffix}",
        sale=fx["sale"],
        status=Invoice.Status.VALIDATED,
        total_amount=fx["sale"].subtotal,
        issued_date="2026-08-18",
    )
    cash = CashAccount.objects.create(name=f"Cash {suffix}")
    for payment_date, amount in (("2026-08-19", "10000000.00"), ("2026-09-05", "1000000.00")):
        CustomerPayment.objects.create(
            customer=fx["customer"],
            amount=Decimal(amount),
            payment_date=payment_date,
            method=CustomerPayment.Method.CASH,
            cash_account=cash,
            recorded_by=admin_user,
        )
    return fx, invoice


@pytest.mark.django_db
def test_customer_statement_opening_balance_covers_history_before_date_from():
    fx, invoice = _customer_history("CUSTOPEN")
    customer_id = fx["customer"].id

    opening = CustomerStatementQuery.opening_balance(customer_id=customer_id, date_from="2026-09-01")
    rows = CustomerStatementQuery.run(customer_id=customer_id, date_from="2026-09-01")

    assert opening == invoice.total_amount - Decimal("10000000.00")
    assert [r["type"] for r in rows] == ["PAYMENT"]
    assert rows[0]["balance"] == opening - Decimal("1000000.00")
    closing = CustomerStatementQuery.opening_balance(customer_id=customer_id, date_from="2026-10-01")
    assert closing == rows[-1]["balance"]


@pytest.mark.django_db
def test_customer_statement_without_date_from_has_zero_opening_and_unchanged_rows():
    fx, invoice = _customer_history("CUSTOPEN0")
    customer_id = fx["customer"].id

    assert CustomerStatementQuery.opening_balance(customer_id=customer_id) == Decimal("0.00")
    rows = CustomerStatementQuery.run(customer_id=customer_id)
    assert [r["balance"] for r in rows] == [
        invoice.total_amount,
        invoice.total_amount - Decimal("10000000.00"),
        invoice.total_amount - Decimal("11000000.00"),
    ]


@pytest.mark.django_db
def test_customer_statement_period_without_entries_still_has_nonzero_opening():
    fx, invoice = _customer_history("CUSTOPENEMPTY")
    customer_id = fx["customer"].id

    rows = CustomerStatementQuery.run(
        customer_id=customer_id, date_from="2026-10-01", date_to="2026-10-31"
    )
    opening = CustomerStatementQuery.opening_balance(
        customer_id=customer_id, date_from="2026-10-01", date_to="2026-10-31"
    )

    assert rows == []
    assert opening == invoice.total_amount - Decimal("11000000.00")


@pytest.mark.django_db
def test_supplier_statement_opening_balance_covers_history_before_date_from():
    admin_user = _make_admin("SUPPOPEN")
    fx = _make_full_trip("SUPPOPEN", admin_user)
    cash = CashAccount.objects.create(name="Cash SUPPOPEN")
    for payment_date, amount in (("2026-08-19", "5000000.00"), ("2026-09-05", "1000000.00")):
        SupplierPayment.objects.create(
            supplier=fx["supplier"],
            amount=Decimal(amount),
            payment_date=payment_date,
            method=SupplierPayment.Method.CASH,
            cash_account=cash,
            recorded_by=admin_user,
        )
    supplier_id = fx["supplier"].id

    opening = SupplierStatementQuery.opening_balance(supplier_id=supplier_id, date_from="2026-09-01")
    rows = SupplierStatementQuery.run(supplier_id=supplier_id, date_from="2026-09-01")

    assert opening == fx["supplier_order"].total_amount - Decimal("5000000.00")
    assert [r["type"] for r in rows] == ["PAYMENT"]
    assert rows[0]["balance"] == opening - Decimal("1000000.00")
    assert SupplierStatementQuery.opening_balance(supplier_id=supplier_id) == Decimal("0.00")


@pytest.mark.django_db
def test_shareholder_statement_opening_balance_covers_history_before_date_from():
    admin_user = _make_admin("SHROPEN")
    shareholder = Shareholder.objects.create(name="Assoc SHROPEN", participation_percent=Decimal("100"))
    bank = BankAccount.objects.create(name="Bank SHROPEN", opening_balance=Decimal("0.00"))
    for contribution_date, amount in (("2026-06-01", "500000.00"), ("2026-09-05", "100000.00")):
        ShareholderContribution.objects.create(
            shareholder=shareholder, amount=Decimal(amount), date=contribution_date,
            bank_account=bank, recorded_by=admin_user,
        )

    opening = ShareholderStatementQuery.opening_balance(
        shareholder_id=shareholder.id, date_from="2026-09-01"
    )
    rows = ShareholderStatementQuery.run(shareholder_id=shareholder.id, date_from="2026-09-01")

    assert opening == Decimal("500000.00")
    assert [r["credit"] for r in rows] == [Decimal("100000.00")]
    assert rows[0]["balance"] == Decimal("600000.00")
    assert ShareholderStatementQuery.opening_balance(shareholder_id=shareholder.id) == Decimal("0.00")


def _treasury_history(suffix):
    admin_user = _make_admin(suffix)
    account = CashAccount.objects.create(name=f"Cash {suffix}", opening_balance=Decimal("100000.00"))
    IN, OUT = TreasuryTransaction.Type.MONEY_IN, TreasuryTransaction.Type.MONEY_OUT
    for txn_type, amount, txn_date, is_transfer in (
        (IN, "1000000.00", "2026-08-10", False),
        (OUT, "200000.00", "2026-08-15", True),  # transfer before the period
        (IN, "500000.00", "2026-09-05", False),
        (OUT, "100000.00", "2026-09-10", False),
        (OUT, "50000.00", "2026-09-12", True),  # transfers inside the period
        (IN, "20000.00", "2026-09-20", True),
        (IN, "999.00", "2026-10-05", False),  # after the period
    ):
        TreasuryTransaction.objects.create(
            cash_account=account, type=txn_type, amount=Decimal(amount), date=txn_date,
            is_transfer=is_transfer, recorded_by=admin_user,
        )
    return account


@pytest.mark.django_db
def test_treasury_statement_context_reconciles_with_signed_internal_transfers():
    account = _treasury_history("TREASCTX")
    period = {"cash_account_id": account.id, "date_from": "2026-09-01", "date_to": "2026-09-30"}

    context = TreasuryStatementQuery.statement_context(**period)
    rows = TreasuryStatementQuery.run(**period)

    assert context["opening_balance"] == Decimal("900000.00")  # 100,000 + 1,000,000 - 200,000
    assert context["period_in"] == Decimal("500000.00")
    assert context["period_out"] == Decimal("100000.00")
    assert context["transfers_net"] == Decimal("-30000.00")  # -50,000 + 20,000, signed
    assert context["closing_balance"] == Decimal("1270000.00")  # the 10-05 entry is after date_to
    assert (
        context["opening_balance"] + context["period_in"] - context["period_out"] + context["transfers_net"]
        == context["closing_balance"]
    )
    # period_in/out are exactly the sums of the displayed (non-transfer) rows.
    movements = [r for r in rows if r["kind"] == "movement"]
    assert context["period_in"] == sum(r["amount"] for r in movements if r["type"] == "MONEY_IN")
    assert context["period_out"] == sum(r["amount"] for r in movements if r["type"] == "MONEY_OUT")


@pytest.mark.django_db
def test_treasury_statement_context_without_dates_spans_the_full_history():
    account = _treasury_history("TREASCTXALL")

    context = TreasuryStatementQuery.statement_context(cash_account_id=account.id)

    assert context["opening_balance"] == Decimal("100000.00")  # the account's own opening balance
    assert context["closing_balance"] == TreasuryStatementQuery.run(cash_account_id=account.id)[-1]["balance"]
    assert (
        context["opening_balance"] + context["period_in"] - context["period_out"] + context["transfers_net"]
        == context["closing_balance"]
    )


@pytest.mark.django_db
def test_treasury_statement_context_for_an_empty_period_keeps_the_opening_balance():
    account = _treasury_history("TREASCTXEMPTY")

    context = TreasuryStatementQuery.statement_context(
        cash_account_id=account.id, date_from="2026-12-01", date_to="2026-12-31"
    )

    assert context["opening_balance"] == context["closing_balance"] == Decimal("1270000.00") + Decimal("999.00")
    assert context["period_in"] == context["period_out"] == context["transfers_net"] == Decimal("0.00")

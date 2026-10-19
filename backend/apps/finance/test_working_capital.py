# WorkingCapitalService tests (Task 7, docs/superpowers/sdd/2026-09-04-
# recette-corrections/task-7-brief.md; business rationale in
# docs/superpowers/specs/2026-09-04-recette-corrections-design.md Section 3).
#
# Client-corrected "fond de roulement" (2026-09-04, third pass - confirmed
# bug during actual client recette testing, reverting the second pass's
# subtraction): gross = treasury + receivables; total = gross + open debts
# (supplier/transporter/customs-transit, each total_due, never netted
# against open advances at the per-debt level - open debts are ADDED here,
# never subtracted). A management indicator matching the client's own
# spreadsheet, not the accounting working capital. Capital is informational
# only, never part of gross/total (only subtracted separately to reach
# distributable_result).

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import (
    BankAccount,
    CashAccount,
    Expense,
    SupplierAdvance,
    SupplierPayment,
)
from apps.finance.services import (
    ControlledDebtPaymentService,
    ShareholderProfitPreviewService,
    WorkingCapitalService,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.purchasing.services import SupplierStockService
from apps.sales.models import Invoice, Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role)


def _make_supplier_order_with_status(suffix, status, *, quantity=Decimal("1000.00"), unit_price=Decimal("1000.0000")):
    admin_user = _make_admin(suffix)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    order = SupplierOrder.objects.create(
        reference=f"SO-WC-{suffix}", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=quantity, unit_price=unit_price,
        status=status, created_by=admin_user,
    )
    return admin_user, supplier, order


def _fully_load(order, *, suffix, admin_user=None):
    """Load the order's full quantity_litres via a real Trip - bug fix
    (client business rule, confirmed 2026-09-06): supplier debt is now
    priced on quantity actually loaded, not on the full confirmed order,
    so every fixture in this file that needs a real open supplier debt
    needs a Trip behind the order. This file's tests are about the fond
    de roulement aggregate formula, not about the loaded-vs-purchased
    debt timing rule itself, so a full load keeps every pre-existing
    assertion correct unchanged."""
    if admin_user is None:
        admin_user = order.created_by
    short_suffix = suffix[-16:]
    cession = CessionLetter.objects.create(
        reference=f"CL-{suffix}", supplier_order=order,
        authorized_quantity=order.quantity_litres, issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-{short_suffix}", tractor_registration=f"{short_suffix}-TRAC",
        tanker_registration=f"{short_suffix}-TANK", capacity_litres=Decimal("45000.00"),
    )
    transporter = Transporter.objects.create(name=f"Transporteur {suffix}")
    return Trip.objects.create(
        reference=f"TRIP-{suffix}", truck=truck, transporter=transporter,
        supplier=order.supplier, supplier_order=order, cession_letter=cession,
        product=order.product, quantity_loaded=order.quantity_litres, loading_date="2026-08-18",
        bl_reference=f"BL-{suffix}", created_by=admin_user,
    )


def _make_trip_for_transporter_debt(suffix):
    admin_user = _make_admin(suffix)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Trans Supplier {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    supplier_order = SupplierOrder.objects.create(
        # unit_price=0 on purpose: this supplier order only exists to
        # satisfy Trip's required FKs (supplier/cession) so a
        # TransportPayment can be created - it must not incidentally add
        # its own supplier debt on top of the transporter debt under test.
        reference=f"SO-WCTRIP-{suffix}", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("0.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-WCTRIP-{suffix}", supplier_order=supplier_order,
        authorized_quantity=Decimal("500000.00"), issue_date="2026-08-18", created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-WCTRIP-{suffix}", tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER", capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-WCTRIP-{suffix}", truck=truck, transporter=transporter, supplier=supplier,
        supplier_order=supplier_order, cession_letter=cession, product=product,
        quantity_loaded=Decimal("45000.00"), loading_date="2026-08-18",
        bl_reference=f"BL-WCTRIP-{suffix}", created_by=admin_user,
    )
    return trip, transporter


@pytest.mark.django_db
def test_working_capital_gross_and_total_breakdown():
    # treasury_available = 2,000,000 (bank 1,500,000 + cash 500,000)
    BankAccount.objects.create(name="WC Bank", opening_balance=Decimal("1500000.00"), is_active=True)
    CashAccount.objects.create(name="WC Cash", opening_balance=Decimal("500000.00"), is_active=True)

    # customer_receivables = 1,000,000 (one unpaid invoice)
    admin_user = _make_admin("WCADD")
    customer = Customer.objects.create(name="WC Customer")
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="WC Recv Supplier", country="Senegal")
    supplier_order = SupplierOrder.objects.create(
        # unit_price=0 on purpose: this order only exists to satisfy Trip's
        # required FKs so a Sale/Invoice can be created for the
        # customer_receivables scenario - it must not incidentally add its
        # own supplier debt.
        reference="SO-WCADD-RECV", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("1.00"),
        unit_price=Decimal("0.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference="CL-WCADD-RECV", supplier_order=supplier_order,
        authorized_quantity=Decimal("1.00"), issue_date="2026-08-18", created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id="TRK-WCADD-RECV", tractor_registration="WCADD-TRACTOR",
        tanker_registration="WCADD-TANKER", capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference="TRIP-WCADD-RECV", truck=truck, transporter=Transporter.objects.create(name="WC Recv Transporter"),
        supplier=supplier, supplier_order=supplier_order, cession_letter=cession, product=product,
        quantity_loaded=Decimal("1.00"), loading_date="2026-08-18",
        bl_reference="BL-WCADD-RECV", created_by=admin_user,
    )
    sale = Sale.objects.create(
        trip=trip, customer=customer, product=product,
        delivered_quantity=Decimal("1.00"), unit_selling_price=Decimal("1000000.0000"),
    )
    Invoice.objects.create(
        invoice_number="INV-WCADD", sale=sale, status=Invoice.Status.VALIDATED,
        total_amount=Decimal("1000000.00"), issued_date="2026-08-18",
    )

    # supplier_debt_total = 1,000,000 (open supplier debt, no advance)
    _, _, wcadd_sup_order = _make_supplier_order_with_status(
        "WCADD-SUP", SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("1000.00"), unit_price=Decimal("1000.0000"),
    )
    _fully_load(wcadd_sup_order, suffix="WCADD-SUP")

    # transporter_debt_total = 1,000,000 (open transporter debt, no advance)
    from apps.finance.models import TransportPayment

    debt_trip, debt_transporter = _make_trip_for_transporter_debt("WCADD-TRA")
    TransportPayment.objects.create(
        trip=debt_trip, transporter=debt_transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("1000000.00"),
    )

    # other_debts = 1,000,000 (customs expense debt)
    Expense.objects.create(
        category=Expense.Category.CUSTOMS, amount=Decimal("1000000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL, date="2026-08-18",
    )

    result = WorkingCapitalService.get_working_capital()

    assert result["treasury_available"] == Decimal("2000000.00")
    assert result["customer_receivables"] == Decimal("1000000.00")
    assert result["supplier_debt_total"] == Decimal("1000000.00")
    assert result["transporter_debt_total"] == Decimal("1000000.00")
    assert result["other_debts"] == Decimal("1000000.00")
    # gross = treasury + receivables (2,000,000 + 1,000,000)
    assert result["gross"] == Decimal("3000000.00")
    # The supplier order is loaded and not sold: its 1,000,000 of fuel is stock
    # (en cours). total = gross + stock - the 3 debt buckets
    # = 3,000,000 + 1,000,000 - 3 x 1,000,000.
    assert result["supplier_in_transit_value"] == Decimal("1000000.00")
    assert result["debts_total"] == Decimal("3000000.00")
    assert result["total"] == Decimal("1000000.00")


@pytest.mark.django_db
def test_get_other_debts_breakdown_splits_the_lump_sum_into_4_named_buckets():
    """Added for the Benefices PDF export (client request 2026-09-06),
    which shows douane/transit/transit routiere/autres frais as separate
    lines - must sum back to get_working_capital()'s other_debts exactly,
    since both call the same underlying ControlledDebtPaymentService
    groups."""
    Expense.objects.create(
        category=Expense.Category.CUSTOMS, amount=Decimal("1000000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL, date="2026-08-18",
    )
    Expense.objects.create(
        category=Expense.Category.TRANSIT, amount=Decimal("200000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL, date="2026-08-18",
    )
    Expense.objects.create(
        category=Expense.Category.ROAD_TRANSIT, amount=Decimal("300000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL, date="2026-08-18",
    )
    # "other" collapses border (ROAD) + loading.
    Expense.objects.create(
        category=Expense.Category.ROAD, amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL, date="2026-08-18",
    )
    Expense.objects.create(
        category=Expense.Category.LOADING, amount=Decimal("70000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL, date="2026-08-18",
    )

    breakdown = WorkingCapitalService.get_other_debts_breakdown()

    assert breakdown == {
        "customs": Decimal("1000000.00"),
        "transit": Decimal("200000.00"),
        "road_transit": Decimal("300000.00"),
        "other": Decimal("120000.00"),
    }
    assert sum(breakdown.values(), Decimal("0.00")) == (
        WorkingCapitalService.get_working_capital()["other_debts"]
    )


@pytest.mark.django_db
def test_working_capital_debt_total_is_gross_not_net_of_advances():
    # Order confirmed first (total_due = 1,000,000), no advance exists yet
    # to consume, so nothing is netted at creation time.
    admin_user, supplier, order = _make_supplier_order_with_status(
        "WCGROSS", SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("1000.00"), unit_price=Decimal("1000.0000"),
    )
    _fully_load(order, suffix="WCGROSS")
    cash = CashAccount.objects.create(name="WC Gross Cash", opening_balance=Decimal("5000000.00"))
    # Advance recorded directly (bypassing AdvanceService.create_supplier_advance,
    # which would reject this while a debt is open) - reproduces a state
    # where both an open advance and an open debt coexist without FIFO
    # consumption ever having run between them.
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-19",
        cash_account=cash, recorded_by=admin_user,
    )

    from apps.finance.services import ControlledDebtPaymentService

    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    # Fixture sanity: net_balance is -500,000 (500,000 advance - 1,000,000 debt),
    # not the gross 1,000,000 the working capital indicator must use.
    assert balance["net_balance"] == Decimal("-500000.00")

    result = WorkingCapitalService.get_working_capital()

    assert result["supplier_debt_total"] == Decimal("1000000.00")


@pytest.mark.django_db
def test_working_capital_matches_client_recette_example():
    """Client example (2026-09-04), re-read with the corrected rule of
    2026-10-19 (the accountant confirmed that debts are DEDUCTED):
      gross (tresorerie + creances)   = 300 000 000
      + stock carburant (45 000 L)    =  45 000 000
      - dettes fournisseurs ouvertes  =  45 000 000
      - dettes transporteurs ouvertes =   2 925 000
      - dettes douane/transit/frais   =  10 255 000
      = 286 820 000
    The unpaid fuel nets to zero (stock - supplier debt); only the
    transporter and customs debts lower the figure.
    """
    BankAccount.objects.create(
        name="WC Recette Bank", opening_balance=Decimal("300000000.00"), is_active=True
    )

    # dettes fournisseurs ouvertes = 45 000 000 (45 000 L x 1 000.0000, no advance)
    _, _, wcrecette_sup_order = _make_supplier_order_with_status(
        "WCRECETTE-SUP", SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("45000.00"), unit_price=Decimal("1000.0000"),
    )
    _fully_load(wcrecette_sup_order, suffix="WCRECETTE-SUP")

    # dettes transporteurs ouvertes = 2 925 000 (no advance)
    from apps.finance.models import TransportPayment

    debt_trip, debt_transporter = _make_trip_for_transporter_debt("WCRECETTE-TRA")
    TransportPayment.objects.create(
        trip=debt_trip, transporter=debt_transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("2925000.00"),
    )

    # dettes douane/transit/frais ouvertes = 10 255 000
    Expense.objects.create(
        category=Expense.Category.CUSTOMS, amount=Decimal("10255000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL, date="2026-08-18",
    )

    result = WorkingCapitalService.get_working_capital()

    assert result["gross"] == Decimal("300000000.00")
    assert result["supplier_debt_total"] == Decimal("45000000.00")
    assert result["transporter_debt_total"] == Decimal("2925000.00")
    assert result["other_debts"] == Decimal("10255000.00")
    assert result["supplier_in_transit_value"] == Decimal("45000000.00")
    assert result["total"] == Decimal("286820000.00")


def _load_partial(order, quantity, *, suffix):
    """Load only `quantity` (< order.quantity_litres) via a real Trip, to
    exercise the unloaded reliquat - counterpart to _fully_load() above."""
    admin_user = order.created_by
    short_suffix = suffix[-16:]
    cession = CessionLetter.objects.create(
        reference=f"CL-{suffix}", supplier_order=order,
        authorized_quantity=order.quantity_litres, issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-{short_suffix}", tractor_registration=f"{short_suffix}-TRAC",
        tanker_registration=f"{short_suffix}-TANK", capacity_litres=Decimal("45000.00"),
    )
    transporter = Transporter.objects.create(name=f"Transporteur {suffix}")
    return Trip.objects.create(
        reference=f"TRIP-{suffix}", truck=truck, transporter=transporter,
        supplier=order.supplier, supplier_order=order, cession_letter=cession,
        product=order.product, quantity_loaded=quantity, loading_date="2026-08-18",
        bl_reference=f"BL-{suffix}", created_by=admin_user,
    )


@pytest.mark.django_db
def test_working_capital_unpaid_purchase_nets_to_zero():
    """Bug fix (client-reported, confirmed during live recette testing,
    2026-09-14): buy 720,000 L for 532,800,000 XOF, load nothing, pay
    nothing - supplier_debt_total already books the full 532,800,000 as an
    open debt immediately on confirmation, so the unloaded reliquat must
    NOT also add its value on top (that was counting the exact same,
    entirely unpaid litres twice: once as "owed", once as "stock held").
    Until the company actually pays the supplier, the open debt alone
    represents the full engaged value."""
    _, _, order = _make_supplier_order_with_status(
        "WCRELIQUATUNPAID-SUP", SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("720000.00"), unit_price=Decimal("740.0000"),
    )

    result = WorkingCapitalService.get_working_capital()

    assert result["supplier_debt_total"] == Decimal("532800000.00")
    # The unloaded fuel is stock in full, the debt is deducted in full: an
    # unpaid purchase nets to zero (it is neither counted twice nor lost).
    assert result["supplier_reliquat_value"] == Decimal("532800000.00")
    assert result["supplier_in_transit_value"] == Decimal("0.00")
    assert result["supplier_company_stock_value"] == Decimal("0.00")
    assert result["total"] == result["gross"]


@pytest.mark.django_db
def test_working_capital_counts_the_unloaded_reliquat_as_stock_and_deducts_the_debt():
    """Business rule reversal (client request, 2026-09-10), refined
    2026-09-14 to cap the reliquat by what was actually paid (see the
    class docstring): purchase 200,000 L at 1,000 XOF/L (debt = 200,000,000
    immediately), load only 45,000 L, and pay the supplier 155,000,000 (the
    exact unloaded value) - that payment converts open debt into
    company-owned stock still sitting at the supplier, so it must show up
    as its own asset line in the Fond de roulement client card, added into
    `total` the same way open debts are, then cancelled back out of
    distributable_result (see ShareholderProfitPreviewService). debt
    (45,000,000 remaining) + reliquat (155,000,000 paid) still sums back to
    the order's full 200,000,000 - never more."""
    admin_user, supplier, order = _make_supplier_order_with_status(
        "WCRELIQUATPAID-SUP", SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("200000.00"), unit_price=Decimal("1000.0000"),
    )
    _load_partial(order, Decimal("45000.00"), suffix="WCRELIQUATPAID-SUP")

    cash = CashAccount.objects.create(
        name="WC Reliquat Paid Cash", opening_balance=Decimal("500000000.00")
    )
    SupplierPayment.objects.create(
        supplier=supplier, supplier_order=order, amount=Decimal("155000000.00"),
        payment_date="2026-08-19", method=SupplierPayment.Method.CASH,
        cash_account=cash, recorded_by=admin_user,
    )

    result = WorkingCapitalService.get_working_capital()

    assert result["supplier_debt_total"] == Decimal("45000000.00")
    # The 45,000 L loaded via _load_partial sits at the default ASSIGNED
    # status (still "en cours"). Client rule (2026-09-24): a payment first
    # covers fuel that has already left the supplier (company stock, then
    # en cours) and only then the reliquat still at the supplier - so the
    # 155,000,000 payment gives 45,000,000 to en cours and the remaining
    # 110,000,000 to the reliquat.
    #
    # Since the 2026-10-19 rule the Fond de roulement values the stock IN
    # FULL (the debt is deducted in full): 45,000,000 en cours and
    # 155,000,000 at the supplier. The "paid" split above is only used by
    # the Situation financiere page (get_supplier_pipeline_breakdown).
    paid_split = WorkingCapitalService.get_supplier_pipeline_breakdown()
    assert paid_split["supplier_company_stock_value"] == Decimal("0.00")
    assert paid_split["supplier_in_transit_value"] == Decimal("45000000.00")
    assert paid_split["supplier_reliquat_value"] == Decimal("110000000.00")
    assert result["supplier_company_stock_value"] == Decimal("0.00")
    assert result["supplier_in_transit_value"] == Decimal("45000000.00")
    assert result["supplier_reliquat_value"] == Decimal("155000000.00")
    assert result["stock_total"] == Decimal("200000000.00")
    assert result["debts_total"] == Decimal("45000000.00")
    assert result["total"] == result["gross"] + Decimal("200000000.00") - Decimal("45000000.00")


@pytest.mark.django_db
def test_working_capital_splits_fully_paid_stock_across_the_three_pipeline_stages():
    """Same-day follow-up (client request, 2026-09-14): "en cours" (loaded,
    on the road) and "stock entreprise" (arrived at the depot) are the
    later stages of the same pipeline the reliquat covers for the unloaded
    stage. Client example: purchase 300,000 L at 1,000 XOF/L (300,000,000),
    50,000 L loaded and still on the road (en cours), 50,000 L loaded and
    arrived at the depot (stock entreprise), the remaining 200,000 L still
    at the supplier (reliquat) - order paid in full. debt drops to 0 and
    the three stages split the entire 300,000,000 between them, each
    counted exactly once."""
    admin_user, supplier, order = _make_supplier_order_with_status(
        "WCPIPELINE-SUP", SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("300000.00"), unit_price=Decimal("1000.0000"),
    )
    _load_partial(order, Decimal("50000.00"), suffix="WCPIPELINE-TRANSIT")
    stocked_trip = _load_partial(order, Decimal("50000.00"), suffix="WCPIPELINE-STOCK")
    stocked_trip.status = Trip.Status.STOCKED
    stocked_trip.save(update_fields=["status"])

    cash = CashAccount.objects.create(
        name="WC Pipeline Cash", opening_balance=Decimal("500000000.00")
    )
    SupplierPayment.objects.create(
        supplier=supplier, supplier_order=order, amount=Decimal("300000000.00"),
        payment_date="2026-08-19", method=SupplierPayment.Method.CASH,
        cash_account=cash, recorded_by=admin_user,
    )

    result = WorkingCapitalService.get_working_capital()

    assert result["supplier_debt_total"] == Decimal("0.00")
    assert result["supplier_reliquat_value"] == Decimal("200000000.00")
    assert result["supplier_in_transit_value"] == Decimal("50000000.00")
    assert result["supplier_company_stock_value"] == Decimal("50000000.00")
    assert (
        result["supplier_reliquat_value"]
        + result["supplier_in_transit_value"]
        + result["supplier_company_stock_value"]
    ) == Decimal("300000000.00")


@pytest.mark.django_db
def test_working_capital_supplier_reliquat_is_zero_once_fully_loaded():
    _, _, order = _make_supplier_order_with_status(
        "WCRELIQUATFULL-SUP", SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("200000.00"), unit_price=Decimal("1000.0000"),
    )
    _fully_load(order, suffix="WCRELIQUATFULL-SUP")

    result = WorkingCapitalService.get_working_capital()

    assert result["supplier_debt_total"] == Decimal("200000000.00")
    # Fully loaded and not sold: nothing left at the supplier, all of it en cours.
    assert result["supplier_reliquat_value"] == Decimal("0.00")
    assert result["supplier_in_transit_value"] == Decimal("200000000.00")
    assert result["supplier_company_stock_value"] == Decimal("0.00")


@pytest.mark.django_db
def test_working_capital_supplier_reliquat_ignores_draft_and_cancelled_orders():
    _make_supplier_order_with_status(
        "WCRELIQUATDRAFT-SUP", SupplierOrder.Status.DRAFT,
        quantity=Decimal("200000.00"), unit_price=Decimal("1000.0000"),
    )
    _make_supplier_order_with_status(
        "WCRELIQUATCANC-SUP", SupplierOrder.Status.CANCELLED,
        quantity=Decimal("200000.00"), unit_price=Decimal("1000.0000"),
    )

    result = WorkingCapitalService.get_working_capital()

    assert result["supplier_reliquat_value"] == Decimal("0.00")
    assert result["supplier_in_transit_value"] == Decimal("0.00")
    assert result["supplier_company_stock_value"] == Decimal("0.00")


# --- Payment allocation order across the three pipeline stages -----------
# Client rule (2026-09-24, recette meeting): a supplier payment first covers
# the fuel already taken from the supplier - company stock, then en cours -
# and only then the reliquat still sitting at the supplier. The physical
# values do not change; only which of the 3 lines a payment lands in.
#
# Shared scenario: 100,000 L at 1,000 XOF/L = 100,000,000. 20,000 L arrived
# in company stock (20,000,000), 10,000 L en cours (10,000,000), 70,000 L
# still at the supplier (70,000,000).


def _pipeline_scenario(suffix, *, paid):
    admin_user, supplier, order = _make_supplier_order_with_status(
        suffix, SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("100000.00"), unit_price=Decimal("1000.0000"),
    )
    _load_partial(order, Decimal("10000.00"), suffix=f"{suffix}-TRANSIT")
    stocked_trip = _load_partial(order, Decimal("20000.00"), suffix=f"{suffix}-STOCK")
    stocked_trip.status = Trip.Status.STOCKED
    stocked_trip.save(update_fields=["status"])
    if paid:
        cash = CashAccount.objects.create(
            name=f"WC {suffix} Cash", opening_balance=Decimal("500000000.00")
        )
        SupplierPayment.objects.create(
            supplier=supplier, supplier_order=order, amount=paid,
            payment_date="2026-08-19", method=SupplierPayment.Method.CASH,
            cash_account=cash, recorded_by=admin_user,
        )
    return order


def _paid_split():
    """The capped, allocation-ordered split (Situation financiere page)."""
    return WorkingCapitalService.get_supplier_pipeline_breakdown()


def _three_lines(result):
    return (
        result["supplier_company_stock_value"],
        result["supplier_in_transit_value"],
        result["supplier_reliquat_value"],
    )


@pytest.mark.django_db
def test_payment_covers_company_stock_then_in_transit_then_reliquat():
    _pipeline_scenario("WCORDER-PARTIAL", paid=Decimal("50000000.00"))

    result = {**WorkingCapitalService.get_working_capital(), **_paid_split()}

    assert _three_lines(result) == (
        Decimal("20000000.00"), Decimal("10000000.00"), Decimal("20000000.00"),
    )
    assert result["supplier_debt_total"] == Decimal("50000000.00")


@pytest.mark.django_db
def test_payment_smaller_than_company_stock_goes_entirely_to_company_stock():
    _pipeline_scenario("WCORDER-SMALL", paid=Decimal("15000000.00"))

    result = {**WorkingCapitalService.get_working_capital(), **_paid_split()}

    assert _three_lines(result) == (
        Decimal("15000000.00"), Decimal("0.00"), Decimal("0.00"),
    )


@pytest.mark.django_db
def test_payment_covering_company_stock_and_part_of_in_transit_leaves_reliquat_at_zero():
    _pipeline_scenario("WCORDER-MID", paid=Decimal("25000000.00"))

    result = {**WorkingCapitalService.get_working_capital(), **_paid_split()}

    assert _three_lines(result) == (
        Decimal("20000000.00"), Decimal("5000000.00"), Decimal("0.00"),
    )


@pytest.mark.django_db
def test_fully_paid_order_covers_each_stage_at_its_raw_value():
    order = _pipeline_scenario("WCORDER-FULL", paid=Decimal("100000000.00"))

    result = WorkingCapitalService.get_working_capital()

    assert _three_lines(result) == (
        Decimal("20000000.00"), Decimal("10000000.00"), Decimal("70000000.00"),
    )
    assert result["supplier_debt_total"] == Decimal("0.00")
    # Each counted line equals the raw physical value of its stage.
    assert result["supplier_company_stock_value"] == (
        SupplierStockService.get_purchase_company_stock_amount(order)
    )
    assert result["supplier_in_transit_value"] == (
        SupplierStockService.get_purchase_in_transit_amount(order)
    )
    assert result["supplier_reliquat_value"] == (
        SupplierStockService.get_purchase_reliquat_amount(order)
    )


@pytest.mark.django_db
def test_unpaid_order_has_nothing_paid_and_keeps_the_full_debt():
    _pipeline_scenario("WCORDER-UNPAID", paid=None)

    result = {**WorkingCapitalService.get_working_capital(), **_paid_split()}

    assert _three_lines(result) == (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))
    assert result["supplier_debt_total"] == Decimal("100000000.00")


@pytest.mark.django_db
def test_sold_trip_stays_excluded_from_in_transit_and_company_stock():
    """No new allocation rule for sold trips (deliberately out of scope):
    a trip attached to a Sale is a customer receivable, so it is still left
    out of the en cours / stock entreprise lines exactly as before."""
    admin_user, supplier, order = _make_supplier_order_with_status(
        "WCORDER-SOLD", SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("100000.00"), unit_price=Decimal("1000.0000"),
    )
    stocked_trip = _load_partial(order, Decimal("20000.00"), suffix="WCORDER-SOLD-STOCK")
    stocked_trip.status = Trip.Status.STOCKED
    stocked_trip.save(update_fields=["status"])
    sold_trip = _load_partial(order, Decimal("10000.00"), suffix="WCORDER-SOLD-SALE")
    Sale.objects.create(
        trip=sold_trip, customer=Customer.objects.create(name="WC Sold Customer"),
        product=order.product, delivered_quantity=Decimal("10000.00"),
        unit_selling_price=Decimal("1500.0000"),
    )
    cash = CashAccount.objects.create(
        name="WC Sold Cash", opening_balance=Decimal("500000000.00")
    )
    SupplierPayment.objects.create(
        supplier=supplier, supplier_order=order, amount=Decimal("100000000.00"),
        payment_date="2026-08-19", method=SupplierPayment.Method.CASH,
        cash_account=cash, recorded_by=admin_user,
    )

    result = WorkingCapitalService.get_working_capital()

    assert result["supplier_company_stock_value"] == Decimal("20000000.00")
    assert result["supplier_in_transit_value"] == Decimal("0.00")
    assert result["supplier_reliquat_value"] == Decimal("70000000.00")


def _old_reliquat_first_breakdown():
    """Reference copy of the pre-2026-09-24 allocation (reliquat -> en cours
    -> company stock), used only to prove that the order is purely a
    presentation split of the same total."""
    zero = Decimal("0.00")
    reliquat_total = in_transit_total = company_stock_total = zero
    for order in SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED):
        paid = ControlledDebtPaymentService.describe_supplier_order(order)["paid_amount"]
        reliquat = min(paid, SupplierStockService.get_purchase_reliquat_amount(order))
        paid -= reliquat
        in_transit = min(paid, SupplierStockService.get_purchase_in_transit_amount(order))
        paid -= in_transit
        company_stock = min(paid, SupplierStockService.get_purchase_company_stock_amount(order))
        reliquat_total += reliquat
        in_transit_total += in_transit
        company_stock_total += company_stock
    return {
        "supplier_reliquat_value": reliquat_total,
        "supplier_in_transit_value": in_transit_total,
        "supplier_company_stock_value": company_stock_total,
    }


@pytest.mark.django_db
def test_allocation_order_changes_only_the_paid_split_never_the_total_or_distributable_result(
    monkeypatch,
):
    BankAccount.objects.create(name="WC Order Bank", opening_balance=Decimal("40000000.00"), is_active=True)
    _pipeline_scenario("WCORDER-INVARIANT", paid=Decimal("50000000.00"))

    new_split = _paid_split()
    new_wc = WorkingCapitalService.get_working_capital()
    new_preview = ShareholderProfitPreviewService.get_preview()

    monkeypatch.setattr(
        WorkingCapitalService, "get_supplier_pipeline_breakdown",
        staticmethod(_old_reliquat_first_breakdown),
    )
    old_split = _paid_split()
    old_wc = WorkingCapitalService.get_working_capital()
    old_preview = ShareholderProfitPreviewService.get_preview()

    # The paid split differs (old: everything in reliquat first)...
    assert _three_lines(old_split) == (
        Decimal("0.00"), Decimal("0.00"), Decimal("50000000.00"),
    )
    assert _three_lines(new_split) != _three_lines(old_split)
    assert sum(_three_lines(new_split), Decimal("0.00")) == sum(
        _three_lines(old_split), Decimal("0.00")
    )
    # ...but the Fond de roulement (stock valued in full) and the profit
    # do not depend on it at all.
    assert new_wc == old_wc
    assert new_preview["distributable_result"] == old_preview["distributable_result"]

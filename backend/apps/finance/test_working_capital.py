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
)
from apps.finance.services import WorkingCapitalService
from apps.purchasing.models import CessionLetter, SupplierOrder
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
    # total = gross + the 3 debt buckets, ADDED (3,000,000 + 1,000,000 x 3)
    assert result["total"] == Decimal("6000000.00")


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
    """Confirmed bug during actual client recette testing (2026-09-04,
    third pass): the dashboard "Fond de roulement net client" card showed
    dettes ouvertes as positive line items but the headline figure still
    subtracted them. Client-provided example, reproduced exactly here:
      gross (tresorerie + creances) = 300 000 000
      + dettes fournisseurs ouvertes  =  45 000 000
      + dettes transporteurs ouvertes =   2 925 000
      + dettes douane/transit/frais   =  10 255 000
      = 358 180 000
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
    assert result["total"] == Decimal("358180000.00")


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
def test_working_capital_includes_unloaded_supplier_reliquat_as_an_asset():
    """Business rule reversal (client request, 2026-09-10), client's own
    example: purchase 200,000 L at 1,000 XOF/L (debt = 200,000,000,
    immediately), load only 45,000 L (45,000,000) so far -> the unloaded
    155,000 L (155,000,000 XOF) is company-owned stock still sitting at the
    supplier, and must show up as its own asset line in the Fond de
    roulement client card, added into `total` the same way open debts are,
    then cancelled back out of distributable_result (see
    ShareholderProfitPreviewService)."""
    admin_user, supplier, order = _make_supplier_order_with_status(
        "WCRELIQUAT-SUP", SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("200000.00"), unit_price=Decimal("1000.0000"),
    )
    _load_partial(order, Decimal("45000.00"), suffix="WCRELIQUAT-SUP")

    result = WorkingCapitalService.get_working_capital()

    assert result["supplier_debt_total"] == Decimal("200000000.00")
    assert result["supplier_reliquat_value"] == Decimal("155000000.00")
    assert result["total"] == (
        result["gross"] + result["supplier_debt_total"] + result["transporter_debt_total"]
        + result["other_debts"] + result["supplier_reliquat_value"]
    )


@pytest.mark.django_db
def test_working_capital_supplier_reliquat_is_zero_once_fully_loaded():
    _, _, order = _make_supplier_order_with_status(
        "WCRELIQUATFULL-SUP", SupplierOrder.Status.CONFIRMED,
        quantity=Decimal("200000.00"), unit_price=Decimal("1000.0000"),
    )
    _fully_load(order, suffix="WCRELIQUATFULL-SUP")

    result = WorkingCapitalService.get_working_capital()

    assert result["supplier_debt_total"] == Decimal("200000000.00")
    assert result["supplier_reliquat_value"] == Decimal("0.00")


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

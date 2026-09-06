from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.finance.models import (
    AdvanceConsumption,
    BankAccount,
    CashAccount,
    SupplierAdvance,
    SupplierPayment,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import (
    AdvanceError,
    AdvanceService,
    ControlledDebtPaymentService,
    SupplierLedgerService,
    TransporterLedgerService,
)
from apps.purchasing.models import SupplierOrder
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _proof_file(name="proof.jpg"):
    return SimpleUploadedFile(name, b"fake-proof-bytes", content_type="image/jpeg")


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role)


def _fully_load(order, *, suffix, admin_user=None, quantity=None):
    """Load `quantity` (default: the order's full quantity_litres) against
    `order` via a real Trip - bug fix (client business rule, confirmed
    2026-09-06): ControlledDebtPaymentService.describe_supplier_order now
    prices the supplier debt on quantity actually loaded, not on the full
    confirmed order, so every fixture in this file that exercises debt-
    based assertions needs a real Trip behind the order. Defaulting to a
    full load keeps every pre-existing assertion of the form
    `... == order.total_amount` correct unchanged; this file's tests are
    about advance-consumption mechanics (FIFO, partial, surplus), not
    about the loaded-vs-purchased debt timing rule itself, which is
    covered separately in apps.purchasing.tests and apps.finance.tests."""
    if admin_user is None:
        admin_user = order.created_by
    quantity = order.quantity_litres if quantity is None else quantity
    short_suffix = suffix[-16:]
    from apps.purchasing.models import CessionLetter

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


def _make_supplier_order_with_status(suffix, status, *, quantity=Decimal("1000.00"), unit_price=Decimal("600.0000")):
    admin_user = _make_admin(suffix)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    order = SupplierOrder.objects.create(
        reference=f"SO-ADV-{suffix}", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=quantity, unit_price=unit_price,
        status=status, created_by=admin_user,
    )
    return admin_user, supplier, order


def _make_trip_for_deduction(suffix):
    admin_user = _make_admin(suffix)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Trans Supplier {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    from apps.purchasing.models import CessionLetter

    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-ADVTRIP-{suffix}", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-ADVTRIP-{suffix}", supplier_order=supplier_order,
        authorized_quantity=Decimal("500000.00"), issue_date="2026-08-18", created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-ADVTRIP-{suffix}", tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER", capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-ADVTRIP-{suffix}", truck=truck, transporter=transporter, supplier=supplier,
        supplier_order=supplier_order, cession_letter=cession, product=product,
        quantity_loaded=Decimal("45000.00"), loading_date="2026-08-18",
        bl_reference=f"BL-ADVTRIP-{suffix}", created_by=admin_user,
    )
    return trip, transporter


# ---------------------------------------------------------------------------
# Task 3: SupplierOrder confirmation/cancellation wiring
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_confirming_supplier_order_directly_consumes_open_advance_fifo():
    admin_user = _make_admin("CONFIRM-DIRECT")
    supplier = Supplier.objects.create(name="Supplier CONFIRM-DIRECT", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Main Cash")
    # Advance exists and is OPEN before any debt (the only order in which the
    # design permits an advance to exist for this supplier).
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("400000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    assert advance.remaining_amount == Decimal("400000.00")

    # Capture TreasuryTransaction count before order creation to verify
    # consumption never creates a TreasuryTransaction.
    treasury_count_before = TreasuryTransaction.objects.count()

    # Order created directly at CONFIRMED -> SupplierOrder.save() hook consumes
    # the pre-existing open advance FIFO at confirmation time.
    order = SupplierOrder.objects.create(
        reference="SO-ADV-CONFIRM-DIRECT", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 600000
    _fully_load(order, suffix="CONFIRM-DIRECT")

    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("0.00")
    remaining_debt = ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"]
    assert remaining_debt == Decimal("200000.00")

    # Consumption never creates a TreasuryTransaction
    assert TreasuryTransaction.objects.count() == treasury_count_before


@pytest.mark.django_db
def test_draft_to_confirmed_transition_consumes_advance_but_draft_creation_does_not():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "DRAFT-THEN-CONFIRM", SupplierOrder.Status.DRAFT,
    )
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("600000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    assert advance.remaining_amount == Decimal("600000.00")

    order.status = SupplierOrder.Status.CONFIRMED
    order.save()
    _fully_load(order, suffix="DRAFT-THEN-CONFIRM")
    advance.refresh_from_db()

    assert advance.remaining_amount == Decimal("0.00")
    assert ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"] == Decimal("0.00")


@pytest.mark.django_db
def test_supplier_advance_partially_covers_larger_order_leaves_remaining_payable():
    admin_user = _make_admin("PARTIAL")
    supplier = Supplier.objects.create(name="Supplier PARTIAL", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Main Cash")
    # Advance exists first
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("250000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    # Order created at CONFIRMED consumes the advance
    order = SupplierOrder.objects.create(
        reference="SO-PARTIAL", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 600000
    _fully_load(order, suffix="PARTIAL")

    remaining = ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"]
    assert remaining == Decimal("350000.00")


@pytest.mark.django_db
def test_advance_exceeding_order_leaves_surplus_open_for_next_order():
    admin_user = _make_admin("SURPLUS")
    supplier = Supplier.objects.create(name="Supplier SURPLUS", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Main Cash")
    # Advance exists first, larger than next order
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    # Order created at CONFIRMED consumes part of the advance
    order = SupplierOrder.objects.create(
        reference="SO-SURPLUS", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 300000
    _fully_load(order, suffix="SURPLUS")

    assert ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"] == Decimal("0.00")
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("200000.00")


@pytest.mark.django_db
def test_resaving_already_confirmed_order_does_not_double_consume():
    admin_user = _make_admin("IDEMPOTENT")
    supplier = Supplier.objects.create(name="Supplier IDEMPOTENT", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Main Cash")
    # Advance exists first
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    # Order created at CONFIRMED consumes the advance
    order = SupplierOrder.objects.create(
        reference="SO-IDEMPOTENT", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 300000
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("200000.00")

    # Re-save the order with unrelated edit - should not double-consume
    order.notes = "unrelated edit"
    order.save()
    advance.refresh_from_db()

    assert advance.remaining_amount == Decimal("200000.00")


@pytest.mark.django_db
def test_cancelling_confirmed_order_reverses_its_advance_consumption():
    admin_user = _make_admin("CANCEL-REVERSE")
    supplier = Supplier.objects.create(name="Supplier CANCEL-REVERSE", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Main Cash")
    # Advance exists first
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("300000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    # Order created at CONFIRMED consumes the entire advance
    order = SupplierOrder.objects.create(
        reference="SO-CANCEL-REVERSE", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 300000
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("0.00")

    # Cancel the order - should reverse the consumption
    order.status = SupplierOrder.Status.CANCELLED
    order.save()
    advance.refresh_from_db()

    assert advance.remaining_amount == Decimal("300000.00")
    consumption = AdvanceConsumption.objects.get(supplier_advance=advance)
    assert consumption.reversed_at is not None


@pytest.mark.django_db
def test_reverting_confirmed_order_to_draft_also_reverses_advance_consumption():
    """Final-review fix: reversal must not be CANCELLED-only. Any transition
    OUT of CONFIRMED (not just to CANCELLED) must release the advance it
    consumed, or the credit is silently lost - describe_supplier_order
    already stops counting a non-CONFIRMED order as debt, so its consumed
    advance must come back too."""
    admin_user = _make_admin("REVERT-DRAFT")
    supplier = Supplier.objects.create(name="Supplier REVERT-DRAFT", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("300000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    order = SupplierOrder.objects.create(
        reference="SO-REVERT-DRAFT", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 300000
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("0.00")

    order.status = SupplierOrder.Status.DRAFT
    order.save()
    advance.refresh_from_db()

    assert advance.remaining_amount == Decimal("300000.00")
    consumption = AdvanceConsumption.objects.get(supplier_advance=advance)
    assert consumption.reversed_at is not None


@pytest.mark.django_db
def test_reconfirming_order_after_reverting_to_draft_consumes_the_advance_again():
    """Round-trip: CONFIRMED -> DRAFT (reversed) -> CONFIRMED must consume
    again, not skip because a reversed AdvanceConsumption row already
    exists for this order."""
    admin_user = _make_admin("REVERT-RECONFIRM")
    supplier = Supplier.objects.create(name="Supplier REVERT-RECONFIRM", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("300000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    order = SupplierOrder.objects.create(
        reference="SO-REVERT-RECONFIRM", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    order.status = SupplierOrder.Status.DRAFT
    order.save()
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("300000.00")

    order.status = SupplierOrder.Status.CONFIRMED
    order.save()
    advance.refresh_from_db()

    assert advance.remaining_amount == Decimal("0.00")


@pytest.mark.django_db
def test_increasing_total_amount_of_an_already_confirmed_order_consumes_the_delta():
    """Final-review fix: staying CONFIRMED while total_amount increases (an
    edit, not a status transition) must also pull from any newly-available
    open advance for the remaining delta - the hook now re-attempts
    consumption on every save while CONFIRMED, not just on the transition
    edge, and this is idempotent when nothing changed."""
    admin_user = _make_admin("INCREASE-CONFIRMED")
    supplier = Supplier.objects.create(name="Supplier INCREASE-CONFIRMED", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Main Cash")
    order = SupplierOrder.objects.create(
        reference="SO-INCREASE-CONFIRMED", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 300000, no advance yet -> nothing consumed
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("300000.00"), date="2026-08-19",
        cash_account=cash_account, recorded_by=admin_user,
    )
    # advance created AFTER the order already exists - by design this does
    # NOT retroactively consume (only a save() of the order can trigger
    # consumption), so the advance stays fully open until the order itself
    # is saved again.
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("300000.00")

    order.quantity_litres = Decimal("1000.00")  # total becomes 600000
    order.save()  # still CONFIRMED -> CONFIRMED, re-attempts consumption
    _fully_load(order, suffix="INCREASE-CONFIRMED")  # loads the full, now-1000L quantity

    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("0.00")
    remaining_debt = ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"]
    assert remaining_debt == Decimal("300000.00")


@pytest.mark.django_db
def test_supplier_advance_alone_without_debt_does_not_create_payable_debt():
    admin_user = _make_admin("NO-DEBT")
    supplier = Supplier.objects.create(name="No Order Supplier", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("1000000.00"), date="2026-08-18",
        cash_account=cash_account, recorded_by=admin_user,
    )
    payable = [
        row for row in ControlledDebtPaymentService.get_payable_debts("supplier")
        if row["id"] == supplier.id
    ]
    assert payable == []


# ---------------------------------------------------------------------------
# Task 4: TransportPayment automatic consumption
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_transport_payment_consumes_advance_automatically_without_manual_selection():
    trip, transporter = _make_trip_for_deduction("AUTO-CONSUME")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-17",
        cash_account=cash_account,
    )

    payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"), deduction_amount=Decimal("42500.00"),
    )

    assert payment.net_amount == Decimal("557500.00")
    assert payment.advance_applied_id is None


@pytest.mark.django_db
def test_transport_payment_partial_advance_leaves_remaining_payable():
    trip, transporter = _make_trip_for_deduction("PARTIAL-TRANS")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("200000.00"), date="2026-08-17",
        cash_account=cash_account,
    )

    payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )

    assert payment.net_amount == Decimal("500000.00")
    remaining = ControlledDebtPaymentService.describe_transport_payment(payment)["remaining_amount"]
    assert remaining == Decimal("500000.00")


@pytest.mark.django_db
def test_transport_payment_advance_surplus_stays_open_for_next_trip():
    trip, transporter = _make_trip_for_deduction("SURPLUS-TRANS")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("900000.00"), date="2026-08-17",
        cash_account=cash_account,
    )

    payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )

    assert payment.net_amount == Decimal("0.00")
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("200000.00")


@pytest.mark.django_db
def test_transporter_advance_alone_without_trip_does_not_create_payable_debt():
    trip, transporter = _make_trip_for_deduction("NO-DEBT-TRANS")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("500000.00"), date="2026-08-18",
        cash_account=cash_account,
    )
    payable = [
        row for row in ControlledDebtPaymentService.get_payable_debts("transporter")
        if row["id"] == transporter.id
    ]
    assert payable == []


# ---------------------------------------------------------------------------
# Task 5: describe_supplier_balance / describe_transporter_balance
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_describe_supplier_balance_debt_only():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "BAL-DEBT", SupplierOrder.Status.CONFIRMED,
    )
    _fully_load(order, suffix="BAL-DEBT")
    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["total_due"] == Decimal("600000.00")
    assert balance["open_advances"] == Decimal("0.00")
    assert balance["net_balance"] == Decimal("-600000.00")


@pytest.mark.django_db
def test_describe_supplier_balance_advance_only():
    admin_user = _make_admin("BAL-ADV-ONLY")
    cash_account = CashAccount.objects.create(name="Main Cash")
    supplier = Supplier.objects.create(name="No Debt Supplier", country="Senegal")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("300000.00"), date="2026-08-18",
        cash_account=cash_account, recorded_by=admin_user,
    )
    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["total_due"] == Decimal("0.00")
    assert balance["open_advances"] == Decimal("300000.00")
    assert balance["net_balance"] == Decimal("300000.00")


@pytest.mark.django_db
def test_describe_supplier_balance_partial_consumption():
    admin_user = _make_admin("BAL-PARTIAL")
    supplier = Supplier.objects.create(name="Supplier BAL-PARTIAL", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Main Cash")
    # Advance created first
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("250000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    # Order created at CONFIRMED, consumes the advance
    order = SupplierOrder.objects.create(
        reference="SO-BAL-PARTIAL", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 600000
    _fully_load(order, suffix="BAL-PARTIAL")
    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["total_due"] == Decimal("350000.00")
    assert balance["open_advances"] == Decimal("0.00")
    assert balance["net_balance"] == Decimal("-350000.00")


@pytest.mark.django_db
def test_describe_supplier_balance_full_consumption_with_surplus():
    admin_user = _make_admin("BAL-FULL")
    supplier = Supplier.objects.create(name="Supplier BAL-FULL", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Main Cash")
    # Advance created first, larger than order
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    # Order created at CONFIRMED, consumes part of the advance
    order = SupplierOrder.objects.create(
        reference="SO-BAL-FULL", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 300000
    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["total_due"] == Decimal("0.00")
    assert balance["open_advances"] == Decimal("200000.00")
    assert balance["net_balance"] == Decimal("200000.00")


@pytest.mark.django_db
def test_describe_transporter_balance_debt_only():
    trip, transporter = _make_trip_for_deduction("TBAL-DEBT")
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    balance = ControlledDebtPaymentService.describe_transporter_balance(transporter)
    assert balance["total_due"] == Decimal("700000.00")
    assert balance["net_balance"] == Decimal("-700000.00")


@pytest.mark.django_db
def test_describe_transporter_balance_advance_only():
    trip, transporter = _make_trip_for_deduction("TBAL-ADV")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("150000.00"), date="2026-08-18",
        cash_account=cash_account,
    )
    balance = ControlledDebtPaymentService.describe_transporter_balance(transporter)
    assert balance["total_due"] == Decimal("0.00")
    assert balance["open_advances"] == Decimal("150000.00")
    assert balance["net_balance"] == Decimal("150000.00")


@pytest.mark.django_db
def test_describe_transporter_balance_partial_consumption():
    trip, transporter = _make_trip_for_deduction("TBAL-PARTIAL")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("200000.00"), date="2026-08-17",
        cash_account=cash_account,
    )
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    balance = ControlledDebtPaymentService.describe_transporter_balance(transporter)
    assert balance["total_due"] == Decimal("500000.00")
    assert balance["open_advances"] == Decimal("0.00")
    assert balance["net_balance"] == Decimal("-500000.00")


# ---------------------------------------------------------------------------
# Task 6: AdvanceService (creation, treasury posting, open-debt guard)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_supplier_advance_posts_one_treasury_transaction_and_document():
    admin_user = _make_admin("CREATE-SADV")
    supplier = Supplier.objects.create(name="Create Advance Supplier", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    advance = AdvanceService.create_supplier_advance(
        supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
        amount=Decimal("1000000.00"), date="2026-08-18", reference="SADV-1", notes="",
        attachment=_proof_file(), actor=admin_user,
    )

    assert advance.remaining_amount == Decimal("1000000.00")
    assert advance.document_id is not None
    cash_account.refresh_from_db()
    assert cash_account.current_balance == Decimal("4000000.00")
    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(SupplierAdvance), source_object_id=advance.id,
    )
    assert txn.type == TreasuryTransaction.Type.MONEY_OUT
    assert txn.amount == Decimal("1000000.00")
    assert txn.document_id == advance.document_id


@pytest.mark.django_db
def test_create_supplier_advance_succeeds_without_attachment():
    """Task 13 (2026-09-04 recette corrections): AdvanceService itself must
    not require an attachment - it must not attempt to create a Document
    row (whose file field is mandatory) when none is supplied."""
    admin_user = _make_admin("CREATE-SADV-NOATT")
    supplier = Supplier.objects.create(name="Create Advance Supplier No Attachment", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    advance = AdvanceService.create_supplier_advance(
        supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
        amount=Decimal("1000000.00"), date="2026-08-18", reference="SADV-NOATT", notes="",
        attachment=None, actor=admin_user,
    )

    assert advance.document_id is None
    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(SupplierAdvance), source_object_id=advance.id,
    )
    assert txn.document_id is None


@pytest.mark.django_db
def test_create_supplier_advance_rejected_when_open_debt_exists():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "REJECT-SADV", SupplierOrder.Status.CONFIRMED,
    )  # total 600000, no advance yet -> net_balance = -600000
    _fully_load(order, suffix="REJECT-SADV")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    with pytest.raises(AdvanceError):
        AdvanceService.create_supplier_advance(
            supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
            amount=Decimal("100000.00"), date="2026-08-18", reference="", notes="",
            attachment=_proof_file(), actor=admin_user,
        )
    assert SupplierAdvance.objects.filter(supplier=supplier).count() == 0


@pytest.mark.django_db
def test_create_supplier_advance_allowed_when_net_balance_is_already_positive():
    admin_user = _make_admin("STACK-SADV")
    supplier = Supplier.objects.create(name="Stack Advance Supplier", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))
    AdvanceService.create_supplier_advance(
        supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
        amount=Decimal("300000.00"), date="2026-08-17", reference="SADV-A", notes="",
        attachment=_proof_file(), actor=admin_user,
    )

    second = AdvanceService.create_supplier_advance(
        supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
        amount=Decimal("200000.00"), date="2026-08-18", reference="SADV-B", notes="",
        attachment=_proof_file(), actor=admin_user,
    )

    assert second.remaining_amount == Decimal("200000.00")
    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["open_advances"] == Decimal("500000.00")


@pytest.mark.django_db
def test_create_transporter_advance_posts_treasury_transaction():
    trip, transporter = _make_trip_for_deduction("CREATE-TADV")
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance=Decimal("2000000.00"))

    advance = AdvanceService.create_transporter_advance(
        transporter_id=transporter.id, bank_account_id=bank_account.id, cash_account_id=None,
        amount=Decimal("500000.00"), date="2026-08-18", reference="TADV-1", notes="",
        attachment=_proof_file(), actor=_make_admin("CREATE-TADV-ACTOR"),
    )

    assert advance.remaining_amount == Decimal("500000.00")
    bank_account.refresh_from_db()
    assert bank_account.current_balance == Decimal("1500000.00")
    assert TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(TransporterAdvance),
        source_object_id=advance.id,
    ).exists()


@pytest.mark.django_db
def test_create_transporter_advance_succeeds_without_attachment():
    """Task 13 (2026-09-04 recette corrections): same as the supplier
    advance case - no attachment must not crash AdvanceService."""
    trip, transporter = _make_trip_for_deduction("CREATE-TADV-NOATT")
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance=Decimal("2000000.00"))

    advance = AdvanceService.create_transporter_advance(
        transporter_id=transporter.id, bank_account_id=bank_account.id, cash_account_id=None,
        amount=Decimal("500000.00"), date="2026-08-18", reference="TADV-NOATT", notes="",
        attachment=None, actor=_make_admin("TADV-NOATT-ACTOR"),
    )

    assert advance.document_id is None
    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(TransporterAdvance),
        source_object_id=advance.id,
    )
    assert txn.document_id is None


@pytest.mark.django_db
def test_create_transporter_advance_rejected_when_open_debt_exists():
    trip, transporter = _make_trip_for_deduction("REJECT-TADV")
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance=Decimal("2000000.00"))

    with pytest.raises(AdvanceError):
        AdvanceService.create_transporter_advance(
            transporter_id=transporter.id, bank_account_id=bank_account.id, cash_account_id=None,
            amount=Decimal("100000.00"), date="2026-08-18", reference="", notes="",
            attachment=_proof_file(), actor=_make_admin("REJECT-TADV-ACTOR"),
        )


@pytest.mark.django_db
def test_create_supplier_advance_rejects_amount_exceeding_account_balance():
    admin_user = _make_admin("INSUF-SADV")
    supplier = Supplier.objects.create(name="Insufficient Balance Supplier", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("100000.00"))

    with pytest.raises(AdvanceError):
        AdvanceService.create_supplier_advance(
            supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
            amount=Decimal("1000000.00"), date="2026-08-18", reference="", notes="",
            attachment=_proof_file(), actor=admin_user,
        )


# ---------------------------------------------------------------------------
# Task 13: profit non-impact (pinning test - no production code change)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_advance_creation_and_consumption_never_touch_the_fields_profit_reads_from():
    """TripProfitService/TripCostService read SupplierOrder.unit_price and
    TransportPayment.base_amount for cost purposes - never total_amount or
    net_amount, which are the only fields advance consumption can affect.
    Pinning this at the source is more decisive than wiring up a full
    Sale/margin computation: if either input field below ever moved, the
    margin formula would silently change too."""
    admin_user, supplier, order = _make_supplier_order_with_status(
        "PROFIT-ADV", SupplierOrder.Status.DRAFT, quantity=Decimal("45000.00"),
    )
    cash_account = CashAccount.objects.create(name="Main Cash")
    trip, transporter = _make_trip_for_deduction("PROFIT-ADV-TRIP")

    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("2000000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    order.status = SupplierOrder.Status.CONFIRMED
    order.save()
    order.refresh_from_db()

    assert order.unit_price == Decimal("600.0000")
    assert order.total_amount == Decimal("27000000.00")

    payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("300000.00"), date="2026-08-17",
        cash_account=cash_account,
    )
    payment.refresh_from_db()
    assert payment.base_amount == Decimal("700000.00")


# ---------------------------------------------------------------------------
# Task 7: API endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def advances_finance_client():
    from apps.accounts.models import Role, User
    from rest_framework.test import APIClient

    role = Role.objects.get(name=Role.NAME_FINANCE)
    user = User.objects.create_user(phone="+2220000077", pin="1234", role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_supplier_advance_endpoint_succeeds_without_attachment(advances_finance_client):
    """Task 13 (2026-09-04 recette corrections): no justificatif is ever
    mandatory - a supplier advance with no attachment must still succeed
    and leave proof_url null."""
    supplier = Supplier.objects.create(name="API Advance Supplier", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    response = advances_finance_client.post(
        "/api/supplier-advances/",
        {
            "supplier": supplier.id, "cash_account": cash_account.id,
            "amount": "500000.00", "date": "2026-08-18", "reference": "SADV-API",
        },
    )
    assert response.status_code == 201, response.data
    assert response.data["remaining_amount"] == "500000.00"
    assert response.data["proof_url"] is None


@pytest.mark.django_db
def test_supplier_advance_endpoint_rejects_non_image_attachment(advances_finance_client):
    supplier = Supplier.objects.create(name="API Advance Supplier PDF", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))
    pdf_file = SimpleUploadedFile("proof.pdf", b"%PDF-1.4 fake", content_type="application/pdf")

    response = advances_finance_client.post(
        "/api/supplier-advances/",
        {
            "supplier": supplier.id, "cash_account": cash_account.id,
            "amount": "500000.00", "date": "2026-08-18", "attachment": pdf_file,
        },
        format="multipart",
    )
    assert response.status_code == 400
    assert "attachment" in response.data


@pytest.mark.django_db
def test_supplier_advance_endpoint_creates_advance_with_valid_image(advances_finance_client):
    supplier = Supplier.objects.create(name="API Advance Supplier OK", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    response = advances_finance_client.post(
        "/api/supplier-advances/",
        {
            "supplier": supplier.id, "cash_account": cash_account.id,
            "amount": "500000.00", "date": "2026-08-18", "reference": "SADV-API-OK",
            "attachment": _proof_file(),
        },
        format="multipart",
    )
    assert response.status_code == 201, response.data
    assert response.data["remaining_amount"] == "500000.00"
    assert response.data["proof_url"] is not None


@pytest.mark.django_db
def test_supplier_advance_endpoint_rejects_creation_with_open_debt(advances_finance_client):
    admin_user, supplier, order = _make_supplier_order_with_status(
        "API-REJECT", SupplierOrder.Status.CONFIRMED,
    )
    _fully_load(order, suffix="API-REJECT")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    response = advances_finance_client.post(
        "/api/supplier-advances/",
        {
            "supplier": supplier.id, "cash_account": cash_account.id,
            "amount": "100000.00", "date": "2026-08-18", "attachment": _proof_file(),
        },
        format="multipart",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_transporter_advance_endpoint_succeeds_without_attachment(advances_finance_client):
    """Task 13 (2026-09-04 recette corrections): no justificatif is ever
    mandatory - a transporter advance with no attachment must still
    succeed (the account is still required)."""
    trip, transporter = _make_trip_for_deduction("API-TADV")
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance=Decimal("2000000.00"))

    response = advances_finance_client.post(
        "/api/transporter-advances/",
        {"transporter": transporter.id, "bank_account": bank_account.id, "amount": "100000.00", "date": "2026-08-18"},
    )
    assert response.status_code == 201, response.data
    assert response.data["proof_url"] is None
    bank_account.refresh_from_db()
    assert bank_account.current_balance == Decimal("1900000.00")


@pytest.mark.django_db
def test_transporter_advance_endpoint_creates_advance_and_posts_treasury(advances_finance_client):
    trip, transporter = _make_trip_for_deduction("API-TADV-OK")
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance=Decimal("2000000.00"))

    response = advances_finance_client.post(
        "/api/transporter-advances/",
        {
            "transporter": transporter.id, "bank_account": bank_account.id,
            "amount": "300000.00", "date": "2026-08-18", "attachment": _proof_file(),
        },
        format="multipart",
    )
    assert response.status_code == 201, response.data
    bank_account.refresh_from_db()
    assert bank_account.current_balance == Decimal("1700000.00")


# ---------------------------------------------------------------------------
# Task 8: party-balances endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_party_balances_endpoint_matches_describe_supplier_balance(advances_finance_client):
    admin_user, supplier, order = _make_supplier_order_with_status(
        "PB-SUP", SupplierOrder.Status.CONFIRMED,
    )
    cash_account = CashAccount.objects.create(name="Main Cash")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("250000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )

    response = advances_finance_client.get(
        "/api/treasury-transactions/party-balances/?debt_type=supplier"
    )
    assert response.status_code == 200
    row = next(r for r in response.data if r["id"] == supplier.id)
    expected = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert row["total_due"] == f"{expected['total_due']:.2f}"
    assert row["net_balance"] == f"{expected['net_balance']:.2f}"


@pytest.mark.django_db
def test_party_balances_endpoint_lists_transporters(advances_finance_client):
    trip, transporter = _make_trip_for_deduction("PB-TRANS")
    response = advances_finance_client.get(
        "/api/treasury-transactions/party-balances/?debt_type=transporter"
    )
    assert response.status_code == 200
    assert any(r["id"] == transporter.id for r in response.data)


@pytest.mark.django_db
def test_party_balances_endpoint_rejects_unknown_debt_type(advances_finance_client):
    response = advances_finance_client.get(
        "/api/treasury-transactions/party-balances/?debt_type=bogus"
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Task 12 (simplified): retire SupplierPayment.is_advance for new writes.
# No data migration: dev DB has zero existing is_advance=True rows.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_supplier_payment_serializer_rejects_new_advance_creation(advances_finance_client):
    admin_user, supplier, order = _make_supplier_order_with_status(
        "BLOCK-ADV", SupplierOrder.Status.CONFIRMED,
    )
    cash_account = CashAccount.objects.create(name="Main Cash")
    response = advances_finance_client.post(
        "/api/supplier-payments/",
        {
            "supplier": supplier.id, "amount": "500000.00", "payment_date": "2026-08-18",
            "method": "CASH", "cash_account": cash_account.id, "is_advance": True,
        },
    )
    assert response.status_code == 400
    assert "is_advance" in response.data


# ---------------------------------------------------------------------------
# Task 10: SupplierLedgerService / TransporterLedgerService
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_supplier_ledger_service_orders_entries_chronologically_with_all_four_types():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "LEDGER-SVC", SupplierOrder.Status.DRAFT,
    )
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("300000.00"), date="2026-08-10",
        cash_account=cash_account, recorded_by=admin_user,
    )
    order.purchase_date = "2026-08-15"
    order.status = SupplierOrder.Status.CONFIRMED
    order.save()  # 600000 debt, consumes the 300000 advance, leaves 300000 payable
    _fully_load(order, suffix="LEDGER-SVC")

    ControlledDebtPaymentService.record_payment(
        debt_type="supplier", debt_id=supplier.id,
        bank_account_id=BankAccount.objects.create(
            name="Ledger Bank", opening_balance=Decimal("5000000.00")
        ).id,
        amount=Decimal("300000.00"), date="2026-08-20", reference="PAY-LEDGER-SVC", actor=admin_user,
    )

    ledger = SupplierLedgerService.get_ledger(supplier)

    assert ledger["summary"]["net_balance"] == Decimal("0.00")
    types_in_order = [entry["type"] for entry in ledger["entries"]]
    assert types_in_order == ["advance_given", "debt_created", "advance_consumed", "payment"]
    assert ledger["entries"][0]["amount"] == Decimal("300000.00")
    assert ledger["entries"][1]["amount"] == Decimal("600000.00")
    assert ledger["entries"][3]["amount"] == Decimal("300000.00")


@pytest.mark.django_db
def test_transporter_ledger_service_reports_summary_and_entries():
    trip, transporter = _make_trip_for_deduction("LEDGER-SVC-T")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("200000.00"), date="2026-08-10",
        cash_account=cash_account,
    )
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )

    ledger = TransporterLedgerService.get_ledger(transporter)

    assert ledger["summary"]["total_due"] == Decimal("500000.00")
    types_present = {entry["type"] for entry in ledger["entries"]}
    assert types_present == {"advance_given", "debt_created", "advance_consumed"}


@pytest.mark.django_db
def test_supplier_ledger_endpoint_keeps_existing_keys_and_adds_summary_entries(advances_finance_client):
    admin_user, supplier, order = _make_supplier_order_with_status(
        "LEDGER-API", SupplierOrder.Status.CONFIRMED,
    )
    response = advances_finance_client.get(f"/api/suppliers/{supplier.id}/ledger/")
    assert response.status_code == 200
    for key in ("orders", "reliquat_summary", "payments", "total_purchased", "total_paid", "outstanding_balance"):
        assert key in response.data
    assert "summary" in response.data
    assert "entries" in response.data


@pytest.mark.django_db
def test_transporter_ledger_endpoint_advances_applied_reflects_automatic_consumption(advances_finance_client):
    trip, transporter = _make_trip_for_deduction("LEDGER-API-T")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-17",
        cash_account=cash_account,
    )
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )

    response = advances_finance_client.get(f"/api/transporters/{transporter.id}/ledger/")
    assert response.status_code == 200
    assert response.data["advances_applied"] == "100000.00"
    assert "summary" in response.data
    assert "entries" in response.data

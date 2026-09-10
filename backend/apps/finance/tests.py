import json
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from django.contrib.contenttypes.models import ContentType

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.core.models import Product
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.finance.models import (
    AdvanceConsumption,
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ExpenseAllocation,
    PaymentAllocation,
    Shareholder,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
    SupplierAdvance,
    SupplierPayment,
    TransportDeduction,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import (
    AdvanceConsumptionService,
    ControlledDebtPaymentError,
    ControlledDebtPaymentService,
    FinancePostingService,
    IndirectSettlementService,
    PaymentAllocationError,
    PaymentAllocationService,
    ShareholderDistributionError,
    ShareholderDistributionService,
    ShareholderLedgerService,
    ShareholderLoanError,
    ShareholderLoanService,
    ShareholderParticipationError,
    ShareholderProfitPreviewService,
    ShareholderService,
    ShareholderWithdrawalError,
    ShareholderWithdrawalService,
    TreasuryService,
    TreasuryTransferError,
)


def _proof_file(name="proof.jpg"):
    return SimpleUploadedFile(name, b"fake-proof-bytes", content_type="image/jpeg")
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.purchasing.services import SupplierStockService
from apps.sales.models import Invoice, Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


@pytest.mark.django_db
def test_bank_account_current_balance_defaults_to_opening_balance():
    account = BankAccount.objects.create(
        name="Main BOA Account", bank_name="Bank of Africa", opening_balance="1000000.00"
    )
    assert account.current_balance == Decimal("1000000.00")


@pytest.mark.django_db
def test_bank_account_current_balance_sums_money_in_and_out():
    """opening_balance + MONEY_IN - MONEY_OUT (guide Section 8.10/D) -
    computed live from TreasuryTransaction, never stored."""
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000011", pin="1234", role=admin_role
    )
    account = BankAccount.objects.create(name="Main BOA Account", opening_balance="1000000.00")

    TreasuryTransaction.objects.create(
        bank_account=account, type=TreasuryTransaction.Type.MONEY_IN,
        amount=Decimal("500000.00"), date="2026-08-18", recorded_by=admin_user,
    )
    TreasuryTransaction.objects.create(
        bank_account=account, type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("200000.00"), date="2026-08-18", recorded_by=admin_user,
    )

    assert account.current_balance == Decimal("1300000.00")


@pytest.mark.django_db
def test_cash_account_currency_defaults_to_xof():
    account = CashAccount.objects.create(name="Main Cash", location="Dakar office")
    assert account.currency == "XOF"


@pytest.fixture
def finance_client():
    role = Role.objects.get(name=Role.NAME_FINANCE)
    user = User.objects.create_user(phone="+2220000003", pin="1234", role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_bank_account_crud_via_api(finance_client):
    created = finance_client.post(
        "/api/bank-accounts/", {"name": "Main BOA Account", "bank_name": "Bank of Africa", "opening_balance": "1000000.00"}
    )
    assert created.status_code == 201

    listed = finance_client.get("/api/bank-accounts/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1

    account_id = created.data["id"]
    retrieved = finance_client.get(f"/api/bank-accounts/{account_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["current_balance"] == "1000000.00"

    updated = finance_client.patch(f"/api/bank-accounts/{account_id}/", {"account_number": "SN001"})
    assert updated.status_code == 200
    assert updated.data["account_number"] == "SN001"


@pytest.mark.django_db
def test_cash_account_crud_via_api(finance_client):
    created = finance_client.post(
        "/api/cash-accounts/", {"name": "Main Cash", "location": "Dakar office", "opening_balance": "500000.00"}
    )
    assert created.status_code == 201

    listed = finance_client.get("/api/cash-accounts/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1

    account_id = created.data["id"]
    retrieved = finance_client.get(f"/api/cash-accounts/{account_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["current_balance"] == "500000.00"

    updated = finance_client.patch(f"/api/cash-accounts/{account_id}/", {"location": "Bamako office"})
    assert updated.status_code == 200
    assert updated.data["location"] == "Bamako office"


@pytest.mark.django_db
def test_operations_role_can_create_truck_but_not_bank_account():
    """Mandatory scenario from roadmap/phase_1_foundation.md: an Operations
    user must be able to create a Truck (operations module) but must be
    denied creating a BankAccount (finance module)."""
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    user = User.objects.create_user(phone="+2220000001", pin="1234", role=role)
    client = APIClient()
    client.force_authenticate(user)

    truck_response = client.post(
        "/api/trucks/",
        {
            "internal_id": "TRK-100",
            "tractor_registration": "EE-345-SN",
            "tanker_registration": "FF-678-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "COMPANY_OWNED",
        },
    )
    assert truck_response.status_code == 201

    bank_response = client.post(
        "/api/bank-accounts/", {"name": "Main BOA Account", "opening_balance": "1000000.00"}
    )
    assert bank_response.status_code == 403


# ---------------------------------------------------------------------------
# Phase 4 Etape 3: TransportDeduction (docs/PHASE_4_PLAN.md; guide Section 7.5)
# ---------------------------------------------------------------------------


def _make_trip_for_deduction(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone=(f"+222{suffix}")[:20],
        pin="1234",
        role=admin_role,
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    transporter = Transporter.objects.create(name="Trans SA")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-DED-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-DED-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("500000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-DED-{suffix}",
        tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-DED-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=product,
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference=f"BL-DED-{suffix}",
        created_by=admin_user,
    )
    return trip, transporter


@pytest.mark.django_db
def test_transport_deduction_amount_computed_on_save():
    trip, transporter = _make_trip_for_deduction("AMT")

    deduction = TransportDeduction.objects.create(
        trip=trip,
        transporter=transporter,
        chargeable_quantity=Decimal("50.00"),
        unit_price=Decimal("600.0000"),
    )

    assert deduction.amount == Decimal("30000.00")
    assert deduction.status == TransportDeduction.Status.DRAFT
    assert deduction.currency == "XOF"


@pytest.mark.django_db
def test_transport_deduction_requires_positive_chargeable_quantity():
    trip, transporter = _make_trip_for_deduction("NEG")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TransportDeduction.objects.create(
                trip=trip,
                transporter=transporter,
                chargeable_quantity=Decimal("0.00"),
                unit_price=Decimal("600.0000"),
            )


# ---------------------------------------------------------------------------
# Phase 5 Etape 1: CustomerPayment / PaymentAllocation
# (docs/PHASE_5_PLAN.md; guide Section 8.2/8.3/1.7)
# ---------------------------------------------------------------------------


def _make_invoice_for_payment(suffix, total_amount=None, customer=None):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone=(f"+222{suffix}")[:20],
        pin="1234",
        role=admin_role,
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    transporter = Transporter.objects.create(name="Trans SA")
    if customer is None:
        customer = Customer.objects.create(name=f"Client {suffix}")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-PAY-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-PAY-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("500000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-PAY-{suffix}",
        tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-PAY-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=product,
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference=f"BL-PAY-{suffix}",
        status=Trip.Status.DELIVERED,
        created_by=admin_user,
    )
    sale = Sale.objects.create(
        trip=trip,
        customer=customer,
        product=product,
        delivered_quantity=Decimal("44850.00"),
        unit_selling_price=Decimal("650.0000"),
    )
    invoice = Invoice.objects.create(
        invoice_number=f"INV-PAY-{suffix}",
        sale=sale,
        total_amount=total_amount if total_amount is not None else sale.subtotal,
        status=Invoice.Status.VALIDATED,
        issued_date="2026-08-18",
    )
    return admin_user, customer, invoice


@pytest.mark.django_db
def test_customer_payment_requires_positive_amount():
    admin_user, customer, _invoice = _make_invoice_for_payment("AMT")
    cash_account = CashAccount.objects.create(name="Main Cash")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CustomerPayment.objects.create(
                customer=customer,
                amount=Decimal("0.00"),
                payment_date="2026-08-18",
                method=CustomerPayment.Method.CASH,
                cash_account=cash_account,
                recorded_by=admin_user,
            )


@pytest.mark.django_db
def test_customer_payment_cannot_set_both_accounts():
    admin_user, customer, _invoice = _make_invoice_for_payment("BOTH")
    bank_account = BankAccount.objects.create(name="Main BOA Account")
    cash_account = CashAccount.objects.create(name="Main Cash")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CustomerPayment.objects.create(
                customer=customer,
                amount=Decimal("1000000.00"),
                payment_date="2026-08-18",
                method=CustomerPayment.Method.BANK_TRANSFER,
                bank_account=bank_account,
                cash_account=cash_account,
                recorded_by=admin_user,
            )


@pytest.mark.django_db
def test_indirect_customer_payment_requires_no_treasury_account():
    admin_user, customer, _invoice = _make_invoice_for_payment("IND")

    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("5000000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.OTHER,
        is_indirect=True,
        recorded_by=admin_user,
    )

    assert payment.bank_account is None
    assert payment.cash_account is None
    assert payment.is_indirect is True


# ---------------------------------------------------------------------------
# Task 4 (client modifications plan): destination/note, treasury posting for
# direct customer payments, and the customerpayment document-proof upload.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_finance_posting_service_returns_none_for_indirect_payment():
    admin_user, customer, _invoice = _make_invoice_for_payment("FPS-IND")
    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("1000000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.OTHER,
        is_indirect=True,
        destination=CustomerPayment.Destination.INDIRECT,
        recorded_by=admin_user,
    )

    result = FinancePostingService.record_customer_payment_treasury(payment)

    assert result is None
    assert TreasuryTransaction.objects.count() == 0


@pytest.mark.django_db
def test_finance_posting_service_posts_money_in_on_cash_account():
    admin_user, customer, _invoice = _make_invoice_for_payment("FPS-CASH")
    cash_account = CashAccount.objects.create(name="Main Cash")
    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("750000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH,
        cash_account=cash_account,
        destination=CustomerPayment.Destination.CASH,
        recorded_by=admin_user,
    )

    txn = FinancePostingService.record_customer_payment_treasury(payment)

    assert txn is not None
    assert txn.type == TreasuryTransaction.Type.MONEY_IN
    assert txn.cash_account_id == cash_account.id
    assert txn.bank_account is None
    assert txn.amount == Decimal("750000.00")
    assert txn.source_object == payment
    assert txn.source_content_type == ContentType.objects.get_for_model(CustomerPayment)


@pytest.mark.django_db
def test_finance_posting_service_prevents_duplicate_posting():
    """Calling the service twice for the same payment (e.g. a retried
    request) must only ever create one TreasuryTransaction (task 4 brief:
    "Prevent duplicate posting if a linked transaction already exists")."""
    admin_user, customer, _invoice = _make_invoice_for_payment("FPS-DUP")
    cash_account = CashAccount.objects.create(name="Main Cash")
    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("300000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH,
        cash_account=cash_account,
        destination=CustomerPayment.Destination.CASH,
        recorded_by=admin_user,
    )

    first = FinancePostingService.record_customer_payment_treasury(payment)
    second = FinancePostingService.record_customer_payment_treasury(payment)

    assert first is not None
    assert second is None
    assert TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(CustomerPayment),
        source_object_id=payment.id,
    ).count() == 1


@pytest.mark.django_db
def test_finance_posting_service_vers_moi_maps_to_dedicated_cash_account():
    admin_user, customer, _invoice = _make_invoice_for_payment("FPS-VM")
    vers_moi = FinancePostingService.get_or_create_vers_moi_account()
    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("200000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH,
        cash_account=vers_moi,
        destination=CustomerPayment.Destination.VERS_MOI,
        recorded_by=admin_user,
    )

    txn = FinancePostingService.record_customer_payment_treasury(payment)

    assert txn is not None
    assert txn.cash_account_id == vers_moi.id


@pytest.mark.django_db
def test_get_or_create_vers_moi_account_does_not_duplicate():
    account_a = FinancePostingService.get_or_create_vers_moi_account()
    account_b = FinancePostingService.get_or_create_vers_moi_account()

    assert account_a.id == account_b.id
    assert CashAccount.objects.filter(name="Vers moi").count() == 1


@pytest.mark.django_db
def test_payment_allocation_requires_positive_amount():
    admin_user, customer, invoice = _make_invoice_for_payment("ALLOC-NEG")
    cash_account = CashAccount.objects.create(name="Main Cash")
    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("10000000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH,
        cash_account=cash_account,
        recorded_by=admin_user,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PaymentAllocation.objects.create(
                payment=payment, invoice=invoice, amount=Decimal("0.00")
            )


@pytest.mark.django_db
def test_payment_allocation_links_payment_to_invoice():
    admin_user, customer, invoice = _make_invoice_for_payment("ALLOC-LINK")
    cash_account = CashAccount.objects.create(name="Main Cash")
    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("10000000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH,
        cash_account=cash_account,
        recorded_by=admin_user,
    )

    allocation = PaymentAllocation.objects.create(
        payment=payment, invoice=invoice, amount=Decimal("10000000.00")
    )

    assert payment.allocations.count() == 1
    assert invoice.allocations.first() == allocation


@pytest.mark.django_db
def test_payment_allocation_invoice_null_means_unallocated_credit():
    admin_user, customer, _invoice = _make_invoice_for_payment("ALLOC-CREDIT")
    cash_account = CashAccount.objects.create(name="Main Cash")
    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("2000000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH,
        cash_account=cash_account,
        recorded_by=admin_user,
    )

    allocation = PaymentAllocation.objects.create(
        payment=payment, invoice=None, amount=Decimal("2000000.00")
    )

    assert allocation.invoice is None
    assert payment.allocations.get().invoice is None


# ---------------------------------------------------------------------------
# Phase 5 Etape 2: SupplierPayment (docs/PHASE_5_PLAN.md; guide Section 8.5)
# ---------------------------------------------------------------------------


def _load_trip_for_supplier_order(*, supplier, supplier_order, quantity, suffix, admin_user):
    """Load `quantity` litres against `supplier_order` via a real Trip.
    Since the 2026-09-10 business rule reversal, loading no longer affects
    the supplier debt itself (ControlledDebtPaymentService.
    describe_supplier_order now books the full confirmed order immediately)
    - this helper still matters for get_purchase_loaded_amount/
    get_purchase_reliquat_amount, which do depend on it."""
    if quantity <= Decimal("0.00"):
        return None
    # Truncated defensively: Truck's internal_id/tractor_registration/
    # tanker_registration are all varchar(30), and this helper's callers
    # pass arbitrarily long test suffixes.
    short_suffix = suffix[-16:]
    cession = CessionLetter.objects.create(
        reference=f"CL-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=supplier_order.quantity_litres,
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-{short_suffix}",
        tractor_registration=f"{short_suffix}-TRAC",
        tanker_registration=f"{short_suffix}-TANK",
        capacity_litres=Decimal("45000.00"),
    )
    transporter = Transporter.objects.create(name=f"Transporteur {suffix}")
    return Trip.objects.create(
        reference=f"TRIP-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=supplier_order.product,
        quantity_loaded=quantity,
        loading_date="2026-08-18",
        bl_reference=f"BL-{suffix}",
        created_by=admin_user,
    )


def _make_supplier_order(suffix, *, loaded_quantity=None):
    """`loaded_quantity`: since the 2026-09-10 business rule reversal the
    supplier debt itself no longer depends on loading (it's the full
    confirmed order, immediately) - this only still matters for tests that
    exercise get_purchase_loaded_amount/get_purchase_reliquat_amount.
    Defaulting to a trip that loads the FULL purchased quantity keeps this
    helper backward compatible with every existing caller. Pass an explicit
    smaller Decimal to test partial loading instead."""
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone=(f"+222{suffix}")[:20],
        pin="1234",
        role=admin_role,
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    quantity_litres = Decimal("500000.00")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-SUPPAY-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=quantity_litres,
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    quantity_to_load = quantity_litres if loaded_quantity is None else loaded_quantity
    _load_trip_for_supplier_order(
        supplier=supplier,
        supplier_order=supplier_order,
        quantity=quantity_to_load,
        suffix=f"SUPPAY-{suffix}",
        admin_user=admin_user,
    )
    return admin_user, supplier, supplier_order


@pytest.mark.django_db
def test_supplier_debt_is_priced_on_full_order_immediately_not_loaded_quantity():
    """Business rule reversal (client request, 2026-09-10): purchase
    200,000 L at 500 XOF/L -> supplier debt = 200,000 x 500 = 100,000,000
    XOF immediately on confirmation, before any truck has loaded anything.
    Loading fuel afterwards (partially or fully) does not change the debt -
    only a payment does."""
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+222DEBTCLIENTEX", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Supplier Debt Example", country="Senegal")
    order = SupplierOrder.objects.create(
        reference="SO-DEBT-CLIENT-EXAMPLE",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("200000.00"),
        unit_price=Decimal("500.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )

    # Nothing loaded yet: the debt is already the full order.
    debt = ControlledDebtPaymentService.describe_supplier_order(order)
    assert debt["total_amount"] == Decimal("100000000.00")
    assert debt["remaining_amount"] == Decimal("100000000.00")

    _load_trip_for_supplier_order(
        supplier=supplier, supplier_order=order, quantity=Decimal("100000.00"),
        suffix="DEBT-CLIENT-EX-1", admin_user=admin_user,
    )

    # Partial loading does not move the debt - it was already booked in full.
    debt = ControlledDebtPaymentService.describe_supplier_order(order)
    assert debt["total_amount"] == Decimal("100000000.00")
    assert debt["remaining_amount"] == Decimal("100000000.00")

    # The unloaded half now shows up as the reliquat's monetary value.
    reliquat_amount = SupplierStockService.get_purchase_reliquat_amount(order)
    assert reliquat_amount == Decimal("50000000.00")

    # Loading the rest still doesn't move the debt, only the reliquat.
    _load_trip_for_supplier_order(
        supplier=supplier, supplier_order=order, quantity=Decimal("100000.00"),
        suffix="DEBT-CLIENT-EX-2", admin_user=admin_user,
    )

    debt = ControlledDebtPaymentService.describe_supplier_order(order)
    assert debt["total_amount"] == Decimal("100000000.00")
    assert debt["remaining_amount"] == Decimal("100000000.00")
    assert debt["total_amount"] == order.total_amount
    assert SupplierStockService.get_purchase_reliquat_amount(order) == Decimal("0.00")


@pytest.mark.django_db
def test_supplier_payment_requires_positive_amount():
    admin_user, supplier, _order = _make_supplier_order("AMT")
    cash_account = CashAccount.objects.create(name="Main Cash")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SupplierPayment.objects.create(
                supplier=supplier,
                amount=Decimal("0.00"),
                payment_date="2026-08-18",
                method=SupplierPayment.Method.CASH,
                cash_account=cash_account,
                recorded_by=admin_user,
            )


@pytest.mark.django_db
def test_supplier_payment_cannot_set_both_accounts():
    admin_user, supplier, _order = _make_supplier_order("BOTH")
    bank_account = BankAccount.objects.create(name="Main BOA Account")
    cash_account = CashAccount.objects.create(name="Main Cash")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SupplierPayment.objects.create(
                supplier=supplier,
                amount=Decimal("1000000.00"),
                payment_date="2026-08-18",
                method=SupplierPayment.Method.BANK_TRANSFER,
                bank_account=bank_account,
                cash_account=cash_account,
                recorded_by=admin_user,
            )


@pytest.mark.django_db
def test_supplier_payment_requires_one_account():
    admin_user, supplier, _order = _make_supplier_order("NOACC")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SupplierPayment.objects.create(
                supplier=supplier,
                amount=Decimal("1000000.00"),
                payment_date="2026-08-18",
                method=SupplierPayment.Method.CASH,
                recorded_by=admin_user,
            )


@pytest.mark.django_db
def test_supplier_payment_as_general_advance_without_order():
    admin_user, supplier, _order = _make_supplier_order("ADV")
    cash_account = CashAccount.objects.create(name="Main Cash")

    payment = SupplierPayment.objects.create(
        supplier=supplier,
        amount=Decimal("2000000.00"),
        payment_date="2026-08-18",
        method=SupplierPayment.Method.CASH,
        cash_account=cash_account,
        is_advance=True,
        recorded_by=admin_user,
    )

    assert payment.supplier_order is None
    assert payment.is_advance is True


# ---------------------------------------------------------------------------
# Task 5 (client modifications plan): supplier debt repayment must use
# BANK_TRANSFER + a BankAccount and post one TreasuryTransaction(MONEY_OUT);
# advances are exempt from the bank-only restriction but still post treasury
# (ruling 2); SupplierPayment becomes create-only via the API (ruling 3).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_supplier_debt_payment_rejects_cash_method_via_api(finance_client):
    _admin_user, supplier, _order = _make_supplier_order("DEBT-CASH")
    cash_account = CashAccount.objects.create(name="Main Cash")

    response = finance_client.post(
        "/api/supplier-payments/",
        {
            "supplier": supplier.id,
            "amount": "1000000.00",
            "payment_date": "2026-08-18",
            "method": SupplierPayment.Method.CASH,
            "cash_account": cash_account.id,
            "is_advance": False,
        },
        format="json",
    )

    assert response.status_code == 400
    assert TreasuryTransaction.objects.count() == 0


@pytest.mark.django_db
def test_supplier_debt_payment_rejects_missing_bank_account_via_api(finance_client):
    _admin_user, supplier, _order = _make_supplier_order("DEBT-NOACC")
    cash_account = CashAccount.objects.create(name="Main Cash")

    response = finance_client.post(
        "/api/supplier-payments/",
        {
            "supplier": supplier.id,
            "amount": "1000000.00",
            "payment_date": "2026-08-18",
            "method": SupplierPayment.Method.BANK_TRANSFER,
            # Deliberately sending a cash_account and no bank_account: the
            # base "exactly one account" rule alone would accept this, only
            # the new debt-repayment rule rejects it (ruling 1).
            "cash_account": cash_account.id,
            "is_advance": False,
        },
        format="json",
    )

    assert response.status_code == 400
    assert TreasuryTransaction.objects.count() == 0


@pytest.mark.django_db
def test_supplier_debt_payment_bank_transfer_creates_linked_treasury_transaction(finance_client):
    _admin_user, supplier, _order = _make_supplier_order("DEBT-BANK")
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance="5000000.00")
    treasury_count_before = TreasuryTransaction.objects.count()

    response = finance_client.post(
        "/api/supplier-payments/",
        {
            "supplier": supplier.id,
            "amount": "1000000.00",
            "payment_date": "2026-08-18",
            "method": SupplierPayment.Method.BANK_TRANSFER,
            "bank_account": bank_account.id,
            "is_advance": False,
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert TreasuryTransaction.objects.count() == treasury_count_before + 1

    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(SupplierPayment),
        source_object_id=response.data["id"],
    )
    assert txn.type == TreasuryTransaction.Type.MONEY_OUT
    assert txn.bank_account_id == bank_account.id
    assert txn.amount == Decimal("1000000.00")

    bank_account.refresh_from_db()
    assert bank_account.current_balance == Decimal("4000000.00")


@pytest.mark.django_db
def test_supplier_payment_update_via_api_is_rejected(finance_client):
    """Ruling 3: every SupplierPayment is already posted to treasury inside
    create()'s atomic block, so there's no meaningful unposted state to
    allow editing - SupplierPayment is create-only via the API."""
    _admin_user, supplier, _order = _make_supplier_order("NOEDIT")
    bank_account = BankAccount.objects.create(name="Main BOA Account")
    created = finance_client.post(
        "/api/supplier-payments/",
        {
            "supplier": supplier.id,
            "amount": "1000000.00",
            "payment_date": "2026-08-18",
            "method": SupplierPayment.Method.BANK_TRANSFER,
            "bank_account": bank_account.id,
            "is_advance": False,
        },
        format="json",
    )
    assert created.status_code == 201, created.data

    response = finance_client.patch(
        f"/api/supplier-payments/{created.data['id']}/",
        {"amount": "2000000.00"},
        format="json",
    )

    assert response.status_code == 400
    payment = SupplierPayment.objects.get(pk=created.data["id"])
    assert payment.amount == Decimal("1000000.00")


@pytest.mark.django_db
def test_supplier_outstanding_and_bank_balance_decrease_after_debt_payment(finance_client):
    """Brief verification: supplier outstanding decreases by the payment
    amount and the bank account's current balance decreases by the payment
    amount, using the same GET /api/suppliers/{id}/ledger/ endpoint the new
    SupplierPaymentForm.vue reuses for its "outstanding before submit" display."""
    _admin_user, supplier, order = _make_supplier_order("OUTSTANDING")
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance="10000000.00")

    before = finance_client.get(f"/api/suppliers/{supplier.id}/ledger/")
    assert before.status_code == 200
    outstanding_before = Decimal(before.data["outstanding_balance"])
    assert outstanding_before == order.total_amount

    response = finance_client.post(
        "/api/supplier-payments/",
        {
            "supplier": supplier.id,
            "amount": "1500000.00",
            "payment_date": "2026-08-18",
            "method": SupplierPayment.Method.BANK_TRANSFER,
            "bank_account": bank_account.id,
            "is_advance": False,
        },
        format="json",
    )
    assert response.status_code == 201, response.data

    after = finance_client.get(f"/api/suppliers/{supplier.id}/ledger/")
    assert after.status_code == 200
    outstanding_after = Decimal(after.data["outstanding_balance"])
    assert outstanding_after == outstanding_before - Decimal("1500000.00")

    bank_account.refresh_from_db()
    assert bank_account.current_balance == Decimal("8500000.00")


# ---------------------------------------------------------------------------
# Phase 5 Etape 3: TransporterAdvance / TransportPayment
# (docs/PHASE_5_PLAN.md; guide Section 1.5/8.6)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_transporter_advance_requires_positive_amount():
    trip, transporter = _make_trip_for_deduction("ADV-NEG")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TransporterAdvance.objects.create(
                transporter=transporter, amount=Decimal("0.00"), date="2026-08-18"
            )


@pytest.mark.django_db
def test_transport_payment_net_amount_deducts_losses_and_advance():
    """Guide Section 1.5/§16/§31 worked example: 700 000 gross, 42 500
    deduction (50 L x 850), 100 000 advance applied -> net 557 500."""
    trip, transporter = _make_trip_for_deduction("NET")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-18"
    )

    payment = TransportPayment.objects.create(
        trip=trip,
        transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
        deduction_amount=Decimal("42500.00"),
        advance_applied=advance,
    )

    assert payment.net_amount == Decimal("557500.00")
    assert payment.status == TransportPayment.Status.PLANNED


@pytest.mark.django_db
def test_transport_payment_net_amount_without_advance():
    trip, transporter = _make_trip_for_deduction("NOADV")

    payment = TransportPayment.objects.create(
        trip=trip,
        transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.PER_LITRE,
        base_amount=Decimal("500000.00"),
    )

    assert payment.net_amount == Decimal("500000.00")


# ---------------------------------------------------------------------------
# Advance management (docs/superpowers/specs/2026-08-31-supplier-
# transporter-advances-design.md): SupplierAdvance, AdvanceConsumption,
# TransporterAdvance extended with treasury accounts + document.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_supplier_advance_requires_positive_amount():
    admin_user, supplier, _order = _make_supplier_order("SADV-NEG")
    cash_account = CashAccount.objects.create(name="Main Cash")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SupplierAdvance.objects.create(
                supplier=supplier, amount=Decimal("0.00"), date="2026-08-18",
                cash_account=cash_account, recorded_by=admin_user,
            )


@pytest.mark.django_db
def test_supplier_advance_requires_exactly_one_account():
    admin_user, supplier, _order = _make_supplier_order("SADV-ACC")
    bank_account = BankAccount.objects.create(name="Main BOA Account")
    cash_account = CashAccount.objects.create(name="Main Cash")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SupplierAdvance.objects.create(
                supplier=supplier, amount=Decimal("1000000.00"), date="2026-08-18",
                bank_account=bank_account, cash_account=cash_account, recorded_by=admin_user,
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SupplierAdvance.objects.create(
                supplier=supplier, amount=Decimal("1000000.00"), date="2026-08-18",
                recorded_by=admin_user,
            )


@pytest.mark.django_db
def test_supplier_advance_remaining_amount_defaults_to_full_amount():
    admin_user, supplier, _order = _make_supplier_order("SADV-REM")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("2000000.00"), date="2026-08-18",
        cash_account=cash_account, recorded_by=admin_user,
    )
    assert advance.remaining_amount == Decimal("2000000.00")


@pytest.mark.django_db
def test_advance_consumption_reduces_remaining_amount_but_reversed_rows_do_not():
    admin_user, supplier, order = _make_supplier_order("SADV-CONS")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("2000000.00"), date="2026-08-18",
        cash_account=cash_account, recorded_by=admin_user,
    )
    order_ct = ContentType.objects.get_for_model(SupplierOrder)
    AdvanceConsumption.objects.create(
        supplier_advance=advance, debt_content_type=order_ct, debt_object_id=order.id,
        amount=Decimal("500000.00"),
    )
    assert advance.remaining_amount == Decimal("1500000.00")

    reversed_consumption = AdvanceConsumption.objects.create(
        supplier_advance=advance, debt_content_type=order_ct, debt_object_id=order.id,
        amount=Decimal("300000.00"), reversed_at=timezone.now(),
    )
    assert advance.remaining_amount == Decimal("1500000.00")
    assert reversed_consumption.reversed_at is not None


@pytest.mark.django_db
def test_advance_consumption_requires_exactly_one_advance_type():
    admin_user, supplier, order = _make_supplier_order("CONS-BOTH")
    cash_account = CashAccount.objects.create(name="Main Cash")
    supplier_advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-18",
        cash_account=cash_account, recorded_by=admin_user,
    )
    trip, transporter = _make_trip_for_deduction("CONS-BOTH2")
    transporter_advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-18",
        cash_account=cash_account,
    )
    order_ct = ContentType.objects.get_for_model(SupplierOrder)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AdvanceConsumption.objects.create(
                supplier_advance=supplier_advance, transporter_advance=transporter_advance,
                debt_content_type=order_ct, debt_object_id=order.id, amount=Decimal("100.00"),
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AdvanceConsumption.objects.create(
                debt_content_type=order_ct, debt_object_id=order.id, amount=Decimal("100.00"),
            )


@pytest.mark.django_db
def test_transporter_advance_now_supports_treasury_account_and_document():
    trip, transporter = _make_trip_for_deduction("TADV-ACC")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-18",
        cash_account=cash_account,
    )
    assert advance.remaining_amount == Decimal("100000.00")
    assert advance.settled is False
    assert advance.document_id is None


@pytest.mark.django_db
def test_transporter_advance_settled_property_reflects_consumption():
    trip, transporter = _make_trip_for_deduction("TADV-SETTLE")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-18",
        cash_account=cash_account,
    )
    payment_ct = ContentType.objects.get_for_model(TransportPayment)
    dummy_payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    AdvanceConsumption.objects.create(
        transporter_advance=advance, debt_content_type=payment_ct,
        debt_object_id=dummy_payment.id, amount=Decimal("100000.00"),
    )
    assert advance.settled is True


# ---------------------------------------------------------------------------
# Task 2: AdvanceConsumptionService — pure FIFO engine
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_consume_for_supplier_order_is_fifo_across_two_advances():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+222-fifo-two", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Supplier FIFO-TWO", country="Senegal")
    order = SupplierOrder.objects.create(
        reference="SO-FIFO-TWO", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.DRAFT,
        created_by=admin_user,
    )  # total 600000, still DRAFT - not yet a debt
    cash_account = CashAccount.objects.create(name="Main Cash")
    older_advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("200000.00"), date="2026-08-10",
        cash_account=cash_account, recorded_by=admin_user,
    )
    newer_advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-15",
        cash_account=cash_account, recorded_by=admin_user,
    )

    AdvanceConsumptionService.consume_for_supplier_order(order)  # DRAFT: no-op
    older_advance.refresh_from_db()
    newer_advance.refresh_from_db()
    assert older_advance.remaining_amount == Decimal("200000.00")
    assert newer_advance.remaining_amount == Decimal("500000.00")

    order.status = SupplierOrder.Status.CONFIRMED
    order.save()
    AdvanceConsumptionService.consume_for_supplier_order(order)

    older_advance.refresh_from_db()
    newer_advance.refresh_from_db()
    assert older_advance.remaining_amount == Decimal("0.00")  # oldest consumed first, in full
    assert newer_advance.remaining_amount == Decimal("100000.00")  # 400000 consumed, 100000 left


@pytest.mark.django_db
def test_consume_for_supplier_order_is_idempotent_when_called_twice():
    admin_user, supplier, order = _make_supplier_order("FIFO-IDEMPOTENT")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("50000000.00"), date="2026-08-10",
        cash_account=cash_account, recorded_by=admin_user,
    )

    AdvanceConsumptionService.consume_for_supplier_order(order)
    AdvanceConsumptionService.consume_for_supplier_order(order)

    assert AdvanceConsumption.objects.filter(supplier_advance=advance).count() == 1


@pytest.mark.django_db
def test_consume_for_supplier_order_only_matches_advances_of_the_same_supplier():
    admin_user, supplier, order = _make_supplier_order("FIFO-SAMETENANT")
    other_supplier = Supplier.objects.create(name="Other Supplier FIFO", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash")
    SupplierAdvance.objects.create(
        supplier=other_supplier, amount=Decimal("50000000.00"), date="2026-08-10",
        cash_account=cash_account, recorded_by=admin_user,
    )

    AdvanceConsumptionService.consume_for_supplier_order(order)

    assert AdvanceConsumption.objects.count() == 0


@pytest.mark.django_db
def test_reverse_for_supplier_order_restores_the_advance():
    admin_user, supplier, order = _make_supplier_order("FIFO-REVERSE")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("50000000.00"), date="2026-08-10",
        cash_account=cash_account, recorded_by=admin_user,
    )
    AdvanceConsumptionService.consume_for_supplier_order(order)
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("0.00")

    AdvanceConsumptionService.reverse_for_supplier_order(order)
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("50000000.00")
    consumption = AdvanceConsumption.objects.get(supplier_advance=advance)
    assert consumption.reversed_at is not None


@pytest.mark.django_db
def test_consume_for_transport_payment_caps_at_the_payment_amount():
    trip, transporter = _make_trip_for_deduction("FIFO-TRANS-CAP")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("900000.00"), date="2026-08-10",
        cash_account=cash_account,
    )
    payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    payment.advance_applied = None  # this task's service isn't wired to save() yet

    consumed = AdvanceConsumptionService.consume_for_transport_payment(payment)

    assert consumed == Decimal("700000.00")
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("200000.00")


# ---------------------------------------------------------------------------
# Client modification Task 2: transporter fees per litre create payable
# debt - TransportPayment.unit_price_per_litre auto-computes base_amount
# for calculation_method=PER_LITRE, and a mismatched transporter is
# rejected (docs/notes-et-demandes-client-modifications-application.md).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_transport_payment_per_litre_computes_base_amount_via_api(finance_client):
    """calculation_method=PER_LITRE with unit_price_per_litre=60 on a trip
    carrying 45 000 L must auto-compute base_amount=2 700 000.00 - the
    client must never be able to submit base_amount directly."""
    trip, transporter = _make_trip_for_deduction("PERLITRE")

    response = finance_client.post(
        "/api/transport-payments/",
        {
            "trip": trip.id,
            "transporter": transporter.id,
            "calculation_method": TransportPayment.CalculationMethod.PER_LITRE,
            "unit_price_per_litre": "60.0000",
            "base_amount": "1.00",  # must be ignored/overridden by the server
        },
    )

    assert response.status_code == 201
    assert response.data["base_amount"] == "2700000.00"
    assert response.data["net_amount"] == "2700000.00"

    payment = TransportPayment.objects.get(pk=response.data["id"])
    assert payment.unit_price_per_litre == Decimal("60.0000")
    assert payment.base_amount == Decimal("2700000.00")


@pytest.mark.django_db
def test_transport_payment_per_litre_requires_unit_price(finance_client):
    trip, transporter = _make_trip_for_deduction("PERLITRE-NOPRICE")

    response = finance_client.post(
        "/api/transport-payments/",
        {
            "trip": trip.id,
            "transporter": transporter.id,
            "calculation_method": TransportPayment.CalculationMethod.PER_LITRE,
        },
    )

    assert response.status_code == 400
    assert "unit_price_per_litre" in response.data


@pytest.mark.django_db
def test_transport_payment_per_litre_appears_in_transporter_outstanding_when_not_paid(
    finance_client,
):
    trip, transporter = _make_trip_for_deduction("PERLITRE-OUTSTANDING")

    created = finance_client.post(
        "/api/transport-payments/",
        {
            "trip": trip.id,
            "transporter": transporter.id,
            "calculation_method": TransportPayment.CalculationMethod.PER_LITRE,
            "unit_price_per_litre": "60.0000",
        },
    )
    assert created.status_code == 201
    assert created.data["status"] == TransportPayment.Status.PLANNED

    ledger = finance_client.get(f"/api/transporters/{transporter.id}/ledger/")

    assert ledger.status_code == 200
    assert ledger.data["net_outstanding"] == "2700000.00"


@pytest.mark.django_db
def test_transport_payment_rejects_transporter_not_matching_trip(finance_client):
    trip, _transporter = _make_trip_for_deduction("PERLITRE-MISMATCH")
    other_transporter = Transporter.objects.create(name="Autre Transporteur")

    response = finance_client.post(
        "/api/transport-payments/",
        {
            "trip": trip.id,
            "transporter": other_transporter.id,
            "calculation_method": TransportPayment.CalculationMethod.PER_LITRE,
            "unit_price_per_litre": "60.0000",
        },
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Phase 5 Etape 4: Expense / ExpenseAllocation (docs/PHASE_5_PLAN.md;
# guide Section 8.7/8.8)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_expense_requires_positive_amount():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Expense.objects.create(
                category=Expense.Category.CUSTOMS,
                amount=Decimal("0.00"),
                calculation_method=Expense.CalculationMethod.FIXED,
                date="2026-08-18",
            )


@pytest.mark.django_db
def test_expense_defaults_to_unpaid_status():
    expense = Expense.objects.create(
        category=Expense.Category.ADMINISTRATION,
        amount=Decimal("500000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )

    assert expense.status == Expense.Status.UNPAID
    assert expense.paid_by_customer_directly is False


@pytest.mark.django_db
def test_expense_allocation_splits_across_multiple_trips():
    """Guide Section 8.7: "a customs payment may affect several trips"."""
    trip_a, _t1 = _make_trip_for_deduction("EXP-A")
    trip_b, _t2 = _make_trip_for_deduction("EXP-B")
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("1000000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-08-18",
    )
    trip_content_type = ContentType.objects.get_for_model(Trip)

    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=trip_content_type,
        object_id=trip_a.id,
        allocated_amount=Decimal("600000.00"),
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=trip_content_type,
        object_id=trip_b.id,
        allocated_amount=Decimal("400000.00"),
    )

    allocations = expense.allocations.all()
    assert allocations.count() == 2
    assert {a.content_object for a in allocations} == {trip_a, trip_b}


@pytest.mark.django_db
def test_expense_allocation_requires_positive_amount():
    expense = Expense.objects.create(
        category=Expense.Category.OTHER,
        amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ExpenseAllocation.objects.create(
                expense=expense, allocated_amount=Decimal("0.00")
            )


@pytest.mark.django_db
def test_allocatable_types_returns_content_type_id_per_kind(finance_client):
    """The frontend allocation picker has no other way to resolve a human
    choice ("Trip") to the ContentType PK ExpenseAllocationInputSerializer
    expects - this is that lookup."""
    response = finance_client.get("/api/allocatable-types/")

    assert response.status_code == 200
    kinds = {row["kind"]: row["content_type"] for row in response.data}
    assert set(kinds) == {"trip", "truck", "customer", "supplier", "transporter"}
    assert kinds["trip"] == ContentType.objects.get_for_model(Trip).id
    assert kinds["truck"] == ContentType.objects.get_for_model(Truck).id


@pytest.mark.django_db
def test_expense_list_filters_by_trip(finance_client):
    trip_a, _ = _make_trip_for_deduction("FLT-A")
    trip_b, _ = _make_trip_for_deduction("FLT-B")
    trip_content_type = ContentType.objects.get_for_model(Trip)

    expense_a = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=expense_a,
        content_type=trip_content_type,
        object_id=trip_a.id,
        allocated_amount=Decimal("100000.00"),
    )
    expense_b = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=expense_b,
        content_type=trip_content_type,
        object_id=trip_b.id,
        allocated_amount=Decimal("50000.00"),
    )

    response = finance_client.get(f"/api/expenses/?trip={trip_a.id}")

    assert response.status_code == 200
    returned_ids = {row["id"] for row in response.data["results"]}
    assert returned_ids == {expense_a.id}


# ---------------------------------------------------------------------------
# Phase 5 Etape 5: TreasuryTransaction (docs/PHASE_5_PLAN.md;
# guide Section 8.10/D)
# ---------------------------------------------------------------------------


@pytest.fixture
def treasury_user():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        phone="+2220000012", pin="1234", role=admin_role
    )


@pytest.mark.django_db
def test_treasury_transaction_requires_positive_amount(treasury_user):
    cash_account = CashAccount.objects.create(name="Main Cash")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TreasuryTransaction.objects.create(
                cash_account=cash_account,
                type=TreasuryTransaction.Type.MONEY_IN,
                amount=Decimal("0.00"),
                date="2026-08-18",
                recorded_by=treasury_user,
            )


@pytest.mark.django_db
def test_treasury_transaction_cannot_set_both_accounts(treasury_user):
    bank_account = BankAccount.objects.create(name="Main BOA Account")
    cash_account = CashAccount.objects.create(name="Main Cash")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TreasuryTransaction.objects.create(
                bank_account=bank_account,
                cash_account=cash_account,
                type=TreasuryTransaction.Type.MONEY_OUT,
                amount=Decimal("10000000.00"),
                date="2026-08-18",
                recorded_by=treasury_user,
            )


@pytest.mark.django_db
def test_treasury_transaction_requires_one_account(treasury_user):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TreasuryTransaction.objects.create(
                type=TreasuryTransaction.Type.MONEY_OUT,
                amount=Decimal("10000000.00"),
                date="2026-08-18",
                recorded_by=treasury_user,
            )


@pytest.mark.django_db
def test_treasury_transaction_source_object_traces_origin(treasury_user):
    admin_user, supplier, _order = _make_supplier_order("TRACE")
    cash_account = CashAccount.objects.create(name="Main Cash")
    payment = SupplierPayment.objects.create(
        supplier=supplier,
        amount=Decimal("2000000.00"),
        payment_date="2026-08-18",
        method=SupplierPayment.Method.CASH,
        cash_account=cash_account,
        recorded_by=admin_user,
    )

    txn = TreasuryTransaction.objects.create(
        cash_account=cash_account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=payment.amount,
        date="2026-08-18",
        source_content_type=ContentType.objects.get_for_model(SupplierPayment),
        source_object_id=payment.id,
        recorded_by=treasury_user,
    )

    assert txn.source_object == payment


# ---------------------------------------------------------------------------
# Controlled debt payment from Treasury ledger
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_controlled_supplier_payment_rejects_amount_above_remaining(treasury_user):
    _admin_user, supplier, order = _make_supplier_order("CTRL-SUP-OVER")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account", opening_balance=Decimal("999999999.00")
    )

    with pytest.raises(ControlledDebtPaymentError):
        ControlledDebtPaymentService.record_payment(
            debt_type="supplier",
            debt_id=supplier.id,
            bank_account_id=bank_account.id,
            amount=order.total_amount + Decimal("0.01"),
            date="2026-08-18",
            reference="PAY-OVER",
            actor=treasury_user,
        )

    assert SupplierPayment.objects.count() == 0
    assert TreasuryTransaction.objects.count() == 0


@pytest.mark.django_db
def test_controlled_supplier_payment_rejects_insufficient_bank_balance(treasury_user):
    _admin_user, supplier, _order = _make_supplier_order("CTRL-SUP-BANK")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account", opening_balance=Decimal("1000.00")
    )

    with pytest.raises(ControlledDebtPaymentError) as exc_info:
        ControlledDebtPaymentService.record_payment(
            debt_type="supplier",
            debt_id=supplier.id,
            bank_account_id=bank_account.id,
            amount=Decimal("1001.00"),
            date="2026-08-18",
            reference="PAY-NOBAL",
            actor=treasury_user,
        )

    assert "Solde bancaire insuffisant" in str(exc_info.value)
    assert SupplierPayment.objects.count() == 0
    assert TreasuryTransaction.objects.count() == 0


@pytest.mark.django_db
def test_controlled_supplier_payment_creates_supplier_payment_and_money_out(treasury_user):
    _admin_user, supplier, order = _make_supplier_order("CTRL-SUP-OK")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account", opening_balance=Decimal("1000000.00")
    )

    result = ControlledDebtPaymentService.record_payment(
        debt_type="supplier",
        debt_id=supplier.id,
        bank_account_id=bank_account.id,
        amount=Decimal("250000.00"),
        date="2026-08-18",
        reference="PAY-SUP",
        actor=treasury_user,
    )

    payment = SupplierPayment.objects.get()
    assert payment.supplier == supplier
    assert payment.supplier_order == order
    assert payment.method == SupplierPayment.Method.BANK_TRANSFER
    assert payment.bank_account == bank_account
    assert payment.amount == Decimal("250000.00")
    assert result["transaction"].type == TreasuryTransaction.Type.MONEY_OUT
    assert result["transaction"].source_object == payment
    assert result["remaining_after"] == order.total_amount - Decimal("250000.00")


@pytest.mark.django_db
def test_payable_supplier_debts_are_grouped_by_supplier(treasury_user):
    admin_user, supplier, old_order = _make_supplier_order("CTRL-SUP-GROUP-A")
    product = Product.objects.get(code="gasoil")
    new_order = SupplierOrder.objects.create(
        reference="SO-SUPPAY-CTRL-SUP-GROUP-B",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-19",
        quantity_litres=Decimal("10.00"),
        unit_price=Decimal("100.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    # Fully load new_order too, so its debt equals its total_amount (bug
    # fix, client business rule confirmed 2026-09-06: debt now tracks
    # quantity loaded, not the full confirmed order).
    _load_trip_for_supplier_order(
        supplier=supplier, supplier_order=new_order, quantity=new_order.quantity_litres,
        suffix="CTRL-SUP-GROUP-B", admin_user=admin_user,
    )
    other_supplier = Supplier.objects.create(name="Other Supplier", country="Senegal")
    SupplierOrder.objects.create(
        reference="SO-SUPPAY-CTRL-SUP-GROUP-C",
        supplier=other_supplier,
        product=product,
        purchase_date="2026-08-20",
        quantity_litres=Decimal("5.00"),
        unit_price=Decimal("100.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )

    rows = ControlledDebtPaymentService.get_payable_debts("supplier")
    supplier_row = next(row for row in rows if row["id"] == supplier.id)

    assert supplier_row["label"] == supplier.name
    assert supplier_row["total_amount"] == old_order.total_amount + new_order.total_amount
    assert supplier_row["paid_amount"] == Decimal("0.00")
    assert supplier_row["remaining_amount"] == old_order.total_amount + new_order.total_amount
    assert [line["id"] for line in supplier_row["lines"]] == [old_order.id, new_order.id]


@pytest.mark.django_db
def test_payable_supplier_debts_only_count_confirmed_orders(treasury_user):
    admin_user, supplier, confirmed_order = _make_supplier_order("CTRL-SUP-CONF-ONLY")
    product = Product.objects.get(code="gasoil")
    SupplierOrder.objects.create(
        reference="SO-SUPPAY-CTRL-SUP-CANCELLED",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-19",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("500.0000"),
        status=SupplierOrder.Status.CANCELLED,
        created_by=admin_user,
    )
    SupplierOrder.objects.create(
        reference="SO-SUPPAY-CTRL-SUP-DRAFT",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-20",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("500.0000"),
        status=SupplierOrder.Status.DRAFT,
        created_by=admin_user,
    )

    supplier_row = ControlledDebtPaymentService.describe_supplier(supplier)

    assert supplier_row["total_amount"] == confirmed_order.total_amount
    assert supplier_row["paid_amount"] == Decimal("0.00")
    assert supplier_row["remaining_amount"] == confirmed_order.total_amount
    assert [line["id"] for line in supplier_row["lines"]] == [confirmed_order.id]


@pytest.mark.django_db
def test_controlled_supplier_payment_allocates_to_oldest_orders_first(treasury_user):
    admin_user, supplier, old_order = _make_supplier_order("CTRL-SUP-FIFO-A")
    product = Product.objects.get(code="gasoil")
    new_order = SupplierOrder.objects.create(
        reference="SO-SUPPAY-CTRL-SUP-FIFO-B",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-19",
        quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    # Fully load new_order too, so its debt equals its total_amount (bug
    # fix, client business rule confirmed 2026-09-06).
    _load_trip_for_supplier_order(
        supplier=supplier, supplier_order=new_order, quantity=new_order.quantity_litres,
        suffix="CTRL-SUP-FIFO-B", admin_user=admin_user,
    )
    bank_account = BankAccount.objects.create(
        name="Main BOA Account", opening_balance=Decimal("999999999.00")
    )

    ControlledDebtPaymentService.record_payment(
        debt_type="supplier",
        debt_id=supplier.id,
        bank_account_id=bank_account.id,
        amount=old_order.total_amount + Decimal("100000.00"),
        date="2026-08-18",
        reference="PAY-SUP-FIFO",
        actor=treasury_user,
    )

    old_payment = SupplierPayment.objects.get(supplier_order=old_order)
    new_payment = SupplierPayment.objects.get(supplier_order=new_order)
    assert old_payment.amount == old_order.total_amount
    assert new_payment.amount == Decimal("100000.00")
    assert TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(SupplierPayment),
        type=TreasuryTransaction.Type.MONEY_OUT,
    ).count() == 2


@pytest.mark.django_db
def test_controlled_transport_payment_updates_remaining_and_paid_status(treasury_user):
    trip, transporter = _make_trip_for_deduction("CTRL-TRP")
    debt = TransportPayment.objects.create(
        trip=trip,
        transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
        status=TransportPayment.Status.PAYABLE,
    )
    bank_account = BankAccount.objects.create(
        name="Main BOA Account", opening_balance=Decimal("1000000.00")
    )

    first = ControlledDebtPaymentService.record_payment(
        debt_type="transporter",
        debt_id=transporter.id,
        bank_account_id=bank_account.id,
        amount=Decimal("300000.00"),
        date="2026-08-18",
        reference="PAY-TRP-1",
        actor=treasury_user,
    )
    debt.refresh_from_db()

    assert first["remaining_after"] == Decimal("400000.00")
    assert debt.status == TransportPayment.Status.PARTIALLY_PAID

    second = ControlledDebtPaymentService.record_payment(
        debt_type="transporter",
        debt_id=transporter.id,
        bank_account_id=bank_account.id,
        amount=Decimal("400000.00"),
        date="2026-08-19",
        reference="PAY-TRP-2",
        actor=treasury_user,
    )
    debt.refresh_from_db()

    assert second["remaining_after"] == Decimal("0.00")
    assert debt.status == TransportPayment.Status.PAID
    assert TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(TransportPayment),
        source_object_id=debt.id,
        type=TreasuryTransaction.Type.MONEY_OUT,
    ).count() == 2


@pytest.mark.django_db
def test_controlled_transport_payment_allocates_by_transporter_fifo(treasury_user):
    trip_a, transporter = _make_trip_for_deduction("CTRL-TRP-FIFO-A")
    trip_b, _same = _make_trip_for_deduction("CTRL-TRP-FIFO-B")
    trip_b.transporter = transporter
    trip_b.save(update_fields=["transporter", "updated_at"])
    first_debt = TransportPayment.objects.create(
        trip=trip_a,
        transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
        status=TransportPayment.Status.PAYABLE,
    )
    second_debt = TransportPayment.objects.create(
        trip=trip_b,
        transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("500000.00"),
        status=TransportPayment.Status.PAYABLE,
    )
    bank_account = BankAccount.objects.create(
        name="Main BOA Account", opening_balance=Decimal("2000000.00")
    )

    result = ControlledDebtPaymentService.record_payment(
        debt_type="transporter",
        debt_id=transporter.id,
        bank_account_id=bank_account.id,
        amount=Decimal("900000.00"),
        date="2026-08-18",
        reference="PAY-TRP-FIFO",
        actor=treasury_user,
    )
    first_debt.refresh_from_db()
    second_debt.refresh_from_db()

    assert first_debt.status == TransportPayment.Status.PAID
    assert second_debt.status == TransportPayment.Status.PARTIALLY_PAID
    assert result["remaining_after"] == Decimal("300000.00")
    assert [txn.amount for txn in result["transactions"]] == [
        Decimal("700000.00"),
        Decimal("200000.00"),
    ]


@pytest.mark.django_db
def test_controlled_expense_payment_creates_bank_out_and_keeps_cost_basis(treasury_user):
    trip, _transporter = _make_trip_for_deduction("CTRL-EXP")
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("100000.00"),
    )
    bank_account = BankAccount.objects.create(
        name="Main BOA Account", opening_balance=Decimal("1000000.00")
    )

    result = ControlledDebtPaymentService.record_payment(
        debt_type="customs",
        debt_id=0,
        bank_account_id=bank_account.id,
        amount=Decimal("100000.00"),
        date="2026-08-18",
        reference="PAY-CUSTOMS",
        actor=treasury_user,
    )
    expense.refresh_from_db()

    assert expense.status == Expense.Status.PAID
    assert result["transaction"].type == TreasuryTransaction.Type.MONEY_OUT
    assert result["transaction"].source_object == expense
    from apps.trips.services import TripCostService

    cost_basis = TripCostService.calculate_trip_cost_basis(trip)
    assert cost_basis["expenses_by_category"][Expense.Category.CUSTOMS] == Decimal("100000.00")


@pytest.mark.django_db
def test_road_transit_expense_has_its_own_payable_debt_and_cost_basis(treasury_user):
    trip, _transporter = _make_trip_for_deduction("CTRL-ROAD-TRANSIT")
    road_transit = Expense.objects.create(
        category=Expense.Category.ROAD_TRANSIT,
        amount=Decimal("450000.00"),
        calculation_method=Expense.CalculationMethod.PER_LITRE,
        date="2026-08-18",
    )
    classic_transit = Expense.objects.create(
        category=Expense.Category.TRANSIT,
        amount=Decimal("90000.00"),
        calculation_method=Expense.CalculationMethod.PER_LITRE,
        date="2026-08-18",
    )
    trip_content_type = ContentType.objects.get_for_model(Trip)
    ExpenseAllocation.objects.create(
        expense=road_transit,
        content_type=trip_content_type,
        object_id=trip.id,
        allocated_amount=Decimal("450000.00"),
    )
    ExpenseAllocation.objects.create(
        expense=classic_transit,
        content_type=trip_content_type,
        object_id=trip.id,
        allocated_amount=Decimal("90000.00"),
    )
    bank_account = BankAccount.objects.create(
        name="Main BOA Account ROAD-TRANSIT", opening_balance=Decimal("1000000.00")
    )

    road_rows = ControlledDebtPaymentService.get_payable_debts("road_transit")
    transit_rows = ControlledDebtPaymentService.get_payable_debts("transit")

    assert road_rows[0]["remaining_amount"] == Decimal("450000.00")
    assert road_rows[0]["lines"][0]["debt_type"] == "road_transit"
    assert transit_rows[0]["remaining_amount"] == Decimal("90000.00")

    result = ControlledDebtPaymentService.record_payment(
        debt_type="road_transit",
        debt_id=0,
        bank_account_id=bank_account.id,
        amount=Decimal("450000.00"),
        date="2026-08-18",
        reference="PAY-ROAD-TRANSIT",
        actor=treasury_user,
        attachment=SimpleUploadedFile(
            "road-transit.webp", b"fake webp receipt", content_type="image/webp"
        ),
    )
    road_transit.refresh_from_db()
    classic_transit.refresh_from_db()

    assert road_transit.status == Expense.Status.PAID
    assert classic_transit.status == Expense.Status.UNPAID
    assert result["transaction"].source_object == road_transit
    from apps.trips.services import TripCostService

    cost_basis = TripCostService.calculate_trip_cost_basis(trip)
    assert cost_basis["expenses_by_category"][Expense.Category.ROAD_TRANSIT] == Decimal("450000.00")
    assert cost_basis["unit_components_per_litre"]["road_transit"] == Decimal("10.0000")


@pytest.mark.django_db
def test_transit_expense_has_its_own_payable_debt_and_is_settled_without_transport(
    treasury_user,
):
    trip, _transporter = _make_trip_for_deduction("CTRL-TRANSIT")
    transit = Expense.objects.create(
        category="transit",
        amount=Decimal("90000.00"),
        calculation_method=Expense.CalculationMethod.PER_LITRE,
        date="2026-08-18",
    )
    transport = Expense.objects.create(
        category=Expense.Category.TRANSPORT,
        amount=Decimal("125000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-08-18",
    )
    trip_content_type = ContentType.objects.get_for_model(Trip)
    ExpenseAllocation.objects.create(
        expense=transit,
        content_type=trip_content_type,
        object_id=trip.id,
        allocated_amount=Decimal("90000.00"),
    )
    ExpenseAllocation.objects.create(
        expense=transport,
        content_type=trip_content_type,
        object_id=trip.id,
        allocated_amount=Decimal("125000.00"),
    )
    bank_account = BankAccount.objects.create(
        name="Main BOA Account TRANSIT", opening_balance=Decimal("1000000.00")
    )

    transit_rows = ControlledDebtPaymentService.get_payable_debts("transit")

    assert transit_rows[0]["remaining_amount"] == Decimal("90000.00")
    assert transit_rows[0]["lines"][0]["debt_type"] == "transit"

    result = ControlledDebtPaymentService.record_payment(
        debt_type="transit",
        debt_id=0,
        bank_account_id=bank_account.id,
        amount=Decimal("90000.00"),
        date="2026-08-18",
        reference="PAY-TRANSIT",
        actor=treasury_user,
        attachment=SimpleUploadedFile(
            "transit.jpg", b"fake jpg receipt", content_type="image/jpeg"
        ),
    )
    transit.refresh_from_db()
    transport.refresh_from_db()

    assert transit.status == Expense.Status.PAID
    assert transport.status == Expense.Status.UNPAID
    assert result["transaction"].source_object == transit
    assert ControlledDebtPaymentService.get_payable_debts("transit") == []

    from apps.trips.services import TripCostService

    cost_basis = TripCostService.calculate_trip_cost_basis(trip)
    assert cost_basis["expenses_by_category"]["transit"] == Decimal("90000.00")
    assert cost_basis["unit_components_per_litre"]["transit"] == Decimal("2.0000")


@pytest.mark.django_db
def test_controlled_expense_payment_allocates_category_fifo(treasury_user):
    old_expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-08-17",
    )
    new_expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("80000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-08-18",
    )
    bank_account = BankAccount.objects.create(
        name="Main BOA Account", opening_balance=Decimal("300000.00")
    )

    result = ControlledDebtPaymentService.record_payment(
        debt_type="customs",
        debt_id=0,
        bank_account_id=bank_account.id,
        amount=Decimal("120000.00"),
        date="2026-08-18",
        reference="PAY-CUSTOMS-FIFO",
        actor=treasury_user,
    )
    old_expense.refresh_from_db()
    new_expense.refresh_from_db()

    assert old_expense.status == Expense.Status.PAID
    assert new_expense.status == Expense.Status.PARTIALLY_PAID
    assert result["remaining_after"] == Decimal("60000.00")
    assert [txn.source_object for txn in result["transactions"]] == [old_expense, new_expense]


@pytest.mark.django_db
def test_controlled_debt_payment_api_returns_remaining_fields(finance_client):
    _admin_user, supplier, order = _make_supplier_order("CTRL-API")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account", opening_balance=Decimal("1000000.00")
    )

    response = finance_client.post(
        "/api/treasury-transactions/record-debt-payment/",
        {
            "debt_type": "supplier",
            "debt_id": supplier.id,
            "bank_account": bank_account.id,
            "amount": "100000.00",
            "date": "2026-08-18",
            "reference": "PAY-API",
            "attachment": SimpleUploadedFile(
                "pay-api.png", b"fake png receipt", content_type="image/png"
            ),
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert response.data["transaction"]["type"] == TreasuryTransaction.Type.MONEY_OUT
    assert response.data["debt"]["total_amount"] == str(order.total_amount)
    assert response.data["debt"]["paid_amount"] == "100000.00"
    assert response.data["debt"]["remaining_amount"] == str(order.total_amount - Decimal("100000.00"))


# ---------------------------------------------------------------------------
# docs/tresororie_edit.md "Nouveau paiement" - reference/note/attachment
# (docs/edit.md UI pass 2026-08-26): a controlled debt payment can carry a
# free-text note and a proof-of-payment file, both surfaced back on the
# created TreasuryTransaction(s) for the journal to display.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_controlled_debt_payment_persists_note_on_the_treasury_transaction(treasury_user):
    _admin_user, supplier, _order = _make_supplier_order("NOTE-SVC")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account NOTE-SVC", opening_balance=Decimal("1000000.00")
    )

    result = ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER,
        debt_id=supplier.id,
        bank_account_id=bank_account.id,
        amount=Decimal("100000.00"),
        date="2026-08-18",
        reference="PAY-NOTE",
        actor=treasury_user,
        note="Virement confirme par le fournisseur au telephone.",
    )

    assert len(result["transactions"]) == 1
    assert result["transactions"][0].note == "Virement confirme par le fournisseur au telephone."


@pytest.mark.django_db
def test_controlled_debt_payment_attaches_uploaded_proof_to_the_transaction(treasury_user):
    _admin_user, supplier, _order = _make_supplier_order("ATTACH-SVC")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account ATTACH-SVC", opening_balance=Decimal("1000000.00")
    )
    proof = SimpleUploadedFile("recu.jpg", b"fake jpeg receipt", content_type="image/jpeg")

    result = ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER,
        debt_id=supplier.id,
        bank_account_id=bank_account.id,
        amount=Decimal("100000.00"),
        date="2026-08-18",
        reference="PAY-ATTACH",
        actor=treasury_user,
        attachment=proof,
    )

    txn = result["transactions"][0]
    assert txn.document_id is not None
    assert txn.document.uploaded_by_id == treasury_user.id
    assert txn.document.content_type == ContentType.objects.get_for_model(TreasuryTransaction)
    assert txn.document.object_id == txn.id


@pytest.mark.django_db
def test_controlled_debt_payment_api_accepts_multipart_note_and_attachment(finance_client):
    _admin_user, supplier, _order = _make_supplier_order("NOTE-API")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account NOTE-API", opening_balance=Decimal("1000000.00")
    )
    proof = SimpleUploadedFile("recu.jpg", b"fake jpeg receipt", content_type="image/jpeg")

    response = finance_client.post(
        "/api/treasury-transactions/record-debt-payment/",
        {
            "debt_type": "supplier",
            "debt_id": supplier.id,
            "bank_account": bank_account.id,
            "amount": "100000.00",
            "date": "2026-08-18",
            "reference": "PAY-NOTE-API",
            "note": "Paiement confirme par SMS.",
            "attachment": proof,
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert response.data["transaction"]["note"] == "Paiement confirme par SMS."
    assert response.data["transaction"]["document"] is not None
    # Root-relative, never an absolute URL baking in the backend's internal
    # Host header (unreachable from the browser behind the dev proxy - see
    # docs/edit.md UI pass 2026-08-26, "Justificatif" fix).
    assert response.data["transaction"]["document_url"].startswith("/media/")


@pytest.mark.django_db
def test_controlled_debt_payment_api_rejects_non_image_attachment(finance_client):
    _admin_user, supplier, _order = _make_supplier_order("NOTE-API-PDF")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account NOTE-API-PDF", opening_balance=Decimal("1000000.00")
    )
    proof = SimpleUploadedFile("recu.pdf", b"%PDF-1.4 fake receipt", content_type="application/pdf")

    response = finance_client.post(
        "/api/treasury-transactions/record-debt-payment/",
        {
            "debt_type": "supplier",
            "debt_id": supplier.id,
            "bank_account": bank_account.id,
            "amount": "100000.00",
            "date": "2026-08-18",
            "reference": "PAY-NOTE-API-PDF",
            "note": "Paiement confirme par SMS.",
            "attachment": proof,
        },
        format="multipart",
    )

    assert response.status_code == 400, response.data
    assert response.data["attachment"][0] == "Seules les images JPG, JPEG, PNG ou WEBP sont autorisées."
    assert TreasuryTransaction.objects.count() == 0


@pytest.mark.django_db
def test_controlled_debt_payment_api_succeeds_without_attachment(finance_client):
    """Task 13 (2026-09-04 recette corrections): no justificatif is ever
    mandatory for a controlled debt payment."""
    _admin_user, supplier, _order = _make_supplier_order("NO-NOTE-API")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account NO-NOTE-API", opening_balance=Decimal("1000000.00")
    )

    response = finance_client.post(
        "/api/treasury-transactions/record-debt-payment/",
        {
            "debt_type": "supplier",
            "debt_id": supplier.id,
            "bank_account": bank_account.id,
            "amount": "100000.00",
            "date": "2026-08-18",
            "reference": "PAY-NO-NOTE",
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["transaction"]["document"] is None
    assert TreasuryTransaction.objects.count() == 1


# ---------------------------------------------------------------------------
# Phase 5 Etape 9: Acceptance scenarios (docs/PHASE_5_PLAN.md)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_acceptance_partial_invoice_payment_leaves_exact_outstanding():
    """40 000 000 XOF invoice, two payments of 10M and 15M -> outstanding
    exactly 15 000 000 XOF (guide Section 22)."""
    admin_user, customer, invoice = _make_invoice_for_payment(
        "ACC-PARTIAL", total_amount=Decimal("40000000.00")
    )
    cash_account = CashAccount.objects.create(name="Main Cash")

    payment_a = CustomerPayment.objects.create(
        customer=customer, amount=Decimal("10000000.00"), payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH, cash_account=cash_account, recorded_by=admin_user,
    )
    PaymentAllocationService.allocate_payment(
        payment_a.id, [{"invoice_id": invoice.id, "amount": Decimal("10000000.00")}]
    )

    payment_b = CustomerPayment.objects.create(
        customer=customer, amount=Decimal("15000000.00"), payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH, cash_account=cash_account, recorded_by=admin_user,
    )
    PaymentAllocationService.allocate_payment(
        payment_b.id, [{"invoice_id": invoice.id, "amount": Decimal("15000000.00")}]
    )

    invoice.refresh_from_db()
    assert PaymentAllocationService.get_invoice_outstanding(invoice) == Decimal("15000000.00")
    assert invoice.status == Invoice.Status.PARTIALLY_PAID


@pytest.mark.django_db
def test_acceptance_single_payment_split_across_two_invoices_pays_both():
    """A single 20M payment split 8M/12M across two invoices -> both PAID."""
    admin_user, customer, invoice_a = _make_invoice_for_payment(
        "ACC-SPLIT-A", total_amount=Decimal("8000000.00")
    )
    _admin_user_b, _customer_b, invoice_b = _make_invoice_for_payment(
        "ACC-SPLIT-B", total_amount=Decimal("12000000.00"), customer=customer
    )
    cash_account = CashAccount.objects.create(name="Main Cash")

    payment = CustomerPayment.objects.create(
        customer=customer, amount=Decimal("20000000.00"), payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH, cash_account=cash_account, recorded_by=admin_user,
    )
    PaymentAllocationService.allocate_payment(
        payment.id,
        [
            {"invoice_id": invoice_a.id, "amount": Decimal("8000000.00")},
            {"invoice_id": invoice_b.id, "amount": Decimal("12000000.00")},
        ],
    )

    invoice_a.refresh_from_db()
    invoice_b.refresh_from_db()
    assert invoice_a.status == Invoice.Status.PAID
    assert invoice_b.status == Invoice.Status.PAID


@pytest.mark.django_db
def test_allocate_payment_rejects_total_exceeding_payment_amount():
    admin_user, customer, invoice = _make_invoice_for_payment(
        "ACC-OVER", total_amount=Decimal("8000000.00")
    )
    cash_account = CashAccount.objects.create(name="Main Cash")
    payment = CustomerPayment.objects.create(
        customer=customer, amount=Decimal("5000000.00"), payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH, cash_account=cash_account, recorded_by=admin_user,
    )

    with pytest.raises(PaymentAllocationError):
        PaymentAllocationService.allocate_payment(
            payment.id, [{"invoice_id": invoice.id, "amount": Decimal("6000000.00")}]
        )


@pytest.mark.django_db
def test_acceptance_indirect_customer_payment_reduces_debt_without_treasury_row():
    """5M expense paid directly by a customer owing 50M -> debt reduced to
    45M and zero TreasuryTransaction rows created (guide Section 1.6/§25)."""
    admin_user, customer, invoice = _make_invoice_for_payment(
        "ACC-INDIRECT", total_amount=Decimal("50000000.00")
    )
    assert PaymentAllocationService.get_customer_outstanding(customer) == Decimal("50000000.00")
    treasury_count_before = TreasuryTransaction.objects.count()

    expense, payment, allocation = IndirectSettlementService.record_indirect_payment(
        customer_id=customer.id,
        expense_data={
            "category": Expense.Category.CUSTOMS,
            "amount": Decimal("5000000.00"),
            "date": "2026-08-18",
        },
        actor=admin_user,
        invoice_id=invoice.id,
    )

    assert expense.status == Expense.Status.PAID
    assert expense.paid_by_customer_directly is True
    assert payment.is_indirect is True
    assert payment.bank_account is None
    assert payment.cash_account is None
    assert allocation.amount == Decimal("5000000.00")
    assert PaymentAllocationService.get_customer_outstanding(customer) == Decimal("45000000.00")
    assert TreasuryTransaction.objects.count() == treasury_count_before


@pytest.mark.django_db
def test_acceptance_transporter_net_settlement_via_api(finance_client):
    """700 000 XOF gross transport fee, 50 L x 850 = 42 500 XOF deduction,
    100 000 XOF advance applied -> net payable 557 500 XOF (guide Section
    16/31), exercised through the transport-payments API."""
    trip, transporter = _make_trip_for_deduction("ACC-TRANSPORT")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-18"
    )

    response = finance_client.post(
        "/api/transport-payments/",
        {
            "trip": trip.id,
            "transporter": transporter.id,
            "calculation_method": TransportPayment.CalculationMethod.FIXED,
            "base_amount": "700000.00",
            "deduction_amount": "42500.00",
            "advance_applied": advance.id,
        },
    )

    assert response.status_code == 201
    assert response.data["net_amount"] == "557500.00"

    advance.refresh_from_db()
    assert advance.settled is True


@pytest.mark.django_db
def test_acceptance_treasury_transfer_creates_matched_transfer_pair(treasury_user):
    """10M transfer from Bank to Cash -> a MONEY_OUT/MONEY_IN pair, both
    is_transfer=True, and current_balance reflects the movement on both
    accounts (guide Section D)."""
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance="20000000.00")
    cash_account = CashAccount.objects.create(name="Main Cash")

    out_txn, in_txn = TreasuryService.record_transfer(
        source_account_type="bank",
        source_account_id=bank_account.id,
        dest_account_type="cash",
        dest_account_id=cash_account.id,
        amount=Decimal("10000000.00"),
        date="2026-08-18",
        reference="TRF-001",
        user=treasury_user,
    )

    assert out_txn.type == TreasuryTransaction.Type.MONEY_OUT
    assert in_txn.type == TreasuryTransaction.Type.MONEY_IN
    assert out_txn.is_transfer is True
    assert in_txn.is_transfer is True
    assert out_txn.bank_account == bank_account
    assert out_txn.cash_account is None
    assert in_txn.cash_account == cash_account
    assert in_txn.bank_account is None
    assert TreasuryTransaction.objects.filter(
        is_transfer=True, reference="TRF-001"
    ).count() == 2

    bank_account.refresh_from_db()
    cash_account.refresh_from_db()
    assert bank_account.current_balance == Decimal("10000000.00")
    assert cash_account.current_balance == Decimal("10000000.00")


@pytest.mark.django_db
def test_treasury_transfer_to_same_account_is_rejected(treasury_user):
    cash_account = CashAccount.objects.create(name="Main Cash")

    with pytest.raises(TreasuryTransferError):
        TreasuryService.record_transfer(
            source_account_type="cash",
            source_account_id=cash_account.id,
            dest_account_type="cash",
            dest_account_id=cash_account.id,
            amount=Decimal("1000000.00"),
            date="2026-08-18",
            reference="",
            user=treasury_user,
        )


@pytest.mark.django_db
def test_treasury_transfer_rejected_via_api_for_same_account(finance_client):
    cash_account = CashAccount.objects.create(name="Main Cash")

    response = finance_client.post(
        "/api/treasury-transactions/transfer/",
        {
            "source_account_type": "cash",
            "source_account_id": cash_account.id,
            "dest_account_type": "cash",
            "dest_account_id": cash_account.id,
            "amount": "1000000.00",
            "date": "2026-08-18",
        },
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_direct_is_transfer_flag_is_ignored_on_api_create(finance_client):
    """is_transfer is read-only - only TreasuryService.record_transfer()
    may set it, so posting it directly is silently ignored rather than
    honoured (docs/PHASE_5_PLAN.md Etape 7)."""
    cash_account = CashAccount.objects.create(name="Main Cash")

    response = finance_client.post(
        "/api/treasury-transactions/",
        {
            "cash_account": cash_account.id,
            "type": TreasuryTransaction.Type.MONEY_IN,
            "is_transfer": True,
            "amount": "1000000.00",
            "date": "2026-08-18",
        },
    )

    assert response.status_code == 201, response.data
    assert response.data["is_transfer"] is False


@pytest.mark.django_db
def test_invalid_transfer_type_value_rejected_via_api(finance_client):
    cash_account = CashAccount.objects.create(name="Main Cash")

    response = finance_client.post(
        "/api/treasury-transactions/",
        {
            "cash_account": cash_account.id,
            "type": "TRANSFER",
            "amount": "1000000.00",
            "date": "2026-08-18",
        },
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_customer_payment_with_nested_allocations_via_api(finance_client):
    admin_user, customer, invoice = _make_invoice_for_payment(
        "API-NESTED", total_amount=Decimal("8000000.00")
    )
    cash_account = CashAccount.objects.create(name="Main Cash")

    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "8000000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.CASH,
            "cash_account": cash_account.id,
            "allocations": json.dumps([{"invoice": invoice.id, "amount": "8000000.00"}]),
            "proof": _proof_file(),
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert len(response.data["allocations_detail"]) == 1
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID


@pytest.mark.django_db
def test_customer_payment_rejects_direct_payment_without_account(finance_client):
    _admin_user, customer, _invoice = _make_invoice_for_payment("API-NOACC")

    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "1000000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.CASH,
        },
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_indirect_settlement_via_api(finance_client):
    _admin_user, customer, invoice = _make_invoice_for_payment(
        "API-INDIRECT", total_amount=Decimal("50000000.00")
    )

    response = finance_client.post(
        "/api/expenses/record-indirect/",
        {
            "customer": customer.id,
            "invoice": invoice.id,
            "category": Expense.Category.CUSTOMS,
            "amount": "5000000.00",
            "date": "2026-08-18",
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["expense"]["paid_by_customer_directly"] is True
    assert response.data["payment"]["is_indirect"] is True
    # Ruling 1 invariant: destination=INDIRECT must always agree with
    # is_indirect=True, even for payments created directly by
    # IndirectSettlementService (bypassing CustomerPaymentSerializer.validate()).
    assert response.data["payment"]["destination"] == CustomerPayment.Destination.INDIRECT
    assert TreasuryTransaction.objects.count() == 0


@pytest.mark.django_db
def test_customer_ledger_endpoint_reports_outstanding_balance(finance_client):
    _admin_user, customer, invoice = _make_invoice_for_payment(
        "API-CUSTLEDGER", total_amount=Decimal("40000000.00")
    )
    cash_account = CashAccount.objects.create(name="Main Cash")
    payment = CustomerPayment.objects.create(
        customer=customer, amount=Decimal("10000000.00"), payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH, cash_account=cash_account, recorded_by=_admin_user,
    )
    PaymentAllocationService.allocate_payment(
        payment.id, [{"invoice_id": invoice.id, "amount": Decimal("10000000.00")}]
    )

    response = finance_client.get(f"/api/customers/{customer.id}/ledger/")

    assert response.status_code == 200
    assert response.data["outstanding_balance"] == "30000000.00"
    assert len(response.data["invoices"]) == 1
    assert len(response.data["payments"]) == 1


@pytest.mark.django_db
def test_transporter_ledger_endpoint_reports_net_outstanding(finance_client):
    trip, transporter = _make_trip_for_deduction("API-TRANSLEDGER")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-18"
    )
    TransportDeduction.objects.create(
        trip=trip,
        transporter=transporter,
        chargeable_quantity=Decimal("50.00"),
        unit_price=Decimal("850.0000"),
    )
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"), deduction_amount=Decimal("42500.00"),
        advance_applied=advance,
    )

    response = finance_client.get(f"/api/transporters/{transporter.id}/ledger/")

    assert response.status_code == 200
    assert response.data["net_outstanding"] == "557500.00"
    assert response.data["payments"][0]["deduction_label"] == (
        f"Manque quantite - {trip.reference} - 50.00 L x 850.0000 XOF/L"
    )


@pytest.mark.django_db
def test_transporter_ledger_endpoint_lists_only_external_trucks(finance_client):
    """Phase 6 (docs/superpowers/specs/2026-09-02-business-corrections-6-
    phases-design.md): the Grand livre transporteur lists the trucks
    rattaches to that transporter - only EXTERNAL ones, since a
    COMPANY_OWNED truck never has an owner_transporter."""
    trip, transporter = _make_trip_for_deduction("API-TRANSTRUCKS")
    external_truck = Truck.objects.create(
        internal_id="TRK-TRANSTRUCKS-EXT",
        tractor_registration="EXT-TRACTOR",
        tanker_registration="EXT-TANKER",
        capacity_litres=Decimal("45000.00"),
        ownership_type=Truck.OwnershipType.EXTERNAL,
        owner_transporter=transporter,
    )
    Truck.objects.create(
        internal_id="TRK-TRANSTRUCKS-CO",
        tractor_registration="CO-TRACTOR",
        tanker_registration="CO-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    other_transporter = Transporter.objects.create(name="Other Transport")
    Truck.objects.create(
        internal_id="TRK-TRANSTRUCKS-OTHER",
        tractor_registration="OTH-TRACTOR",
        tanker_registration="OTH-TANKER",
        capacity_litres=Decimal("45000.00"),
        ownership_type=Truck.OwnershipType.EXTERNAL,
        owner_transporter=other_transporter,
    )

    response = finance_client.get(f"/api/transporters/{transporter.id}/ledger/")

    assert response.status_code == 200
    truck_ids = {row["id"] for row in response.data["trucks"]}
    assert truck_ids == {external_truck.id}


@pytest.mark.django_db
def test_transporter_ledger_endpoint_counts_partial_treasury_settlements(
    finance_client, treasury_user
):
    trip, transporter = _make_trip_for_deduction("API-TRP-PART")
    payment = TransportPayment.objects.create(
        trip=trip,
        transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
        status=TransportPayment.Status.PAYABLE,
    )
    bank_account = BankAccount.objects.create(
        name="Main BOA Account", opening_balance=Decimal("1000000.00")
    )
    ControlledDebtPaymentService.record_payment(
        debt_type="transporter",
        debt_id=transporter.id,
        bank_account_id=bank_account.id,
        amount=Decimal("300000.00"),
        date="2026-08-18",
        reference="PAY-TRP-PART",
        actor=treasury_user,
    )

    response = finance_client.get(f"/api/transporters/{transporter.id}/ledger/")

    assert response.status_code == 200
    assert response.data["settled"] == "300000.00"
    assert response.data["net_outstanding"] == "400000.00"


# ---------------------------------------------------------------------------
# Task 4 (client modifications plan): destination/note over the API, treasury
# posting on direct customer payments, and the customerpayment proof upload.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_customer_payment_serializer_exposes_note_and_destination(finance_client):
    _admin_user, customer, _invoice = _make_invoice_for_payment("API-NOTE-DEST")
    cash_account = CashAccount.objects.create(name="Main Cash")

    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "150000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.CASH,
            "destination": CustomerPayment.Destination.CASH,
            "cash_account": cash_account.id,
            "note": "Paiement remis par le chauffeur",
            "proof": _proof_file(),
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert response.data["destination"] == CustomerPayment.Destination.CASH
    assert response.data["note"] == "Paiement remis par le chauffeur"
    assert response.data["is_indirect"] is False


@pytest.mark.django_db
def test_customer_payment_api_succeeds_without_payment_proof(finance_client):
    """Task 13 (2026-09-04 recette corrections): no justificatif is ever
    mandatory - a customer payment with no proof must still be accepted,
    and no Document row should be created for it."""
    _admin_user, customer, _invoice = _make_invoice_for_payment("API-PROOF-REQ")
    cash_account = CashAccount.objects.create(name="Main Cash")

    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "150000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.CASH,
            "destination": CustomerPayment.Destination.CASH,
            "cash_account": cash_account.id,
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["proof_url"] is None
    payment = CustomerPayment.objects.get(pk=response.data["id"])
    assert TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(CustomerPayment),
        source_object_id=payment.id,
    ).count() == 1
    assert not Document.objects.filter(
        content_type=ContentType.objects.get_for_model(CustomerPayment),
        object_id=payment.id,
    ).exists()


@pytest.mark.django_db
def test_customer_payment_api_rejects_non_image_proof(finance_client):
    _admin_user, customer, _invoice = _make_invoice_for_payment("API-PROOF-PDF")
    cash_account = CashAccount.objects.create(name="Main Cash PDF")
    proof = SimpleUploadedFile("recu.pdf", b"%PDF-1.4 fake receipt", content_type="application/pdf")

    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "150000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.CASH,
            "destination": CustomerPayment.Destination.CASH,
            "cash_account": cash_account.id,
            "proof": proof,
        },
        format="multipart",
    )

    assert response.status_code == 400, response.data
    assert response.data["proof"][0] == "Seules les images JPG, JPEG, PNG ou WEBP sont autorisées."
    assert CustomerPayment.objects.count() == 0
    assert TreasuryTransaction.objects.count() == 0


@pytest.mark.django_db
def test_customer_payment_api_creates_payment_proof_and_treasury_document(
    finance_client, settings, tmp_path
):
    settings.MEDIA_ROOT = str(tmp_path)
    _admin_user, customer, _invoice = _make_invoice_for_payment("API-PROOF-OK")
    cash_account = CashAccount.objects.create(name="Main Cash")
    proof = SimpleUploadedFile("recu.jpg", b"fake-image-bytes", content_type="image/jpeg")

    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "150000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.CASH,
            "destination": CustomerPayment.Destination.CASH,
            "cash_account": str(cash_account.id),
            "proof": proof,
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert response.data["proof_url"]

    payment = CustomerPayment.objects.get(pk=response.data["id"])
    document = Document.objects.get(
        content_type=ContentType.objects.get_for_model(CustomerPayment),
        object_id=payment.id,
        document_type="customer_payment_proof",
    )
    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(CustomerPayment),
        source_object_id=payment.id,
    )

    assert txn.document_id == document.id
    assert document.uploaded_by_id == payment.recorded_by_id


@pytest.mark.django_db
def test_customer_payment_destination_vers_moi_accepted_via_api(finance_client):
    _admin_user, customer, _invoice = _make_invoice_for_payment("API-VERSMOI")

    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "80000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.CASH,
            "destination": CustomerPayment.Destination.VERS_MOI,
            "proof": _proof_file(),
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert response.data["destination"] == CustomerPayment.Destination.VERS_MOI
    assert response.data["is_indirect"] is False
    assert response.data["cash_account"] is not None

    vers_moi = CashAccount.objects.get(name="Vers moi")
    assert response.data["cash_account"] == vers_moi.id
    # One dedicated account, no duplicate created on this call.
    assert CashAccount.objects.filter(name="Vers moi").count() == 1


@pytest.mark.django_db
def test_direct_bank_customer_payment_creates_linked_treasury_transaction(finance_client):
    _admin_user, customer, _invoice = _make_invoice_for_payment("API-TREAS-BANK")
    bank_account = BankAccount.objects.create(name="Main BOA Account")
    treasury_count_before = TreasuryTransaction.objects.count()

    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "2500000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.BANK_TRANSFER,
            "destination": CustomerPayment.Destination.BANK,
            "bank_account": bank_account.id,
            "proof": _proof_file(),
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert TreasuryTransaction.objects.count() == treasury_count_before + 1

    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(CustomerPayment),
        source_object_id=response.data["id"],
    )
    assert txn.type == TreasuryTransaction.Type.MONEY_IN
    assert txn.bank_account_id == bank_account.id
    assert txn.amount == Decimal("2500000.00")


# ---------------------------------------------------------------------------
# Bug fix (2026-09-06): editing a CustomerPayment's amount/account/date/
# customer/reference must never silently desync the TreasuryTransaction
# already posted at creation - since a plain PATCH has no safe way to
# reverse-and-repost that transaction yet, those fields are blocked outright
# once the payment exists (note/proof/allocations remain editable - none of
# them are read by FinancePostingService.record_customer_payment_treasury).
# ---------------------------------------------------------------------------


def _create_direct_bank_customer_payment(finance_client, suffix, *, amount="2500000.00"):
    _admin_user, customer, _invoice = _make_invoice_for_payment(suffix)
    bank_account = BankAccount.objects.create(name=f"Bank {suffix}")
    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": amount,
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.BANK_TRANSFER,
            "destination": CustomerPayment.Destination.BANK,
            "bank_account": bank_account.id,
        },
    )
    assert response.status_code == 201, response.data
    return response.data, bank_account, customer


@pytest.mark.django_db
def test_customer_payment_amount_edit_is_blocked_to_avoid_treasury_desync(finance_client):
    payment_data, bank_account, _customer = _create_direct_bank_customer_payment(
        finance_client, "EDIT-AMOUNT"
    )
    txn_before = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(CustomerPayment),
        source_object_id=payment_data["id"],
    )

    response = finance_client.patch(
        f"/api/customer-payments/{payment_data['id']}/", {"amount": "9999999.00"}
    )

    assert response.status_code == 400
    assert "amount" in response.data

    payment = CustomerPayment.objects.get(pk=payment_data["id"])
    assert payment.amount == Decimal("2500000.00")
    txn_before.refresh_from_db()
    assert txn_before.amount == Decimal("2500000.00")


@pytest.mark.django_db
def test_customer_payment_bank_account_edit_is_blocked_to_avoid_treasury_desync(finance_client):
    payment_data, bank_account, _customer = _create_direct_bank_customer_payment(
        finance_client, "EDIT-BANK"
    )
    other_bank = BankAccount.objects.create(name="Other Bank EDIT-BANK")

    response = finance_client.patch(
        f"/api/customer-payments/{payment_data['id']}/", {"bank_account": other_bank.id}
    )

    assert response.status_code == 400
    assert "bank_account" in response.data

    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(CustomerPayment),
        source_object_id=payment_data["id"],
    )
    assert txn.bank_account_id == bank_account.id


@pytest.mark.django_db
def test_customer_payment_date_and_customer_edit_are_blocked_to_avoid_treasury_desync(
    finance_client,
):
    payment_data, _bank_account, customer = _create_direct_bank_customer_payment(
        finance_client, "EDIT-DATE-CUST"
    )
    _admin_user, other_customer, _other_invoice = _make_invoice_for_payment("EDIT-DATE-CUST-2")

    date_response = finance_client.patch(
        f"/api/customer-payments/{payment_data['id']}/", {"payment_date": "2026-08-19"}
    )
    assert date_response.status_code == 400
    assert "payment_date" in date_response.data

    customer_response = finance_client.patch(
        f"/api/customer-payments/{payment_data['id']}/", {"customer": other_customer.id}
    )
    assert customer_response.status_code == 400
    assert "customer" in customer_response.data


@pytest.mark.django_db
def test_customer_payment_note_and_proof_edit_remain_allowed(finance_client):
    payment_data, _bank_account, _customer = _create_direct_bank_customer_payment(
        finance_client, "EDIT-NOTE-OK"
    )

    response = finance_client.patch(
        f"/api/customer-payments/{payment_data['id']}/", {"note": "Correction du libelle"}
    )

    assert response.status_code == 200, response.data
    payment = CustomerPayment.objects.get(pk=payment_data["id"])
    assert payment.note == "Correction du libelle"
    # Amount/account untouched - the treasury transaction stays in sync.
    assert payment.amount == Decimal("2500000.00")


@pytest.mark.django_db
def test_customer_payment_allocating_an_unallocated_credit_via_update_remains_allowed(
    finance_client,
):
    # Allocating an existing, still-unallocated payment credit to an
    # invoice via update() never touches the TreasuryTransaction (money
    # already received, no change in amount or account) - this must stay
    # a safe, available correction (e.g. "this payment was recorded as a
    # pure credit, now allocate it to the right invoice").
    admin_user, customer, invoice = _make_invoice_for_payment("EDIT-ALLOC-LATER")
    bank_account = BankAccount.objects.create(name="Bank EDIT-ALLOC-LATER")
    create_response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "1000000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.BANK_TRANSFER,
            "destination": CustomerPayment.Destination.BANK,
            "bank_account": bank_account.id,
        },
    )
    assert create_response.status_code == 201, create_response.data
    payment_id = create_response.data["id"]
    assert not PaymentAllocation.objects.filter(payment_id=payment_id).exists()

    response = finance_client.patch(
        f"/api/customer-payments/{payment_id}/",
        {"allocations": json.dumps([{"invoice": invoice.id, "amount": "1000000.00"}])},
    )

    assert response.status_code == 200, response.data
    assert PaymentAllocation.objects.filter(payment_id=payment_id, invoice=invoice).exists()
    # Amount/account untouched throughout.
    payment = CustomerPayment.objects.get(pk=payment_id)
    assert payment.amount == Decimal("1000000.00")
    assert payment.bank_account_id == bank_account.id


@pytest.mark.django_db
def test_direct_cash_customer_payment_creates_linked_treasury_transaction(finance_client):
    _admin_user, customer, _invoice = _make_invoice_for_payment("API-TREAS-CASH")
    cash_account = CashAccount.objects.create(name="Main Cash")
    treasury_count_before = TreasuryTransaction.objects.count()

    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "600000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.CASH,
            "destination": CustomerPayment.Destination.CASH,
            "cash_account": cash_account.id,
            "proof": _proof_file(),
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert TreasuryTransaction.objects.count() == treasury_count_before + 1

    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(CustomerPayment),
        source_object_id=response.data["id"],
    )
    assert txn.type == TreasuryTransaction.Type.MONEY_IN
    assert txn.cash_account_id == cash_account.id
    assert txn.amount == Decimal("600000.00")


@pytest.mark.django_db
def test_indirect_customer_payment_via_api_still_creates_no_treasury_transaction(finance_client):
    _admin_user, customer, _invoice = _make_invoice_for_payment("API-TREAS-INDIRECT")
    treasury_count_before = TreasuryTransaction.objects.count()

    response = finance_client.post(
        "/api/customer-payments/",
        {
            "customer": customer.id,
            "amount": "900000.00",
            "payment_date": "2026-08-18",
            "method": CustomerPayment.Method.OTHER,
            "destination": CustomerPayment.Destination.INDIRECT,
            "proof": _proof_file(),
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert response.data["is_indirect"] is True
    assert TreasuryTransaction.objects.count() == treasury_count_before


@pytest.mark.django_db
def test_documents_endpoint_accepts_customer_payment_proof_upload(finance_client, settings, tmp_path):
    """The seeded Finance role only has purchasing:view (never
    purchasing:create, see apps/accounts/migrations/0002_seed_roles.py) -
    before DocumentViewSet.module resolved dynamically per content type,
    this exact request 403'd because the viewset hardcoded module=
    "purchasing". This is the bug ruling 2 (Task 4) fixes, not just an
    ALLOWED_ATTACHMENT_MODELS entry."""
    settings.MEDIA_ROOT = str(tmp_path)
    admin_user, customer, _invoice = _make_invoice_for_payment("API-DOC-PROOF")
    cash_account = CashAccount.objects.create(name="Main Cash")
    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("400000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH,
        cash_account=cash_account,
        destination=CustomerPayment.Destination.CASH,
        recorded_by=admin_user,
    )
    proof = SimpleUploadedFile("proof.jpg", b"fake-image-bytes", content_type="image/jpeg")

    response = finance_client.post(
        "/api/documents/",
        {
            "file": proof,
            "document_type": "customer_payment_proof",
            "content_type_name": "customerpayment",
            "object_id": str(payment.id),
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    document = Document.objects.get(pk=response.data["id"])
    assert document.content_type == ContentType.objects.get_for_model(CustomerPayment)
    assert document.object_id == payment.id
    assert document.document_type == "customer_payment_proof"


@pytest.mark.django_db
def test_documents_endpoint_accepts_supplier_order_png_upload(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+222DOCIMG", pin="1234", role=admin_role
    )
    client = APIClient()
    client.force_authenticate(admin_user)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Doc Image Supplier")
    order = SupplierOrder.objects.create(
        reference="SO-DOC-IMAGE",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("500.0000"),
        created_by=admin_user,
    )
    image = SimpleUploadedFile("contract.png", b"fake-png", content_type="image/png")

    response = client.post(
        "/api/documents/",
        {
            "file": image,
            "document_type": "purchase_contract",
            "content_type_name": "supplierorder",
            "object_id": str(order.id),
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    document = Document.objects.get(pk=response.data["id"])
    assert document.file.name.endswith(".png")
    assert document.content_type == ContentType.objects.get_for_model(SupplierOrder)
    assert document.object_id == order.id


@pytest.mark.django_db
def test_documents_endpoint_rejects_non_image_upload(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+222DOCPDF", pin="1234", role=admin_role
    )
    client = APIClient()
    client.force_authenticate(admin_user)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Doc PDF Supplier")
    order = SupplierOrder.objects.create(
        reference="SO-DOC-PDF",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("500.0000"),
        created_by=admin_user,
    )
    pdf = SimpleUploadedFile(
        "contract.pdf", b"%PDF-1.4\n", content_type="application/pdf"
    )

    response = client.post(
        "/api/documents/",
        {
            "file": pdf,
            "document_type": "purchase_contract",
            "content_type_name": "supplierorder",
            "object_id": str(order.id),
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert response.data["file"][0] == "Seules les images JPG, JPEG, PNG ou WEBP sont autorisées."
    assert not Document.objects.filter(content_type=ContentType.objects.get_for_model(SupplierOrder), object_id=order.id).exists()


@pytest.fixture
def finance_only_client():
    """A role with ONLY finance permissions - no "purchasing" key at all
    (unlike the seeded Finance role, which happens to also grant
    purchasing:view - apps/accounts/migrations/0002_seed_roles.py). This is
    the role DocumentViewSet must work for without relying on that
    coincidence: retrieve/list/destroy of a customerpayment document must
    not require any purchasing permission."""
    role, _created = Role.objects.get_or_create(
        name="Finance Only (test)",
        defaults={
            "permissions": {"finance": ["view", "create", "edit", "validate", "cancel", "export"]}
        },
    )
    user = User.objects.create_user(phone="+2220000099", pin="1234", role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_documents_endpoint_retrieve_customer_payment_proof_for_finance_only_role(
    finance_only_client, settings, tmp_path
):
    """Ruling 2 fix, part 2: DocumentViewSet.module used to fall back to a
    hardcoded "purchasing" for retrieve/destroy (no content_type_name in a
    GET/DELETE body), so a role with finance permissions but zero
    purchasing access could upload a customer-payment proof and then 403
    trying to read it back. module must resolve from the existing
    Document's own content_type for these actions too."""
    settings.MEDIA_ROOT = str(tmp_path)
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000098", pin="1234", role=admin_role)
    _admin_user, customer, _invoice = _make_invoice_for_payment("API-DOC-RETRIEVE")
    cash_account = CashAccount.objects.create(name="Main Cash")
    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("150000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH,
        cash_account=cash_account,
        destination=CustomerPayment.Destination.CASH,
        recorded_by=admin_user,
    )
    document = Document.objects.create(
        file=SimpleUploadedFile("proof.jpg", b"fake-bytes", content_type="image/jpeg"),
        document_type="customer_payment_proof",
        uploaded_by=admin_user,
        content_type=ContentType.objects.get_for_model(CustomerPayment),
        object_id=payment.id,
    )

    retrieved = finance_only_client.get(f"/api/documents/{document.id}/")
    assert retrieved.status_code == 200, retrieved.data

    listed = finance_only_client.get("/api/documents/")
    assert listed.status_code == 200, listed.data
    listed_ids = {row["id"] for row in listed.data["results"]}
    assert document.id in listed_ids

    deleted = finance_only_client.delete(f"/api/documents/{document.id}/")
    assert deleted.status_code == 204, getattr(deleted, "data", None)
    assert not Document.objects.filter(pk=document.id).exists()


@pytest.mark.django_db
def test_documents_endpoint_list_excludes_modules_role_cannot_view(finance_only_client, settings, tmp_path):
    """get_queryset() must still filter by what the caller's role can
    actually view, even though _AnyAttachableModulePermission lets the
    request through as soon as they can view ANY attachable module - a
    finance-only role must not see a purchasing (supplierorder) document."""
    settings.MEDIA_ROOT = str(tmp_path)
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000097", pin="1234", role=admin_role)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Supplier Doc", country="Senegal")
    supplier_order = SupplierOrder.objects.create(
        reference="SO-DOC-1",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("10000.00"),
        unit_price=Decimal("500.0000"),
        created_by=admin_user,
    )
    purchasing_document = Document.objects.create(
        file=SimpleUploadedFile("contract.pdf", b"fake-bytes", content_type="application/pdf"),
        document_type="purchase_contract",
        uploaded_by=admin_user,
        content_type=ContentType.objects.get_for_model(SupplierOrder),
        object_id=supplier_order.id,
    )

    listed = finance_only_client.get("/api/documents/")

    assert listed.status_code == 200, listed.data
    listed_ids = {row["id"] for row in listed.data["results"]}
    assert purchasing_document.id not in listed_ids


# ---------------------------------------------------------------------------
# Task 7 (client modifications plan): Shareholders / Associates domain
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client():
    role = Role.objects.get(name=Role.NAME_ADMIN)
    user = User.objects.create_user(phone="+2220000200", pin="1234", role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


def _make_admin_user(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=(f"+222900{suffix}")[:20], pin="1234", role=admin_role)


def _make_shareholders(percents, prefix="SH"):
    return [
        Shareholder.objects.create(name=f"{prefix}-{i}", participation_percent=Decimal(str(p)))
        for i, p in enumerate(percents)
    ]


def _seed_distributable(amount=Decimal("10000000.00"), name="Seed Till"):
    """Give the company enough treasury that validate_distribution's hard
    amount block (2026-09-08 review, point 2) clears - for tests where the
    amount guard is not what is under test.

    distributable_result == treasury + receivables - capital -
    already_distributed, so a CashAccount opening balance alone lifts it.
    """
    return CashAccount.objects.create(name=name, opening_balance=Decimal(str(amount)))


@pytest.mark.django_db
def test_shareholder_percent_must_be_between_0_and_100():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Shareholder.objects.create(name="Over", participation_percent=Decimal("100.01"))

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Shareholder.objects.create(name="Under", participation_percent=Decimal("-0.01"))


@pytest.mark.django_db
def test_active_shareholder_percentages_cannot_exceed_100_total():
    _make_shareholders([Decimal("60"), Decimal("30")])

    with pytest.raises(ShareholderParticipationError):
        ShareholderService.validate_total_participation(Decimal("20"))

    # Exactly reaching 100 total is allowed.
    ShareholderService.validate_total_participation(Decimal("10"))


@pytest.mark.django_db
def test_active_shareholder_percentages_check_excludes_inactive():
    _make_shareholders([Decimal("60")])
    Shareholder.objects.create(
        name="Inactive", participation_percent=Decimal("50"), is_active=False
    )

    # The inactive 50% doesn't count towards the 100 cap.
    ShareholderService.validate_total_participation(Decimal("40"))


@pytest.mark.django_db
def test_active_shareholder_percentages_check_excludes_self_on_update():
    a, b = _make_shareholders([Decimal("60"), Decimal("30")])

    # Raising `a` from 60 to 70 keeps the same total shareholder (a) out of
    # its own comparison, so it must be evaluated against b's 30 only.
    ShareholderService.validate_total_participation(Decimal("70"), exclude_id=a.id)

    with pytest.raises(ShareholderParticipationError):
        ShareholderService.validate_total_participation(Decimal("71"), exclude_id=a.id)


@pytest.mark.django_db
def test_shareholder_crud_via_admin_api(admin_client):
    """`contribution` is read-only via this API (bug fix, 2026-09-10 - see
    ShareholderSerializer.Meta): a value submitted here must be ignored,
    not persisted. Real capital always goes through
    ShareholderContributionService.record_contribution() instead, which
    requires a bank/cash account."""
    created = admin_client.post(
        "/api/shareholders/",
        {
            "name": "Amadou Diallo",
            "participation_percent": "50.00",
            "contribution": "1000000.00",
            "phone": "+22212345678",
        },
    )
    assert created.status_code == 201, created.data
    assert created.data["contribution"] == "0.00"

    updated = admin_client.patch(
        f"/api/shareholders/{created.data['id']}/",
        {"participation_percent": "55.00", "contribution": "1250000.00"},
    )
    assert updated.status_code == 200, updated.data
    assert updated.data["participation_percent"] == "55.00"
    assert updated.data["contribution"] == "0.00"


@pytest.mark.django_db
def test_shareholder_creation_rejected_via_api_when_total_exceeds_100(admin_client):
    Shareholder.objects.create(name="Existing", participation_percent=Decimal("90"))

    response = admin_client.post(
        "/api/shareholders/",
        {"name": "New", "participation_percent": "20.00", "is_active": True},
    )

    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_finance_role_can_create_but_not_edit_shareholder(finance_client):
    created = finance_client.post(
        "/api/shareholders/", {"name": "Fatou Sow", "participation_percent": "10.00"}
    )
    assert created.status_code == 201, created.data

    updated = finance_client.patch(
        f"/api/shareholders/{created.data['id']}/", {"participation_percent": "15.00"}
    )
    assert updated.status_code == 403


@pytest.mark.django_db
def test_create_distribution_calculates_shares_80_10_10():
    a, b, c = _make_shareholders([Decimal("80"), Decimal("10"), Decimal("10")])
    actor = _make_admin_user("1")
    _seed_distributable()

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("1000000.00"),
        actor=actor,
    )

    assert distribution.status == ShareholderProfitDistribution.Status.DRAFT
    assert distribution.created_by == actor

    shares = {
        share.shareholder_id: share.amount_due
        for share in ShareholderProfitShare.objects.filter(distribution=distribution)
    }
    assert shares[a.id] == Decimal("800000.00")
    assert shares[b.id] == Decimal("100000.00")
    assert shares[c.id] == Decimal("100000.00")


@pytest.mark.django_db
def test_create_distribution_allocates_rounding_remainder_deterministically():
    """2026-09-08 review, point 8: sum(amount_due) equals
    total_profit * sum(percents)/100 to the cent, with the leftover
    centime assigned deterministically - never created, never lost."""
    a, b, c = _make_shareholders(
        [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")], prefix="ROUND"
    )
    actor = _make_admin_user("ROUND")

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100.01"),
        actor=actor,
    )

    shares = {
        s.shareholder_id: s.amount_due
        for s in ShareholderProfitShare.objects.filter(distribution=distribution)
    }
    assert sum(shares.values()) == Decimal("100.01")
    # c holds the largest fractional remainder (33.34% -> .343334), so the
    # odd centime lands there - and it lands there every time.
    assert shares[c.id] == Decimal("33.35")
    assert shares[a.id] == Decimal("33.33")
    assert shares[b.id] == Decimal("33.33")

    twin = ShareholderDistributionService.create_distribution(
        period_start="2026-08-01",
        period_end="2026-08-31",
        total_profit=Decimal("100.01"),
        actor=actor,
    )
    assert {
        s.shareholder_id: s.amount_due
        for s in ShareholderProfitShare.objects.filter(distribution=twin)
    } == shares


@pytest.mark.django_db
def test_create_distribution_remainder_when_percentages_sum_below_100():
    """The invariant is against total_profit * sum(percents)/100, not
    total_profit itself - two associates at 33.33% each only share 66.66%
    of the profit."""
    a, b = _make_shareholders([Decimal("33.33"), Decimal("33.33")], prefix="ROUNDLOW")
    actor = _make_admin_user("ROUNDLOW")

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100.01"),
        actor=actor,
    )

    shares = ShareholderProfitShare.objects.filter(distribution=distribution)
    assert sum(s.amount_due for s in shares) == Decimal("66.67")  # 100.01 * 66.66 / 100


@pytest.mark.django_db
def test_create_distribution_only_snapshots_active_shareholders():
    active = Shareholder.objects.create(name="Active", participation_percent=Decimal("70"))
    Shareholder.objects.create(name="Inactive", participation_percent=Decimal("20"), is_active=False)
    actor = _make_admin_user("2")
    _seed_distributable()

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("500000.00"),
        actor=actor,
    )

    shares = ShareholderProfitShare.objects.filter(distribution=distribution)
    assert shares.count() == 1
    assert shares.first().shareholder_id == active.id


@pytest.mark.django_db
def test_distribution_percent_snapshot_unaffected_by_later_shareholder_change():
    """Changing a shareholder's ongoing participation_percent after a
    distribution exists must not retroactively alter that distribution's
    already-calculated shares (Task 7 design guidance)."""
    shareholder = Shareholder.objects.create(name="Solo", participation_percent=Decimal("50"))
    actor = _make_admin_user("3")
    _seed_distributable()

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("200000.00"),
        actor=actor,
    )
    share = ShareholderProfitShare.objects.get(distribution=distribution)
    assert share.percent_snapshot == Decimal("50.00")
    assert share.amount_due == Decimal("100000.00")

    shareholder.participation_percent = Decimal("90.00")
    shareholder.save(update_fields=["participation_percent"])

    share.refresh_from_db()
    assert share.percent_snapshot == Decimal("50.00")
    assert share.amount_due == Decimal("100000.00")


@pytest.mark.django_db
def test_create_distribution_raises_when_no_active_shareholders():
    """Recette bug (2026-09-06): a manager created AND validated a profit
    distribution while the Shareholder list was completely empty - the
    money was "distributed" to nobody, with zero ShareholderProfitShare
    rows. create_distribution must refuse outright instead."""
    actor = _make_admin_user("NOSHR")
    _seed_distributable()

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.create_distribution(
            period_start="2026-07-01",
            period_end="2026-07-31",
            total_profit=Decimal("1000000.00"),
            actor=actor,
        )

    assert ShareholderProfitDistribution.objects.count() == 0


@pytest.mark.django_db
def test_create_distribution_raises_when_only_inactive_shareholders():
    """Same bug, but with a Shareholder row that exists yet is inactive -
    still zero shares would result, so it must still be refused."""
    Shareholder.objects.create(name="Inactive", participation_percent=Decimal("50"), is_active=False)
    actor = _make_admin_user("NOSHRINACT")
    _seed_distributable()

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.create_distribution(
            period_start="2026-07-01",
            period_end="2026-07-31",
            total_profit=Decimal("1000000.00"),
            actor=actor,
        )

    assert ShareholderProfitDistribution.objects.count() == 0


@pytest.mark.django_db
def test_create_distribution_rejects_exact_duplicate_period():
    """Recette bug (2026-09-08): the exact same period/benefice was
    distributed three times in a row because create_distribution never
    checked for an existing distribution covering the same period -
    shareholders ended up "owed" the same real profit 3x."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("DUP1")
    _seed_distributable()
    ShareholderDistributionService.create_distribution(
        period_start="2026-09-08",
        period_end="2026-09-08",
        total_profit=Decimal("9034000.00"),
        actor=actor,
    )

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.create_distribution(
            period_start="2026-09-08",
            period_end="2026-09-08",
            total_profit=Decimal("9034000.00"),
            actor=actor,
        )

    assert ShareholderProfitDistribution.objects.count() == 1


@pytest.mark.django_db
def test_create_distribution_rejects_partially_overlapping_period():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("DUP2")
    _seed_distributable()
    ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.create_distribution(
            period_start="2026-07-15",
            period_end="2026-08-15",
            total_profit=Decimal("50000.00"),
            actor=actor,
        )

    assert ShareholderProfitDistribution.objects.count() == 1


@pytest.mark.django_db
def test_create_distribution_allows_adjacent_non_overlapping_period():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("DUP3")
    _seed_distributable()
    ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    second = ShareholderDistributionService.create_distribution(
        period_start="2026-08-01",
        period_end="2026-08-31",
        total_profit=Decimal("50000.00"),
        actor=actor,
    )

    assert ShareholderProfitDistribution.objects.count() == 2
    assert second.period_start.isoformat() == "2026-08-01"


@pytest.mark.django_db
def test_create_distribution_ignores_cancelled_distribution_when_checking_overlap():
    """A cancelled distribution must never block re-creating a corrected
    one for the same period (that's the whole point of cancelling a
    mistake)."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("DUP4")
    _seed_distributable()
    first = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.cancel_distribution(first.id, actor)

    second = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("120000.00"),
        actor=actor,
    )

    assert ShareholderProfitDistribution.objects.filter(
        status=ShareholderProfitDistribution.Status.DRAFT
    ).count() == 1
    assert second.total_profit == Decimal("120000.00")


@pytest.mark.django_db
def test_overlapping_active_distributions_are_rejected_at_the_database_level():
    """2026-09-08 review, point 6: even bypassing the service entirely,
    two non-cancelled distributions covering overlapping periods cannot
    both be committed - the exclusion constraint is the atomic guard that
    two concurrent creates would otherwise race straight past."""
    actor = _make_admin_user("XCON")
    ShareholderProfitDistribution.objects.create(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        created_by=actor,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ShareholderProfitDistribution.objects.create(
                period_start="2026-07-15",
                period_end="2026-08-15",
                total_profit=Decimal("50000.00"),
                created_by=actor,
            )


@pytest.mark.django_db
def test_cancelled_distribution_frees_its_period_at_the_database_level():
    """The exclusion constraint is partial (status in DRAFT/VALIDATED) so
    a cancelled distribution never blocks a corrected one for the same
    period."""
    actor = _make_admin_user("XCON2")
    ShareholderProfitDistribution.objects.create(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        created_by=actor,
        status=ShareholderProfitDistribution.Status.CANCELLED,
    )

    ShareholderProfitDistribution.objects.create(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("120000.00"),
        created_by=actor,
    )

    assert ShareholderProfitDistribution.objects.filter(period_start="2026-07-01").count() == 2


@pytest.mark.django_db
def test_create_distribution_via_api_rejects_when_no_active_shareholders(admin_client):
    response = admin_client.post(
        "/api/shareholder-distributions/",
        {"period_start": "2026-07-01", "period_end": "2026-07-31", "total_profit": "300000.00"},
    )

    assert response.status_code == 400, response.data
    assert ShareholderProfitDistribution.objects.count() == 0


@pytest.mark.django_db
def test_distribution_validate_action_via_admin_api(admin_client):
    _make_shareholders([Decimal("100")])
    _seed_distributable()

    created = admin_client.post(
        "/api/shareholder-distributions/",
        {"period_start": "2026-07-01", "period_end": "2026-07-31", "total_profit": "300000.00"},
    )
    assert created.status_code == 201, created.data
    assert created.data["status"] == "DRAFT"

    validated = admin_client.post(f"/api/shareholder-distributions/{created.data['id']}/validate/")
    assert validated.status_code == 200, validated.data
    assert validated.data["status"] == "VALIDATED"
    assert validated.data["validated_by"] is not None
    assert validated.data["validated_at"] is not None


@pytest.mark.django_db
def test_distribution_cancel_action_via_admin_api(admin_client):
    _make_shareholders([Decimal("100")])

    created = admin_client.post(
        "/api/shareholder-distributions/",
        {"period_start": "2026-07-01", "period_end": "2026-07-31", "total_profit": "300000.00"},
    )
    assert created.status_code == 201, created.data

    cancelled = admin_client.post(f"/api/shareholder-distributions/{created.data['id']}/cancel/")
    assert cancelled.status_code == 200, cancelled.data
    assert cancelled.data["status"] == "CANCELLED"
    assert cancelled.data["cancelled_by"] is not None
    assert cancelled.data["cancelled_at"] is not None


@pytest.mark.django_db
def test_distribution_cancel_action_rejects_when_withdrawal_exists(admin_client):
    shareholder = _make_shareholders([Decimal("100")])[0]
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    actor = User.objects.create_user(phone="+2220000201", pin="1234", role=admin_role)
    _seed_distributable()

    created = admin_client.post(
        "/api/shareholder-distributions/",
        {"period_start": "2026-07-01", "period_end": "2026-07-31", "total_profit": "300000.00"},
    )
    admin_client.post(f"/api/shareholder-distributions/{created.data['id']}/validate/")
    share = ShareholderProfitShare.objects.get(distribution_id=created.data["id"])
    cash_account = CashAccount.objects.create(name="API Cash", opening_balance=Decimal("300000.00"))
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("1000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=actor,
    )

    response = admin_client.post(f"/api/shareholder-distributions/{created.data['id']}/cancel/")

    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_distribution_cancel_action_requires_cancel_permission():
    """Finance role only has view/create on the shareholders module (see
    backend/apps/accounts/migrations/0005_seed_shareholder_permissions.py)
    - it must not be able to cancel a distribution."""
    finance_role = Role.objects.get(name=Role.NAME_FINANCE)
    user = User.objects.create_user(phone="+2220000202", pin="1234", role=finance_role)
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000203", pin="1234", role=admin_role)
    _make_shareholders([Decimal("100")])
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=admin_user,
    )

    client = APIClient()
    client.force_authenticate(user)
    response = client.post(f"/api/shareholder-distributions/{distribution.id}/cancel/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_distribution_cancel_action_allowed_for_management():
    """2026-09-08 review, point 9: migration 0006 grants the cancel tier
    to Admin AND Management - Management must be able to cancel."""
    mgmt_role = Role.objects.get(name=Role.NAME_MANAGEMENT)
    user = User.objects.create_user(phone="+2220000210", pin="1234", role=mgmt_role)
    admin_user = _make_admin_user("MGMTADM")
    _make_shareholders([Decimal("100")])
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=admin_user,
    )

    client = APIClient()
    client.force_authenticate(user)
    response = client.post(f"/api/shareholder-distributions/{distribution.id}/cancel/")

    assert response.status_code == 200, response.data
    assert response.data["status"] == "CANCELLED"


@pytest.mark.django_db
def test_distribution_create_validate_cancel_are_all_audited():
    """2026-09-08 review, point 9: every lifecycle transition of a
    distribution lands in the journal d'audit, attributed to its actor."""
    _make_shareholders([Decimal("100")])
    _seed_distributable()
    actor = _make_admin_user("AUDITLC")
    ct = ContentType.objects.get_for_model(ShareholderProfitDistribution)

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    create_log = AuditLog.objects.get(
        content_type=ct, object_id=distribution.id, action=AuditLog.Action.CREATE
    )
    assert create_log.user_id == actor.id

    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    assert AuditLog.objects.filter(
        content_type=ct, object_id=distribution.id, action=AuditLog.Action.UPDATE
    ).exists()

    ShareholderDistributionService.cancel_distribution(distribution.id, actor)
    cancel_log = AuditLog.objects.get(
        content_type=ct, object_id=distribution.id, action=AuditLog.Action.CANCEL
    )
    assert cancel_log.user_id == actor.id
    assert cancel_log.previous_value["status"] == "VALIDATED"
    assert cancel_log.new_value["status"] == "CANCELLED"

    distribution.refresh_from_db()
    assert distribution.cancelled_by_id == actor.id
    assert distribution.cancelled_at is not None


@pytest.mark.django_db
def test_shareholder_api_rejects_hard_delete(admin_client):
    """Regression test (code review, fix round 1): migration
    0006_grant_shareholder_cancel_permission grants Admin/Management the
    "cancel" tier on the whole "shareholders" module, not just the
    distribution viewset. destroy() maps to "cancel" via ACTION_MAP's
    default fallback, so an admin's DELETE now clears HasModulePermission
    for every viewset sharing that module - including ShareholderViewSet,
    which had no destroy() override. Without this override, the request
    would reach ModelViewSet.destroy() and hard-delete the row (or raise
    an unhandled ProtectedError if referenced by a ShareholderProfitShare)."""
    shareholder = _make_shareholders([Decimal("100")])[0]

    response = admin_client.delete(f"/api/shareholders/{shareholder.id}/")

    assert response.status_code == 405


@pytest.mark.django_db
def test_shareholder_loan_api_rejects_hard_delete(admin_client):
    """Regression test (code review, fix round 1): same gap as
    test_shareholder_api_rejects_hard_delete above, for
    ShareholderLoanViewSet - it also had no destroy() override, so an
    admin's DELETE would silently hard-delete the loan (no protecting FK
    exists for ShareholderLoan)."""
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")])
    loan = ShareholderLoan.objects.create(
        borrower=borrower, lender=lender, amount=Decimal("100000.00"), date="2026-08-01"
    )

    response = admin_client.delete(f"/api/shareholder-loans/{loan.id}/")

    assert response.status_code == 405


@pytest.mark.django_db
def test_validate_distribution_rejects_when_shares_became_empty(admin_client):
    """Defense in depth alongside create_distribution's own guard: the
    DRAFT's only shareholder is deactivated AFTER creation (so its
    ShareholderProfitShare row still exists, but the invariant "a validated
    distribution always has at least one live share" is what actually
    matters) - simulate the zero-share case directly, the way the recette
    bug (2026-09-06) manifested, and confirm validate refuses it."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("VALEMPTY")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("300000.00"),
        actor=actor,
    )
    ShareholderProfitShare.objects.filter(distribution=distribution).delete()

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.validate_distribution(distribution.id, actor)

    distribution.refresh_from_db()
    assert distribution.status == ShareholderProfitDistribution.Status.DRAFT

    response = admin_client.post(f"/api/shareholder-distributions/{distribution.id}/validate/")
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_cancel_distribution_from_draft():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("CANCEL1")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    cancelled = ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    assert cancelled.status == ShareholderProfitDistribution.Status.CANCELLED
    assert cancelled.cancelled_by == actor
    assert cancelled.cancelled_at is not None
    # Shares stay for audit history, they're just excluded downstream.
    assert ShareholderProfitShare.objects.filter(distribution=distribution).count() == 1


@pytest.mark.django_db
def test_cancel_distribution_from_validated_releases_available_balance():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("CANCEL2")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("100000.00")

    ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("0.00")


@pytest.mark.django_db
def test_cancel_distribution_rejects_when_withdrawal_already_recorded():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("CANCEL3")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    share = distribution.shares.get(shareholder=shareholder)
    cash_account = CashAccount.objects.create(name="Cancel Cash", opening_balance=Decimal("100000.00"))
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("10000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=actor,
    )

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    distribution.refresh_from_db()
    assert distribution.status == ShareholderProfitDistribution.Status.VALIDATED


@pytest.mark.django_db
def test_cancel_distribution_is_idempotent():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("CANCEL4")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.cancel_distribution(distribution.id, actor)
    distribution.refresh_from_db()
    first_cancelled_at = distribution.cancelled_at

    result = ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    distribution.refresh_from_db()
    assert result.status == ShareholderProfitDistribution.Status.CANCELLED
    assert distribution.cancelled_at == first_cancelled_at


@pytest.mark.django_db
def test_validate_distribution_rejects_cancelled_distribution():
    """2026-09-08 review, point 3: CANCELLED is terminal - a cancelled
    distribution can never be resurrected into VALIDATED."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("REVIVE")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.validate_distribution(distribution.id, actor)

    distribution.refresh_from_db()
    assert distribution.status == ShareholderProfitDistribution.Status.CANCELLED
    assert distribution.validated_by is None
    assert distribution.validated_at is None


@pytest.mark.django_db
def test_validate_distribution_is_idempotent_and_keeps_original_stamp():
    """2026-09-08 review, point 3: re-validating an already-VALIDATED
    distribution repeats the same action without touching the original
    validated_by / validated_at."""
    _make_shareholders([Decimal("100")])
    first_actor = _make_admin_user("VAL1")
    second_actor = _make_admin_user("VAL2")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=first_actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, first_actor)
    distribution.refresh_from_db()
    original_by, original_at = distribution.validated_by_id, distribution.validated_at

    ShareholderDistributionService.validate_distribution(distribution.id, second_actor)

    distribution.refresh_from_db()
    assert distribution.validated_by_id == original_by == first_actor.id
    assert distribution.validated_at == original_at


@pytest.mark.django_db
def test_cancel_distribution_rejects_draft_after_cancel_is_terminal():
    """2026-09-08 review, point 3: the only transitions out of a
    distribution are DRAFT->VALIDATED, DRAFT->CANCELLED,
    VALIDATED->CANCELLED. Nothing leaves CANCELLED."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("TERMINAL")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.validate_distribution(distribution.id, actor)


@pytest.mark.django_db
def test_validate_distribution_rejects_amount_over_distributable_result():
    """2026-09-08 review, point 2: the backend hard-blocks a validation
    whose total_profit exceeds the amount actually still available for
    distribution - the soft frontend warning must never be the only
    guard."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("HARDCAP")
    CashAccount.objects.create(name="Small Till", opening_balance=Decimal("50000.00"))
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.validate_distribution(distribution.id, actor)

    distribution.refresh_from_db()
    assert distribution.status == ShareholderProfitDistribution.Status.DRAFT


@pytest.mark.django_db
def test_validate_distribution_allows_amount_within_distributable_result():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("HARDOK")
    CashAccount.objects.create(name="Full Till", opening_balance=Decimal("500000.00"))
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    ShareholderDistributionService.validate_distribution(distribution.id, actor)

    distribution.refresh_from_db()
    assert distribution.status == ShareholderProfitDistribution.Status.VALIDATED


@pytest.mark.django_db
def test_validate_distribution_amount_check_is_recomputed_at_validation_time():
    """2026-09-08 review, point 2: the check is redone at validation even
    though the amount looked fine at creation - the financial situation
    moved in between (here: a second distribution was validated and ate
    the headroom)."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("HARDFRESH")
    CashAccount.objects.create(name="Shared Till", opening_balance=Decimal("150000.00"))

    first = ShareholderDistributionService.create_distribution(
        period_start="2026-06-01",
        period_end="2026-06-30",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    second = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    ShareholderDistributionService.validate_distribution(first.id, actor)

    # 150000 treasury - 100000 already committed = 50000 left, < 100000.
    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.validate_distribution(second.id, actor)


@pytest.mark.django_db
def test_shareholder_withdrawal_creates_treasury_transaction_and_reduces_remaining_due():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("4")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("1000000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    share = ShareholderProfitShare.objects.get(distribution=distribution)
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("1000000.00"))

    withdrawal = ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("400000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=actor,
    )

    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(ShareholderWithdrawal),
        source_object_id=withdrawal.id,
    )
    assert txn.type == TreasuryTransaction.Type.MONEY_OUT
    assert txn.cash_account_id == cash_account.id
    assert txn.amount == Decimal("400000.00")

    share.refresh_from_db()
    assert share.amount_withdrawn == Decimal("400000.00")
    assert share.remaining_due == Decimal("600000.00")


@pytest.mark.django_db
def test_shareholder_withdrawal_rejects_amount_exceeding_remaining_due():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("5")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    share = ShareholderProfitShare.objects.get(distribution=distribution)
    cash_account = CashAccount.objects.create(name="Main Cash")

    with pytest.raises(ShareholderWithdrawalError):
        ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=shareholder.id,
            profit_share_id=share.id,
            amount=Decimal("150000.00"),
            date="2026-08-01",
            cash_account_id=cash_account.id,
            actor=actor,
        )


@pytest.mark.django_db
def test_shareholder_withdrawal_requires_a_profit_share():
    """2026-09-08 review, point 5: a profit withdrawal must always be tied
    to one traceable validated share - an unlinked "retrait general"
    debited treasury while decrementing nothing, leaving the shareholder's
    available balance unchanged."""
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("6")
    _seed_distributable()
    _distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(_distribution.id, actor)
    bank_account = BankAccount.objects.create(name="Main BOA", opening_balance=Decimal("100000.00"))

    with pytest.raises(ShareholderWithdrawalError):
        ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=shareholder.id,
            profit_share_id=None,
            amount=Decimal("50000.00"),
            date="2026-08-01",
            bank_account_id=bank_account.id,
            actor=actor,
        )

    assert not ShareholderWithdrawal.objects.filter(shareholder=shareholder).exists()
    assert not TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(ShareholderWithdrawal)
    ).exists()


@pytest.mark.django_db
def test_shareholder_withdrawal_reduces_available_balance_permanently():
    """2026-09-08 review, point 5: a withdrawal really and definitively
    lowers the shareholder's available balance - the money left, the
    remaining_due dropped, and it stays dropped."""
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("6b")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    share = distribution.shares.get(shareholder=shareholder)
    cash_account = CashAccount.objects.create(
        name="Perm Cash", opening_balance=Decimal("100000.00")
    )
    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("100000.00")

    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("40000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=actor,
    )

    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("60000.00")
    # Re-reading (a fresh service call, no caching) keeps the lower figure.
    assert ShareholderLedgerService.get_shareholder_summary(shareholder.id)[
        "remaining_due"
    ] == Decimal("60000.00")


@pytest.mark.django_db
def test_shareholder_withdrawal_rejects_amount_exceeding_bank_balance():
    """Fix 1: the destination account's balance was never checked either -
    a withdrawal could exceed what the selected bank/cash account actually
    held."""
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("6c")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("1000000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    share = distribution.shares.get(shareholder=shareholder)
    bank_account = BankAccount.objects.create(name="Poor BOA", opening_balance=Decimal("1000.00"))

    with pytest.raises(ShareholderWithdrawalError):
        ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=shareholder.id,
            profit_share_id=share.id,
            amount=Decimal("50000.00"),
            date="2026-08-01",
            bank_account_id=bank_account.id,
            actor=actor,
        )


@pytest.mark.django_db
def test_get_shareholder_summary_excludes_cancelled_distribution_shares():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("SUMMARYCANCEL")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    assert ShareholderLedgerService.get_shareholder_summary(shareholder.id)["remaining_due"] == (
        Decimal("100000.00")
    )

    ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    summary = ShareholderLedgerService.get_shareholder_summary(shareholder.id)

    assert summary["shares"] == []
    assert summary["total_amount_due"] == Decimal("0.00")
    assert summary["total_withdrawn"] == Decimal("0.00")
    assert summary["remaining_due"] == Decimal("0.00")


@pytest.mark.django_db
def test_shareholder_withdrawal_rejects_profit_share_from_cancelled_distribution():
    """The shareholder has enough OTHER, legitimate balance (from a second,
    non-overlapping, still-VALIDATED distribution) to pass the aggregate
    available_balance check - the withdrawal must still be refused because
    it explicitly names a profit_share_id belonging to a CANCELLED
    distribution, not because of the aggregate."""
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("WDRAWCANCEL")
    _seed_distributable()
    cancelled_distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(cancelled_distribution.id, actor)
    ShareholderDistributionService.cancel_distribution(cancelled_distribution.id, actor)
    cancelled_share = cancelled_distribution.shares.get(shareholder=shareholder)

    other_distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-08-01",
        period_end="2026-08-31",
        total_profit=Decimal("50000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(other_distribution.id, actor)

    cash_account = CashAccount.objects.create(
        name="Gap Cash", opening_balance=Decimal("100000.00")
    )

    with pytest.raises(ShareholderWithdrawalError):
        ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=shareholder.id,
            profit_share_id=cancelled_share.id,
            amount=Decimal("30000.00"),
            date="2026-09-01",
            cash_account_id=cash_account.id,
            actor=actor,
        )

    cancelled_share.refresh_from_db()
    assert cancelled_share.amount_withdrawn == Decimal("0.00")
    assert not ShareholderWithdrawal.objects.filter(profit_share=cancelled_share).exists()


@pytest.mark.django_db
def test_shareholder_withdrawal_requires_exactly_one_account():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("7")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ShareholderWithdrawal.objects.create(
                shareholder=shareholder,
                amount=Decimal("1000.00"),
                date="2026-08-01",
                recorded_by=actor,
            )


@pytest.mark.django_db
def test_shareholder_withdrawal_via_api_posts_treasury(admin_client):
    shareholder = _make_shareholders([Decimal("100")])[0]
    _api_actor = _make_admin_user("6d")
    _seed_distributable()
    _api_distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=_api_actor,
    )
    ShareholderDistributionService.validate_distribution(_api_distribution.id, _api_actor)
    share = _api_distribution.shares.get(shareholder=shareholder)
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("100000.00"))

    response = admin_client.post(
        "/api/shareholder-withdrawals/",
        {
            "shareholder": shareholder.id,
            "profit_share": share.id,
            "amount": "25000.00",
            "date": "2026-08-01",
            "cash_account": cash_account.id,
        },
    )

    assert response.status_code == 201, response.data
    assert TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(ShareholderWithdrawal),
        source_object_id=response.data["id"],
    ).exists()


@pytest.mark.django_db
def test_shareholder_withdrawal_via_api_rejects_missing_profit_share(admin_client):
    """2026-09-08 review, point 5: the API must refuse a withdrawal with no
    profit_share, independently of the frontend form."""
    shareholder = _make_shareholders([Decimal("100")])[0]
    cash_account = CashAccount.objects.create(
        name="No Share Cash", opening_balance=Decimal("100000.00")
    )

    response = admin_client.post(
        "/api/shareholder-withdrawals/",
        {
            "shareholder": shareholder.id,
            "amount": "25000.00",
            "date": "2026-08-01",
            "cash_account": cash_account.id,
        },
    )

    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_shareholder_loan_tracks_borrower_lender_and_balances():
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")])

    loan = ShareholderLoan.objects.create(
        borrower=borrower, lender=lender, amount=Decimal("100000.00"), date="2026-08-01"
    )

    assert loan.status == ShareholderLoan.Status.OPEN
    assert loan.remaining_amount == Decimal("100000.00")

    loan.amount_repaid = Decimal("40000.00")
    loan.save()
    loan.refresh_from_db()
    assert loan.status == ShareholderLoan.Status.PARTIALLY_REPAID
    assert loan.remaining_amount == Decimal("60000.00")

    loan.amount_repaid = Decimal("100000.00")
    loan.save()
    loan.refresh_from_db()
    assert loan.status == ShareholderLoan.Status.REPAID
    assert loan.remaining_amount == Decimal("0.00")


@pytest.mark.django_db
def test_shareholder_loan_repaid_amount_cannot_exceed_principal():
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")])

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ShareholderLoan.objects.create(
                borrower=borrower,
                lender=lender,
                amount=Decimal("100000.00"),
                amount_repaid=Decimal("100000.01"),
                date="2026-08-01",
            )


@pytest.mark.django_db
def test_shareholder_loan_borrower_cannot_equal_lender():
    solo = _make_shareholders([Decimal("100")])[0]

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ShareholderLoan.objects.create(
                borrower=solo, lender=solo, amount=Decimal("10000.00"), date="2026-08-01"
            )


@pytest.mark.django_db
def test_shareholder_loan_service_rejects_amount_exceeding_lender_available_balance():
    """Fix 2 (design doc 2026-08-26-benefices-associes-refinement-design.md):
    before this, creating a ShareholderLoan never checked the lender had
    anything to lend - a lender with no profit share and no prior loans
    could still "lend" an arbitrary amount."""
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")], prefix="LOANBAL")

    with pytest.raises(ShareholderLoanError):
        ShareholderLoanService.create_loan(
            borrower_id=borrower.id,
            lender_id=lender.id,
            amount=Decimal("1.00"),
            date="2026-08-01",
        )


@pytest.mark.django_db
def test_shareholder_loan_service_creates_loan_within_lender_available_balance():
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")], prefix="LOANOK")
    _loanok_actor = _make_admin_user("LOANOK")
    _seed_distributable()
    _loanok_distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=_loanok_actor,
    )
    ShareholderDistributionService.validate_distribution(_loanok_distribution.id, _loanok_actor)

    loan = ShareholderLoanService.create_loan(
        borrower_id=borrower.id,
        lender_id=lender.id,
        amount=Decimal("20000.00"),
        date="2026-08-01",
    )

    assert loan.borrower_id == borrower.id
    assert loan.lender_id == lender.id
    assert loan.amount == Decimal("20000.00")
    assert loan.status == ShareholderLoan.Status.OPEN


@pytest.mark.django_db
def test_shareholder_loan_service_never_creates_treasury_transaction():
    """Money moving between shareholders is a ledger-only entry, never a
    company treasury movement (design doc, point 3: "une avance entre
    associes ne doit pas creer de TreasuryTransaction si l'argent ne sort
    pas d'un compte de l'entreprise")."""
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")], prefix="LOANTXN")
    _loantxn_actor = _make_admin_user("LOANTXN")
    _seed_distributable()
    _loantxn_distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=_loantxn_actor,
    )
    ShareholderDistributionService.validate_distribution(_loantxn_distribution.id, _loantxn_actor)
    treasury_count_before = TreasuryTransaction.objects.count()

    ShareholderLoanService.create_loan(
        borrower_id=borrower.id, lender_id=lender.id, amount=Decimal("20000.00"), date="2026-08-01"
    )

    assert TreasuryTransaction.objects.count() == treasury_count_before


@pytest.mark.django_db
def test_shareholder_loan_creation_rejected_via_api_when_lender_balance_insufficient(admin_client):
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")], prefix="LOANAPIREJ")

    response = admin_client.post(
        "/api/shareholder-loans/",
        {
            "borrower": borrower.id,
            "lender": lender.id,
            "amount": "20000.00",
            "date": "2026-08-01",
        },
    )

    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_get_available_balance_loan_given_increases_loan_received_decreases():
    """Pins the sign convention explicitly requested during design review:
    lending money out is a receivable (increases available_balance),
    receiving an advance is a liability (decreases it) - easy to get
    backwards, so this regression test locks it in."""
    a, b = _make_shareholders([Decimal("50"), Decimal("50")], prefix="SIGN")
    actor = _make_admin_user("SIGN")
    _seed_distributable()
    _sign_distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(_sign_distribution.id, actor)
    # a's own profit share is 50000. a lends 10000 to b (a is lender) and
    # separately receives a 5000 advance from b (a is borrower on this one).
    ShareholderLoan.objects.create(
        borrower=b, lender=a, amount=Decimal("10000.00"), date="2026-08-01"
    )
    ShareholderLoan.objects.create(
        borrower=a, lender=b, amount=Decimal("5000.00"), date="2026-08-01"
    )

    available = ShareholderLedgerService.get_available_balance(a.id)

    assert available == Decimal("55000.00")  # 50000 + 10000 (given) - 5000 (received)


@pytest.mark.django_db
def test_get_available_balance_excludes_cancelled_distribution_shares():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("AVAILCANCEL")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("100000.00")

    ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("0.00")


@pytest.mark.django_db
def test_get_available_balance_ignores_draft_distribution_shares():
    """2026-09-08 review, point 1: a DRAFT distribution is a preparatory
    proposal - its shares must credit no available balance until the
    distribution is validated."""
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("AVAILDRAFT")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("0.00")

    ShareholderDistributionService.validate_distribution(distribution.id, actor)

    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("100000.00")


@pytest.mark.django_db
def test_draft_profit_share_blocks_withdrawal_and_loan():
    """2026-09-08 review, point 1/4: no withdrawal and no loan may be
    booked on the strength of a DRAFT share."""
    shareholder, other = _make_shareholders([Decimal("100"), Decimal("0")], prefix="DRAFTBLOCK")
    actor = _make_admin_user("DRAFTBLOCK")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    share = distribution.shares.get(shareholder=shareholder)
    cash_account = CashAccount.objects.create(
        name="Draft Cash", opening_balance=Decimal("100000.00")
    )

    with pytest.raises(ShareholderWithdrawalError):
        ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=shareholder.id,
            profit_share_id=share.id,
            amount=Decimal("10000.00"),
            date="2026-08-01",
            cash_account_id=cash_account.id,
            actor=actor,
        )

    with pytest.raises(ShareholderLoanError):
        ShareholderLoanService.create_loan(
            borrower_id=other.id,
            lender_id=shareholder.id,
            amount=Decimal("10000.00"),
            date="2026-08-01",
        )

    assert not ShareholderWithdrawal.objects.filter(profit_share=share).exists()


@pytest.mark.django_db
def test_get_preview_subtracts_already_distributed_from_distributable_result():
    """Recette bug (2026-09-08): distributable_result never moved after
    creating a distribution, because it never subtracted what had already
    been committed to shareholders - the same real profit could be (and
    was) redistributed on top of itself."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("PREVIEWCOMMIT")
    _seed_distributable()

    before = ShareholderProfitPreviewService.get_preview()
    assert before["already_distributed"] == Decimal("0.00")

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    # A DRAFT proposal must not move the figure (2026-09-08 review).
    draft_preview = ShareholderProfitPreviewService.get_preview()
    assert draft_preview["already_distributed"] == Decimal("0.00")
    assert draft_preview["distributable_result"] == before["distributable_result"]

    ShareholderDistributionService.validate_distribution(distribution.id, actor)

    after = ShareholderProfitPreviewService.get_preview()
    assert after["already_distributed"] == Decimal("100000.00")
    assert after["distributable_result"] == before["distributable_result"] - Decimal("100000.00")


@pytest.mark.django_db
def test_get_preview_already_distributed_excludes_cancelled_distributions():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("PREVIEWCANCEL")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    assert ShareholderProfitPreviewService.get_preview()["already_distributed"] == Decimal(
        "100000.00"
    )

    ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["already_distributed"] == Decimal("0.00")


@pytest.mark.django_db
def test_get_preview_already_distributed_nets_out_partial_withdrawal():
    """Once part of a distribution has actually been withdrawn, that
    portion has left treasury already (working_capital reflects it) - only
    the still-unwithdrawn remainder must keep reducing distributable_result,
    or it would be subtracted twice."""
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("PREVIEWPARTIAL")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    share = distribution.shares.get(shareholder=shareholder)
    cash_account = CashAccount.objects.create(name="Partial Cash", opening_balance=Decimal("100000.00"))
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("40000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=actor,
    )

    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["already_distributed"] == Decimal("60000.00")


@pytest.mark.django_db
def test_shareholder_loan_crud_via_api(admin_client):
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")])
    # Loan creation now checks the lender's available_balance (design doc
    # 2026-08-26-benefices-associes-refinement-design.md, Fix 2) - give the
    # lender a VALIDATED distribution to draw from (2026-09-08 review: a
    # DRAFT credits no balance).
    _loanapi_actor = _make_admin_user("LOANAPI")
    _seed_distributable()
    _loanapi_distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=_loanapi_actor,
    )
    ShareholderDistributionService.validate_distribution(_loanapi_distribution.id, _loanapi_actor)

    created = admin_client.post(
        "/api/shareholder-loans/",
        {
            "borrower": borrower.id,
            "lender": lender.id,
            "amount": "20000.00",
            "date": "2026-08-01",
        },
    )
    assert created.status_code == 201, created.data
    assert created.data["status"] == "OPEN"

    updated = admin_client.post(
        f"/api/shareholder-loans/{created.data['id']}/record-repayment/", {"amount": "20000.00"}
    )
    assert updated.status_code == 200, updated.data
    assert updated.data["status"] == "REPAID"
    assert updated.data["remaining_amount"] == "0.00"


@pytest.mark.django_db
def test_shareholder_loan_amount_repaid_is_read_only_on_plain_update(admin_client):
    """Task 7 fix (reviewer: loan-repayment lost-update race) -
    amount_repaid must only ever move through
    ShareholderLoanService.record_repayment()'s atomic increment, never a
    plain PATCH of a client-computed absolute value (which is exactly the
    stale-read-then-overwrite pattern that lost updates)."""
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")])
    loan = ShareholderLoan.objects.create(
        borrower=borrower, lender=lender, amount=Decimal("20000.00"), date="2026-08-01"
    )

    response = admin_client.patch(
        f"/api/shareholder-loans/{loan.id}/", {"amount_repaid": "20000.00"}
    )

    assert response.status_code == 200, response.data
    loan.refresh_from_db()
    assert loan.amount_repaid == Decimal("0.00")
    assert loan.status == ShareholderLoan.Status.OPEN


@pytest.mark.django_db
def test_shareholder_loan_record_repayment_service_increments_from_current_db_value():
    """Closes the reviewer-reported lost-update race by reasoning through
    the locked-read-then-write (the codebase's `test_concurrency_select_for_update`
    precedent in apps/purchasing/tests.py demonstrates the same guarantee
    with real threads, but that pattern requires
    `@pytest.mark.django_db(transaction=True)`, which flushes the test DB
    on teardown and - verified empirically while writing this fix, even
    with `serialized_rollback=True` - does not reliably restore the
    Role/Product rows other data migrations seed, so it reintroduces the
    documented "--reuse-db loses seeded data" flake deterministically for
    whichever test runs next. This sequential-calls version proves the
    core guarantee instead: record_repayment() always increments off the
    value it just read from the DB **under its own select_for_update()
    lock**, never a value the caller computed - so however two calls are
    interleaved by the database's row lock, each one's increment lands on
    top of the true current total, and no update is ever silently
    dropped.
    """
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")])
    loan = ShareholderLoan.objects.create(
        borrower=borrower, lender=lender, amount=Decimal("100000.00"), date="2026-08-01"
    )

    ShareholderLoanService.record_repayment(loan.id, Decimal("40000.00"))
    loan.refresh_from_db()
    assert loan.amount_repaid == Decimal("40000.00")
    assert loan.status == ShareholderLoan.Status.PARTIALLY_REPAID

    ShareholderLoanService.record_repayment(loan.id, Decimal("60000.00"))
    loan.refresh_from_db()
    assert loan.amount_repaid == Decimal("100000.00")
    assert loan.status == ShareholderLoan.Status.REPAID


@pytest.mark.django_db
def test_shareholder_loan_record_repayment_rejects_amount_exceeding_principal():
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")])
    loan = ShareholderLoan.objects.create(
        borrower=borrower,
        lender=lender,
        amount=Decimal("100000.00"),
        amount_repaid=Decimal("80000.00"),
        date="2026-08-01",
    )

    with pytest.raises(ShareholderLoanError):
        ShareholderLoanService.record_repayment(loan.id, Decimal("30000.00"))

    loan.refresh_from_db()
    assert loan.amount_repaid == Decimal("80000.00")


@pytest.mark.django_db
def test_shareholder_loan_record_repayment_rejects_non_numeric_amount():
    """Reviewer finding (final whole-branch review, promoted from a
    deferred Task 7 Minor): record_repayment()'s `amount` arrives from the
    record-repayment action's raw request.data.get("amount") - it never
    passes through a DRF serializer field, so nothing upstream validates
    it's numeric before it reaches Decimal(str(...)) here. A bad value like
    "abc" must raise ShareholderLoanError (which the view already turns
    into a clean 400), not an uncaught decimal.InvalidOperation."""
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")], prefix="BADAMT")
    loan = ShareholderLoan.objects.create(
        borrower=borrower, lender=lender, amount=Decimal("20000.00"), date="2026-08-01"
    )

    with pytest.raises(ShareholderLoanError):
        ShareholderLoanService.record_repayment(loan.id, "abc")

    loan.refresh_from_db()
    assert loan.amount_repaid == Decimal("0.00")


@pytest.mark.django_db
def test_shareholder_loan_record_repayment_endpoint_rejects_non_numeric_amount(admin_client):
    """API-level counterpart: POSTing a non-numeric amount to
    record-repayment/ must come back as a clean 400, not a 500 - this was
    the only unhandled-500 path in the new shareholders API surface before
    ShareholderLoanService.record_repayment() started catching
    decimal.InvalidOperation and re-raising it as ShareholderLoanError."""
    borrower, lender = _make_shareholders([Decimal("50"), Decimal("50")], prefix="BADAMTAPI")
    loan = ShareholderLoan.objects.create(
        borrower=borrower, lender=lender, amount=Decimal("20000.00"), date="2026-08-01"
    )

    response = admin_client.post(
        f"/api/shareholder-loans/{loan.id}/record-repayment/", {"amount": "abc"}
    )

    assert response.status_code == 400, response.data
    loan.refresh_from_db()
    assert loan.amount_repaid == Decimal("0.00")


@pytest.mark.django_db
def test_shareholder_ledger_service_get_shareholder_summary():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("8")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    share = ShareholderProfitShare.objects.get(distribution=distribution)
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("100000.00"))
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("30000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=actor,
    )
    other = _make_shareholders([Decimal("0")], prefix="LOAN")[0]
    ShareholderLoan.objects.create(
        borrower=other, lender=shareholder, amount=Decimal("15000.00"), date="2026-08-01"
    )

    summary = ShareholderLedgerService.get_shareholder_summary(shareholder.id)

    assert summary["total_amount_due"] == Decimal("100000.00")
    assert summary["total_withdrawn"] == Decimal("30000.00")
    assert summary["remaining_due"] == Decimal("70000.00")
    assert len(summary["loans_lent"]) == 1
    assert summary["loans_lent"][0]["remaining_amount"] == Decimal("15000.00")
    # available_balance = remaining_due (70000) + net_loan_balance (15000
    # lent out, nothing borrowed) - a loan given increases it.
    assert summary["available_balance"] == Decimal("85000.00")


@pytest.mark.django_db
def test_shareholder_ledger_endpoint_via_api(admin_client):
    shareholder = _make_shareholders([Decimal("100")])[0]

    response = admin_client.get(f"/api/shareholders/{shareholder.id}/ledger/")

    assert response.status_code == 200, response.data
    assert response.data["shareholder"]["id"] == shareholder.id
    assert "remaining_due" in response.data
    assert "loans_borrowed" in response.data
    assert "loans_lent" in response.data


@pytest.mark.django_db
def test_shareholder_ledger_endpoint_money_fields_are_strings_not_floats(admin_client):
    """Reviewer finding (final whole-branch review): this is the only new
    endpoint in the plan that built its Response() from a plain dict
    instead of a ModelSerializer, so without decimals_to_str() every money
    value would ride over the wire as a DRF-JSONEncoder-coerced float
    instead of the exact Decimal string every other endpoint in this
    codebase sends (guide "never float" discipline) - matching the
    frontend ShareholderLedger TypeScript type, which declares these
    fields as `string`."""
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("9")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    share = ShareholderProfitShare.objects.get(distribution=distribution)
    cash_account = CashAccount.objects.create(
        name="Ledger Test Cash", opening_balance=Decimal("100000.00")
    )
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("30000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=actor,
    )
    other = _make_shareholders([Decimal("0")], prefix="LOANLDG")[0]
    ShareholderLoan.objects.create(
        borrower=other, lender=shareholder, amount=Decimal("15000.00"), date="2026-08-01"
    )

    response = admin_client.get(f"/api/shareholders/{shareholder.id}/ledger/")

    assert response.status_code == 200, response.data
    assert isinstance(response.data["total_amount_due"], str)
    assert isinstance(response.data["total_withdrawn"], str)
    assert isinstance(response.data["remaining_due"], str)
    assert isinstance(response.data["available_balance"], str)
    assert isinstance(response.data["net_loan_balance"], str)
    assert isinstance(response.data["shares"][0]["amount_due"], str)
    assert isinstance(response.data["shares"][0]["remaining_due"], str)
    assert isinstance(response.data["loans_lent"][0]["amount"], str)
    assert isinstance(response.data["loans_lent"][0]["remaining_amount"], str)
    assert isinstance(response.data["withdrawals"][0]["amount"], str)


# ---------------------------------------------------------------------------
# Journal de tresorerie readability (docs/edit.md UI pass 2026-08-26) -
# describe_treasury_transaction() resolves a movement's counterparty
# ("Fournisseur - Ahmed", "Douane", "Transfert Banque BOA -> Caisse
# Recette", ...) so the frontend never has to show a bare account +
# "Sortie"/"Entree" with no context.
# ---------------------------------------------------------------------------

from apps.finance.labels import describe_treasury_transaction  # noqa: E402


@pytest.mark.django_db
def test_describe_treasury_transaction_labels_a_supplier_payment():
    _admin_user, supplier, _order = _make_supplier_order("DESCRIBE-TXN-SUP")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account DESCRIBE-TXN-SUP", opening_balance="5000000.00"
    )
    payment = SupplierPayment.objects.create(
        supplier=supplier,
        amount=Decimal("1000000.00"),
        payment_date="2026-08-18",
        method=SupplierPayment.Method.BANK_TRANSFER,
        bank_account=bank_account,
        is_advance=False,
        recorded_by=_admin_user,
    )
    txn = TreasuryTransaction.objects.create(
        bank_account=bank_account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("1000000.00"),
        date="2026-08-18",
        source_content_type=ContentType.objects.get_for_model(SupplierPayment),
        source_object_id=payment.id,
        recorded_by=_admin_user,
    )

    assert describe_treasury_transaction(txn) == {"counterparty": f"Fournisseur - {supplier.name}"}


@pytest.mark.django_db
def test_describe_treasury_transaction_labels_a_customs_expense():
    admin_user = _make_admin_user("DESCRIBE-TXN-EXP")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account DESCRIBE-TXN-EXP", opening_balance="5000000.00"
    )
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("90000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )
    txn = TreasuryTransaction.objects.create(
        bank_account=bank_account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("90000.00"),
        date="2026-08-18",
        source_content_type=ContentType.objects.get_for_model(Expense),
        source_object_id=expense.id,
        recorded_by=admin_user,
    )

    assert describe_treasury_transaction(txn) == {"counterparty": "Douane"}


@pytest.mark.django_db
def test_describe_treasury_transaction_labels_a_custom_expense_category():
    from apps.finance.models import ExpenseCategory

    admin_user = _make_admin_user("DESCRIBE-TXN-CUSTOM-EXP")
    bank_account = BankAccount.objects.create(
        name="Main BOA Account DESCRIBE-TXN-CUSTOM-EXP", opening_balance="5000000.00"
    )
    ExpenseCategory.objects.create(name="Internet", code="internet")
    expense = Expense.objects.create(
        category="internet",
        amount=Decimal("90000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )
    txn = TreasuryTransaction.objects.create(
        bank_account=bank_account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("90000.00"),
        date="2026-08-18",
        source_content_type=ContentType.objects.get_for_model(Expense),
        source_object_id=expense.id,
        recorded_by=admin_user,
    )

    assert describe_treasury_transaction(txn) == {"counterparty": "Internet"}


@pytest.mark.django_db
def test_describe_treasury_transaction_labels_a_transfer_with_direction():
    admin_user = _make_admin_user("DESCRIBE-TXN-TRF")
    bank_account = BankAccount.objects.create(
        name="Banque BOA DESCRIBE-TXN-TRF", opening_balance="20000000.00"
    )
    cash_account = CashAccount.objects.create(name="Caisse Recette DESCRIBE-TXN-TRF")

    out_txn, in_txn = TreasuryService.record_transfer(
        source_account_type="bank",
        source_account_id=bank_account.id,
        dest_account_type="cash",
        dest_account_id=cash_account.id,
        amount=Decimal("10000000.00"),
        date="2026-08-18",
        reference="TRF-DESCRIBE",
        user=admin_user,
    )

    assert describe_treasury_transaction(out_txn) == {
        "counterparty": "Transfert Banque BOA DESCRIBE-TXN-TRF -> Caisse Recette DESCRIBE-TXN-TRF"
    }
    assert describe_treasury_transaction(in_txn) == {
        "counterparty": "Transfert Banque BOA DESCRIBE-TXN-TRF -> Caisse Recette DESCRIBE-TXN-TRF"
    }


@pytest.mark.django_db
def test_describe_treasury_transaction_has_no_counterparty_for_a_manual_entry():
    admin_user = _make_admin_user("DESCRIBE-TXN-MANUAL")
    cash_account = CashAccount.objects.create(name="Main Cash DESCRIBE-TXN-MANUAL")
    txn = TreasuryTransaction.objects.create(
        cash_account=cash_account,
        type=TreasuryTransaction.Type.MONEY_IN,
        amount=Decimal("50000.00"),
        date="2026-08-18",
        recorded_by=admin_user,
    )

    assert describe_treasury_transaction(txn) == {"counterparty": None}


# ---------------------------------------------------------------------------
# Phase 3: Depenses generales + categories configurables
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_expense_category_migration_seeds_system_and_custom_categories():
    from apps.finance.models import ExpenseCategory

    # "transport" is deliberately excluded here: transport cost only ever
    # flows through the transporter commission (TransportPayment), never a
    # manual trip fee, so the category is retired (see
    # test_transport_category_is_retired).
    system_codes = {"customs", "transit", "road_transit", "road", "loading"}
    seeded = {category.code: category.is_system for category in ExpenseCategory.objects.all()}
    assert system_codes <= set(seeded)
    for code in system_codes:
        assert seeded[code] is True
    assert seeded["rent"] is False
    assert seeded["other"] is False


@pytest.mark.django_db
def test_transport_category_is_retired():
    """A manual "Transport" trip fee reduced trip margin but no debt type
    could ever pay it - the money vanished with no way to settle it. The
    category is retired: not offered as a trip system fee, not offered as a
    general expense, and rejected by the expense serializer."""
    from apps.finance.models import ExpenseCategory

    transport = ExpenseCategory.objects.get(code="transport")
    assert transport.is_system is False
    assert transport.is_active is False


@pytest.mark.django_db
def test_expense_rejects_retired_transport_category(finance_client):
    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "transport",
            "amount": "100000.00",
            "calculation_method": "FIXED",
            "date": "2026-09-08",
        },
    )
    assert response.status_code == 400
    assert "category" in response.data


@pytest.mark.django_db
def test_expense_category_crud_via_api(finance_client):
    response = finance_client.post(
        "/api/expense-categories/", {"name": "Internet", "code": "internet"}
    )
    assert response.status_code == 201, response.data
    assert response.data["is_system"] is False
    assert response.data["is_active"] is True

    list_response = finance_client.get("/api/expense-categories/")
    assert list_response.status_code == 200
    codes = {row["code"] for row in list_response.data["results"]}
    assert "internet" in codes
    assert "customs" in codes


@pytest.mark.django_db
def test_expense_category_api_generates_code_from_name(finance_client):
    response = finance_client.post(
        "/api/expense-categories/", {"name": "Frais internet mensuels"}, format="json"
    )

    assert response.status_code == 201, response.data
    assert response.data["name"] == "Frais internet mensuels"
    assert response.data["code"] == "frais_internet_mensuels"


@pytest.mark.django_db
def test_expense_category_system_rows_cannot_be_deactivated_or_renamed():
    from apps.finance.models import ExpenseCategory

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+22200000ADM", pin="1234", role=admin_role)
    client = APIClient()
    client.force_authenticate(admin_user)
    customs = ExpenseCategory.objects.get(code="customs")

    response = client.patch(
        f"/api/expense-categories/{customs.id}/", {"is_active": False}, format="json"
    )
    assert response.status_code == 400
    customs.refresh_from_db()
    assert customs.is_active is True

    rename_response = client.patch(
        f"/api/expense-categories/{customs.id}/", {"name": "Renamed"}, format="json"
    )
    assert rename_response.status_code == 400


@pytest.mark.django_db
def test_expense_category_system_rows_cannot_be_hard_deleted():
    from apps.finance.models import ExpenseCategory

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+22200000ADM2", pin="1234", role=admin_role)
    client = APIClient()
    client.force_authenticate(admin_user)
    customs = ExpenseCategory.objects.get(code="customs")

    response = client.delete(f"/api/expense-categories/{customs.id}/")
    assert response.status_code in (400, 405)
    assert ExpenseCategory.objects.filter(code="customs").exists()


@pytest.mark.django_db
def test_expense_category_non_system_rows_can_be_edited_and_deleted():
    from apps.finance.models import ExpenseCategory

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+22200000ADM3", pin="1234", role=admin_role)
    client = APIClient()
    client.force_authenticate(admin_user)

    custom = ExpenseCategory.objects.create(name="Fournitures", code="fournitures")
    response = client.patch(
        f"/api/expense-categories/{custom.id}/", {"name": "Fournitures bureau"}, format="json"
    )
    assert response.status_code == 200
    delete_response = client.delete(f"/api/expense-categories/{custom.id}/")
    assert delete_response.status_code == 204


@pytest.mark.django_db
def test_expense_accepts_custom_category(finance_client):
    from apps.finance.models import ExpenseCategory

    ExpenseCategory.objects.create(name="Internet", code="internet")
    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "internet",
            "amount": "50000.00",
            "calculation_method": "MANUAL",
            "date": "2026-09-02",
        },
    )
    assert response.status_code == 201, response.data
    assert response.data["category"] == "internet"


@pytest.mark.django_db
def test_expense_custom_category_display_uses_category_name():
    from apps.finance.models import Expense, ExpenseCategory

    ExpenseCategory.objects.create(name="Internet", code="internet")
    expense = Expense.objects.create(
        category="internet",
        amount="50000.00",
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-09-02",
    )

    assert expense.get_category_display() == "Internet"
    assert str(expense).startswith("Internet:")


@pytest.mark.django_db
def test_expense_rejects_unknown_category(finance_client):
    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "not_a_real_category",
            "amount": "50000.00",
            "calculation_method": "MANUAL",
            "date": "2026-09-02",
        },
    )
    assert response.status_code == 400
    assert "category" in response.data


@pytest.mark.django_db
def test_expense_still_accepts_system_categories(finance_client):
    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "customs",
            "amount": "100000.00",
            "calculation_method": "FIXED",
            "date": "2026-09-02",
        },
    )
    assert response.status_code == 201, response.data


@pytest.mark.django_db
def test_general_expense_with_bank_account_posts_money_out(finance_client):
    bank_account = BankAccount.objects.create(
        name="Banque recette generale", opening_balance=Decimal("500000.00")
    )

    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "rent",
            "amount": "120000.00",
            "calculation_method": "MANUAL",
            "date": "2026-09-02",
            "notes": "Loyer bureau",
            "bank_account": bank_account.id,
        },
    )

    assert response.status_code == 201, response.data
    assert response.data["status"] == Expense.Status.PAID
    transaction = TreasuryTransaction.objects.get(source_object_id=response.data["id"])
    assert transaction.source_content_type == ContentType.objects.get_for_model(Expense)
    assert transaction.bank_account == bank_account
    assert transaction.cash_account is None
    assert transaction.type == TreasuryTransaction.Type.MONEY_OUT
    assert transaction.amount == Decimal("120000.00")


@pytest.mark.django_db
def test_general_expense_with_cash_account_posts_money_out(finance_client):
    cash_account = CashAccount.objects.create(
        name="Caisse recette generale", opening_balance=Decimal("500000.00")
    )

    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "salary",
            "amount": "90000.00",
            "calculation_method": "MANUAL",
            "date": "2026-09-02",
            "cash_account": cash_account.id,
        },
    )

    assert response.status_code == 201, response.data
    assert response.data["status"] == Expense.Status.PAID
    transaction = TreasuryTransaction.objects.get(source_object_id=response.data["id"])
    assert transaction.source_content_type == ContentType.objects.get_for_model(Expense)
    assert transaction.cash_account == cash_account
    assert transaction.bank_account is None
    assert transaction.type == TreasuryTransaction.Type.MONEY_OUT
    assert transaction.amount == Decimal("90000.00")


@pytest.mark.django_db
def test_expense_rejects_two_treasury_accounts(finance_client):
    bank_account = BankAccount.objects.create(name="Banque double", opening_balance=Decimal("1.00"))
    cash_account = CashAccount.objects.create(name="Caisse double", opening_balance=Decimal("1.00"))

    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "other",
            "amount": "10000.00",
            "calculation_method": "MANUAL",
            "date": "2026-09-02",
            "bank_account": bank_account.id,
            "cash_account": cash_account.id,
        },
    )

    assert response.status_code == 400
    assert "Un seul compte" in str(response.data)


@pytest.mark.django_db
def test_expense_rejects_inactive_category(finance_client):
    from apps.finance.models import ExpenseCategory

    ExpenseCategory.objects.create(name="Old", code="old_cat", is_active=False)
    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "old_cat",
            "amount": "10000.00",
            "calculation_method": "MANUAL",
            "date": "2026-09-02",
        },
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_expense_list_unallocated_filter(finance_client):
    unallocated = Expense.objects.create(
        category=Expense.Category.RENT,
        amount=Decimal("300000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-09-02",
    )
    trip, _ = _make_trip_for_deduction("UNALLOC")
    allocated = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-09-02",
    )
    ExpenseAllocation.objects.create(
        expense=allocated,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("100000.00"),
    )

    response = finance_client.get("/api/expenses/?unallocated=true")

    assert response.status_code == 200
    returned_ids = {row["id"] for row in response.data["results"]}
    assert unallocated.id in returned_ids
    assert allocated.id not in returned_ids


@pytest.mark.django_db
def test_general_expense_does_not_change_trip_cost_basis():
    from apps.trips.services import TripCostService

    trip, _ = _make_trip_for_deduction("GENCOST")
    allocated = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-09-02",
    )
    ExpenseAllocation.objects.create(
        expense=allocated,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("100000.00"),
    )
    before = TripCostService.calculate_trip_cost_basis(trip)

    Expense.objects.create(
        category=Expense.Category.RENT,
        amount=Decimal("300000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-09-02",
    )

    after = TripCostService.calculate_trip_cost_basis(trip)
    assert after["total_expenses"] == before["total_expenses"]
    assert after["total_cost"] == before["total_cost"]


@pytest.mark.django_db
def test_trip_other_debt_bucket_is_removed():
    """The "Autres frais du trajet" (trip_other) debt type is gone: every
    fee the trip-fee form can create now maps to a real, correctly-named
    bucket (Douane / Transit / Transit routiere / Frontiere / Chargement),
    so the vague catch-all - which also silently swallowed retired
    "transport" fees the payment screen could not settle - is retired for
    clarity. A general company expense is settled on the Depenses
    generales page, never a trip debt bucket."""
    assert "trip_other" not in ControlledDebtPaymentService.supported_debt_types()

    with pytest.raises(ControlledDebtPaymentError):
        ControlledDebtPaymentService.get_payable_debts("trip_other")


# ---------------------------------------------------------------------------
# Phase 5 (docs/superpowers/specs/2026-09-02-business-corrections-6-phases-
# design.md): Par litre / Par camion calculation for trip-allocated fees,
# PAID/PARTIALLY_PAID edit lock, and POST /api/expenses/{id}/cancel/.
# ---------------------------------------------------------------------------


def _admin_client(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role
    )
    client = APIClient()
    client.force_authenticate(admin_user)
    return client, admin_user


@pytest.mark.django_db
def test_payable_debt_for_per_litre_trip_fee_uses_allocated_total_not_raw_rate(finance_client):
    """Bug fix (2026-09-03 recette manuelle): Transit at 10 XOF/L on a
    trip that loaded 45 000 L must show as a 450 000 XOF payable debt
    (Depenses generales monitoring, Journal tresorerie payment form) - it
    was showing 10 XOF, the raw per-litre rate (Expense.amount), instead
    of the real allocated total."""
    trip, _ = _make_trip_for_deduction("PAYABLEPERLITRE")
    trip_content_type_id = ContentType.objects.get_for_model(Trip).id

    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "transit",
            "amount": "10.00",
            "calculation_method": "PER_LITRE",
            "date": "2026-09-02",
            "allocations": [
                {
                    "content_type": trip_content_type_id,
                    "object_id": trip.id,
                    "allocated_amount": "1.00",
                }
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    expected_total = Decimal("10.00") * trip.quantity_loaded

    rows = ControlledDebtPaymentService.get_payable_debts("transit")

    assert rows[0]["remaining_amount"] == expected_total
    assert rows[0]["lines"][0]["total_amount"] == expected_total
    assert rows[0]["lines"][0]["remaining_amount"] == expected_total


@pytest.mark.django_db
def test_payable_debt_for_per_truck_trip_fee_uses_raw_amount_unmultiplied(finance_client):
    trip, _ = _make_trip_for_deduction("PAYABLEPERTRUCK")
    trip_content_type_id = ContentType.objects.get_for_model(Trip).id

    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "transit",
            "amount": "50000.00",
            "calculation_method": "PER_TRUCK",
            "date": "2026-09-02",
            "allocations": [
                {
                    "content_type": trip_content_type_id,
                    "object_id": trip.id,
                    "allocated_amount": "1.00",
                }
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data

    rows = ControlledDebtPaymentService.get_payable_debts("transit")

    assert rows[0]["remaining_amount"] == Decimal("50000.00")


@pytest.mark.django_db
def test_payable_debt_status_transitions_to_partially_paid_for_per_litre_fee(treasury_user):
    """Bug fix (2026-09-03 recette manuelle): _sync_expense_status used to
    compare the (now allocation-aware) remaining_amount against the raw
    Expense.amount - for a PER_LITRE fee that comparison denominator was
    still the per-litre rate, so a real partial payment against the true
    total never actually flipped the status to PARTIALLY_PAID."""
    trip, _ = _make_trip_for_deduction("SYNCSTATUS")
    bank = BankAccount.objects.create(
        name="Bank Sync Status", opening_balance=Decimal("1000000.00")
    )
    expense = Expense.objects.create(
        category=Expense.Category.TRANSIT,
        amount=Decimal("10.00"),
        calculation_method=Expense.CalculationMethod.PER_LITRE,
        date="2026-09-02",
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("10.00") * trip.quantity_loaded,
    )
    total = Decimal("10.00") * trip.quantity_loaded
    half_payment = (total / 2).quantize(Decimal("0.01"))

    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.TRANSIT,
        debt_id=0,
        bank_account_id=bank.id,
        amount=half_payment,
        date="2026-09-02",
        reference="",
        actor=treasury_user,
    )

    expense.refresh_from_db()
    assert expense.status == Expense.Status.PARTIALLY_PAID


@pytest.mark.django_db
def test_general_expense_never_appears_in_trip_fee_payable_debts_by_amount(finance_client):
    """Companion to the Phase 4 fix (test_unallocated_general_expense_never_shows_as_trip_other_debt) -
    here specifically checking a general expense with an amount that could
    be mistaken for a trip-fee debt never shows up in any trip-fee bucket,
    by category (Internet has no category bucket at all) and confirming
    its own amount is untouched."""
    unallocated = Expense.objects.create(
        category="internet",
        amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-09-02",
    )

    for debt_type in ["customs", "transit", "road_transit", "border", "loading"]:
        rows = ControlledDebtPaymentService.get_payable_debts(debt_type)
        all_expense_ids = {
            line["id"] for row in rows for line in row.get("lines", [])
        }
        assert unallocated.id not in all_expense_ids

    unallocated.refresh_from_db()
    assert unallocated.amount == Decimal("100000.00")


@pytest.mark.django_db
def test_trip_fee_per_litre_total_is_rate_times_quantity_loaded(finance_client):
    trip, _ = _make_trip_for_deduction("PERLITRE")
    trip_content_type_id = ContentType.objects.get_for_model(Trip).id

    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "customs",
            "amount": "100.00",
            "calculation_method": "PER_LITRE",
            "date": "2026-09-02",
            "allocations": [
                {
                    "content_type": trip_content_type_id,
                    "object_id": trip.id,
                    "allocated_amount": "1.00",
                }
            ],
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    expense = Expense.objects.get(pk=response.data["id"])
    # "montant saisi" (amount) stays the XOF/L rate as typed - never
    # overwritten with the computed total.
    assert expense.amount == Decimal("100.00")
    allocation = expense.allocations.get(object_id=trip.id)
    assert allocation.allocated_amount == Decimal("100.00") * trip.quantity_loaded


@pytest.mark.django_db
def test_trip_fee_per_truck_total_is_unmultiplied_and_unit_cost_derived(finance_client):
    trip, _ = _make_trip_for_deduction("PERTRUCK")
    assert trip.quantity_loaded == Decimal("45000.00")
    trip_content_type_id = ContentType.objects.get_for_model(Trip).id

    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "customs",
            "amount": "10000.00",
            "calculation_method": "PER_TRUCK",
            "date": "2026-09-02",
            "allocations": [
                {
                    "content_type": trip_content_type_id,
                    "object_id": trip.id,
                    "allocated_amount": "1.00",
                }
            ],
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    expense = Expense.objects.get(pk=response.data["id"])
    allocation = expense.allocations.get(object_id=trip.id)
    # Par camion: total = montant saisi, never multiplied by quantity.
    assert allocation.allocated_amount == Decimal("10000.00")

    from apps.trips.services import TripCostService

    cost_basis = TripCostService.calculate_trip_cost_basis(trip)
    unit_cost = (allocation.allocated_amount / trip.quantity_loaded).quantize(Decimal("0.0001"))
    assert unit_cost == Decimal("0.2222")
    assert cost_basis["expenses_by_category"]["customs"] == Decimal("10000.00")


@pytest.mark.django_db
def test_trip_allocation_rejects_calculation_methods_other_than_per_litre_or_truck(
    finance_client,
):
    trip, _ = _make_trip_for_deduction("BADMETHOD")
    trip_content_type_id = ContentType.objects.get_for_model(Trip).id

    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "customs",
            "amount": "100000.00",
            "calculation_method": "FIXED",
            "date": "2026-09-02",
            "allocations": [
                {
                    "content_type": trip_content_type_id,
                    "object_id": trip.id,
                    "allocated_amount": "100000.00",
                }
            ],
        },
        format="json",
    )

    assert response.status_code == 400
    assert "Par litre" in str(response.data) or "Par camion" in str(response.data)


@pytest.mark.django_db
def test_unpaid_trip_fee_can_be_edited_freely_with_no_treasury_movement(finance_client):
    trip, _ = _make_trip_for_deduction("EDITUNPAID")
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("100.00"),
        calculation_method=Expense.CalculationMethod.PER_LITRE,
        date="2026-09-02",
        status=Expense.Status.UNPAID,
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("100.00") * trip.quantity_loaded,
    )
    treasury_count_before = TreasuryTransaction.objects.count()

    response = finance_client.patch(
        f"/api/expenses/{expense.id}/", {"amount": "150.00"}, format="json"
    )

    assert response.status_code == 200, response.data
    expense.refresh_from_db()
    assert expense.amount == Decimal("150.00")
    assert TreasuryTransaction.objects.count() == treasury_count_before


@pytest.mark.django_db
def test_unpaid_trip_fee_edit_replaces_allocation_instead_of_duplicating_it(finance_client):
    """Bug fix (2026-09-03 recette manuelle): PATCHing a new allocations
    list used to *append* a second ExpenseAllocation row instead of
    replacing the existing one, silently doubling the trip's allocated
    amount every time a fee was edited."""
    trip, _ = _make_trip_for_deduction("EDITALLOC")
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("100.00"),
        calculation_method=Expense.CalculationMethod.PER_LITRE,
        date="2026-09-02",
        status=Expense.Status.UNPAID,
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("100.00") * trip.quantity_loaded,
    )

    trip_content_type_id = ContentType.objects.get_for_model(Trip).id
    response = finance_client.patch(
        f"/api/expenses/{expense.id}/",
        {
            "amount": "150.00",
            "allocations": [
                {
                    "content_type": trip_content_type_id,
                    "object_id": trip.id,
                    "allocated_amount": "1.00",
                }
            ],
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    expense.refresh_from_db()
    assert expense.allocations.count() == 1
    allocation = expense.allocations.get()
    assert allocation.allocated_amount == Decimal("150.00") * trip.quantity_loaded


@pytest.mark.django_db
def test_unpaid_expense_can_be_hard_deleted():
    """Bug fix (2026-09-03 recette manuelle): ExpenseViewSet.destroy() used
    to unconditionally reject every DELETE (_NO_HARD_DELETE_DETAIL,
    shared with every money-touching model), even though an UNPAID expense
    has no accounting impact yet - Phase 5's own design doc says deletion
    stays allowed for UNPAID ("comportement actuel conserve"). destroy is
    gated on the "cancel" permission tier (HasModulePermission.ACTION_MAP),
    same as every other hard-delete-blocked viewset - needs an admin
    client, not the plain finance_client fixture."""
    finance_client, _admin_user = _admin_client("DELUNPAIDA")
    trip, _ = _make_trip_for_deduction("DELUNPAIDB")
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.FIXED,
        date="2026-09-02",
        status=Expense.Status.UNPAID,
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("100000.00"),
    )

    response = finance_client.delete(f"/api/expenses/{expense.id}/")

    assert response.status_code == 204
    assert not Expense.objects.filter(pk=expense.id).exists()
    assert not ExpenseAllocation.objects.filter(expense_id=expense.id).exists()

    from apps.trips.services import TripCostService

    assert TripCostService.calculate_trip_cost_basis(trip)["expenses_by_category"] == {}


@pytest.mark.django_db
def test_paid_or_partially_paid_expense_cannot_be_hard_deleted():
    finance_client, _admin_user = _admin_client("DELPAID")
    for status in (Expense.Status.PAID, Expense.Status.PARTIALLY_PAID):
        expense = Expense.objects.create(
            category=Expense.Category.RENT,
            amount=Decimal("50000.00"),
            calculation_method=Expense.CalculationMethod.MANUAL,
            date="2026-09-02",
            status=status,
        )

        response = finance_client.delete(f"/api/expenses/{expense.id}/")

        assert response.status_code == 405, (status, response.data)
        assert Expense.objects.filter(pk=expense.id).exists()


@pytest.mark.django_db
def test_paid_expense_rejects_amount_modification(finance_client):
    expense = Expense.objects.create(
        category=Expense.Category.RENT,
        amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-09-02",
        status=Expense.Status.PAID,
    )

    response = finance_client.patch(
        f"/api/expenses/{expense.id}/", {"amount": "60000.00"}, format="json"
    )

    assert response.status_code == 400
    assert "annulation" in str(response.data)
    expense.refresh_from_db()
    assert expense.amount == Decimal("50000.00")


@pytest.mark.django_db
def test_cancel_fully_paid_treasury_expense_reverses_and_clears_trip_cost():
    client, admin_user = _admin_client("CANCELPAIDA")
    trip, _ = _make_trip_for_deduction("CANCELPAIDB")
    bank_account = BankAccount.objects.create(
        name="Banque annulation", opening_balance=Decimal("1000000.00")
    )
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS,
        amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.PER_TRUCK,
        date="2026-09-02",
        status=Expense.Status.PAID,
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=Decimal("100000.00"),
    )
    TreasuryTransaction.objects.create(
        bank_account=bank_account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("100000.00"),
        date="2026-09-02",
        source_content_type=ContentType.objects.get_for_model(Expense),
        source_object_id=expense.id,
        recorded_by=admin_user,
    )

    from apps.trips.services import TripCostService

    before = TripCostService.calculate_trip_cost_basis(trip)
    assert before["expenses_by_category"]["customs"] == Decimal("100000.00")

    response = client.post(f"/api/expenses/{expense.id}/cancel/")

    assert response.status_code == 200, response.data
    expense.refresh_from_db()
    assert expense.status == Expense.Status.CANCELLED

    reversal = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(Expense),
        source_object_id=expense.id,
        type=TreasuryTransaction.Type.MONEY_IN,
    )
    assert reversal.amount == Decimal("100000.00")
    assert reversal.bank_account == bank_account

    after = TripCostService.calculate_trip_cost_basis(trip)
    assert "customs" not in after["expenses_by_category"]
    assert after["total_cost"] == before["total_cost"] - Decimal("100000.00")


@pytest.mark.django_db
def test_cancel_partially_paid_expense_reverses_only_the_amount_actually_paid():
    client, admin_user = _admin_client("CANCELPARTIAL")
    bank_account = BankAccount.objects.create(
        name="Banque partielle", opening_balance=Decimal("1000000.00")
    )
    expense = Expense.objects.create(
        category=Expense.Category.RENT,
        amount=Decimal("200000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-09-02",
        status=Expense.Status.PARTIALLY_PAID,
    )
    TreasuryTransaction.objects.create(
        bank_account=bank_account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("80000.00"),
        date="2026-09-02",
        source_content_type=ContentType.objects.get_for_model(Expense),
        source_object_id=expense.id,
        recorded_by=admin_user,
    )

    response = client.post(f"/api/expenses/{expense.id}/cancel/")

    assert response.status_code == 200, response.data
    reversal = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(Expense),
        source_object_id=expense.id,
        type=TreasuryTransaction.Type.MONEY_IN,
    )
    # Reverses the 80 000 actually paid, never the 200 000 face amount.
    assert reversal.amount == Decimal("80000.00")


@pytest.mark.django_db
def test_cancel_indirect_expense_restores_customer_receivable_with_no_treasury_row():
    client, admin_user = _admin_client("CANCELINDIRA")
    _, customer, invoice = _make_invoice_for_payment(
        "CANCELINDIRB", total_amount=Decimal("50000000.00")
    )
    treasury_count_before = TreasuryTransaction.objects.count()

    expense, payment, allocation = IndirectSettlementService.record_indirect_payment(
        customer_id=customer.id,
        expense_data={
            "category": Expense.Category.CUSTOMS,
            "amount": Decimal("5000000.00"),
            "date": "2026-08-18",
        },
        actor=admin_user,
        invoice_id=invoice.id,
    )
    assert PaymentAllocationService.get_customer_outstanding(customer) == Decimal("45000000.00")

    response = client.post(f"/api/expenses/{expense.id}/cancel/")

    assert response.status_code == 200, response.data
    expense.refresh_from_db()
    assert expense.status == Expense.Status.CANCELLED
    assert TreasuryTransaction.objects.count() == treasury_count_before
    # Never hard-deleted (AuditableModel blocks that past draft) - marked
    # reversed instead, and every balance consumer excludes it.
    payment.refresh_from_db()
    assert payment.is_reversed is True
    assert PaymentAllocationService.get_customer_outstanding(customer) == Decimal("50000000.00")
    assert PaymentAllocationService.get_invoice_outstanding(invoice) == invoice.total_amount


@pytest.mark.django_db
def test_cancel_already_cancelled_expense_is_rejected():
    client, _ = _admin_client("CANCELTWICE")
    expense = Expense.objects.create(
        category=Expense.Category.RENT,
        amount=Decimal("10000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-09-02",
        status=Expense.Status.CANCELLED,
    )

    response = client.post(f"/api/expenses/{expense.id}/cancel/")

    assert response.status_code == 400
    assert "annule" in str(response.data)


@pytest.mark.django_db
def test_cancel_unpaid_expense_is_rejected():
    client, _ = _admin_client("CANCELUNPAID")
    expense = Expense.objects.create(
        category=Expense.Category.RENT,
        amount=Decimal("10000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-09-02",
        status=Expense.Status.UNPAID,
    )

    response = client.post(f"/api/expenses/{expense.id}/cancel/")

    assert response.status_code == 400

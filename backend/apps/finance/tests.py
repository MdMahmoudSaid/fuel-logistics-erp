from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from django.contrib.contenttypes.models import ContentType

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ExpenseAllocation,
    PaymentAllocation,
    SupplierPayment,
    TransportDeduction,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import (
    FinancePostingService,
    IndirectSettlementService,
    PaymentAllocationError,
    PaymentAllocationService,
    TreasuryService,
    TreasuryTransferError,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
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


def _make_supplier_order(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone=(f"+222{suffix}")[:20],
        pin="1234",
        role=admin_role,
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-SUPPAY-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        created_by=admin_user,
    )
    return admin_user, supplier, supplier_order


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
def test_supplier_advance_via_cash_is_still_allowed_and_posts_treasury(finance_client):
    """Ruling 1: the bank-only restriction applies only to non-advance debt
    repayment. An advance (is_advance=True) may still use cash - but ruling
    2 says it's still real money leaving the company, so it must still post
    a TreasuryTransaction(MONEY_OUT)."""
    _admin_user, supplier, _order = _make_supplier_order("ADV-CASH-API")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance="2000000.00")
    treasury_count_before = TreasuryTransaction.objects.count()

    response = finance_client.post(
        "/api/supplier-payments/",
        {
            "supplier": supplier.id,
            "amount": "500000.00",
            "payment_date": "2026-08-18",
            "method": SupplierPayment.Method.CASH,
            "cash_account": cash_account.id,
            "is_advance": True,
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
    assert txn.cash_account_id == cash_account.id


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
            "allocations": [{"invoice": invoice.id, "amount": "8000000.00"}],
        },
        format="json",
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
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"), deduction_amount=Decimal("42500.00"),
        advance_applied=advance,
    )

    response = finance_client.get(f"/api/transporters/{transporter.id}/ledger/")

    assert response.status_code == 200
    assert response.data["net_outstanding"] == "557500.00"


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
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["destination"] == CustomerPayment.Destination.CASH
    assert response.data["note"] == "Paiement remis par le chauffeur"
    assert response.data["is_indirect"] is False


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
        },
        format="json",
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
        },
        format="json",
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
        },
        format="json",
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
        },
        format="json",
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

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    PaymentAllocation,
    TransportDeduction,
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
    # No TreasuryTransaction model exists until Phase 5 — current_balance is
    # opening_balance alone for now, and will sum real transactions later.
    assert account.current_balance == account.opening_balance


@pytest.mark.django_db
def test_cash_account_currency_defaults_to_xof():
    account = CashAccount.objects.create(name="Main Cash", location="Dakar office")
    assert account.currency == "XOF"


@pytest.fixture
def finance_client():
    role = Role.objects.get(name=Role.NAME_FINANCE)
    user = User.objects.create_user(email="fin@example.com", password="testpass123", role=role)
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
    user = User.objects.create_user(email="ops@example.com", password="testpass123", role=role)
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
        email=f"admin-deduction-{suffix}@example.com",
        password="testpass123",
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


def _make_invoice_for_payment(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        email=f"admin-payment-{suffix}@example.com",
        password="testpass123",
        role=admin_role,
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    transporter = Transporter.objects.create(name="Trans SA")
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
        total_amount=sale.subtotal,
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

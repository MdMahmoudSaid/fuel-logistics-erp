# "Nouvelle dette" (client request 2026-10-11): a debt from before the app on a
# customer / supplier / transporter ledger, treated like that party's ordinary
# debts - plus the customer receipt cancellation and the payment/advance PDFs
# delivered with it.

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.customers.models import Customer
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    OpeningDebt,
    SupplierAdvance,
    SupplierPayment,
    TreasuryTransaction,
)
from apps.finance.services import (
    AdvanceService,
    ControlledDebtPaymentService,
    CustomerPaymentCancellationService,
    OpeningDebtError,
    OpeningDebtService,
    PaymentAllocationService,
    SupplierLedgerService,
    TransporterLedgerService,
)
from apps.finance.tests import _make_invoice_for_payment
from apps.reports.queries.customer_statement import CustomerStatementQuery
from apps.reports.queries.general_debt_report import GeneralDebtReportQuery
from apps.reports.queries.general_receivable_report import GeneralReceivableReportQuery
from apps.reports.services.payment_pdf import build_customer_payment_document
from apps.sales.models import Invoice
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter

D = Decimal


def _admin(suffix):
    role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=(f"+223{suffix}")[:20], pin="1234", role=role)


@pytest.fixture
def client():
    role = Role.objects.get(name=Role.NAME_FINANCE)
    user = User.objects.create_user(phone="+2230009001", pin="1234", role=role)
    api = APIClient()
    api.force_authenticate(user)
    return api


def _admin_client(suffix):
    api = APIClient()
    api.force_authenticate(_admin(suffix))
    return api


def _debt(party_type, party, amount, actor, reference="ANC-1", date="2026-01-01"):
    return OpeningDebtService.create(
        party_type=party_type, party_id=party.id, amount=amount, date=date,
        reference=reference, notes="", attachment=None, actor=actor,
    )


def _receipt(client, customer, amount, *, advance=False, suffix="R"):
    cash = CashAccount.objects.create(name=f"Caisse {suffix}")
    payload = {
        "customer": customer.id, "amount": amount, "payment_date": "2026-10-11",
        "method": "CASH", "destination": "CASH", "cash_account": cash.id, "is_advance": advance,
    }
    if advance:
        payload["allocations"] = [{"invoice": None, "amount": amount}]
    response = client.post("/api/customer-payments/", payload, format="json")
    assert response.status_code == 201, response.data
    return CustomerPayment.objects.get(pk=response.data["id"]), cash


# --- customer ---------------------------------------------------------------


@pytest.mark.django_db
def test_customer_opening_debt_is_owed_and_paid_by_a_plain_receipt(client):
    customer = Customer.objects.create(name="DAHMA")
    debt = _debt("customer", customer, D("69765000.00"), _admin("C1"))

    assert PaymentAllocationService.get_customer_outstanding(customer) == D("69765000.00")

    payment, _cash = _receipt(client, customer, "60000000.00", suffix="C1")

    assert OpeningDebtService.remaining_amount(debt) == D("9765000.00")
    assert PaymentAllocationService.get_payment_unallocated_amount(payment) == D("0.00")
    assert PaymentAllocationService.get_customer_outstanding(customer) == D("9765000.00")


@pytest.mark.django_db
def test_customer_opening_debt_consumes_the_open_advance_at_creation(client):
    customer = Customer.objects.create(name="Client avance")
    _receipt(client, customer, "1000000.00", advance=True, suffix="C2")

    debt = _debt("customer", customer, D("400000.00"), _admin("C2"))

    assert OpeningDebtService.describe(debt)["status"] == "PAID"
    assert PaymentAllocationService.get_customer_available_credit(customer) == D("600000.00")
    assert PaymentAllocationService.get_customer_outstanding(customer) == D("-600000.00")


@pytest.mark.django_db
def test_receipt_pays_the_opening_debt_before_the_invoices(client):
    _admin_user, customer, invoice = _make_invoice_for_payment("ODINV", total_amount=D("1000000.00"))
    debt = _debt("customer", customer, D("500000.00"), _admin("C3"))

    _receipt(client, customer, "800000.00", suffix="C3")

    invoice.refresh_from_db()
    assert OpeningDebtService.remaining_amount(debt) == D("0.00")
    assert PaymentAllocationService.get_invoice_outstanding(invoice) == D("700000.00")
    assert invoice.status == Invoice.Status.PARTIALLY_PAID


@pytest.mark.django_db
def test_cancelling_a_customer_opening_debt_gives_the_receipt_back_as_credit(client):
    customer = Customer.objects.create(name="Client annulation")
    debt = _debt("customer", customer, D("300000.00"), _admin("C4"))
    _receipt(client, customer, "300000.00", suffix="C4")

    OpeningDebtService.cancel(debt, _admin("C4B"))

    assert PaymentAllocationService.get_customer_outstanding(customer) == D("-300000.00")
    assert PaymentAllocationService.get_customer_available_credit(customer) == D("300000.00")


@pytest.mark.django_db
def test_advance_typed_by_mistake_is_cancelled_then_recorded_as_a_debt(client):
    """The DAHMA/DAMMA case: a prior debt entered as "Nouvelle avance"."""
    customer = Customer.objects.create(name="DAMMA")
    payment, cash = _receipt(client, customer, "61527683.00", advance=True, suffix="C5")
    assert payment.is_advance
    assert cash.current_balance == D("61527683.00")

    # Cancelling needs the finance "cancel" right (admin), like supplier payments.
    assert client.post(f"/api/customer-payments/{payment.id}/cancel/").status_code == 403
    response = _admin_client("C5").post(f"/api/customer-payments/{payment.id}/cancel/")
    assert response.status_code == 200, response.data
    assert response.data["is_reversed"] is True
    assert CashAccount.objects.get(pk=cash.pk).current_balance == D("0.00")

    response = client.post(
        "/api/opening-debts/",
        {"customer": customer.id, "amount": "61527683.00", "date": "2025-12-31", "reference": "Najah"},
        format="multipart",
    )
    assert response.status_code == 201, response.data
    assert response.data["remaining_amount"] == "61527683.00"

    ledger = client.get(f"/api/customers/{customer.id}/ledger/").data
    assert ledger["outstanding_balance"] == "61527683.00"
    assert ledger["available_credit"] == "0.00"
    assert [d["reference"] for d in ledger["opening_debts"]] == ["Najah"]


@pytest.mark.django_db
def test_cancelling_a_receipt_reopens_the_invoice_it_paid(client):
    _admin_user, customer, invoice = _make_invoice_for_payment("CANREC", total_amount=D("1000000.00"))
    payment, _cash = _receipt(client, customer, "1000000.00", suffix="C6")
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID

    CustomerPaymentCancellationService.cancel_customer_payment(payment, _admin("C6"))

    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.VALIDATED
    assert PaymentAllocationService.get_customer_outstanding(customer) == D("1000000.00")
    response = _admin_client("C6B").post(f"/api/customer-payments/{payment.id}/cancel/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_opening_debt_endpoint_requires_exactly_one_party(client):
    customer = Customer.objects.create(name="Client A")
    supplier = Supplier.objects.create(name="Fournisseur A", country="Senegal")

    both = client.post(
        "/api/opening-debts/",
        {"customer": customer.id, "supplier": supplier.id, "amount": "10.00", "date": "2026-01-01"},
        format="multipart",
    )
    none = client.post("/api/opening-debts/", {"amount": "10.00", "date": "2026-01-01"}, format="multipart")

    assert both.status_code == 400
    assert none.status_code == 400
    assert not OpeningDebt.objects.exists()


@pytest.mark.django_db
def test_customer_reports_list_the_opening_debt(client):
    customer = Customer.objects.create(name="Client rapport")
    _debt("customer", customer, D("250000.00"), _admin("C8"), reference="ANC-R")

    receivable = [r for r in GeneralReceivableReportQuery.run() if r["customer"] == "Client rapport"]
    assert [(r["line_type"], r["remaining_amount"]) for r in receivable] == [
        ("opening_debt", D("250000.00")),
        ("customer_total", D("250000.00")),
    ]
    statement = CustomerStatementQuery.run(customer_id=customer.id)
    assert [(r["type"], r["debit"]) for r in statement] == [("OPENING_DEBT", D("250000.00"))]


@pytest.mark.django_db
def test_customer_payment_pdf_document_shows_the_allocation(client):
    customer = Customer.objects.create(name="Client PDF")
    _debt("customer", customer, D("100000.00"), _admin("C9"), reference="ANC-PDF")
    payment, _cash = _receipt(client, customer, "150000.00", suffix="C9")

    document, rows = build_customer_payment_document(payment, "fr")

    assert document["title"] == "Paiement client — Client PDF"
    assert [(r["target"], r["applied"]) for r in rows] == [
        ("Dette antérieure ANC-PDF", D("100000.00")),
        ("Avance disponible", D("50000.00")),
    ]
    assert document["summary"][-1]["value"] == D("50000.00")
    response = client.get(f"/api/customer-payments/{payment.id}/pdf/?lang=ar")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


# --- supplier ---------------------------------------------------------------


@pytest.mark.django_db
def test_supplier_opening_debt_is_paid_by_nouveau_paiement():
    actor = _admin("S1")
    supplier = Supplier.objects.create(name="Fournisseur ancien", country="Senegal")
    bank = BankAccount.objects.create(name="Banque S1", opening_balance=D("10000000.00"))
    debt = _debt("supplier", supplier, D("3000000.00"), actor)

    assert ControlledDebtPaymentService.describe_supplier_balance(supplier)["net_balance"] == D("-3000000.00")
    assert [row["id"] for row in ControlledDebtPaymentService.get_payable_debts("supplier")] == [supplier.id]

    ControlledDebtPaymentService.record_payment(
        debt_type="supplier", debt_id=supplier.id, bank_account_id=bank.id, amount=D("3000000.00"),
        date="2026-10-11", reference="VIR-1", actor=actor,
    )

    payment = SupplierPayment.objects.get(supplier=supplier)
    assert payment.opening_debt_id == debt.id
    assert OpeningDebtService.remaining_amount(debt) == D("0.00")
    assert bank.current_balance == D("7000000.00")
    types = [entry["type"] for entry in SupplierLedgerService.get_ledger(supplier)["entries"]]
    assert types == ["opening_debt", "payment"]
    rows = GeneralDebtReportQuery.run()
    assert not [r for r in rows if r.get("supplier") == "Fournisseur ancien"]


@pytest.mark.django_db
def test_supplier_opening_debt_consumes_the_advance_and_cancel_releases_it():
    actor = _admin("S2")
    supplier = Supplier.objects.create(name="Fournisseur avance", country="Senegal")
    bank = BankAccount.objects.create(name="Banque S2", opening_balance=D("5000000.00"))
    advance = AdvanceService.create_supplier_advance(
        supplier_id=supplier.id, bank_account_id=bank.id, cash_account_id=None, amount=D("1000000.00"),
        date="2026-10-01", reference="AV-1", notes="", attachment=None, actor=actor,
    )

    debt = _debt("supplier", supplier, D("1500000.00"), actor)

    assert SupplierAdvance.objects.get(pk=advance.pk).remaining_amount == D("0.00")
    assert OpeningDebtService.remaining_amount(debt) == D("500000.00")
    rows = [r for r in GeneralDebtReportQuery.run() if r.get("supplier") == "Fournisseur avance"]
    assert [(r["reference"], r["remaining_amount"]) for r in rows] == [("ANC-1", D("500000.00"))]

    OpeningDebtService.cancel(debt, actor)

    assert SupplierAdvance.objects.get(pk=advance.pk).remaining_amount == D("1000000.00")
    assert ControlledDebtPaymentService.describe_supplier_balance(supplier)["net_balance"] == D("1000000.00")


@pytest.mark.django_db
def test_paid_supplier_opening_debt_cannot_be_cancelled():
    actor = _admin("S3")
    supplier = Supplier.objects.create(name="Fournisseur paye", country="Senegal")
    bank = BankAccount.objects.create(name="Banque S3", opening_balance=D("5000000.00"))
    debt = _debt("supplier", supplier, D("1000000.00"), actor)
    ControlledDebtPaymentService.record_payment(
        debt_type="supplier", debt_id=supplier.id, bank_account_id=bank.id, amount=D("400000.00"),
        date="2026-10-11", reference="VIR-2", actor=actor,
    )

    with pytest.raises(OpeningDebtError):
        OpeningDebtService.cancel(debt, actor)


# --- transporter ------------------------------------------------------------


@pytest.mark.django_db
def test_transporter_opening_debt_is_paid_through_treasury(client):
    actor = _admin("T1")
    transporter = Transporter.objects.create(name="Transporteur ancien")
    bank = BankAccount.objects.create(name="Banque T1", opening_balance=D("2000000.00"))
    debt = _debt("transporter", transporter, D("800000.00"), actor)

    assert ControlledDebtPaymentService.describe_transporter_balance(transporter)["total_due"] == D("800000.00")

    ControlledDebtPaymentService.record_payment(
        debt_type="transporter", debt_id=transporter.id, bank_account_id=bank.id, amount=D("800000.00"),
        date="2026-10-11", reference="VIR-T", actor=actor,
    )

    assert OpeningDebtService.remaining_amount(debt) == D("0.00")
    assert TreasuryTransaction.objects.filter(source_object_id=debt.id, amount=D("800000.00")).exists()
    ledger = TransporterLedgerService.get_ledger(transporter)
    assert sorted(entry["type"] for entry in ledger["entries"]) == ["opening_debt", "payment"]
    assert ledger["summary"]["last_payment"]["amount"] == D("800000.00")

    data = client.get(f"/api/transporters/{transporter.id}/ledger/").data
    assert data["opening_debts"][0]["status"] == "PAID"


@pytest.mark.django_db
def test_advance_pdfs_are_generated(client):
    actor = _admin("T2")
    bank = BankAccount.objects.create(name="Banque T2", opening_balance=D("5000000.00"))
    supplier = Supplier.objects.create(name="Fournisseur PDF", country="Senegal")
    transporter = Transporter.objects.create(name="Transporteur PDF")
    supplier_advance = AdvanceService.create_supplier_advance(
        supplier_id=supplier.id, bank_account_id=bank.id, cash_account_id=None, amount=D("100000.00"),
        date="2026-10-01", reference="AV-S", notes="", attachment=None, actor=actor,
    )
    transporter_advance = AdvanceService.create_transporter_advance(
        transporter_id=transporter.id, bank_account_id=bank.id, cash_account_id=None, amount=D("50000.00"),
        date="2026-10-01", reference="AV-T", notes="", attachment=None, actor=actor,
    )
    _debt("supplier", supplier, D("40000.00"), actor)

    for url in (
        f"/api/supplier-advances/{supplier_advance.id}/pdf/?lang=fr",
        f"/api/transporter-advances/{transporter_advance.id}/pdf/?lang=en",
    ):
        response = client.get(url)
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")

    ledger = client.get(f"/api/suppliers/{supplier.id}/ledger/").data
    assert ledger["advances"][0]["remaining_amount"] == "60000.00"
    assert ledger["advances"][0]["account_name"] == "Banque T2"

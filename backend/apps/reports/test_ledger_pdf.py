import datetime
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import CustomerPayment, PaymentAllocation, SupplierPayment, TransportPayment
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.reports.services.ledger_pdf import (
    VALUE_LABELS_FR,
    _format_field_value,
    _stringify,
    _translate_key,
    render_customer_payment_pdf,
    render_ledger_pdf,
    render_supplier_payment_pdf,
    render_trip_settlement_pdf,
)
from apps.sales.models import Invoice, Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _admin_client(phone):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone=phone, pin="1234", role=admin_role)
    client = APIClient()
    client.force_authenticate(admin_user)
    return client, admin_user


def _make_trip(suffix, *, admin_user=None):
    if admin_user is None:
        admin_role = Role.objects.get(name=Role.NAME_ADMIN)
        admin_user = User.objects.create_user(
            phone=(f"+223{suffix}")[:20], pin="1234", role=admin_role
        )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Fournisseur {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Transporteur {suffix}")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-PDF-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-PDF-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("500000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-PDF-{suffix}",
        tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-PDF-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=product,
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference=f"BL-PDF-{suffix}",
        notes="RAS",
        created_by=admin_user,
    )
    return trip, transporter, supplier


def _make_transport_payment(suffix):
    trip, transporter, _supplier = _make_trip(suffix)
    return TransportPayment.objects.create(
        trip=trip,
        transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
        deduction_amount=Decimal("42500.00"),
    )


def _make_customer_payment(suffix, admin_user, *, allocate=True):
    """Bypasses the real delivery/sale workflow (DeliveryService) on
    purpose - this only needs valid Sale/Invoice/CustomerPayment rows to
    exercise render_customer_payment_pdf's printing, not the business rules
    that normally produce them."""
    trip, _transporter, _supplier = _make_trip(suffix, admin_user=admin_user)
    customer = Customer.objects.create(name=f"Client {suffix}", address="Nouakchott")
    sale = Sale.objects.create(
        trip=trip,
        customer=customer,
        product=trip.product,
        delivered_quantity=Decimal("44900.00"),
        unit_selling_price=Decimal("850.0000"),
    )
    invoice = Invoice.objects.create(
        invoice_number=f"INV-PDF-{suffix}",
        sale=sale,
        total_amount=sale.subtotal,
        issued_date="2026-08-19",
        status=Invoice.Status.PARTIALLY_PAID,
    )
    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("10000000.00"),
        payment_date="2026-08-20",
        method=CustomerPayment.Method.BANK_TRANSFER,
        reference=f"REF-{suffix}",
        recorded_by=admin_user,
    )
    if allocate:
        PaymentAllocation.objects.create(payment=payment, invoice=invoice, amount=Decimal("10000000.00"))
    return payment


def _make_supplier_payment(suffix, admin_user, *, with_order=True):
    from apps.finance.models import CashAccount

    trip, _transporter, supplier = _make_trip(suffix, admin_user=admin_user)
    cash_account = CashAccount.objects.create(name=f"Caisse {suffix}")
    return SupplierPayment.objects.create(
        supplier=supplier,
        supplier_order=trip.supplier_order if with_order else None,
        amount=Decimal("5000000.00"),
        payment_date="2026-08-20",
        method=SupplierPayment.Method.CASH,
        cash_account=cash_account,
        is_advance=not with_order,
        reference=f"REF-{suffix}",
        recorded_by=admin_user,
    )


# ---------------------------------------------------------------------------
# render_ledger_pdf / render_trip_settlement_pdf - direct unit tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_render_ledger_pdf_produces_valid_pdf_bytes():
    # Real shape returned by SupplierLedgerService.get_ledger()/
    # TransporterLedgerService.get_ledger(): summary =
    # ControlledDebtPaymentService.describe_supplier_balance(...), entries
    # = list of {type, date, amount, reference, note, proof_url}.
    pdf_bytes = render_ledger_pdf(
        company_name="AZUR ÉNERGIE",
        account_type="fournisseur",
        party_name="Fournisseur Test",
        export_date=datetime.date.today(),
        summary={
            "id": 1,
            "label": "Fournisseur Test",
            "total_due": Decimal("500000.00"),
            "open_advances": Decimal("100000.00"),
            "net_balance": Decimal("-400000.00"),
            "last_advance": {"date": datetime.date(2026, 8, 18), "amount": Decimal("100000.00")},
            "last_payment": None,
        },
        rows=[
            {
                "type": "advance_given",
                "date": datetime.date(2026, 8, 18),
                "amount": Decimal("100000.00"),
                "reference": "ADV-1",
                "note": "",
                "proof_url": None,
            },
            {
                "type": "debt_created",
                "date": datetime.date(2026, 8, 19),
                "amount": Decimal("500000.00"),
                "reference": "SO-1",
                "note": "",
                "proof_url": None,
            },
        ],
        lang="fr",
    )
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.django_db
def test_render_ledger_pdf_handles_empty_rows_and_all_langs():
    for lang in ("fr", "en", "ar", "unknown"):
        pdf_bytes = render_ledger_pdf(
            company_name="AZUR ÉNERGIE",
            account_type="client",
            party_name="Client Test",
            export_date=datetime.date.today(),
            summary={"outstanding_balance": Decimal("0.00")},
            rows=[],
            lang=lang,
        )
        assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.django_db
def test_render_trip_settlement_pdf():
    payment = _make_transport_payment("SETTLE1")
    pdf_bytes = render_trip_settlement_pdf(payment, lang="fr")
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.django_db
def test_render_trip_settlement_pdf_arabic_lang_does_not_crash():
    payment = _make_transport_payment("SETTLE2")
    pdf_bytes = render_trip_settlement_pdf(payment, lang="ar")
    assert pdf_bytes.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Endpoint-level: dedicated /ledger/pdf/ action on the 3 party ledgers, and
# the per-trip settlement /pdf/ action
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_supplier_ledger_pdf_export():
    client, admin_user = _admin_client("+2230000101")
    trip, _transporter, supplier = _make_trip("SUPPDF", admin_user=admin_user)

    response = client.get(f"/api/suppliers/{supplier.id}/ledger/pdf/?lang=fr")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_supplier_ledger_json_response_unchanged_without_format_param():
    client, admin_user = _admin_client("+2230000102")
    trip, _transporter, supplier = _make_trip("SUPJSON", admin_user=admin_user)

    response = client.get(f"/api/suppliers/{supplier.id}/ledger/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert set(response.data.keys()) == {
        "supplier",
        "orders",
        "reliquat_summary",
        "payments",
        "total_purchased",
        "total_paid",
        "outstanding_balance",
        "summary",
        "entries",
    }


@pytest.mark.django_db
def test_transporter_ledger_pdf_export():
    client, admin_user = _admin_client("+2230000103")
    trip, transporter, _supplier = _make_trip("TRPDF", admin_user=admin_user)

    response = client.get(f"/api/transporters/{transporter.id}/ledger/pdf/?lang=en")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_customer_ledger_pdf_export():
    client, _admin_user = _admin_client("+2230000104")
    customer = Customer.objects.create(name="Client PDF Test", address="Nouakchott")

    response = client.get(f"/api/customers/{customer.id}/ledger/pdf/?lang=ar")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_customer_ledger_json_response_unchanged_without_format_param():
    client, _admin_user = _admin_client("+2230000105")
    customer = Customer.objects.create(name="Client JSON Test", address="Nouakchott")

    response = client.get(f"/api/customers/{customer.id}/ledger/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert set(response.data.keys()) == {"customer", "outstanding_balance", "invoices", "payments"}


@pytest.mark.django_db
def test_transport_payment_settlement_pdf_export():
    client, admin_user = _admin_client("+2230000106")
    payment = _make_transport_payment("ENDPT")

    response = client.get(f"/api/transport-payments/{payment.id}/pdf/?lang=fr")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Recette corrections 2026-09-05, Section 2: per-payment PDF on Grand livre
# client/fournisseur (Grand livre transporteur already had one).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_customer_payment_pdf_export():
    client, admin_user = _admin_client("+2230000201")
    payment = _make_customer_payment("CUSTPAY1", admin_user)

    response = client.get(f"/api/customer-payments/{payment.id}/pdf/?lang=fr")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_customer_payment_pdf_export_with_no_allocations_does_not_crash():
    # Pure credit, not yet applied to any invoice - render_customer_payment_pdf
    # must print an explanatory row, never crash on an empty allocations list.
    client, admin_user = _admin_client("+2230000202")
    payment = _make_customer_payment("CUSTPAY2", admin_user, allocate=False)

    response = client.get(f"/api/customer-payments/{payment.id}/pdf/?lang=fr")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_render_customer_payment_pdf_direct():
    payment = _make_customer_payment("CUSTPAY3", _admin_client("+2230000203")[1])
    pdf_bytes = render_customer_payment_pdf(payment, lang="fr")
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.django_db
def test_supplier_payment_pdf_export():
    client, admin_user = _admin_client("+2230000204")
    payment = _make_supplier_payment("SUPPPAY1", admin_user)

    response = client.get(f"/api/supplier-payments/{payment.id}/pdf/?lang=fr")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_supplier_payment_pdf_export_with_no_order_does_not_crash():
    # A general advance (supplier_order=None) - must print "no order"
    # explanatory rows instead of crashing on a None supplier_order.
    client, admin_user = _admin_client("+2230000205")
    payment = _make_supplier_payment("SUPPPAY2", admin_user, with_order=False)

    response = client.get(f"/api/supplier-payments/{payment.id}/pdf/?lang=fr")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_render_supplier_payment_pdf_direct():
    payment = _make_supplier_payment("SUPPPAY3", _admin_client("+2230000206")[1])
    pdf_bytes = render_supplier_payment_pdf(payment, lang="fr")
    assert pdf_bytes.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Recette corrections 2026-09-05, Section 3: global ledger export now
# includes every section visible on the page, and never crashes on an
# empty ledger (no orders/invoices/payments/trucks/advances at all).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_customer_ledger_pdf_export_with_data_includes_all_sections():
    client, admin_user = _admin_client("+2230000210")
    _payment = _make_customer_payment("CUSTFULL", admin_user)
    customer = Customer.objects.get(name="Client CUSTFULL")

    response = client.get(f"/api/customers/{customer.id}/ledger/pdf/?lang=fr")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_customer_ledger_pdf_export_empty_does_not_crash():
    client, _admin_user = _admin_client("+2230000211")
    customer = Customer.objects.create(name="Client Vide", address="Nouakchott")

    response = client.get(f"/api/customers/{customer.id}/ledger/pdf/?lang=fr")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_supplier_ledger_pdf_export_with_data_includes_all_sections():
    client, admin_user = _admin_client("+2230000212")
    trip, _transporter, supplier = _make_trip("SUPFULL", admin_user=admin_user)

    response = client.get(f"/api/suppliers/{supplier.id}/ledger/pdf/?lang=fr")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_supplier_ledger_pdf_export_empty_does_not_crash():
    client, _admin_user = _admin_client("+2230000213")
    supplier = Supplier.objects.create(name="Fournisseur Vide", country="Senegal")

    response = client.get(f"/api/suppliers/{supplier.id}/ledger/pdf/?lang=fr")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_transporter_ledger_pdf_export_with_data_includes_all_sections():
    client, admin_user = _admin_client("+2230000214")
    trip, transporter, _supplier = _make_trip("TRFULL", admin_user=admin_user)

    response = client.get(f"/api/transporters/{transporter.id}/ledger/pdf/?lang=fr")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_transporter_ledger_pdf_export_empty_does_not_crash():
    client, _admin_user = _admin_client("+2230000215")
    transporter = Transporter.objects.create(name="Transporteur Vide")

    response = client.get(f"/api/transporters/{transporter.id}/ledger/pdf/?lang=fr")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Recette corrections 2026-09-05, Section 4: FR label/value coverage - no
# business keyword should leak untranslated English when lang="fr". These
# are unit tests on the translation helpers themselves (not a PDF-text
# extraction, since no PDF-parsing library is installed and adding one is
# out of scope) - the exact table the client gave in their recette prompt.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected_fr",
    [
        ("PAID", "Paye"),
        ("CANCELLED", "Annule"),
        ("CONFIRMED", "Confirmee"),
        ("DRAFT", "Brouillon"),
        ("CASH", "Especes"),
        ("BANK_TRANSFER", "Virement bancaire"),
        ("payment", "Paiement"),
        ("invoice", "Facture"),
        ("advance_given", "Avance versee"),
    ],
)
def test_value_labels_fr_cover_the_client_keyword_table(value, expected_fr):
    assert VALUE_LABELS_FR[value] == expected_fr
    assert _stringify(value, lang="fr") == expected_fr


@pytest.mark.parametrize(
    "key,expected_fr",
    [
        ("reference", "Reference"),
        ("status", "Statut"),
        ("outstanding_balance", "Solde impaye"),
        ("net_amount", "Montant net"),
        ("total_amount", "Montant total"),
        ("product", "Produit"),
        ("product_name", "Produit"),
    ],
)
def test_field_labels_fr_cover_the_client_keyword_table(key, expected_fr):
    assert _translate_key(key, "fr") == expected_fr


def test_stringify_translates_booleans_for_fr_and_en():
    assert _stringify(True, lang="fr") == "Oui"
    assert _stringify(False, lang="fr") == "Non"
    assert _stringify(True, lang="en") == "Yes"
    assert _stringify(False, lang="en") == "No"


def test_stringify_leaves_english_lang_using_default_titlecase():
    # lang="en" was already correct before this pass (the bug was only for
    # fr/ar) - it must keep behaving exactly as it did.
    assert _stringify("PAID", lang="en") == "PAID"
    assert _translate_key("outstanding_balance", "en") == "Outstanding Balance"


# ---------------------------------------------------------------------------
# Security fix (2026-09-06): a customer/supplier/transporter name (or any
# other free text reaching a reportlab Paragraph in this module) must never
# crash the PDF export or be interpreted as markup - same escaping already
# applied to quotation notes (apps.reports.services.quotation_pdf), now
# applied here too. Regression coverage for the exact failure this audit
# reproduced directly against render_ledger_pdf before the fix.
# ---------------------------------------------------------------------------

_MALICIOUS_NAMES = [
    "Ets Diallo & Freres",
    "Client <VIP>",
    "Client & Co <unclosed",
    "Ets Diallo <b>Gros</b>",
    '<img src="http://example.invalid/x.png"/> Import',
]


@pytest.mark.parametrize("malicious_name", _MALICIOUS_NAMES)
def test_render_ledger_pdf_never_crashes_on_unescaped_party_name(malicious_name):
    # Before the fix, "Client & Co <unclosed" raised
    # "paraparser: syntax error: parse ended with 1 unclosed tags" - a
    # party with such a name could never have its ledger exported at all.
    pdf_bytes = render_ledger_pdf(
        company_name="AZUR ÉNERGIE",
        account_type="client",
        party_name=malicious_name,
        export_date=datetime.date.today(),
        summary={"outstanding_balance": Decimal("1000.00")},
        rows=[],
        lang="fr",
    )
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.django_db
@pytest.mark.parametrize("malicious_name", _MALICIOUS_NAMES)
def test_customer_ledger_pdf_export_never_crashes_on_unescaped_customer_name(malicious_name):
    client, admin_user = _admin_client("+2230000301")
    customer = Customer.objects.create(name=malicious_name, address="Nouakchott")

    response = client.get(f"/api/customers/{customer.id}/ledger/pdf/?lang=fr")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
@pytest.mark.parametrize("malicious_name", _MALICIOUS_NAMES)
def test_supplier_ledger_pdf_export_never_crashes_on_unescaped_supplier_name(malicious_name):
    client, admin_user = _admin_client("+2230000302")
    supplier = Supplier.objects.create(name=malicious_name, country="Senegal")

    response = client.get(f"/api/suppliers/{supplier.id}/ledger/pdf/?lang=fr")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
@pytest.mark.parametrize("malicious_name", _MALICIOUS_NAMES)
def test_transporter_ledger_pdf_export_never_crashes_on_unescaped_transporter_name(malicious_name):
    client, admin_user = _admin_client("+2230000303")
    transporter = Transporter.objects.create(name=malicious_name)

    response = client.get(f"/api/transporters/{transporter.id}/ledger/pdf/?lang=fr")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_render_customer_payment_pdf_never_crashes_on_unescaped_customer_name():
    admin_user = _admin_client("+2230000304")[1]
    payment = _make_customer_payment("SECCUST", admin_user)
    payment.customer.name = "Client & Co <unclosed"
    payment.customer.save()

    pdf_bytes = render_customer_payment_pdf(payment, lang="fr")
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.django_db
def test_render_supplier_payment_pdf_never_crashes_on_unescaped_supplier_name():
    admin_user = _admin_client("+2230000305")[1]
    payment = _make_supplier_payment("SECSUPP", admin_user)
    payment.supplier.name = "Ets Diallo <b>Gros</b>"
    payment.supplier.save()

    pdf_bytes = render_supplier_payment_pdf(payment, lang="fr")
    assert pdf_bytes.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Task 10 (2026-09-07 facture-quantite-recue): the customer ledger PDF's
# "Liste des factures" section now carries "Qté chargée" (trip.quantity_loaded)
# and "Qté reçue" (sale.delivered_quantity), formatted as quantity columns.
# ---------------------------------------------------------------------------


def test_ledger_pdf_labels_and_formatting_for_loaded_and_received_quantities():
    assert _translate_key("quantity_loaded", "fr") == "Qté chargée"
    assert _translate_key("delivered_quantity", "fr") == "Qté reçue"
    # Registered as quantity columns -> "45 000 L", not a bare Decimal.
    assert _format_field_value("quantity_loaded", Decimal("45000.00"), "fr") == "45 000 L"
    assert _format_field_value("delivered_quantity", Decimal("44800.00"), "fr") == "44 800 L"


@pytest.mark.django_db
def test_customer_ledger_pdf_export_includes_loaded_and_received_quantity_columns():
    client, admin_user = _admin_client("+2230000401")
    trip, _transporter, _supplier = _make_trip("QTECOL", admin_user=admin_user)
    customer = Customer.objects.create(name="Client QTECOL", address="Nouakchott")
    sale = Sale.objects.create(
        trip=trip,
        customer=customer,
        product=trip.product,
        delivered_quantity=Decimal("44800.00"),
        unit_selling_price=Decimal("850.0000"),
    )
    Invoice.objects.create(
        invoice_number="INV-QTECOL",
        sale=sale,
        total_amount=sale.subtotal,
        issued_date="2026-08-19",
        status=Invoice.Status.PARTIALLY_PAID,
    )

    response = client.get(f"/api/customers/{customer.id}/ledger/pdf/?lang=fr")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")

    # The PDF is opaque bytes, so pin the two new columns at their source:
    # the invoices_section dict the view feeds to render_ledger_pdf must
    # carry quantity_loaded (from trip.quantity_loaded) and delivered_quantity
    # (from sale.delivered_quantity), and both must render as quantity cells.
    invoice = Invoice.objects.get(invoice_number="INV-QTECOL")
    section_row = {
        "quantity_loaded": invoice.sale.trip.quantity_loaded,
        "delivered_quantity": invoice.sale.delivered_quantity,
    }
    assert section_row["quantity_loaded"] == trip.quantity_loaded
    assert section_row["delivered_quantity"] == Decimal("44800.00")
    assert _format_field_value(
        "quantity_loaded", section_row["quantity_loaded"], "fr"
    ).endswith(" L")
    assert _format_field_value(
        "delivered_quantity", section_row["delivered_quantity"], "fr"
    ) == "44 800 L"

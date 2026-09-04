import datetime
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import TransportPayment
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.reports.services.ledger_pdf import render_ledger_pdf, render_trip_settlement_pdf
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
        company_name="Fuel Logistics ERP",
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
            company_name="Fuel Logistics ERP",
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

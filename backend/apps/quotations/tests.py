from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import CustomerPayment, TreasuryTransaction
from apps.sales.models import Invoice, Sale

from .models import Quotation, QuotationLine


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role)


def _sales_client(suffix):
    admin_user = _make_admin(suffix)
    client = APIClient()
    client.force_authenticate(admin_user)
    return client, admin_user


@pytest.mark.django_db
def test_create_quotation_with_lines_computes_total_and_generates_reference():
    client, _user = _sales_client("QCREATE")
    customer = Customer.objects.create(name="Client QCREATE")
    product = Product.objects.get(code="gasoil")

    response = client.post(
        "/api/quotations/",
        {
            "customer": customer.id,
            "issue_date": "2026-09-05",
            "validity_date": "2026-10-05",
            "notes": "Conditions de test",
            "lines": [
                {
                    "product": product.id,
                    "description": "",
                    "quantity": "1000.00",
                    "unit": "L",
                    "unit_price": "650.0000",
                },
                {
                    "product": None,
                    "description": "Frais de livraison",
                    "quantity": "1.00",
                    "unit": "forfait",
                    "unit_price": "50000.0000",
                },
            ],
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["reference"].startswith("DEV-")
    assert response.data["status"] == "DRAFT"
    # 1000 * 650 + 1 * 50000 = 650000 + 50000 = 700000
    assert response.data["total_amount"] == "700000.00"
    assert len(response.data["lines"]) == 2


@pytest.mark.django_db
def test_quotation_requires_customer_or_customer_name():
    client, _user = _sales_client("QNOCUST")
    product = Product.objects.get(code="gasoil")

    response = client.post(
        "/api/quotations/",
        {
            "issue_date": "2026-09-05",
            "lines": [
                {"product": product.id, "quantity": "10.00", "unit": "L", "unit_price": "650.0000"}
            ],
        },
        format="json",
    )

    assert response.status_code == 400
    assert "customer_name" in response.data


@pytest.mark.django_db
def test_quotation_accepts_free_temporary_customer_name_without_existing_customer():
    client, _user = _sales_client("QFREENAME")
    product = Product.objects.get(code="gasoil")

    response = client.post(
        "/api/quotations/",
        {
            "customer_name": "Prospect ABC",
            "issue_date": "2026-09-05",
            "lines": [
                {"product": product.id, "quantity": "10.00", "unit": "L", "unit_price": "650.0000"}
            ],
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["customer"] is None
    assert response.data["customer_name"] == "Prospect ABC"


@pytest.mark.django_db
def test_quotation_line_requires_product_or_description():
    client, _user = _sales_client("QLINEEMPTY")

    response = client.post(
        "/api/quotations/",
        {
            "customer_name": "Prospect",
            "issue_date": "2026-09-05",
            "lines": [{"quantity": "10.00", "unit": "L", "unit_price": "650.0000"}],
        },
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_updating_quotation_lines_recomputes_total():
    client, user = _sales_client("QUPDATE")
    customer = Customer.objects.create(name="Client QUPDATE")
    product = Product.objects.get(code="gasoil")
    quotation = Quotation.objects.create(
        reference="DEV-202609-9001",
        customer=customer,
        issue_date="2026-09-05",
        created_by=user,
    )
    QuotationLine.objects.create(
        quotation=quotation, product=product, quantity=Decimal("10.00"),
        unit="L", unit_price=Decimal("100.0000"),
    )
    quotation.total_amount = Decimal("1000.00")
    quotation.save(update_fields=["total_amount"])

    response = client.patch(
        f"/api/quotations/{quotation.id}/",
        {
            "lines": [
                {
                    "product": product.id,
                    "quantity": "5.00",
                    "unit": "L",
                    "unit_price": "200.0000",
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["total_amount"] == "1000.00"
    assert len(response.data["lines"]) == 1


@pytest.mark.django_db
def test_quotation_status_is_freely_settable():
    client, user = _sales_client("QSTATUS")
    quotation = Quotation.objects.create(
        reference="DEV-202609-9002",
        customer_name="Prospect",
        issue_date="2026-09-05",
        created_by=user,
    )

    for status in ("SENT", "ACCEPTED", "REJECTED", "EXPIRED", "DRAFT"):
        response = client.patch(f"/api/quotations/{quotation.id}/", {"status": status}, format="json")
        assert response.status_code == 200, response.data
        assert response.data["status"] == status


@pytest.mark.django_db
def test_duplicate_quotation_copies_lines_and_resets_status_and_reference():
    client, user = _sales_client("QDUP")
    customer = Customer.objects.create(name="Client QDUP")
    product = Product.objects.get(code="gasoil")
    original = Quotation.objects.create(
        reference="DEV-202609-9003",
        customer=customer,
        status=Quotation.Status.ACCEPTED,
        issue_date="2026-09-05",
        notes="Conditions originales",
        created_by=user,
    )
    QuotationLine.objects.create(
        quotation=original, product=product, quantity=Decimal("10.00"),
        unit="L", unit_price=Decimal("100.0000"),
    )
    original.total_amount = Decimal("1000.00")
    original.save(update_fields=["total_amount"])

    response = client.post(f"/api/quotations/{original.id}/duplicate/")

    assert response.status_code == 201, response.data
    assert response.data["reference"] != original.reference
    assert response.data["status"] == "DRAFT"
    assert response.data["total_amount"] == "1000.00"
    assert response.data["notes"] == "Conditions originales"
    assert len(response.data["lines"]) == 1
    assert Quotation.objects.count() == 2


@pytest.mark.django_db
def test_quotation_pdf_export():
    client, user = _sales_client("QPDF")
    customer = Customer.objects.create(name="Client QPDF")
    product = Product.objects.get(code="gasoil")
    quotation = Quotation.objects.create(
        reference="DEV-202609-9004",
        customer=customer,
        issue_date="2026-09-05",
        validity_date="2026-10-05",
        created_by=user,
    )
    QuotationLine.objects.create(
        quotation=quotation, product=product, quantity=Decimal("10.00"),
        unit="L", unit_price=Decimal("100.0000"),
    )

    response = client.get(f"/api/quotations/{quotation.id}/pdf/?lang=fr")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_quotation_creation_has_no_accounting_side_effects():
    """Product decision 2026-09-05: a quotation must never create a Sale,
    Invoice, CustomerPayment or TreasuryTransaction - it is a standalone
    document, not a step in the delivery/accounting pipeline."""
    client, _user = _sales_client("QNOSIDE")
    customer = Customer.objects.create(name="Client QNOSIDE")
    product = Product.objects.get(code="gasoil")

    sale_count_before = Sale.objects.count()
    invoice_count_before = Invoice.objects.count()
    payment_count_before = CustomerPayment.objects.count()
    txn_count_before = TreasuryTransaction.objects.count()

    response = client.post(
        "/api/quotations/",
        {
            "customer": customer.id,
            "issue_date": "2026-09-05",
            "lines": [
                {"product": product.id, "quantity": "1000.00", "unit": "L", "unit_price": "650.0000"}
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data

    client.post(f"/api/quotations/{response.data['id']}/duplicate/")
    client.patch(f"/api/quotations/{response.data['id']}/", {"status": "ACCEPTED"}, format="json")

    assert Sale.objects.count() == sale_count_before
    assert Invoice.objects.count() == invoice_count_before
    assert CustomerPayment.objects.count() == payment_count_before
    assert TreasuryTransaction.objects.count() == txn_count_before


@pytest.mark.django_db
def test_non_sales_role_cannot_access_quotations():
    role = Role.objects.create(name="NoSales", permissions={"reports": ["view"]})
    user = User.objects.create_user(phone="+2220000099", pin="1234", role=role)
    client = APIClient()
    client.force_authenticate(user)

    response = client.get("/api/quotations/")

    assert response.status_code == 403

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.suppliers.models import Supplier


def _make_cession_letter(admin_user):
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    order = SupplierOrder.objects.create(
        reference="SO-DOC-001",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    return CessionLetter.objects.create(
        reference="CL-DOC-001",
        supplier_order=order,
        authorized_quantity=Decimal("30000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )


@pytest.mark.django_db
def test_document_upload_rejects_non_image_file():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000030", pin="1234", role=admin_role)
    cession = _make_cession_letter(admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)

    pdf_file = SimpleUploadedFile("cession.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
    response = client.post(
        "/api/documents/",
        {
            "file": pdf_file,
            "document_type": "cession_proof",
            "content_type_name": "cessionletter",
            "object_id": cession.id,
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert response.data["file"][0] == "Seules les images JPG, JPEG, PNG ou WEBP sont autorisées."


@pytest.mark.django_db
def test_document_upload_accepts_image_file():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000031", pin="1234", role=admin_role)
    cession = _make_cession_letter(admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)

    image_file = SimpleUploadedFile("cession.jpg", b"fake-jpeg-bytes", content_type="image/jpeg")
    response = client.post(
        "/api/documents/",
        {
            "file": image_file,
            "document_type": "cession_proof",
            "content_type_name": "cessionletter",
            "object_id": cession.id,
        },
        format="multipart",
    )

    assert response.status_code == 201
    assert response.data["document_type"] == "cession_proof"

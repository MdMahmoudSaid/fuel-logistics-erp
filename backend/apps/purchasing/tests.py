import threading
import time
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.documents.models import Document
from apps.finance.models import BankAccount, SupplierPayment, TreasuryTransaction
from apps.suppliers.models import Supplier
from apps.purchasing.models import SupplierOrder, CessionLetter
from apps.purchasing.serializers import CessionLetterSerializer
from apps.purchasing.services import SupplierStockService


@pytest.mark.django_db
def test_supplier_order_total_amount_calculation():
    # Setup
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000002", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")

    order = SupplierOrder.objects.create(
        reference="SO-001",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("600.5000"),
        optional_costs=Decimal("5000.00"),
        created_by=admin_user,
    )

    # 100000 * 600.50 + 5000 = 60050000 + 5000 = 60055000.00
    assert order.total_amount == Decimal("60055000.00")


@pytest.mark.django_db
def test_cession_letter_validation_limits():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000002", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="essence")
    supplier = Supplier.objects.create(name="Shell", country="Mali")

    order = SupplierOrder.objects.create(
        reference="SO-002",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("650.0000"),
        created_by=admin_user,
    )

    # Création d'une première cession de 60,000 L (reliquat restant: 40,000 L)
    CessionLetter.objects.create(
        reference="CL-001",
        supplier_order=order,
        authorized_quantity=Decimal("60000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )

    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("40000.00")

    # Essai de création d'une cession de 50,000 L via le sérialiseur (doit échouer)
    serializer = CessionLetterSerializer(
        data={
            "reference": "CL-002",
            "supplier_order": order.id,
            "authorized_quantity": Decimal("50000.00"),
            "issue_date": "2026-08-18",
        }
    )
    assert not serializer.is_valid()
    assert "authorized_quantity" in serializer.errors

    # Essai de création d'une cession de 40,000 L via le sérialiseur (doit réussir)
    serializer_ok = CessionLetterSerializer(
        data={
            "reference": "CL-002",
            "supplier_order": order.id,
            "authorized_quantity": Decimal("40000.00"),
            "issue_date": "2026-08-18",
        }
    )
    assert serializer_ok.is_valid()


@pytest.mark.django_db
def test_cession_cancellation_releases_reliquat():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000002", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")

    order = SupplierOrder.objects.create(
        reference="SO-003",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )

    cession = CessionLetter.objects.create(
        reference="CL-003",
        supplier_order=order,
        authorized_quantity=Decimal("60000.00"),
        issue_date="2026-08-18",
        status=CessionLetter.Status.ACTIVE,
        created_by=admin_user,
    )

    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("40000.00")

    # Annulation de la cession
    cession.status = CessionLetter.Status.CANCELLED
    cession.save()

    # Le reliquat doit être restauré à 100,000 L
    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("100000.00")


@pytest.mark.django_db
def test_supplier_permissions():
    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)
    ops_user = User.objects.create_user(
        phone="+2220000001", pin="1234", role=ops_role
    )
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000002", pin="1234", role=admin_role
    )

    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")

    client = APIClient()

    # Ops ne peut pas créer de commande d'achat
    client.force_authenticate(ops_user)
    response_ops = client.post(
        "/api/supplier-orders/",
        {
            "reference": "SO-OPS-001",
            "supplier": supplier.id,
            "product": product.id,
            "purchase_date": "2026-08-18",
            "quantity_litres": "50000.00",
            "unit_price": "600.0000",
        },
    )
    assert response_ops.status_code == 403

    # Admin le peut
    client.force_authenticate(admin_user)
    response_admin = client.post(
        "/api/supplier-orders/",
        {
            "reference": "SO-ADMIN-001",
            "supplier": supplier.id,
            "product": product.id,
            "purchase_date": "2026-08-18",
            "quantity_litres": "50000.00",
            "unit_price": "600.0000",
        },
    )
    assert response_admin.status_code == 201


@pytest.mark.django_db
def test_supplier_ledger_endpoint():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000002", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")

    order = SupplierOrder.objects.create(
        reference="SO-LEDGER-001",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )

    CessionLetter.objects.create(
        reference="CL-LEDGER-001",
        supplier_order=order,
        authorized_quantity=Decimal("30000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )

    client = APIClient()
    client.force_authenticate(admin_user)

    response = client.get(f"/api/suppliers/{supplier.id}/ledger/")
    assert response.status_code == 200
    assert "orders" in response.data
    assert len(response.data["orders"]) == 1
    assert response.data["orders"][0]["reliquat"] == "70000.00"
    assert response.data["reliquat_summary"][0]["total_reliquat"] == "70000.00"


@pytest.mark.django_db
def test_supplier_ledger_payments_include_proof_url_for_internal_preview():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000022", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    order = SupplierOrder.objects.create(
        reference="SO-LEDGER-PROOF",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    bank_account = BankAccount.objects.create(name="BIM", opening_balance=Decimal("1000000.00"))
    with_proof = SupplierPayment.objects.create(
        supplier=supplier,
        supplier_order=order,
        amount=Decimal("100000.00"),
        payment_date="2026-08-18",
        method=SupplierPayment.Method.BANK_TRANSFER,
        bank_account=bank_account,
        recorded_by=admin_user,
        reference="PAY-WITH-PROOF",
    )
    SupplierPayment.objects.create(
        supplier=supplier,
        supplier_order=order,
        amount=Decimal("50000.00"),
        payment_date="2026-08-19",
        method=SupplierPayment.Method.BANK_TRANSFER,
        bank_account=bank_account,
        recorded_by=admin_user,
        reference="PAY-NO-PROOF",
    )
    txn = TreasuryTransaction.objects.create(
        bank_account=bank_account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=with_proof.amount,
        date=with_proof.payment_date,
        source_content_type=ContentType.objects.get_for_model(SupplierPayment),
        source_object_id=with_proof.id,
        recorded_by=admin_user,
    )
    document = Document.objects.create(
        file=SimpleUploadedFile("supplier-payment.png", b"fake png", content_type="image/png"),
        document_type="treasury_payment_proof",
        uploaded_by=admin_user,
        content_type=ContentType.objects.get_for_model(TreasuryTransaction),
        object_id=txn.id,
    )
    txn.document = document
    txn.save(update_fields=["document"])

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get(f"/api/suppliers/{supplier.id}/ledger/")

    assert response.status_code == 200, response.data
    payments_by_reference = {payment["reference"]: payment for payment in response.data["payments"]}
    assert payments_by_reference["PAY-WITH-PROOF"]["proof_url"].startswith("/media/")
    assert payments_by_reference["PAY-NO-PROOF"]["proof_url"] is None


@pytest.mark.django_db(transaction=True)
def test_concurrency_select_for_update():
    # Ce test requiert transaction=True pour pouvoir simuler le blocage concurrentiel en BDD.
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000015", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")

    order = SupplierOrder.objects.create(
        reference="SO-CONC-001",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("600.0000"),
        created_by=admin_user,
    )

    results = []
    barrier = threading.Barrier(2)

    def worker_post_cession(ref, qty):
        client = APIClient()
        client.force_authenticate(admin_user)
        # Attente que les deux threads soient prêts
        barrier.wait()
        try:
            response = client.post(
                "/api/cession-letters/",
                {
                    "reference": ref,
                    "supplier_order": order.id,
                    "authorized_quantity": str(qty),
                    "issue_date": "2026-08-18",
                },
            )
            results.append(response.status_code)
        except Exception as e:
            results.append(str(e))

    # Lancement de 2 requêtes concurrentes de cession de 60 000 L chacune.
    # Puisque la commande fait 100 000 L, une des deux doit impérativement échouer.
    t1 = threading.Thread(
        target=worker_post_cession, args=("CL-CONC-001", Decimal("60000.00"))
    )
    t2 = threading.Thread(
        target=worker_post_cession, args=("CL-CONC-002", Decimal("60000.00"))
    )

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Une des requêtes doit avoir réussi (201 Created) et l'autre échoué (400 Bad Request)
    assert 201 in results
    assert 400 in results


@pytest.mark.django_db
def test_supplier_order_reference_is_server_generated():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000040", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.post(
        "/api/supplier-orders/",
        {
            "reference": "CLIENT-SUPPLIED-IGNORED",
            "supplier": supplier.id,
            "product": product.id,
            "purchase_date": "2026-08-18",
            "quantity_litres": "50000.00",
            "unit_price": "600.0000",
        },
    )
    assert response.status_code == 201
    assert response.data["reference"] != "CLIENT-SUPPLIED-IGNORED"
    assert response.data["reference"].startswith("ACH-")


@pytest.mark.django_db
def test_supplier_order_next_reference_endpoint():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000041", pin="1234", role=admin_role
    )
    client = APIClient()
    client.force_authenticate(admin_user)

    response = client.get("/api/supplier-orders/next-reference/")
    assert response.status_code == 200
    assert response.data["reference"].startswith("ACH-")

    # Non-reserving: calling it again without creating anything returns the
    # same preview value.
    response_again = client.get("/api/supplier-orders/next-reference/")
    assert response_again.data["reference"] == response.data["reference"]


@pytest.mark.django_db
def test_cession_letter_reference_is_server_generated():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000042", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    order = SupplierOrder.objects.create(
        reference="SO-CES-GEN-001",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("600.00"),
        created_by=admin_user,
    )

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.post(
        "/api/cession-letters/",
        {
            "reference": "CLIENT-SUPPLIED-IGNORED",
            "supplier_order": order.id,
            "authorized_quantity": "1000.00",
            "issue_date": "2026-08-18",
        },
    )
    assert response.status_code == 201
    assert response.data["reference"] != "CLIENT-SUPPLIED-IGNORED"
    assert response.data["reference"].startswith("CES-")


@pytest.mark.django_db
def test_cession_letter_next_reference_endpoint():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000043", pin="1234", role=admin_role
    )
    client = APIClient()
    client.force_authenticate(admin_user)

    response = client.get("/api/cession-letters/next-reference/")
    assert response.status_code == 200
    assert response.data["reference"].startswith("CES-")


# ---------------------------------------------------------------------------
# docs/superpowers/plans/2026-09-01-supplier-transporter-advances.md, final
# review: financial fields must be frozen once a SupplierOrder is CONFIRMED,
# so an edit can never silently desync total_amount from what an
# AdvanceConsumption has already consumed against it. The only way to
# change the amount is the explicit cancellation workflow (PATCH
# status=CANCELLED, which reverses any advance consumption), not an
# in-place edit of a confirmed order's quantity/price/costs.
# ---------------------------------------------------------------------------


def _confirmed_order(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    order = SupplierOrder.objects.create(
        reference=f"SO-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("600.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    client = APIClient()
    client.force_authenticate(admin_user)
    return client, order


@pytest.mark.django_db
def test_confirmed_order_rejects_quantity_change():
    client, order = _confirmed_order("LOCK-QTY")
    response = client.patch(f"/api/supplier-orders/{order.id}/", {"quantity_litres": "2000.00"})
    assert response.status_code == 400
    assert "quantity_litres" in response.data
    order.refresh_from_db()
    assert order.quantity_litres == Decimal("1000.00")


@pytest.mark.django_db
def test_confirmed_order_rejects_unit_price_change():
    client, order = _confirmed_order("LOCK-PRICE")
    response = client.patch(f"/api/supplier-orders/{order.id}/", {"unit_price": "700.0000"})
    assert response.status_code == 400
    assert "unit_price" in response.data
    order.refresh_from_db()
    assert order.unit_price == Decimal("600.0000")


@pytest.mark.django_db
def test_confirmed_order_rejects_optional_costs_change():
    client, order = _confirmed_order("LOCK-COSTS")
    response = client.patch(f"/api/supplier-orders/{order.id}/", {"optional_costs": "10000.00"})
    assert response.status_code == 400
    assert "optional_costs" in response.data


@pytest.mark.django_db
def test_confirmed_order_setting_the_same_value_is_not_rejected():
    client, order = _confirmed_order("LOCK-SAME")
    response = client.patch(f"/api/supplier-orders/{order.id}/", {"quantity_litres": "1000.00"})
    assert response.status_code == 200


@pytest.mark.django_db
def test_confirmed_order_can_still_be_cancelled_without_touching_financial_fields():
    client, order = _confirmed_order("LOCK-CANCEL")
    response = client.patch(f"/api/supplier-orders/{order.id}/", {"status": "CANCELLED"})
    assert response.status_code == 200, response.data
    order.refresh_from_db()
    assert order.status == SupplierOrder.Status.CANCELLED


@pytest.mark.django_db
def test_confirmed_order_still_allows_editing_non_financial_fields():
    client, order = _confirmed_order("LOCK-NOTES")
    response = client.patch(f"/api/supplier-orders/{order.id}/", {"notes": "Updated note"})
    assert response.status_code == 200, response.data
    order.refresh_from_db()
    assert order.notes == "Updated note"


@pytest.mark.django_db
def test_draft_order_still_allows_financial_field_edits():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000099", pin="1234", role=admin_role)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Draft Lock Supplier", country="Senegal")
    order = SupplierOrder.objects.create(
        reference="SO-LOCK-DRAFT", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.DRAFT,
        created_by=admin_user,
    )
    client = APIClient()
    client.force_authenticate(admin_user)

    response = client.patch(f"/api/supplier-orders/{order.id}/", {"quantity_litres": "2000.00"})
    assert response.status_code == 200, response.data

import threading
import time
from decimal import Decimal
import pytest
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.accounts.models import Role, User
from apps.core.models import Product
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

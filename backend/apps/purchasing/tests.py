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
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _load_trip(*, supplier_order, cession, quantity, suffix, admin_user):
    """Minimal Trip that actually loads `quantity` litres against
    `cession`/`supplier_order` - the only thing that should move
    SupplierStockService.get_purchase_reliquat() (client business rule,
    confirmed 2026-09-06). Mirrors the equivalent fixture already used in
    apps.finance.tests (_make_trip_for_deduction)."""
    truck = Truck.objects.create(
        internal_id=f"TRK-{suffix}",
        tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    transporter = Transporter.objects.create(name=f"Transporteur {suffix}")
    return Trip.objects.create(
        reference=f"TRIP-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier_order.supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=supplier_order.product,
        quantity_loaded=quantity,
        loading_date="2026-08-18",
        bl_reference=f"BL-{suffix}",
        created_by=admin_user,
    )


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

    # Création d'une première cession de 60,000 L.
    CessionLetter.objects.create(
        reference="CL-001",
        supplier_order=order,
        authorized_quantity=Decimal("60000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )

    # Bug fix (client business rule, confirmed 2026-09-06): issuing a
    # cession letter no longer moves the *displayed* reliquat by itself -
    # only an actual loading (a Trip) does. No trip has loaded anything yet
    # here, so the full 100,000 L is still reliquat.
    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("100000.00")

    # The cession-issuance cap below is a different, still-valid check:
    # a cession letter can never authorize more than was actually
    # purchased, regardless of how much has been loaded so far -
    # validate_and_lock_reliquat() (used by the serializer) still sums
    # active cessions against the purchased quantity for that reason.
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
def test_reliquat_unaffected_by_cession_issuance_or_cancellation():
    """Bug fix regression (client business rule, confirmed 2026-09-06):
    issuing or cancelling a cession letter must never move the displayed
    reliquat by itself - only an actual Trip loading does. Replaces the
    old test_cession_cancellation_releases_reliquat, which asserted the
    opposite (pre-fix) behaviour."""
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

    # Issuing the cession alone changes nothing on the reliquat.
    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("100000.00")

    # Loading 25,000 L against it is what actually consumes reliquat.
    _load_trip(
        supplier_order=order, cession=cession, quantity=Decimal("25000.00"),
        suffix="REL003", admin_user=admin_user,
    )
    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("75000.00")

    # Cancelling the (already partly consumed) cession doesn't touch the
    # reliquat either - only cancelling/reducing the trip's loaded quantity
    # would.
    cession.status = CessionLetter.Status.CANCELLED
    cession.save()
    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("75000.00")


@pytest.mark.django_db
def test_reliquat_and_debt_track_loaded_quantity_not_cession_or_full_order():
    """Exact client-confirmed example (2026-09-06): purchase 200,000 L at
    500 XOF/L, cession letter for the full 200,000 L, but only 100,000 L
    actually loaded onto a trip so far.

    -> reliquat fournisseur restant = 100,000 L (not 0)
    -> dette fournisseur = 100,000 x 500 = 50,000,000 XOF (not the full
       order's 100,000,000 XOF)

    When the remaining 100,000 L is loaded later, both figures must update
    to reflect it.
    """
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000099", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total Client Example", country="Senegal")

    order = SupplierOrder.objects.create(
        reference="SO-CLIENT-EXAMPLE",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("200000.00"),
        unit_price=Decimal("500.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference="CL-CLIENT-EXAMPLE",
        supplier_order=order,
        authorized_quantity=Decimal("200000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )

    # No loading yet: reliquat is still the full purchased quantity, and
    # its monetary value is the full order (nothing loaded yet).
    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("200000.00")
    assert SupplierStockService.get_purchase_loaded_amount(order) == Decimal("0.00")
    assert SupplierStockService.get_purchase_reliquat_amount(order) == Decimal("100000000.00")

    _load_trip(
        supplier_order=order, cession=cession, quantity=Decimal("100000.00"),
        suffix="CLIENTEX1", admin_user=admin_user,
    )

    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("100000.00")
    assert SupplierStockService.get_purchase_loaded_amount(order) == Decimal("50000000.00")
    assert SupplierStockService.get_purchase_reliquat_amount(order) == Decimal("50000000.00")

    # Loading the remaining 100,000 L later updates both figures.
    _load_trip(
        supplier_order=order, cession=cession, quantity=Decimal("100000.00"),
        suffix="CLIENTEX2", admin_user=admin_user,
    )

    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("0.00")
    assert SupplierStockService.get_purchase_loaded_amount(order) == Decimal("100000000.00")
    assert SupplierStockService.get_purchase_reliquat_amount(order) == Decimal("0.00")


def _make_order(suffix, admin_user, *, quantity, unit_price):
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Pipeline Supplier {suffix}", country="Senegal")
    return SupplierOrder.objects.create(
        reference=f"SO-{suffix}", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=quantity, unit_price=unit_price,
        status=SupplierOrder.Status.CONFIRMED, created_by=admin_user,
    )


@pytest.mark.django_db
def test_get_purchase_in_transit_amount_counts_loaded_not_yet_arrived_trips():
    """Client's pipeline definition (2026-09-06, mirrored 2026-09-14 into
    SupplierStockService for the Fond de roulement fix): a loaded trip
    still on the road (default ASSIGNED status here) counts as "en cours",
    valued at the order's own unit_price."""
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000101", pin="1234", role=admin_role)
    order = _make_order("INTRANSIT1", admin_user, quantity=Decimal("200000.00"), unit_price=Decimal("1000.0000"))
    cession = CessionLetter.objects.create(
        reference="CL-INTRANSIT1", supplier_order=order,
        authorized_quantity=Decimal("200000.00"), issue_date="2026-08-18", created_by=admin_user,
    )
    _load_trip(supplier_order=order, cession=cession, quantity=Decimal("45000.00"), suffix="INTRANSIT1", admin_user=admin_user)

    assert SupplierStockService.get_purchase_in_transit_amount(order) == Decimal("45000000.00")
    assert SupplierStockService.get_purchase_company_stock_amount(order) == Decimal("0.00")


@pytest.mark.django_db
def test_get_purchase_company_stock_amount_counts_only_stocked_trips():
    """Once a trip reaches ARRIVED_AT_COMPANY_STOCK/STOCKED it drops out of
    "en cours" and becomes "stock entreprise" - valued at the same pure
    unit_price basis (never the fuller cost-basis the Dashboard card uses,
    to avoid double-counting transport/customs debts, see
    WorkingCapitalService's 2026-09-14 docstring entry)."""
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000102", pin="1234", role=admin_role)
    order = _make_order("STOCKED1", admin_user, quantity=Decimal("200000.00"), unit_price=Decimal("1000.0000"))
    cession = CessionLetter.objects.create(
        reference="CL-STOCKED1", supplier_order=order,
        authorized_quantity=Decimal("200000.00"), issue_date="2026-08-18", created_by=admin_user,
    )
    trip = _load_trip(supplier_order=order, cession=cession, quantity=Decimal("45000.00"), suffix="STOCKED1", admin_user=admin_user)
    trip.status = Trip.Status.STOCKED
    trip.save(update_fields=["status"])

    assert SupplierStockService.get_purchase_company_stock_amount(order) == Decimal("45000000.00")
    assert SupplierStockService.get_purchase_in_transit_amount(order) == Decimal("0.00")


@pytest.mark.django_db
def test_get_purchase_in_transit_and_company_stock_amount_exclude_sold_trips():
    """A trip that already produced a Sale is a customer receivable, not
    company-held fuel - it must drop out of both buckets the instant it's
    sold, mirroring TheoreticalStockService's own exclusion."""
    from apps.customers.models import Customer
    from apps.sales.models import Sale

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000103", pin="1234", role=admin_role)
    order = _make_order("SOLD1", admin_user, quantity=Decimal("200000.00"), unit_price=Decimal("1000.0000"))
    cession = CessionLetter.objects.create(
        reference="CL-SOLD1", supplier_order=order,
        authorized_quantity=Decimal("200000.00"), issue_date="2026-08-18", created_by=admin_user,
    )
    trip = _load_trip(supplier_order=order, cession=cession, quantity=Decimal("45000.00"), suffix="SOLD1", admin_user=admin_user)
    trip.status = Trip.Status.STOCKED
    trip.save(update_fields=["status"])
    Sale.objects.create(
        trip=trip, customer=Customer.objects.create(name="Sold Client"), product=order.product,
        delivered_quantity=Decimal("45000.00"), unit_selling_price=Decimal("1200.0000"),
    )

    assert SupplierStockService.get_purchase_company_stock_amount(order) == Decimal("0.00")
    assert SupplierStockService.get_purchase_in_transit_amount(order) == Decimal("0.00")


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

    cession = CessionLetter.objects.create(
        reference="CL-LEDGER-001",
        supplier_order=order,
        authorized_quantity=Decimal("30000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    # Bug fix (client business rule, confirmed 2026-09-06): the reliquat
    # this endpoint exposes only moves once litres are actually loaded, so
    # the cession above by itself leaves it unchanged - an actual Trip is
    # what brings it down to 70,000 L.
    _load_trip(
        supplier_order=order, cession=cession, quantity=Decimal("30000.00"),
        suffix="LEDGER001", admin_user=admin_user,
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
# Amending a CONFIRMED SupplierOrder (client request 2026-09-24): quantity,
# unit price and optional costs used to be frozen (the only way out was
# cancelling the order, which orphaned every trip already loaded on it).
# They can now be corrected in place, provided a written reason is given
# (kept on the audit trail) and the change can't strand what already
# depends on the order: litres already loaded on trips, active cession
# letters, and cash already paid to the supplier. Advance consumption is
# recomputed against the new total.
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


def _patch(client, order, **payload):
    return client.patch(f"/api/supplier-orders/{order.id}/", payload, format="json")


def _admin_of(order):
    return order.created_by


def _cession(order, quantity, suffix):
    return CessionLetter.objects.create(
        reference=f"CL-{suffix}", supplier_order=order,
        authorized_quantity=Decimal(quantity), issue_date="2026-08-18",
        created_by=order.created_by,
    )


def _pay(order, amount, suffix):
    from apps.finance.models import CashAccount

    cash = CashAccount.objects.create(name=f"Cash {suffix}")
    return SupplierPayment.objects.create(
        supplier=order.supplier, supplier_order=order, amount=Decimal(amount),
        payment_date="2026-08-19", method=SupplierPayment.Method.CASH,
        cash_account=cash, recorded_by=order.created_by,
    )


def _advance(order, amount, suffix):
    from apps.finance.models import CashAccount, SupplierAdvance

    cash = CashAccount.objects.create(name=f"AdvCash {suffix}")
    return SupplierAdvance.objects.create(
        supplier=order.supplier, amount=Decimal(amount), date="2026-08-10",
        cash_account=cash, recorded_by=order.created_by,
    )


@pytest.mark.django_db
def test_confirmed_order_quantity_change_requires_a_reason():
    client, order = _confirmed_order("AMD-NOREASON")
    response = _patch(client, order, quantity_litres="2000.00")
    assert response.status_code == 400
    assert "reason" in response.data
    order.refresh_from_db()
    assert order.quantity_litres == Decimal("1000.00")


@pytest.mark.django_db
def test_confirmed_order_blank_reason_is_rejected():
    client, order = _confirmed_order("AMD-BLANK")
    response = _patch(client, order, quantity_litres="2000.00", reason="   ")
    assert response.status_code == 400
    assert "reason" in response.data


@pytest.mark.django_db
def test_confirmed_order_quantity_can_be_amended_with_a_reason():
    client, order = _confirmed_order("AMD-QTY")
    response = _patch(client, order, quantity_litres="2000.00", reason="Erreur de saisie")
    assert response.status_code == 200, response.data
    order.refresh_from_db()
    assert order.quantity_litres == Decimal("2000.00")
    assert order.total_amount == Decimal("1200000.00")


@pytest.mark.django_db
def test_confirmed_order_unit_price_and_optional_costs_can_be_amended():
    client, order = _confirmed_order("AMD-PRICE")
    response = _patch(
        client, order, unit_price="700.0000", optional_costs="10000.00", reason="Prix corrige"
    )
    assert response.status_code == 200, response.data
    order.refresh_from_db()
    assert order.unit_price == Decimal("700.0000")
    assert order.total_amount == Decimal("710000.00")


@pytest.mark.django_db
def test_amendment_reason_is_stored_on_the_audit_log():
    from apps.audit.models import AuditLog

    client, order = _confirmed_order("AMD-AUDIT")
    _patch(client, order, quantity_litres="2000.00", reason="Erreur de saisie")
    log = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(SupplierOrder),
        object_id=order.id,
        action=AuditLog.Action.UPDATE,
    ).latest("id")
    assert log.reason == "Erreur de saisie"
    assert log.previous_value["quantity_litres"] == "1000.00"
    assert log.new_value["quantity_litres"] == "2000.00"


@pytest.mark.django_db
def test_amendment_with_loaded_trips_and_higher_quantity_is_allowed():
    client, order = _confirmed_order("AMD-LOADED")
    cession = _cession(order, "800.00", "AMD-LOADED")
    _load_trip(
        supplier_order=order, cession=cession, quantity=Decimal("500.00"),
        suffix="AMD-LOADED", admin_user=order.created_by,
    )
    response = _patch(client, order, quantity_litres="1500.00", reason="Erreur de saisie")
    assert response.status_code == 200, response.data
    order.refresh_from_db()
    assert SupplierStockService.get_purchase_reliquat(order) == Decimal("1000.00")


@pytest.mark.django_db
def test_amendment_below_loaded_quantity_is_rejected_with_the_minimum():
    client, order = _confirmed_order("AMD-BELOWLOAD")
    cession = _cession(order, "800.00", "AMD-BELOWLOAD")
    _load_trip(
        supplier_order=order, cession=cession, quantity=Decimal("500.00"),
        suffix="AMD-BELOWLOAD", admin_user=order.created_by,
    )
    response = _patch(client, order, quantity_litres="400.00", reason="Erreur de saisie")
    assert response.status_code == 400
    assert "quantity_litres" in response.data
    assert "500" in str(response.data["quantity_litres"])
    order.refresh_from_db()
    assert order.quantity_litres == Decimal("1000.00")


@pytest.mark.django_db
def test_amendment_ignores_cancelled_trips_when_computing_the_minimum():
    client, order = _confirmed_order("AMD-CANCELTRIP")
    cession = _cession(order, "800.00", "AMD-CANCELTRIP")
    trip = _load_trip(
        supplier_order=order, cession=cession, quantity=Decimal("500.00"),
        suffix="AMD-CANCELTRIP", admin_user=order.created_by,
    )
    trip.status = Trip.Status.CANCELLED
    trip.save(update_fields=["status"])
    cession.status = CessionLetter.Status.CANCELLED
    cession.save()
    response = _patch(client, order, quantity_litres="400.00", reason="Erreur de saisie")
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_amendment_below_active_cessions_is_rejected_with_the_minimum():
    client, order = _confirmed_order("AMD-BELOWCES")
    _cession(order, "800.00", "AMD-BELOWCES")
    response = _patch(client, order, quantity_litres="700.00", reason="Erreur de saisie")
    assert response.status_code == 400
    assert "quantity_litres" in response.data
    assert "800" in str(response.data["quantity_litres"])


@pytest.mark.django_db
def test_amendment_below_cash_already_paid_is_rejected():
    client, order = _confirmed_order("AMD-BELOWPAID")
    _pay(order, "500000.00", "AMD-BELOWPAID")
    # 1000 L x 600 = 600 000; cutting to 500 L => 300 000 < 500 000 already paid.
    response = _patch(client, order, quantity_litres="500.00", reason="Erreur de saisie")
    assert response.status_code == 400
    assert "quantity_litres" in response.data
    assert "500" in str(response.data["quantity_litres"])


@pytest.mark.django_db
def test_amendment_down_to_exactly_the_amount_paid_is_allowed():
    client, order = _confirmed_order("AMD-EXACTPAID")
    _pay(order, "300000.00", "AMD-EXACTPAID")
    response = _patch(client, order, quantity_litres="500.00", reason="Erreur de saisie")
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_reversed_payments_do_not_block_an_amendment():
    client, order = _confirmed_order("AMD-REVPAID")
    payment = _pay(order, "500000.00", "AMD-REVPAID")
    payment.is_reversed = True
    payment.save()
    response = _patch(client, order, quantity_litres="500.00", reason="Erreur de saisie")
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_amendment_decrease_releases_the_excess_advance_consumption():
    from apps.finance.services import AdvanceConsumptionService

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000777", pin="1234", role=admin_role)
    supplier = Supplier.objects.create(name="Adv Supplier", country="Senegal")
    order = SupplierOrder.objects.create(
        reference="SO-AMD-ADV", supplier=supplier, product=Product.objects.get(code="gasoil"),
        purchase_date="2026-08-18", quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.DRAFT,
        created_by=admin_user,
    )
    advance = _advance(order, "900000.00", "AMD-ADV")
    order.status = SupplierOrder.Status.CONFIRMED
    order.save()
    assert AdvanceConsumptionService.get_consumed_amount(order) == Decimal("600000.00")
    assert advance.remaining_amount == Decimal("300000.00")

    client = APIClient()
    client.force_authenticate(admin_user)
    response = _patch(client, order, quantity_litres="500.00", reason="Erreur de saisie")
    assert response.status_code == 200, response.data
    order.refresh_from_db()
    # New total 300 000 => consumption trimmed to 300 000, the rest is back.
    assert AdvanceConsumptionService.get_consumed_amount(order) == Decimal("300000.00")
    assert advance.remaining_amount == Decimal("600000.00")


@pytest.mark.django_db
def test_amendment_increase_does_not_double_cover_what_was_already_paid_in_cash():
    from apps.finance.services import AdvanceConsumptionService

    client, order = _confirmed_order("AMD-NODOUBLE")
    _pay(order, "600000.00", "AMD-NODOUBLE")
    advance = _advance(order, "900000.00", "AMD-NODOUBLE")
    # Order is fully paid in cash: no advance was (or should be) consumed.
    response = _patch(client, order, quantity_litres="1500.00", reason="Erreur de saisie")
    assert response.status_code == 200, response.data
    order.refresh_from_db()
    # New total 900 000; 600 000 paid in cash; only the 300 000 delta is covered.
    assert AdvanceConsumptionService.get_consumed_amount(order) == Decimal("300000.00")
    assert advance.remaining_amount == Decimal("600000.00")


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

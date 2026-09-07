import itertools
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import (
    CustomerOrder,
    Invoice,
    InvoiceCorrection,
    ProductSellingPriceHistory,
    Sale,
)
from apps.sales.serializers import CustomerOrderSerializer
from apps.sales.services import (
    CustomerOrderService,
    InvoiceNotValidated,
    InvoicePaidCorrectionUnsupported,
    InvoiceService,
    InvoiceValidationError,
    UnsupportedCorrectionField,
)
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _setup_fixtures(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone=(f"+222{suffix}")[:20],
        pin="1234",
        role=admin_role,
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    transporter = Transporter.objects.create(name="Trans SA")
    customer = Customer.objects.create(name="Client Y")

    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-SALES-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-SALES-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("500000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    return {
        "admin_user": admin_user,
        "product": product,
        "supplier": supplier,
        "transporter": transporter,
        "customer": customer,
        "supplier_order": supplier_order,
        "cession": cession,
    }


def _make_trip(fx, order, reference, quantity, status):
    truck = Truck.objects.create(
        internal_id=f"TRK-{reference}",
        tractor_registration=f"{reference}-TRACTOR",
        tanker_registration=f"{reference}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    return Trip.objects.create(
        reference=reference,
        truck=truck,
        transporter=fx["transporter"],
        supplier=fx["supplier"],
        supplier_order=fx["supplier_order"],
        cession_letter=fx["cession"],
        product=fx["product"],
        quantity_loaded=quantity,
        customer_order=order,
        loading_date="2026-08-18",
        bl_reference=f"BL-{reference}",
        status=status,
        created_by=fx["admin_user"],
    )


@pytest.mark.django_db
def test_customer_order_quantity_must_be_positive():
    fx = _setup_fixtures("QTY")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CustomerOrder.objects.create(
                customer=fx["customer"],
                product=fx["product"],
                quantity_ordered=Decimal("0.00"),
            )


@pytest.mark.django_db
def test_assigned_quantity_excludes_cancelled_trips():
    fx = _setup_fixtures("EXCL")
    order = CustomerOrder.objects.create(
        customer=fx["customer"],
        product=fx["product"],
        quantity_ordered=Decimal("100000.00"),
        status=CustomerOrder.Status.CONFIRMED,
    )

    _make_trip(fx, order, "TRIP-EXCL-KEEP", Decimal("40000.00"), Trip.Status.ASSIGNED)
    _make_trip(
        fx, order, "TRIP-EXCL-CANCELLED", Decimal("40000.00"), Trip.Status.CANCELLED
    )

    assert CustomerOrderService.get_assigned_quantity(order) == Decimal("40000.00")


@pytest.mark.django_db
def test_recompute_status_is_noop_for_manual_lifecycle_states():
    fx = _setup_fixtures("MANUAL")

    for manual_status in (
        CustomerOrder.Status.DRAFT,
        CustomerOrder.Status.CLOSED,
        CustomerOrder.Status.CANCELLED,
    ):
        order = CustomerOrder.objects.create(
            customer=fx["customer"],
            product=fx["product"],
            quantity_ordered=Decimal("100000.00"),
            status=manual_status,
        )
        _make_trip(
            fx,
            order,
            f"TRIP-MANUAL-{manual_status}",
            Decimal("100000.00"),
            Trip.Status.COMPLETED,
        )

        CustomerOrderService.recompute_status(order)
        order.refresh_from_db()
        assert order.status == manual_status


@pytest.mark.django_db
def test_remaining_quantity_tracks_delivered_not_assigned():
    fx = _setup_fixtures("REMAIN")
    order = CustomerOrder.objects.create(
        customer=fx["customer"],
        product=fx["product"],
        quantity_ordered=Decimal("100000.00"),
        status=CustomerOrder.Status.CONFIRMED,
    )

    # Assigned but not yet delivered: remaining should still be the full amount.
    _make_trip(fx, order, "TRIP-REMAIN-001", Decimal("100000.00"), Trip.Status.ASSIGNED)
    assert CustomerOrderService.get_remaining_quantity(order) == Decimal("100000.00")


@pytest.mark.django_db
def test_customer_order_serializer_exposes_computed_quantities():
    fx = _setup_fixtures("SER-QTY")
    order = CustomerOrder.objects.create(
        customer=fx["customer"],
        product=fx["product"],
        quantity_ordered=Decimal("100000.00"),
        status=CustomerOrder.Status.CONFIRMED,
    )
    _make_trip(fx, order, "TRIP-SER-QTY-001", Decimal("40000.00"), Trip.Status.ASSIGNED)
    _make_trip(fx, order, "TRIP-SER-QTY-002", Decimal("30000.00"), Trip.Status.DELIVERED)

    data = CustomerOrderSerializer(order).data

    assert data["assigned_quantity"] == "70000.00"
    assert data["delivered_quantity"] == "30000.00"
    assert data["remaining_quantity"] == "70000.00"
    assert data["customer_detail"]["id"] == fx["customer"].id
    assert data["product_detail"]["id"] == fx["product"].id


@pytest.mark.django_db
def test_customer_order_serializer_rejects_direct_derived_status():
    fx = _setup_fixtures("SER-STATUS")

    serializer = CustomerOrderSerializer(
        data={
            "customer": fx["customer"].id,
            "product": fx["product"].id,
            "quantity_ordered": "100000.00",
            "status": CustomerOrder.Status.DELIVERED,
        }
    )
    assert not serializer.is_valid()
    assert "status" in serializer.errors


@pytest.mark.django_db
def test_customer_order_serializer_allows_manual_confirm():
    fx = _setup_fixtures("SER-CONFIRM")

    serializer = CustomerOrderSerializer(
        data={
            "customer": fx["customer"].id,
            "product": fx["product"].id,
            "quantity_ordered": "100000.00",
            "status": CustomerOrder.Status.CONFIRMED,
        }
    )
    assert serializer.is_valid(), serializer.errors


# ---------------------------------------------------------------------------
# Phase 4 Etape 4/5: Sale, ProductSellingPriceHistory, Invoice, InvoiceCorrection
# models + InvoiceService (docs/PHASE_4_PLAN.md; guide Section 7.6-7.9, 21).
# ---------------------------------------------------------------------------


def _make_sale(fx, reference, delivered_quantity=Decimal("44850.00"),
               unit_selling_price=Decimal("650.0000")):
    trip = _make_trip(
        fx, None, reference, Decimal("45000.00"), Trip.Status.DELIVERED
    )
    return Sale.objects.create(
        trip=trip,
        customer=fx["customer"],
        product=fx["product"],
        delivered_quantity=delivered_quantity,
        unit_selling_price=unit_selling_price,
    )


@pytest.mark.django_db
def test_sale_subtotal_is_computed_on_save():
    fx = _setup_fixtures("SALE-SUB")
    sale = _make_sale(fx, "TRIP-SALE-SUB-001")

    assert sale.subtotal == Decimal("29152500.00")
    assert sale.currency == "XOF"


@pytest.mark.django_db
def test_sale_requires_positive_delivered_quantity():
    fx = _setup_fixtures("SALE-QTY")
    trip = _make_trip(fx, None, "TRIP-SALE-QTY-001", Decimal("45000.00"), Trip.Status.DELIVERED)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Sale.objects.create(
                trip=trip,
                customer=fx["customer"],
                product=fx["product"],
                delivered_quantity=Decimal("0.00"),
                unit_selling_price=Decimal("650.0000"),
            )


@pytest.mark.django_db
def test_product_selling_price_history_keeps_every_entry():
    fx = _setup_fixtures("PRICE-HIST")

    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("600.0000"), changed_by=fx["admin_user"],
    )
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    assert ProductSellingPriceHistory.objects.filter(
        product=fx["product"], customer=fx["customer"]
    ).count() == 2
    latest = ProductSellingPriceHistory.objects.filter(
        product=fx["product"], customer=fx["customer"]
    ).order_by("-effective_at", "-id").first()
    assert latest.price == Decimal("650.0000")


@pytest.mark.django_db
def test_invoice_number_must_be_unique():
    fx = _setup_fixtures("INV-UNIQ")
    sale_a = _make_sale(fx, "TRIP-INV-UNIQ-A")
    sale_b = _make_sale(fx, "TRIP-INV-UNIQ-B")

    Invoice.objects.create(
        invoice_number="INV-0001", sale=sale_a,
        total_amount=sale_a.subtotal, issued_date="2026-08-18",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Invoice.objects.create(
                invoice_number="INV-0001", sale=sale_b,
                total_amount=sale_b.subtotal, issued_date="2026-08-18",
            )


@pytest.mark.django_db
def test_invoice_defaults_to_draft_status():
    fx = _setup_fixtures("INV-DRAFT")
    sale = _make_sale(fx, "TRIP-INV-DRAFT-001")

    invoice = Invoice.objects.create(
        invoice_number="INV-DRAFT-0001", sale=sale,
        total_amount=sale.subtotal, issued_date="2026-08-18",
    )

    assert invoice.status == Invoice.Status.DRAFT


def _make_invoice(fx, reference):
    sale = _make_sale(fx, reference)
    invoice = Invoice.objects.create(
        invoice_number=f"INV-{reference}", sale=sale,
        total_amount=sale.subtotal, issued_date="2026-08-18",
    )
    return sale, invoice


@pytest.mark.django_db
def test_validate_invoice_transitions_draft_to_validated():
    fx = _setup_fixtures("VALIDATE")
    _, invoice = _make_invoice(fx, "TRIP-VALIDATE-001")

    InvoiceService.validate_invoice(invoice.id, fx["admin_user"])

    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.VALIDATED


@pytest.mark.django_db
def test_validate_invoice_rejects_already_validated_invoice():
    fx = _setup_fixtures("REVALIDATE")
    _, invoice = _make_invoice(fx, "TRIP-REVALIDATE-001")
    InvoiceService.validate_invoice(invoice.id, fx["admin_user"])

    with pytest.raises(InvoiceValidationError):
        InvoiceService.validate_invoice(invoice.id, fx["admin_user"])


@pytest.mark.django_db
def test_correct_invoice_rejects_direct_correction_on_draft_invoice():
    # Rule E (plan Section 1): corrections are for *validated* invoices only
    # - a DRAFT invoice's serializer should accept normal field edits instead.
    fx = _setup_fixtures("CORR-DRAFT")
    _, invoice = _make_invoice(fx, "TRIP-CORR-DRAFT-001")

    with pytest.raises(InvoiceNotValidated):
        InvoiceService.correct_invoice(
            invoice.id, "unit_selling_price", Decimal("605.0000"),
            "Erreur de saisie contractuelle", fx["admin_user"],
        )


@pytest.mark.django_db
def test_correct_invoice_updates_price_and_recomputes_total_with_audit_trail():
    # Mandatory recette scenario (plan Section 4): 600 -> 605 XOF/L.
    fx = _setup_fixtures("CORRECT")
    sale, invoice = _make_invoice(fx, "TRIP-CORRECT-001")
    InvoiceService.validate_invoice(invoice.id, fx["admin_user"])

    InvoiceService.correct_invoice(
        invoice.id, "unit_selling_price", Decimal("605.0000"),
        "Erreur de saisie contractuelle", fx["admin_user"],
    )

    sale.refresh_from_db()
    invoice.refresh_from_db()
    assert sale.unit_selling_price == Decimal("605.0000")
    assert sale.subtotal == sale.delivered_quantity * Decimal("605.0000")
    assert invoice.total_amount == sale.subtotal

    correction = InvoiceCorrection.objects.get(invoice=invoice)
    assert correction.field_name == "unit_selling_price"
    assert correction.previous_value == "650.0000"
    assert correction.new_value == "605.0000"
    assert correction.reason == "Erreur de saisie contractuelle"
    assert correction.corrected_by_id == fx["admin_user"].id


@pytest.mark.django_db
def test_correct_invoice_rejects_unsupported_field():
    fx = _setup_fixtures("CORR-BADFIELD")
    _, invoice = _make_invoice(fx, "TRIP-CORR-BADFIELD-001")
    InvoiceService.validate_invoice(invoice.id, fx["admin_user"])

    with pytest.raises(UnsupportedCorrectionField):
        InvoiceService.correct_invoice(
            invoice.id, "invoice_number", "INV-9999", "typo", fx["admin_user"]
        )


# ---------------------------------------------------------------------------
# Phase 4 Etape 6/7: GET|POST /api/sales/, GET|POST /api/invoices/,
# POST /api/invoices/{id}/validate/, POST /api/invoices/{id}/correct/
# (docs/PHASE_4_PLAN.md; guide Section 7.9/Section 21).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_sale_is_read_only_no_direct_create():
    # Sales are generated exclusively by DeliveryService (POST
    # /api/trips/{id}/delivery-control/) so delivered_quantity can never
    # drift from the confirming DeliveryControl.received_quantity.
    fx = _setup_fixtures("API-SALE-RO")
    sale = _make_sale(fx, "TRIP-API-SALE-RO-001")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    list_response = client.get("/api/sales/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 1
    assert list_response.data["results"][0]["id"] == sale.id

    post_response = client.post(
        "/api/sales/",
        {
            "trip": sale.trip_id,
            "customer": fx["customer"].id,
            "product": fx["product"].id,
            "unit_selling_price": "600.0000",
        },
    )
    assert post_response.status_code == 405


@pytest.mark.django_db
def test_api_invoice_create_and_destroy_are_disabled():
    fx = _setup_fixtures("API-INV-NOCREATE")
    sale, invoice = _make_invoice(fx, "TRIP-INV-NOCR-001")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    post_response = client.post(
        "/api/invoices/",
        {"invoice_number": "INV-MANUAL", "sale": sale.id, "total_amount": "1.00",
         "issued_date": "2026-08-18"},
    )
    assert post_response.status_code == 405

    delete_response = client.delete(f"/api/invoices/{invoice.id}/")
    assert delete_response.status_code == 405
    assert Invoice.objects.filter(pk=invoice.id).exists()


@pytest.mark.django_db
def test_api_invoice_validate_then_reject_second_validation():
    fx = _setup_fixtures("API-INV-VALIDATE")
    _, invoice = _make_invoice(fx, "TRIP-INV-VALID-001")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    response = client.post(f"/api/invoices/{invoice.id}/validate/")
    assert response.status_code == 200, response.data
    assert response.data["status"] == Invoice.Status.VALIDATED

    again = client.post(f"/api/invoices/{invoice.id}/validate/")
    assert again.status_code == 400


@pytest.mark.django_db
def test_api_invoice_correction_blocks_direct_edit_but_allows_audited_correction():
    # Mandatory recette scenario (plan Section 4 / Etape 7 test 4): a direct
    # price edit on a VALIDATED invoice is rejected, but the /correct/
    # workflow succeeds (600 -> 605 XOF) and leaves an InvoiceCorrection.
    fx = _setup_fixtures("API-CORRECT")
    sale, invoice = _make_invoice(fx, "TRIP-API-CORRECT-001")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    validate_response = client.post(f"/api/invoices/{invoice.id}/validate/")
    assert validate_response.status_code == 200, validate_response.data

    direct_edit = client.patch(f"/api/invoices/{invoice.id}/", {"total_amount": "9999.00"})
    assert direct_edit.status_code == 400
    invoice.refresh_from_db()
    assert invoice.total_amount != Decimal("9999.00")

    correction_response = client.post(
        f"/api/invoices/{invoice.id}/correct/",
        {
            "field": "unit_selling_price",
            "new_value": "605.0000",
            "reason": "Erreur de saisie contractuelle",
        },
    )
    assert correction_response.status_code == 200, correction_response.data

    sale.refresh_from_db()
    invoice.refresh_from_db()
    assert sale.unit_selling_price == Decimal("605.0000")
    assert invoice.total_amount == sale.subtotal

    detail_response = client.get(f"/api/invoices/{invoice.id}/")
    assert len(detail_response.data["corrections"]) == 1
    assert detail_response.data["corrections"][0]["field_name"] == "unit_selling_price"
    assert detail_response.data["corrections"][0]["previous_value"] == "650.0000"
    assert detail_response.data["corrections"][0]["new_value"] == "605.0000"
    assert detail_response.data["corrections"][0]["reason"] == "Erreur de saisie contractuelle"


@pytest.mark.django_db
def test_api_invoice_correct_rejected_while_still_draft():
    fx = _setup_fixtures("API-CORRECT-DRAFT")
    _, invoice = _make_invoice(fx, "TRIP-CORR-DRAFT-01")

    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    response = client.post(
        f"/api/invoices/{invoice.id}/correct/",
        {"field": "unit_selling_price", "new_value": "605.0000", "reason": "typo"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Spec 2026-09-07 "facture quantité reçue": InvoiceService.adjust_delivered_quantity
# ---------------------------------------------------------------------------

_adjust_qty_counter = itertools.count(1)


def _actor():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        phone=f"+222ADJ{next(_adjust_qty_counter):05d}",
        pin="1234",
        role=admin_role,
    )


def _sale_with_invoice(status):
    suffix = f"ADJ{next(_adjust_qty_counter)}"
    fx = _setup_fixtures(suffix)
    trip = _make_trip(
        fx, None, f"TRIP-{suffix}", Decimal("45000.00"), Trip.Status.DELIVERED
    )
    sale = Sale.objects.create(
        trip=trip,
        customer=fx["customer"],
        product=fx["product"],
        delivered_quantity=Decimal("45000.00"),
        unit_selling_price=Decimal("900.0000"),
    )
    invoice = Invoice.objects.create(
        invoice_number=f"INV-{suffix}",
        sale=sale,
        total_amount=sale.subtotal,
        status=status,
        issued_date="2026-08-18",
    )
    return sale, invoice


@pytest.mark.django_db
def test_adjust_delivered_quantity_draft_edits_directly_no_correction_row():
    sale, invoice = _sale_with_invoice(Invoice.Status.DRAFT)  # 45000 L x 900 = 40,500,000

    result = InvoiceService.adjust_delivered_quantity(
        invoice.id, Decimal("44800.00"), reason="Vérification client", actor=_actor()
    )

    sale.refresh_from_db()
    result.refresh_from_db()
    assert sale.delivered_quantity == Decimal("44800.00")
    assert sale.subtotal == Decimal("40320000.00")
    assert result.total_amount == Decimal("40320000.00")
    assert InvoiceCorrection.objects.filter(invoice=invoice).count() == 0


@pytest.mark.django_db
def test_adjust_delivered_quantity_validated_writes_correction_row():
    sale, invoice = _sale_with_invoice(Invoice.Status.VALIDATED)

    InvoiceService.adjust_delivered_quantity(
        invoice.id, Decimal("44800.00"),
        reason="Vérification client : quantité reçue corrigée de 45000.00 L à 44800.00 L",
        actor=_actor(),
    )

    sale.refresh_from_db()
    invoice.refresh_from_db()
    assert sale.delivered_quantity == Decimal("44800.00")
    assert invoice.total_amount == Decimal("40320000.00")
    correction = InvoiceCorrection.objects.get(invoice=invoice)
    assert correction.field_name == "delivered_quantity"
    assert correction.previous_value == "45000.00"
    assert correction.new_value == "44800.00"
    assert "Vérification client" in correction.reason


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [Invoice.Status.PARTIALLY_PAID, Invoice.Status.PAID, Invoice.Status.CANCELLED],
)
def test_adjust_delivered_quantity_paid_is_refused(status):
    sale, invoice = _sale_with_invoice(status)

    with pytest.raises(InvoicePaidCorrectionUnsupported):
        InvoiceService.adjust_delivered_quantity(
            invoice.id, Decimal("44800.00"), reason="x", actor=_actor()
        )

    sale.refresh_from_db()
    assert sale.delivered_quantity == Decimal("45000.00")


@pytest.mark.django_db
def test_adjust_delivered_quantity_noop_when_unchanged():
    sale, invoice = _sale_with_invoice(Invoice.Status.VALIDATED)

    result = InvoiceService.adjust_delivered_quantity(
        invoice.id, Decimal("45000.00"), reason="x", actor=_actor()
    )

    assert result.id == invoice.id
    assert InvoiceCorrection.objects.filter(invoice=invoice).count() == 0
    invoice.refresh_from_db()
    assert invoice.total_amount == Decimal("40500000.00")


@pytest.mark.django_db
def test_adjust_delivered_quantity_rejects_zero():
    # C1: a zero (total-loss) quantity would hit Sale's
    # CheckConstraint(delivered_quantity__gt=0) -> IntegrityError, which the
    # viewsets' `except ValueError` misses -> HTTP 500. Reject it upfront as
    # a ValueError instead.
    sale, invoice = _sale_with_invoice(Invoice.Status.VALIDATED)

    with pytest.raises(ValueError) as exc:
        InvoiceService.adjust_delivered_quantity(
            invoice.id, Decimal("0"), reason="Perte totale", actor=_actor()
        )
    assert invoice.invoice_number in str(exc.value)

    sale.refresh_from_db()
    assert sale.delivered_quantity == Decimal("45000.00")
    assert InvoiceCorrection.objects.filter(invoice=invoice).count() == 0


@pytest.mark.django_db
def test_correct_invoice_rejects_zero_delivered_quantity():
    sale, invoice = _sale_with_invoice(Invoice.Status.VALIDATED)

    with pytest.raises(ValueError) as exc:
        InvoiceService.correct_invoice(
            invoice.id, "delivered_quantity", "0",
            reason="Perte totale", actor=_actor(),
        )
    assert invoice.invoice_number in str(exc.value)

    sale.refresh_from_db()
    assert sale.delivered_quantity == Decimal("45000.00")
    assert InvoiceCorrection.objects.filter(invoice=invoice).count() == 0


@pytest.mark.django_db
def test_correct_invoice_supports_delivered_quantity_field():
    sale, invoice = _sale_with_invoice(Invoice.Status.VALIDATED)  # 45000 x 900

    InvoiceService.correct_invoice(
        invoice.id, "delivered_quantity", "44750.00",
        reason="Client conteste 250 L", actor=_actor(),
    )

    sale.refresh_from_db()
    invoice.refresh_from_db()
    assert sale.delivered_quantity == Decimal("44750.00")
    assert invoice.total_amount == Decimal("40275000.00")
    correction = InvoiceCorrection.objects.get(invoice=invoice, field_name="delivered_quantity")
    assert correction.previous_value == "45000.00"
    assert correction.new_value == "44750.00"

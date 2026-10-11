from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.suppliers.models import Supplier
from apps.trips.models import DeliveryControl, Trip
from apps.trips.tests import _make_trip, _make_truck, _setup_fixtures

from .models import DeliveryNoteLine


def _api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def fx():
    return _setup_fixtures("CDOC")


@pytest.fixture
def admin_client(fx):
    return _api(fx["admin_user"])


@pytest.fixture
def sales_only_client():
    role = Role.objects.create(name="Ventes seules", permissions={"sales": ["view", "create", "edit"]})
    return _api(User.objects.create_user(phone="+222CDOCS", pin="1234", role=role))


@pytest.fixture
def supplier(fx):
    return fx["supplier"]


@pytest.fixture
def gasoil():
    return Product.objects.get(code="gasoil")


@pytest.fixture
def delivered_trip(fx):
    trip = _make_trip(fx, _make_truck("TRK-CDOC"), "TRIP-CDOC-1", status=Trip.Status.DELIVERED)
    trip.client = Customer.objects.create(name="Baba Dembelé", address="Keneba")
    trip.save(update_fields=["client"])
    DeliveryControl.objects.create(
        trip=trip, loaded_quantity=Decimal("45000.00"), received_quantity=Decimal("44800.00"),
        tolerance_quantity=Decimal("100.00"), control_date="2026-08-18",
        controller=fx["admin_user"], method=DeliveryControl.Method.MANUAL_GAUGE,
    )
    return trip


@pytest.mark.django_db
def test_delivery_note_from_trips_with_reference_and_lines(admin_client, delivered_trip):
    url = f"/api/delivery-notes/deliverable-trips/?customer={delivered_trip.client_id}"
    trips = admin_client.get(url).data
    assert trips[0]["tractor"] == delivered_trip.truck.tractor_registration
    assert trips[0]["quantity"] == "44800.00" and trips[0]["missing"] == "200.00"
    line = {k: trips[0][k] for k in ("trip", "designation", "quantity", "tanker", "tractor", "missing")}
    response = admin_client.post("/api/delivery-notes/", {
        "customer": delivered_trip.client_id, "date": "2026-04-18", "place": "Bamako",
        "delivery_address": "Keneba", "lines": [line]}, format="json")
    assert response.status_code == 201, response.data
    assert response.data["reference"].startswith("BL-")
    assert response.data["lines"][0]["tractor"] == delivered_trip.truck.tractor_registration
    # Already on a note: a warning for the user, never a block.
    assert admin_client.get(url).data[0]["other_notes"] == [response.data["reference"]]


@pytest.mark.django_db
def test_only_delivered_trips_of_that_customer_are_offered(admin_client, fx, delivered_trip):
    other = _make_trip(fx, _make_truck("TRK-CDOC2"), "TRIP-CDOC-2", status=Trip.Status.ASSIGNED)
    other.client = delivered_trip.client
    other.save(update_fields=["client"])
    trips = admin_client.get(f"/api/delivery-notes/deliverable-trips/?customer={delivered_trip.client_id}").data
    assert [t["reference"] for t in trips] == ["TRIP-CDOC-1"]


@pytest.mark.django_db
def test_trip_without_delivery_control_uses_loaded_quantity(fx):
    trip = _make_trip(fx, _make_truck("TRK-CDOC3"), "TRIP-CDOC-3", status=Trip.Status.DELIVERED)
    data = DeliveryNoteLine.from_trip(trip)
    assert data["quantity"] == trip.quantity_loaded
    assert data["missing"] is None


@pytest.mark.django_db
def test_loading_sheet_manual_line_and_blank_line_rejected(admin_client):
    ok = admin_client.post("/api/loading-sheets/", {
        "date": "2026-06-29", "supplier_name": "Dépôt Moussala", "on_behalf_of": "SAHEL COMMERCE",
        "product_name": "GASOIL", "route": "MOUSSALA",
        "lines": [{"tractor": "BA 2947 MD", "tanker": "BA 1591 MD", "capacity_litres": "45000",
                   "be_number": "NUM006"}]}, format="json")
    assert ok.status_code == 201, ok.data
    assert ok.data["reference"].startswith("BCH-")
    assert ok.data["total_litres"] == "45000.00"
    blank = admin_client.post("/api/loading-sheets/", {
        "date": "2026-06-29", "supplier_name": "X", "lines": [{"capacity_litres": "45000"}]}, format="json")
    assert blank.status_code == 400
    no_supplier = admin_client.post("/api/loading-sheets/", {
        "date": "2026-06-29", "lines": [{"tractor": "T", "capacity_litres": "45000"}]}, format="json")
    assert no_supplier.status_code == 400


@pytest.mark.django_db
def test_purchase_order_total_and_supplier_required(admin_client, supplier, gasoil):
    response = admin_client.post("/api/purchase-order-documents/", {
        "supplier": supplier.id, "date": "2026-10-11",
        "lines": [{"product": gasoil.id, "quantity": "180000", "unit": "L", "unit_price": "750"}]},
        format="json")
    assert response.status_code == 201, response.data
    assert response.data["reference"].startswith("BCF-")
    assert response.data["total_amount"] == "135000000.00"
    missing = admin_client.post("/api/purchase-order-documents/", {
        "date": "2026-10-11", "lines": [{"description": "x", "quantity": "1", "unit_price": "1"}]},
        format="json")
    assert missing.status_code == 400
    no_lines = admin_client.post("/api/purchase-order-documents/", {
        "supplier": supplier.id, "date": "2026-10-11", "lines": []}, format="json")
    assert no_lines.status_code == 400


@pytest.mark.django_db
def test_module_permissions(sales_only_client):
    assert sales_only_client.get("/api/delivery-notes/").status_code == 200
    assert sales_only_client.get("/api/loading-sheets/").status_code == 403
    assert sales_only_client.get("/api/purchase-order-documents/").status_code == 403


# --- PDFs (spec §4-§6) --------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("lang", ["fr", "en", "ar"])
def test_every_document_pdf_renders(admin_client, delivered_trip, supplier, lang):
    created = [
        ("delivery-notes", {"customer": delivered_trip.client_id, "date": "2026-04-18", "place": "Bamako",
            "lines": [{"designation": "GASOIL", "quantity": "45000", "tanker": "BP 8795 MD",
                       "tractor": "AZ 7969 MD", "missing": "200"}]}),
        ("loading-sheets", {"date": "2026-06-29", "supplier_name": "Moussala", "on_behalf_of": "SAHEL",
            "lines": [{"tractor": "BA 2947 MD", "tanker": "BA 1591 MD", "capacity_litres": "45000"}]}),
        ("purchase-order-documents", {"supplier": supplier.id, "date": "2026-10-11", "payment_terms": "30%",
            "lines": [{"description": "Gasoil", "quantity": "1000", "unit": "L", "unit_price": "750"}]}),
    ]
    for path, body in created:
        document = admin_client.post(f"/api/{path}/", body, format="json")
        assert document.status_code == 201, (path, document.data)
        response = admin_client.get(f"/api/{path}/{document.data['id']}/pdf/?lang={lang}")
        assert response.status_code == 200 and response.content.startswith(b"%PDF"), path


@pytest.mark.django_db
def test_delivery_note_document_totals_and_signatures(admin_client, delivered_trip):
    from apps.commercial_documents.models import DeliveryNote
    from apps.reports.services.document_pdfs import build_delivery_note_document

    body = {"customer": delivered_trip.client_id, "date": "2026-04-18", "lines": [
        {"designation": "GASOIL", "quantity": "45000"}, {"designation": "GASOIL", "quantity": "45000"}]}
    note = DeliveryNote.objects.get(pk=admin_client.post("/api/delivery-notes/", body, format="json").data["id"])
    document, rows = build_delivery_note_document(note, "fr")
    assert [r["number"] for r in rows] == [1, 2]
    assert document["summary"][0]["value"] == Decimal("90000.00")
    assert document["signatures"] == ["Le réceptionnaire", "Le fournisseur"]
    assert {"label": "Adresse de livraison", "value": "Keneba"} in document["info"]  # customer address default


@pytest.mark.django_db
def test_loading_sheet_document_is_landscape_with_litre_total(admin_client):
    from apps.commercial_documents.models import LoadingSheet
    from apps.reports.services.document_pdfs import build_loading_sheet_document

    body = {"date": "2026-06-29", "supplier_name": "Moussala", "on_behalf_of": "SAHEL COMMERCE",
            "lines": [{"tractor": "T", "capacity_litres": "45000"}] * 4}
    sheet = LoadingSheet.objects.get(pk=admin_client.post("/api/loading-sheets/", body, format="json").data["id"])
    document, _ = build_loading_sheet_document(sheet, "fr")
    assert document["orientation"] == "landscape"
    assert "SAHEL COMMERCE" in document["title"]
    assert document["summary"][-1]["value"] == Decimal("180000.00")


@pytest.mark.django_db
def test_purchase_order_document_is_addressed_to_the_supplier(admin_client, supplier):
    from apps.commercial_documents.models import PurchaseOrderDocument
    from apps.reports.services.document_pdfs import build_purchase_order_document

    body = {"supplier": supplier.id, "date": "2026-10-11",
            "lines": [{"description": "Gasoil", "quantity": "1000", "unit": "L", "unit_price": "750"}]}
    order = PurchaseOrderDocument.objects.get(
        pk=admin_client.post("/api/purchase-order-documents/", body, format="json").data["id"]
    )
    document, rows = build_purchase_order_document(order, "fr")
    assert document["title"].startswith("Bon de commande")
    assert {"label": "Fournisseur", "value": supplier.name} in document["info"]
    assert not [r for r in rows if r["section"] == "banks"]
    assert document["signatures"] == ["Pour l'entreprise"]

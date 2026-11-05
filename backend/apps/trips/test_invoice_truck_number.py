"""The truck number is part of the stored invoice number
(FAC-YYYYMM-NNNN-<TRUCK>), so it shows everywhere the number does."""
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.sales.models import Invoice, ProductSellingPriceHistory
from apps.trips.models import DeliveryControl
from apps.trips.services import DeliveryService, invoice_truck_token
from apps.trips.tests import _deliverable_trip, _fixtures_with_customer


def _deliver(fx, reference):
    trip = _deliverable_trip(fx, reference)
    ProductSellingPriceHistory.objects.get_or_create(
        product=fx["product"], customer=fx["customer"],
        defaults={"price": Decimal("650.0000"), "changed_by": fx["admin_user"]},
    )
    DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("45000.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )
    return trip


@pytest.mark.django_db
def test_invoice_number_carries_the_truck_and_the_sequence_keeps_counting():
    fx = _fixtures_with_customer("INV-TRUCK")
    first = _deliver(fx, "TRIP-INV-TRUCK-1")
    second = _deliver(fx, "TRIP-INV-TRUCK-2")
    yyyymm = timezone.now().strftime("%Y%m")

    n1 = first.sale.invoice.invoice_number
    n2 = second.sale.invoice.invoice_number
    token1 = first.truck.tractor_registration.upper()
    assert n1 == f"FAC-{yyyymm}-0001-{token1}"
    # The suffix must not break the monthly sequence.
    assert n2.startswith(f"FAC-{yyyymm}-0002-")
    assert n2.endswith(second.truck.tractor_registration.upper())


def _sale(plate):
    return SimpleNamespace(trip=SimpleNamespace(truck=SimpleNamespace(tractor_registration=plate)))


def test_truck_token_cleans_dedupes_joins_and_caps_the_length():
    assert invoice_truck_token([_sale("aa 123/bb")]) == "AA123BB"
    assert invoice_truck_token([_sale("AA1"), _sale("BB2"), _sale("AA1")]) == "AA1+BB2"
    assert invoice_truck_token([_sale("")]) == ""
    assert len(invoice_truck_token([_sale("X" * 30), _sale("Y" * 30)])) <= 34


@pytest.mark.django_db
def test_backfill_command_is_a_dry_run_unless_applied():
    fx = _fixtures_with_customer("INV-BACKFILL")
    trip = _deliver(fx, "TRIP-INV-BACKFILL-1")
    invoice = trip.sale.invoice
    token = invoice.invoice_number.split("-", 3)[3]
    old_number = invoice.invoice_number.rsplit("-" + token, 1)[0]
    Invoice.objects.filter(pk=invoice.pk).update(invoice_number=old_number)

    call_command("backfill_invoice_truck_numbers", stdout=StringIO())
    invoice.refresh_from_db()
    assert invoice.invoice_number == old_number  # dry run changed nothing

    call_command("backfill_invoice_truck_numbers", "--apply", stdout=StringIO())
    invoice.refresh_from_db()
    assert invoice.invoice_number == f"{old_number}-{token}"

    out = StringIO()
    call_command("backfill_invoice_truck_numbers", "--apply", stdout=out)
    assert "Renamed 0" in out.getvalue()  # idempotent

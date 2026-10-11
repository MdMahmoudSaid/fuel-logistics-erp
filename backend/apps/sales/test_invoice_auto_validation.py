# Client request 2026-10-11: a completed trip's invoice is validated at once
# (it used to stay DRAFT, so a receipt could never be imputed on it).

import importlib
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient

from apps.finance.models import CashAccount, CustomerPayment
from apps.finance.services import PaymentAllocationService
from apps.sales.models import Invoice
from apps.trips.models import DeliveryControl, Trip
from apps.trips.services import DeliveryService
from apps.trips.tests import _deliverable_trip, _fixtures_with_customer

D = Decimal
PRICE = D("900.0000")
TOTAL = D("40500000.00")  # 45 000 L x 900


def _deliver(fx, reference, *, verify=True):
    trip = _deliverable_trip(fx, reference)
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-10-11",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"], unit_selling_price=PRICE,
    )
    if verify:
        DeliveryService.record_client_verification(
            trip_id=trip.id, received_qty=D("45000.00"),
            verified_at=date(2026, 10, 11), actor=fx["admin_user"],
        )
    trip.refresh_from_db()
    return trip, Invoice.objects.get(sale__trip=trip)


def _api(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def _receipt(user, customer, amount, suffix):
    cash = CashAccount.objects.create(name=f"Caisse {suffix}")
    response = _api(user).post(
        "/api/customer-payments/",
        {
            "customer": customer.id, "amount": str(amount), "payment_date": "2026-10-11",
            "method": "CASH", "destination": "CASH", "cash_account": cash.id,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return CustomerPayment.objects.get(pk=response.data["id"])


@pytest.mark.django_db
def test_invoice_is_draft_at_delivery_and_validated_when_the_trip_completes():
    fx = _fixtures_with_customer("AV-1")
    trip, invoice = _deliver(fx, "TRIP-AV-1", verify=False)
    assert invoice.status == Invoice.Status.DRAFT

    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=D("45000.00"),
        verified_at=date(2026, 10, 11), actor=fx["admin_user"],
    )

    trip.refresh_from_db()
    invoice.refresh_from_db()
    assert trip.status == Trip.Status.COMPLETED
    assert invoice.status == Invoice.Status.VALIDATED


@pytest.mark.django_db
def test_receipt_recorded_while_draft_is_imputed_once_the_trip_completes():
    """The client's complaint: the payment was made but the invoice stayed
    'Brouillon' - the receipt sat as unallocated credit."""
    fx = _fixtures_with_customer("AV-2")
    trip, invoice = _deliver(fx, "TRIP-AV-2", verify=False)
    payment = _receipt(fx["admin_user"], fx["customer"], TOTAL, "AV2")
    assert PaymentAllocationService.get_payment_unallocated_amount(payment) == TOTAL

    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=D("45000.00"),
        verified_at=date(2026, 10, 11), actor=fx["admin_user"],
    )

    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID
    assert PaymentAllocationService.get_payment_unallocated_amount(payment) == D("0.00")


@pytest.mark.django_db
def test_migration_validates_the_draft_invoices_of_already_completed_trips():
    fx = _fixtures_with_customer("AV-3")
    _trip, invoice = _deliver(fx, "TRIP-AV-3")
    _open_trip, open_invoice = _deliver(fx, "TRIP-AV-3B", verify=False)
    Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.DRAFT)
    payment = _receipt(fx["admin_user"], fx["customer"], D("1000000.00"), "AV3")

    migration = importlib.import_module(
        "apps.sales.migrations.0004_validate_completed_trip_invoices"
    )
    migration.validate_completed_trip_invoices(django_apps, None)

    invoice.refresh_from_db()
    open_invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PARTIALLY_PAID  # credit imputed
    assert open_invoice.status == Invoice.Status.DRAFT  # trip not completed yet
    assert PaymentAllocationService.get_payment_unallocated_amount(payment) == D("0.00")

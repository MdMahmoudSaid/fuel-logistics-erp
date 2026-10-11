# Client request 2026-10-11: the customer a trip was assigned to does not
# want it - the trip goes back to the company stock (before delivery only)
# or to another customer; the former customer keeps neither the trip nor
# any invoice for it.

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.customers.models import Customer
from apps.finance.models import CashAccount, CustomerPayment, TreasuryTransaction
from apps.finance.services import PaymentAllocationService
from apps.sales.models import (
    CustomerOrder,
    Invoice,
    InvoiceCorrection,
    ProductSellingPriceHistory,
    Sale,
)
from apps.trips.models import DeliveryControl, Trip, TripCustomerRefusal, TripStatusHistory
from apps.trips.services import DeliveryService, TripCostService, TripCustomerRefusalService
from apps.trips.tests import (
    _deliverable_trip,
    _fixtures_with_customer,
    _make_trip,
    _make_truck,
)

D = Decimal
STOCK = TripCustomerRefusal.Action.RETURN_TO_STOCK
CHANGE = TripCustomerRefusal.Action.CHANGE_CUSTOMER
TOTAL = D("40500000.00")  # 45 000 L x 900


def _deliver(fx, trip, *, verify=True, price="900.0000"):
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-10-11",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"], unit_selling_price=D(price),
    )
    if verify:
        DeliveryService.record_client_verification(
            trip_id=trip.id, received_qty=trip.quantity_loaded,
            verified_at=date(2026, 10, 11), actor=fx["admin_user"],
        )
    trip.refresh_from_db()
    return trip


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


def _price(fx, customer, price):
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=customer, price=D(price), changed_by=fx["admin_user"]
    )


def _outstanding(customer):
    return PaymentAllocationService.get_customer_outstanding(customer)


# --- return to stock (before delivery) --------------------------------------


@pytest.mark.django_db
def test_return_to_stock_at_the_client_sends_the_trip_to_the_company_stock():
    fx = _fixtures_with_customer("RS-1")
    trip = _deliverable_trip(fx, "TRIP-RS-1")  # ARRIVED_AT_CLIENT

    TripCustomerRefusalService.refuse(trip.id, STOCK, "Le client ne veut plus", fx["admin_user"])

    trip.refresh_from_db()
    assert trip.client_id is None
    assert trip.destination_type == Trip.DestinationType.COMPANY_STOCK
    assert trip.status == Trip.Status.ARRIVED_AT_COMPANY_STOCK
    assert TripStatusHistory.objects.filter(
        trip=trip, new_status=Trip.Status.ARRIVED_AT_COMPANY_STOCK
    ).exists()
    refusal = TripCustomerRefusal.objects.get(trip=trip)
    assert (refusal.action, refusal.previous_customer_id, refusal.new_customer_id) == (
        STOCK, fx["customer"].id, None,
    )
    assert not Sale.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_return_to_stock_before_arrival_keeps_the_status_and_reroutes_the_trip():
    fx = _fixtures_with_customer("RS-2")
    trip = _make_trip(fx, _make_truck("TRK-RS-2"), "TRIP-RS-2", customer_order=None)
    Trip.objects.filter(pk=trip.pk).update(
        client=fx["customer"], destination_type=Trip.DestinationType.CUSTOMER,
        status=Trip.Status.CUSTOMS,
    )

    TripCustomerRefusalService.refuse(trip.id, STOCK, "Refus", fx["admin_user"])

    trip.refresh_from_db()
    assert trip.status == Trip.Status.CUSTOMS
    assert trip.destination_type == Trip.DestinationType.COMPANY_STOCK
    from apps.trips.services import TripWorkflowService

    assert Trip.Status.ARRIVED_AT_COMPANY_STOCK in TripWorkflowService.get_allowed_targets(trip)
    assert Trip.Status.ARRIVED_AT_CLIENT not in TripWorkflowService.get_allowed_targets(trip)


@pytest.mark.django_db
def test_return_to_stock_is_refused_once_delivered():
    fx = _fixtures_with_customer("RS-3")
    trip = _deliver(fx, _deliverable_trip(fx, "TRIP-RS-3"))

    with pytest.raises(ValueError, match="déjà livré"):
        TripCustomerRefusalService.refuse(trip.id, STOCK, "Trop tard", fx["admin_user"])


@pytest.mark.django_db
def test_return_to_stock_detaches_the_customer_order():
    fx = _fixtures_with_customer("RS-4")
    order = CustomerOrder.objects.create(
        customer=fx["customer"], product=fx["product"], quantity_ordered=D("45000.00"),
        status=CustomerOrder.Status.CONFIRMED,
    )
    trip = _deliverable_trip(fx, "TRIP-RS-4")
    Trip.objects.filter(pk=trip.pk).update(client=None, customer_order=order)
    order.status = CustomerOrder.Status.IN_PROGRESS
    order.save(update_fields=["status"])

    TripCustomerRefusalService.refuse(trip.id, STOCK, "Commande annulée", fx["admin_user"])

    trip.refresh_from_db()
    order.refresh_from_db()
    assert trip.customer_order_id is None
    assert order.status == CustomerOrder.Status.CONFIRMED


# --- change customer before delivery ----------------------------------------


@pytest.mark.django_db
def test_change_before_delivery_bills_only_the_new_customer():
    fx = _fixtures_with_customer("CB-1")
    old = fx["customer"]
    new = Customer.objects.create(name="Nouveau CB-1")
    trip = _deliverable_trip(fx, "TRIP-CB-1")

    TripCustomerRefusalService.refuse(trip.id, CHANGE, "Refus", fx["admin_user"], customer_id=new.id)
    _deliver(fx, Trip.objects.get(pk=trip.pk))

    assert Invoice.objects.get(sale__trip=trip).sale.customer_id == new.id
    assert not Sale.objects.filter(customer=old).exists()
    assert _outstanding(old) == D("0.00")
    assert _outstanding(new) == TOTAL


# --- change customer after delivery ----------------------------------------


@pytest.mark.django_db
def test_change_after_delivery_moves_the_paid_invoice_at_the_new_customers_price():
    fx = _fixtures_with_customer("CA-1")
    old = fx["customer"]
    new = Customer.objects.create(name="Nouveau CA-1")
    _price(fx, new, "950.0000")
    trip = _deliver(fx, _deliverable_trip(fx, "TRIP-CA-1"))
    invoice = Invoice.objects.get(sale__trip=trip)
    payment = _receipt(fx["admin_user"], old, TOTAL, "CA1")
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID
    treasury_rows = TreasuryTransaction.objects.count()

    TripCustomerRefusalService.refuse(
        trip.id, CHANGE, "Le client a refusé le produit", fx["admin_user"], customer_id=new.id
    )

    invoice.refresh_from_db()
    trip.refresh_from_db()
    assert trip.client_id == new.id
    assert invoice.sale.customer_id == new.id
    assert invoice.sale.unit_selling_price == D("950.0000")
    assert invoice.total_amount == D("42750000.00")  # 45 000 x 950
    assert invoice.status == Invoice.Status.VALIDATED
    # The former customer keeps no invoice, his payment is his advance.
    assert not Invoice.objects.filter(sale__customer=old).exists()
    assert PaymentAllocationService.get_payment_unallocated_amount(payment) == TOTAL
    assert _outstanding(old) == -TOTAL
    assert _outstanding(new) == D("42750000.00")
    assert TreasuryTransaction.objects.count() == treasury_rows
    fields = set(InvoiceCorrection.objects.filter(invoice=invoice).values_list("field_name", flat=True))
    assert {"customer", "unit_selling_price"} <= fields
    refusal = TripCustomerRefusal.objects.get(trip=trip)
    assert refusal.invoice_number == invoice.invoice_number
    assert refusal.released_amount == TOTAL
    assert (refusal.previous_unit_price, refusal.new_unit_price) == (D("900.0000"), D("950.0000"))


@pytest.mark.django_db
def test_explicit_price_wins_and_becomes_the_new_customers_last_price():
    fx = _fixtures_with_customer("CA-2")
    new = Customer.objects.create(name="Nouveau CA-2")
    trip = _deliver(fx, _deliverable_trip(fx, "TRIP-CA-2"))

    TripCustomerRefusalService.refuse(
        trip.id, CHANGE, "Refus", fx["admin_user"], customer_id=new.id,
        unit_selling_price="880.5",
    )

    assert Sale.objects.get(trip=trip).unit_selling_price == D("880.5000")
    assert DeliveryService.get_latest_selling_price(fx["product"].id, new.id) == D("880.5000")


@pytest.mark.django_db
def test_released_payment_settles_the_old_customers_other_invoice_and_new_advance_pays():
    fx = _fixtures_with_customer("CA-3")
    old = fx["customer"]
    new = Customer.objects.create(name="Nouveau CA-3")
    moved = _deliver(fx, _deliverable_trip(fx, "TRIP-CA-3A"))
    _receipt(fx["admin_user"], old, TOTAL, "CA3A")
    kept = _deliver(fx, _deliverable_trip(fx, "TRIP-CA-3B"))
    new_advance = _receipt(fx["admin_user"], new, D("50000000.00"), "CA3B")

    TripCustomerRefusalService.refuse(
        moved.id, CHANGE, "Réattribution", fx["admin_user"], customer_id=new.id,
        unit_selling_price="900",
    )

    moved_invoice = Invoice.objects.get(sale__trip=moved)
    kept_invoice = Invoice.objects.get(sale__trip=kept)
    assert kept_invoice.status == Invoice.Status.PAID  # released credit redistributed
    assert moved_invoice.status == Invoice.Status.PAID  # paid by the new advance
    assert moved_invoice.allocations.get().payment_id == new_advance.id
    assert _outstanding(old) == D("0.00")
    assert _outstanding(new) == TOTAL - D("50000000.00")


@pytest.mark.django_db
@pytest.mark.parametrize("refused_index", [0, 1])
def test_grouped_invoice_is_split_and_the_refused_trip_gets_its_own_invoice(refused_index):
    fx = _fixtures_with_customer(f"GR-{refused_index}")
    old = fx["customer"]
    new = Customer.objects.create(name=f"Nouveau GR-{refused_index}")
    trips = [_deliverable_trip(fx, f"TRIP-GR{refused_index}-{i}") for i in range(2)]
    TripCostService.assign_customers_group_for_sale([t.id for t in trips], old.id, fx["admin_user"])
    trips = [_deliver(fx, Trip.objects.get(pk=t.pk)) for t in trips]
    group_invoice = Invoice.objects.get(sale__trip=trips[0])
    assert group_invoice.total_amount == TOTAL * 2
    _receipt(fx["admin_user"], old, TOTAL * 2, f"GR{refused_index}")
    refused, kept = trips[refused_index], trips[1 - refused_index]

    TripCustomerRefusalService.refuse(
        refused.id, CHANGE, "Un des camions refusé", fx["admin_user"], customer_id=new.id,
        unit_selling_price="900",
    )

    old_invoice = Invoice.objects.get(pk=group_invoice.pk)
    new_invoice = Sale.objects.get(trip=refused).billing_invoice
    assert new_invoice.pk != old_invoice.pk
    assert [s.trip_id for s in old_invoice.all_sales] == [kept.id]
    assert old_invoice.total_amount == TOTAL
    assert old_invoice.status == Invoice.Status.PAID
    assert new_invoice.sale.customer_id == new.id
    assert new_invoice.status == Invoice.Status.VALIDATED
    assert _outstanding(old) == -TOTAL  # paid two trips, kept one: one in advance
    assert _outstanding(new) == TOTAL
    assert InvoiceCorrection.objects.filter(invoice=old_invoice, field_name="trip_removed").exists()


@pytest.mark.django_db
def test_refusing_the_last_undelivered_trip_of_a_group_bills_the_others():
    fx = _fixtures_with_customer("GW-1")
    trips = [_deliverable_trip(fx, f"TRIP-GW-{i}") for i in range(2)]
    TripCostService.assign_customers_group_for_sale([t.id for t in trips], fx["customer"].id, fx["admin_user"])
    delivered = _deliver(fx, Trip.objects.get(pk=trips[0].pk), verify=False)
    assert Sale.objects.get(trip=delivered).billing_invoice is None  # waits for its group

    TripCustomerRefusalService.refuse(trips[1].id, STOCK, "Refus", fx["admin_user"])

    invoice = Sale.objects.get(trip=delivered).billing_invoice
    assert invoice is not None and invoice.total_amount == TOTAL


# --- guards and API ---------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["no_customer", "same", "inactive", "no_reason", "blocked", "cancelled"])
def test_refusal_guards(case):
    fx = _fixtures_with_customer(f"RG-{case}")
    trip = _deliverable_trip(fx, f"TRIP-RG-{case}")
    target = Customer.objects.create(name=f"Cible {case}")
    reason = "Motif"
    if case == "no_customer":
        Trip.objects.filter(pk=trip.pk).update(client=None)
    elif case == "same":
        target = fx["customer"]
    elif case == "inactive":
        Customer.objects.filter(pk=target.pk).update(is_active=False)
    elif case == "no_reason":
        reason = " "
    elif case == "blocked":
        Trip.objects.filter(pk=trip.pk).update(status=Trip.Status.BLOCKED)
    elif case == "cancelled":
        Trip.objects.filter(pk=trip.pk).update(status=Trip.Status.CANCELLED)

    with pytest.raises(ValueError):
        TripCustomerRefusalService.refuse(trip.id, CHANGE, reason, fx["admin_user"], customer_id=target.id)
    assert not TripCustomerRefusal.objects.exists()


@pytest.mark.django_db
def test_api_preview_refuse_and_history():
    fx = _fixtures_with_customer("RA-1")
    old = fx["customer"]
    new = Customer.objects.create(name="Nouveau RA-1")
    _price(fx, new, "950.0000")
    trip = _deliver(fx, _deliverable_trip(fx, "TRIP-RA-1"))
    _receipt(fx["admin_user"], old, D("10000000.00"), "RA1")
    api = _api(fx["admin_user"])

    preview = api.get(
        f"/api/trips/{trip.id}/customer-refusal-preview/?action=CHANGE_CUSTOMER&customer={new.id}"
    )
    assert preview.status_code == 200, preview.data
    data = preview.data
    assert data["delivered"] is True
    assert data["suggested_unit_price"] == "950.0000"
    assert data["new_amount"] == "42750000.00"
    assert data["released_payments"] == "10000000.00"
    assert data["old_customer"]["balance_after"] == "-10000000.00"
    assert data["new_customer"]["balance_after"] == "42750000.00"

    stock = api.get(f"/api/trips/{trip.id}/customer-refusal-preview/?action=RETURN_TO_STOCK")
    assert stock.status_code == 400

    response = api.post(
        f"/api/trips/{trip.id}/customer-refusal/",
        {"action": "CHANGE_CUSTOMER", "customer": new.id, "reason": "Refus", "unit_selling_price": "950"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["client"] == new.id

    history = api.get(f"/api/trips/{trip.id}/customer-refusals/")
    assert history.status_code == 200
    assert history.data[0]["previous_customer"] == old.name
    assert history.data[0]["new_customer"] == new.name


@pytest.mark.django_db
def test_invoiced_trip_refusal_needs_the_sales_validate_tier():
    fx = _fixtures_with_customer("RP-1")
    new = Customer.objects.create(name="Nouveau RP-1")
    role = Role.objects.create(
        name="Opérations RP", permissions={"operations": ["view", "edit"], "sales": ["view"]}
    )
    user = User.objects.create_user(phone="+2230009912", pin="1234", role=role)
    api = _api(user)
    undelivered = _deliverable_trip(fx, "TRIP-RP-1A")
    delivered = _deliver(fx, _deliverable_trip(fx, "TRIP-RP-1B"))

    ok = api.post(
        f"/api/trips/{undelivered.id}/customer-refusal/",
        {"action": "RETURN_TO_STOCK", "reason": "Refus"},
        format="json",
    )
    assert ok.status_code == 200, ok.data
    denied = api.post(
        f"/api/trips/{delivered.id}/customer-refusal/",
        {"action": "CHANGE_CUSTOMER", "customer": new.id, "reason": "Refus"},
        format="json",
    )
    assert denied.status_code == 403

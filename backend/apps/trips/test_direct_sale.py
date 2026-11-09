# Direct client attribution from Ventes (docs/superpowers/specs/2026-11-02-
# attribution-client-directe-design.md): link + arrive + (optional) delivery +
# walk-in cash payment in ONE transaction.

from decimal import Decimal

import pytest

from apps.customers.models import Customer
from apps.finance.models import CashAccount, CustomerPayment, TreasuryTransaction
from apps.finance.services import PaymentAllocationService
from apps.sales.models import Sale
from apps.trips.direct_sale import DirectSaleService
from apps.trips.models import Trip
from apps.trips.services import SaleBelowCostConfirmationRequired
from apps.trips.tests import _make_trip, _make_truck, _setup_fixtures

D = Decimal
PRICE = D("800.0000")  # supplier price in the fixtures is 600


def _stocked_trip(fx, code, status=Trip.Status.STOCKED):
    return _make_trip(fx, _make_truck(f"{code}-T"), f"TRIP-{code}", status=status)


def _cash(destination="CASH"):
    account = CashAccount.objects.create(name="Caisse DS")
    return {"destination": destination, "cash_account": account.id}


def _assign(fx, trips, **overrides):
    kwargs = dict(
        customer_id=None,
        walk_in_name=None,
        unit_selling_price=PRICE,
        received_quantities=None,
        payment_destination=None,
        confirm_loss=False,
        actor=fx["admin_user"],
    )
    kwargs.update(overrides)
    return DirectSaleService.assign_and_arrive([t.id for t in trips], **kwargs)


@pytest.mark.django_db
def test_registered_customer_deferred_quantity():
    fx = _setup_fixtures("DS1")
    trip = _stocked_trip(fx, "DS1")
    customer = Customer.objects.create(name="Client A")

    _assign(fx, [trip], customer_id=customer.id)

    trip.refresh_from_db()
    assert trip.client_id == customer.id
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT
    assert trip.pending_unit_selling_price == PRICE
    assert not Sale.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_arrives_from_border_customs_and_company_stock_too():
    fx = _setup_fixtures("DS1B")
    customer = Customer.objects.create(name="Client A")
    # BORDER = "Douane" (the earliest status a client can be attributed from), CUSTOMS = "Ts".
    for index, status in enumerate(
        (Trip.Status.BORDER, Trip.Status.CUSTOMS, Trip.Status.ARRIVED_AT_COMPANY_STOCK)
    ):
        trip = _stocked_trip(fx, f"DS1B{index}", status=status)
        _assign(fx, [trip], customer_id=customer.id)
        trip.refresh_from_db()
        assert trip.status == Trip.Status.ARRIVED_AT_CLIENT


@pytest.mark.django_db
def test_registered_customer_with_quantity_creates_invoice_for_received_quantity():
    fx = _setup_fixtures("DS2")
    trip = _stocked_trip(fx, "DS2")  # loaded 45000
    customer = Customer.objects.create(name="Client A")

    _assign(fx, [trip], customer_id=customer.id, received_quantities={trip.id: D("44900.00")})

    trip.refresh_from_db()
    sale = Sale.objects.get(trip=trip)
    assert trip.status == Trip.Status.COMPLETED
    assert trip.pending_unit_selling_price is None
    assert sale.delivered_quantity == D("44900.00")
    assert sale.billing_invoice.total_amount == D("44900.00") * PRICE


@pytest.mark.django_db
def test_walk_in_creates_hidden_customer_and_full_cash_payment():
    fx = _setup_fixtures("DS3")
    trip = _stocked_trip(fx, "DS3")

    _assign(
        fx,
        [trip],
        walk_in_name="  Moussa  ",
        received_quantities={trip.id: D("45000.00")},
        payment_destination=_cash(),
    )

    trip.refresh_from_db()
    walk_in = trip.client
    assert walk_in.name == "Moussa" and walk_in.is_walk_in
    invoice = Sale.objects.get(trip=trip).billing_invoice
    payment = CustomerPayment.objects.get(customer=walk_in)
    assert payment.amount == invoice.total_amount
    assert payment.method == CustomerPayment.Method.CASH
    assert PaymentAllocationService.get_invoice_outstanding(invoice) == D("0")
    assert TreasuryTransaction.objects.filter(
        type=TreasuryTransaction.Type.MONEY_IN, amount=invoice.total_amount
    ).exists()


@pytest.mark.django_db
def test_walk_in_deferred_then_confirm_pays_on_confirm():
    fx = _setup_fixtures("DS4")
    trip = _stocked_trip(fx, "DS4")

    _assign(fx, [trip], walk_in_name="Moussa")
    assert not CustomerPayment.objects.exists()

    DirectSaleService.confirm_received_quantity(
        trip.id,
        D("45000.00"),
        payment_destination=_cash(),
        confirm_loss=False,
        actor=fx["admin_user"],
    )

    trip.refresh_from_db()
    invoice = Sale.objects.get(trip=trip).billing_invoice
    assert trip.status == Trip.Status.COMPLETED and trip.pending_unit_selling_price is None
    assert CustomerPayment.objects.get(customer=trip.client).amount == invoice.total_amount
    assert PaymentAllocationService.get_invoice_outstanding(invoice) == D("0")


@pytest.mark.django_db
def test_group_invoice_and_payment_only_after_last_trip():
    fx = _setup_fixtures("DS5")
    first, second = _stocked_trip(fx, "DS5A"), _stocked_trip(fx, "DS5B")
    admin = fx["admin_user"]

    _assign(fx, [first, second], walk_in_name="Moussa")
    pay = _cash()
    DirectSaleService.confirm_received_quantity(
        first.id, D("45000.00"), payment_destination=pay, confirm_loss=False, actor=admin
    )
    assert not CustomerPayment.objects.exists()
    assert Sale.objects.get(trip=first).billing_invoice is None

    DirectSaleService.confirm_received_quantity(
        second.id, D("40000.00"), payment_destination=pay, confirm_loss=False, actor=admin
    )
    invoice = Sale.objects.get(trip=first).billing_invoice
    assert invoice.total_amount == (D("45000.00") + D("40000.00")) * PRICE
    assert CustomerPayment.objects.get().amount == invoice.total_amount
    assert PaymentAllocationService.get_invoice_outstanding(invoice) == D("0")


@pytest.mark.django_db
def test_below_cost_without_confirm_loss_rolls_back():
    fx = _setup_fixtures("DS6")
    trip = _stocked_trip(fx, "DS6")
    customer = Customer.objects.create(name="Client A")

    with pytest.raises(SaleBelowCostConfirmationRequired):
        _assign(
            fx,
            [trip],
            customer_id=customer.id,
            unit_selling_price=D("100.0000"),
            received_quantities={trip.id: D("45000.00")},
        )

    trip.refresh_from_db()
    assert trip.client_id is None
    assert trip.status == Trip.Status.STOCKED
    assert trip.pending_unit_selling_price is None


@pytest.mark.django_db
def test_below_cost_with_confirm_loss_goes_through():
    fx = _setup_fixtures("DS6B")
    trip = _stocked_trip(fx, "DS6B")
    customer = Customer.objects.create(name="Client A")

    _assign(
        fx,
        [trip],
        customer_id=customer.id,
        unit_selling_price=D("100.0000"),
        received_quantities={trip.id: D("45000.00")},
        confirm_loss=True,
    )

    assert Sale.objects.get(trip=trip).unit_selling_price == D("100.0000")


@pytest.mark.django_db
def test_walk_in_sale_writes_no_selling_price_history():
    from apps.sales.models import ProductSellingPriceHistory

    fx = _setup_fixtures("DS6C")
    trip = _stocked_trip(fx, "DS6C")

    _assign(
        fx,
        [trip],
        walk_in_name="Moussa",
        received_quantities={trip.id: D("45000.00")},
        payment_destination=_cash(),
    )

    assert not ProductSellingPriceHistory.objects.filter(customer=trip.client_id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        {},  # neither customer nor walk-in
        {"customer_id": -1, "walk_in_name": "X"},  # both
        {"walk_in_name": "   "},  # blank name
    ],
)
def test_customer_choice_validation(overrides):
    fx = _setup_fixtures("DS7")
    trip = _stocked_trip(fx, "DS7")

    with pytest.raises(ValueError):
        _assign(fx, [trip], **overrides)

    trip.refresh_from_db()
    assert trip.client_id is None and trip.status == Trip.Status.STOCKED


@pytest.mark.django_db
def test_trip_not_in_assignable_status_is_rejected():
    fx = _setup_fixtures("DS8")
    trip = _stocked_trip(fx, "DS8", status=Trip.Status.LOADED)
    customer = Customer.objects.create(name="Client A")

    with pytest.raises(ValueError):
        _assign(fx, [trip], customer_id=customer.id)

    trip.refresh_from_db()
    assert trip.client_id is None and trip.status == Trip.Status.LOADED


@pytest.mark.django_db
def test_trip_with_a_sale_is_rejected():
    fx = _setup_fixtures("DS9")
    trip = _stocked_trip(fx, "DS9")
    customer = Customer.objects.create(name="Client A")
    _assign(fx, [trip], customer_id=customer.id, received_quantities={trip.id: D("45000.00")})

    with pytest.raises(ValueError):
        _assign(fx, [trip], customer_id=customer.id)


@pytest.mark.django_db
def test_walk_in_quantity_without_payment_destination_changes_nothing():
    fx = _setup_fixtures("DS10")
    trip = _stocked_trip(fx, "DS10")

    with pytest.raises(ValueError):
        _assign(fx, [trip], walk_in_name="Moussa", received_quantities={trip.id: D("45000.00")})

    trip.refresh_from_db()
    assert trip.client_id is None and trip.status == Trip.Status.STOCKED
    assert not Customer.objects.filter(is_walk_in=True).exists()


@pytest.mark.django_db
def test_reassigning_a_customer_clears_the_parked_price():
    from apps.trips.services import TripCostService

    fx = _setup_fixtures("DS11")
    trip = _stocked_trip(fx, "DS11")
    customer = Customer.objects.create(name="Client A")
    _assign(fx, [trip], customer_id=customer.id)

    # A new assignment (via the old services) must not keep a stale price.
    trip.status = Trip.Status.STOCKED
    trip.save(update_fields=["status"])
    TripCostService.assign_customer_for_sale(trip.id, customer.id, fx["admin_user"])

    trip.refresh_from_db()
    assert trip.pending_unit_selling_price is None


# --- API -------------------------------------------------------------------


def _api(user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_direct_sale_endpoint_registered_and_walk_in():
    fx = _setup_fixtures("DS20")
    registered, walk = _stocked_trip(fx, "DS20A"), _stocked_trip(fx, "DS20B")
    customer = Customer.objects.create(name="Client A")
    api = _api(fx["admin_user"])

    first = api.post(
        "/api/trips/direct-sale/",
        {"trips": [registered.id], "customer": customer.id, "unit_selling_price": "800.0000"},
        format="json",
    )
    assert first.status_code == 200, first.data
    assert first.data[0]["status"] == "ARRIVED_AT_CLIENT"
    assert first.data[0]["pending_unit_selling_price"] == "800.0000"

    cash = _cash()
    second = api.post(
        "/api/trips/direct-sale/",
        {
            "trips": [walk.id],
            "walk_in_name": "Moussa",
            "unit_selling_price": "800.0000",
            "received_quantities": {str(walk.id): "45000.00"},
            "payment_destination": cash,
        },
        format="json",
    )
    assert second.status_code == 200, second.data
    assert second.data[0]["status"] == "COMPLETED"
    assert second.data[0]["client_detail"]["is_walk_in"] is True
    assert CustomerPayment.objects.count() == 1


@pytest.mark.django_db
def test_direct_sale_endpoint_forbidden_without_operations_edit():
    from apps.accounts.models import Role, User

    fx = _setup_fixtures("DS21")
    trip = _stocked_trip(fx, "DS21")
    role = Role.objects.get(name=Role.NAME_MANAGEMENT)  # operations: view/export only
    viewer = User.objects.create_user(phone="+2220009921", pin="1234", role=role)

    response = _api(viewer).post(
        "/api/trips/direct-sale/",
        {"trips": [trip.id], "walk_in_name": "X", "unit_selling_price": "800"},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_direct_sale_endpoint_rejects_bad_choice_with_400():
    fx = _setup_fixtures("DS22")
    trip = _stocked_trip(fx, "DS22")

    response = _api(fx["admin_user"]).post(
        "/api/trips/direct-sale/",
        {"trips": [trip.id], "unit_selling_price": "800"},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_confirm_received_quantity_endpoint():
    fx = _setup_fixtures("DS23")
    trip = _stocked_trip(fx, "DS23")
    customer = Customer.objects.create(name="Client A")
    _assign(fx, [trip], customer_id=customer.id)

    response = _api(fx["admin_user"]).post(
        f"/api/trips/{trip.id}/confirm-received-quantity/",
        {"received_quantity": "44000.00"},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["status"] == "COMPLETED"
    assert Sale.objects.get(trip=trip).delivered_quantity == D("44000.00")


@pytest.mark.django_db
def test_direct_sale_below_cost_returns_confirmation_error():
    fx = _setup_fixtures("DS24")
    trip = _stocked_trip(fx, "DS24")
    customer = Customer.objects.create(name="Client A")
    payload = {
        "trips": [trip.id],
        "customer": customer.id,
        "unit_selling_price": "100.0000",
        "received_quantities": {str(trip.id): "45000.00"},
    }
    api = _api(fx["admin_user"])

    refused = api.post("/api/trips/direct-sale/", payload, format="json")
    assert refused.status_code == 422
    trip.refresh_from_db()
    assert trip.client_id is None

    accepted = api.post("/api/trips/direct-sale/", {**payload, "confirm_loss": True}, format="json")
    assert accepted.status_code == 200, accepted.data


@pytest.mark.django_db
def test_walk_in_invoice_ends_up_paid_not_draft():
    from apps.sales.models import Invoice

    fx = _setup_fixtures("DS30")
    trip = _stocked_trip(fx, "DS30")

    _assign(
        fx,
        [trip],
        walk_in_name="Moussa",
        received_quantities={trip.id: D("45000.00")},
        payment_destination=_cash(),
    )

    invoice = Sale.objects.get(trip=trip).billing_invoice
    assert invoice.status == Invoice.Status.PAID


@pytest.mark.django_db
def test_customer_refusal_clears_the_parked_price():
    from apps.trips.services import TripCustomerRefusalService

    fx = _setup_fixtures("DS31")
    trip = _stocked_trip(fx, "DS31")
    first, second = Customer.objects.create(name="A"), Customer.objects.create(name="B")
    _assign(fx, [trip], customer_id=first.id)

    TripCustomerRefusalService.refuse(
        trip.id, "CHANGE_CUSTOMER", "refus", fx["admin_user"], customer_id=second.id
    )

    trip.refresh_from_db()
    assert trip.client_id == second.id
    assert trip.pending_unit_selling_price is None


@pytest.mark.django_db
def test_quantity_entered_here_is_the_final_client_verification():
    from apps.sales.models import Invoice
    from apps.trips.models import DeliveryControl

    fx = _setup_fixtures("DS40")
    trip = _stocked_trip(fx, "DS40")
    customer = Customer.objects.create(name="Client A")

    _assign(fx, [trip], customer_id=customer.id, received_quantities={trip.id: D("44800")})

    trip.refresh_from_db()
    invoice = Sale.objects.get(trip=trip).billing_invoice
    assert trip.status == Trip.Status.COMPLETED
    assert invoice.status == Invoice.Status.VALIDATED
    assert invoice.total_amount == D("44800") * PRICE
    control = DeliveryControl.objects.get(trip=trip)
    assert control.verified_at is not None and control.received_quantity == D("44800")


@pytest.mark.django_db
def test_no_second_client_verification_is_possible_afterwards():
    from apps.trips.services import DeliveryService

    fx = _setup_fixtures("DS41")
    trip = _stocked_trip(fx, "DS41")
    customer = Customer.objects.create(name="Client A")
    _assign(fx, [trip], customer_id=customer.id, received_quantities={trip.id: D("44800")})

    with pytest.raises(ValueError):
        DeliveryService.record_client_verification(
            trip.id, D("44800"), timezone_today(), fx["admin_user"]
        )


def timezone_today():
    from django.utils import timezone

    return timezone.localdate()


@pytest.mark.django_db
def test_shortage_is_charged_to_the_transporter_exactly_once():
    from apps.finance.models import TransportDeduction

    fx = _setup_fixtures("DS42")
    trip = _stocked_trip(fx, "DS42")
    customer = Customer.objects.create(name="Client A")

    _assign(fx, [trip], customer_id=customer.id, received_quantities={trip.id: D("44800")})

    deductions = TransportDeduction.objects.filter(trip=trip)
    assert deductions.count() == 1
    assert deductions.get().chargeable_quantity == D("100.00")  # 200 L short, 100 L tolerance


@pytest.mark.django_db
def test_group_invoice_is_validated_once_every_trip_is_verified():
    from apps.sales.models import Invoice

    fx = _setup_fixtures("DS43")
    first, second = _stocked_trip(fx, "DS43A"), _stocked_trip(fx, "DS43B")
    customer = Customer.objects.create(name="Client A")
    admin = fx["admin_user"]
    _assign(fx, [first, second], customer_id=customer.id)

    DirectSaleService.confirm_received_quantity(
        first.id, D("45000"), payment_destination=None, confirm_loss=False, actor=admin
    )
    DirectSaleService.confirm_received_quantity(
        second.id, D("44000"), payment_destination=None, confirm_loss=False, actor=admin
    )

    invoice = Sale.objects.get(trip=first).billing_invoice
    assert invoice.status == Invoice.Status.VALIDATED
    assert invoice.total_amount == (D("45000") + D("44000")) * PRICE

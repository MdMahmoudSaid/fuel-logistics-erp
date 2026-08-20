# AuditLog / AuditableModel tests (docs/PHASE_6_PLAN.md Etape 1/6;
# ERP_Implementation_Experience_Guide.md Section 9.9; Spec Section 39).

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.audit.context import bind_current_request, clear_current_request
from apps.audit.exceptions import HardDeleteBlocked
from apps.audit.models import AuditLog
from apps.audit.services import AuditLogService
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import (
    CustomerPayment,
    Expense,
    SupplierPayment,
    TransportDeduction,
    TreasuryTransaction,
    CashAccount,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import Invoice, Sale
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import DeliveryControl, Trip


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        email=f"admin-audit-{suffix}@example.com", password="testpass123", role=admin_role
    )


def _make_supplier_order(suffix, status=SupplierOrder.Status.DRAFT, user=None):
    admin_user = user or _make_admin(suffix)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    order = SupplierOrder(
        reference=f"SO-AUDIT-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        status=status,
        created_by=admin_user,
    )
    order.save(user=admin_user)
    return admin_user, order


# ---------------------------------------------------------------------------
# AuditLog immutability
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auditlog_cannot_be_edited():
    _admin_user, order = _make_supplier_order("IMMUT-EDIT")
    log = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(SupplierOrder), object_id=order.id
    ).latest("id")

    with pytest.raises(ValueError):
        log.save()


@pytest.mark.django_db
def test_auditlog_cannot_be_deleted():
    _admin_user, order = _make_supplier_order("IMMUT-DEL")
    log = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(SupplierOrder), object_id=order.id
    ).latest("id")

    with pytest.raises(ValueError):
        log.delete()


# ---------------------------------------------------------------------------
# Automatic capture on create/update (AuditableModel via SupplierOrder)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_creating_an_audited_model_writes_a_create_log_with_no_previous_value():
    admin_user, order = _make_supplier_order("CREATE")

    log = AuditLog.objects.get(
        content_type=ContentType.objects.get_for_model(SupplierOrder), object_id=order.id
    )
    assert log.action == AuditLog.Action.CREATE
    assert log.previous_value is None
    assert log.new_value["unit_price"] == "600.0000"
    assert log.user_id == admin_user.id


@pytest.mark.django_db
def test_updating_a_tracked_price_field_writes_an_update_log_with_diff():
    admin_user, order = _make_supplier_order("PRICE", status=SupplierOrder.Status.CONFIRMED)

    order.unit_price = Decimal("650.0000")
    order.save(user=admin_user)

    log = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(SupplierOrder),
        object_id=order.id,
        action=AuditLog.Action.UPDATE,
    ).latest("id")
    assert log.previous_value["unit_price"] == "600.0000"
    assert log.new_value["unit_price"] == "650.0000"


@pytest.mark.django_db
def test_saving_with_no_actual_field_change_does_not_write_a_new_log():
    admin_user, order = _make_supplier_order("NOOP")
    logs_before = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(SupplierOrder), object_id=order.id
    ).count()

    order.save(user=admin_user)

    logs_after = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(SupplierOrder), object_id=order.id
    ).count()
    assert logs_after == logs_before


@pytest.mark.django_db
def test_moving_status_to_cancelled_is_logged_as_a_cancel_action():
    admin_user, order = _make_supplier_order("CANCEL", status=SupplierOrder.Status.CONFIRMED)

    order.status = SupplierOrder.Status.CANCELLED
    order.save(user=admin_user)

    log = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(SupplierOrder), object_id=order.id
    ).latest("id")
    assert log.action == AuditLog.Action.CANCEL
    assert log.previous_value["status"] == "CONFIRMED"
    assert log.new_value["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Hard-delete blocking (Spec Section 39 / plan Etape 1)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_deleting_a_draft_record_is_allowed_and_logged():
    admin_user, order = _make_supplier_order("DEL-DRAFT", status=SupplierOrder.Status.DRAFT)
    order_id = order.id

    order.delete(user=admin_user)

    assert not SupplierOrder.objects.filter(pk=order_id).exists()
    log = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(SupplierOrder),
        object_id=order_id,
        action=AuditLog.Action.DELETE,
    ).latest("id")
    assert log.new_value == {"deleted": True}
    assert log.previous_value["unit_price"] == "600.0000"


@pytest.mark.django_db
def test_deleting_a_confirmed_record_is_blocked():
    admin_user, order = _make_supplier_order("DEL-CONFIRMED", status=SupplierOrder.Status.CONFIRMED)

    with pytest.raises(HardDeleteBlocked):
        order.delete(user=admin_user)

    assert SupplierOrder.objects.filter(pk=order.id).exists()


# ---------------------------------------------------------------------------
# Actor resolution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_audit_log_has_no_user_without_request_context_or_explicit_user():
    admin_user = _make_admin("NOUSER")
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Supplier NOUSER", country="Senegal")
    order = SupplierOrder(
        reference="SO-AUDIT-NOUSER",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        created_by=admin_user,
    )
    order.save()  # no user kwarg, no bound request

    log = AuditLog.objects.get(
        content_type=ContentType.objects.get_for_model(SupplierOrder), object_id=order.id
    )
    assert log.user is None


@pytest.mark.django_db
def test_current_request_middleware_attributes_the_log_to_the_authenticated_user():
    admin_user = _make_admin("API")
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Supplier API", country="Senegal")

    client = APIClient()
    client.force_authenticate(admin_user)

    response = client.post(
        "/api/supplier-orders/",
        {
            "reference": "SO-AUDIT-API",
            "supplier": supplier.id,
            "product": product.id,
            "purchase_date": "2026-08-18",
            "quantity_litres": "500000.00",
            "unit_price": "600.0000",
        },
    )
    assert response.status_code == 201, response.data

    log = AuditLog.objects.get(
        content_type=ContentType.objects.get_for_model(SupplierOrder), object_id=response.data["id"]
    )
    assert log.action == AuditLog.Action.CREATE
    assert log.user_id == admin_user.id


class TestAuditLogServiceFallback:
    def test_record_uses_explicit_user_over_thread_local(self, db):
        admin_user = _make_admin("EXPLICIT")
        other_user = _make_admin("OTHER")

        class _FakeRequest:
            user = other_user

        bind_current_request(_FakeRequest())
        try:
            log = AuditLogService.record(
                content_type=ContentType.objects.get_for_model(User),
                object_id=admin_user.id,
                action=AuditLog.Action.CREATE,
                previous_value=None,
                new_value={"email": admin_user.email},
                user=admin_user,
            )
        finally:
            clear_current_request()

        assert log.user_id == admin_user.id


# ---------------------------------------------------------------------------
# Wiring smoke tests across the other Etape 1 target models: "quantites,
# prix, statuts de factures et paiements, pertes, mouvements de tresorerie"
# (docs/PHASE_6_PLAN.md Etape 1; guide Section 9.9).
# ---------------------------------------------------------------------------


def _audit_logs_for(instance):
    return AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(type(instance)), object_id=instance.pk
    )


def _make_trip_with_sale(suffix):
    admin_user = _make_admin(suffix)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-AUDITWIRE-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-AUDITWIRE-{suffix}",
        supplier_order=supplier_order,
        authorized_quantity=Decimal("500000.00"),
        issue_date="2026-08-18",
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-AUDITWIRE-{suffix}",
        tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER",
        capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-AUDITWIRE-{suffix}",
        truck=truck,
        transporter=transporter,
        supplier=supplier,
        supplier_order=supplier_order,
        cession_letter=cession,
        product=product,
        quantity_loaded=Decimal("45000.00"),
        loading_date="2026-08-18",
        bl_reference=f"BL-AUDITWIRE-{suffix}",
        status=Trip.Status.DELIVERED,
        created_by=admin_user,
    )
    customer = Customer.objects.create(name=f"Client {suffix}")
    sale = Sale.objects.create(
        trip=trip,
        customer=customer,
        product=product,
        delivered_quantity=Decimal("44850.00"),
        unit_selling_price=Decimal("650.0000"),
    )
    return admin_user, trip, customer, sale


@pytest.mark.django_db
def test_creating_a_sale_writes_a_create_audit_log_and_cannot_be_hard_deleted():
    _admin_user, _trip, _customer, sale = _make_trip_with_sale("SALE")

    logs = _audit_logs_for(sale)
    assert logs.filter(action=AuditLog.Action.CREATE).exists()

    with pytest.raises(HardDeleteBlocked):
        sale.delete()


@pytest.mark.django_db
def test_cancelling_a_validated_invoice_is_logged_as_cancel_and_never_hard_deleted():
    """Spec Section 39 / plan Etape 6: cancelling a validated invoice must
    flip its status to CANCELLED (never delete the row), with an AuditLog
    entry tracing the previous/new status."""
    admin_user, _trip, _customer, sale = _make_trip_with_sale("INV-CANCEL")
    invoice = Invoice.objects.create(
        invoice_number="INV-AUDIT-CANCEL",
        sale=sale,
        status=Invoice.Status.VALIDATED,
        total_amount=sale.subtotal,
        issued_date="2026-08-18",
    )

    invoice.status = Invoice.Status.CANCELLED
    invoice.save(user=admin_user)

    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.CANCELLED

    log = _audit_logs_for(invoice).latest("id")
    assert log.action == AuditLog.Action.CANCEL
    assert log.previous_value["status"] == "VALIDATED"
    assert log.new_value["status"] == "CANCELLED"

    with pytest.raises(HardDeleteBlocked):
        invoice.delete()
    assert Invoice.objects.filter(pk=invoice.pk).exists()


@pytest.mark.django_db
def test_draft_invoice_can_be_hard_deleted_and_logged():
    _admin_user, _trip, _customer, sale = _make_trip_with_sale("INV-DRAFT")
    invoice = Invoice.objects.create(
        invoice_number="INV-AUDIT-DRAFT",
        sale=sale,
        total_amount=sale.subtotal,
        issued_date="2026-08-18",
    )
    assert invoice.status == Invoice.Status.DRAFT

    invoice.delete()

    assert not Invoice.objects.filter(pk=invoice.pk).exists()


@pytest.mark.django_db
def test_creating_an_expense_writes_a_create_audit_log_and_cannot_be_hard_deleted():
    expense = Expense.objects.create(
        category=Expense.Category.ROAD,
        amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )

    assert _audit_logs_for(expense).filter(action=AuditLog.Action.CREATE).exists()
    with pytest.raises(HardDeleteBlocked):
        expense.delete()


@pytest.mark.django_db
def test_cancelling_an_expense_is_logged_as_cancel():
    expense = Expense.objects.create(
        category=Expense.Category.ROAD,
        amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
    )

    expense.status = Expense.Status.CANCELLED
    expense.save()

    log = _audit_logs_for(expense).latest("id")
    assert log.action == AuditLog.Action.CANCEL


@pytest.mark.django_db
def test_creating_a_customer_payment_writes_a_create_audit_log_and_cannot_be_hard_deleted():
    admin_user = _make_admin("CUSTPAY")
    customer = Customer.objects.create(name="Client CUSTPAY")
    cash_account = CashAccount.objects.create(name="Main Cash CUSTPAY")

    payment = CustomerPayment.objects.create(
        customer=customer,
        amount=Decimal("100000.00"),
        payment_date="2026-08-18",
        method=CustomerPayment.Method.CASH,
        cash_account=cash_account,
        recorded_by=admin_user,
    )

    assert _audit_logs_for(payment).filter(action=AuditLog.Action.CREATE).exists()
    with pytest.raises(HardDeleteBlocked):
        payment.delete()


@pytest.mark.django_db
def test_creating_a_supplier_payment_writes_a_create_audit_log_and_cannot_be_hard_deleted():
    admin_user = _make_admin("SUPPAY")
    supplier = Supplier.objects.create(name="Supplier SUPPAY", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash SUPPAY")

    payment = SupplierPayment.objects.create(
        supplier=supplier,
        amount=Decimal("100000.00"),
        payment_date="2026-08-18",
        method=SupplierPayment.Method.CASH,
        cash_account=cash_account,
        recorded_by=admin_user,
    )

    assert _audit_logs_for(payment).filter(action=AuditLog.Action.CREATE).exists()
    with pytest.raises(HardDeleteBlocked):
        payment.delete()


@pytest.mark.django_db
def test_creating_a_treasury_transaction_writes_a_create_audit_log_and_cannot_be_hard_deleted():
    admin_user = _make_admin("TREASURY")
    cash_account = CashAccount.objects.create(name="Main Cash TREASURY")

    txn = TreasuryTransaction.objects.create(
        cash_account=cash_account,
        type=TreasuryTransaction.Type.MONEY_IN,
        amount=Decimal("100000.00"),
        date="2026-08-18",
        recorded_by=admin_user,
    )

    assert _audit_logs_for(txn).filter(action=AuditLog.Action.CREATE).exists()
    with pytest.raises(HardDeleteBlocked):
        txn.delete()


@pytest.mark.django_db
def test_draft_transport_deduction_can_be_deleted_but_validated_one_is_blocked():
    admin_user, trip, _customer, _sale = _make_trip_with_sale("DEDUCT")
    transporter = trip.transporter

    draft_deduction = TransportDeduction.objects.create(
        trip=trip,
        transporter=transporter,
        chargeable_quantity=Decimal("50.00"),
        unit_price=Decimal("600.0000"),
    )
    assert _audit_logs_for(draft_deduction).filter(action=AuditLog.Action.CREATE).exists()
    draft_deduction.delete()
    assert not TransportDeduction.objects.filter(pk=draft_deduction.pk).exists()

    validated_deduction = TransportDeduction.objects.create(
        trip=trip,
        transporter=transporter,
        chargeable_quantity=Decimal("60.00"),
        unit_price=Decimal("600.0000"),
        status=TransportDeduction.Status.VALIDATED,
    )
    with pytest.raises(HardDeleteBlocked):
        validated_deduction.delete()


@pytest.mark.django_db
def test_creating_a_delivery_control_writes_a_create_audit_log_and_cannot_be_hard_deleted():
    admin_user, trip, _customer, _sale = _make_trip_with_sale("DELCTRL")

    control = DeliveryControl.objects.create(
        trip=trip,
        loaded_quantity=Decimal("45000.00"),
        received_quantity=Decimal("44850.00"),
        tolerance_quantity=Decimal("100.00"),
        control_date="2026-08-18",
        controller=admin_user,
        method=DeliveryControl.Method.MANUAL_GAUGE,
    )

    assert _audit_logs_for(control).filter(action=AuditLog.Action.CREATE).exists()
    with pytest.raises(HardDeleteBlocked):
        control.delete()

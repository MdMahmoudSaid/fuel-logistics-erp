# AuditLog / AuditableModel tests (docs/PHASE_6_PLAN.md Etape 1/6;
# ERP_Implementation_Experience_Guide.md Section 9.9; Spec Section 39).

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User
from apps.audit.context import bind_current_request, clear_current_request, get_current_user
from apps.audit.exceptions import HardDeleteBlocked
from apps.audit.models import AuditLog
from apps.audit.services import AuditLogService
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import (
    CustomerPayment,
    Expense,
    Shareholder,
    ShareholderContribution,
    SupplierAdvance,
    SupplierPayment,
    TransportDeduction,
    TransporterAdvance,
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
        phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role
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


@pytest.mark.django_db
def test_get_current_user_falls_back_to_jwt_bearer_token():
    """The "Utilisateur" column bug (UI pass 2026-08-27): this app
    authenticates every API call via a JWT bearer token, never a session
    cookie (REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] in
    config/settings/base.py), so `request.user` - Django's own
    session-based attribute - is never populated. A RequestFactory request
    reproduces that exactly: no middleware ran, so `request` doesn't even
    have a `.user` attribute, only the Authorization header - the same
    shape apps.audit.middleware.CurrentRequestMiddleware hands
    get_current_user() on every real request in production.
    """
    admin_user = _make_admin("JWTFALLBACK")
    access_token = str(RefreshToken.for_user(admin_user).access_token)
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {access_token}")

    bind_current_request(request)
    try:
        resolved = get_current_user()
    finally:
        clear_current_request()

    assert resolved is not None
    assert resolved.id == admin_user.id


@pytest.mark.django_db
def test_get_current_user_returns_none_for_missing_or_invalid_bearer_token():
    request_no_auth = RequestFactory().get("/")
    bind_current_request(request_no_auth)
    try:
        assert get_current_user() is None
    finally:
        clear_current_request()

    request_bad_token = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer not-a-real-token")
    bind_current_request(request_bad_token)
    try:
        assert get_current_user() is None
    finally:
        clear_current_request()


@pytest.mark.django_db
def test_expense_created_via_real_jwt_login_is_attributed_to_the_actor():
    """End-to-end repro of the original bug via the real login flow (not
    force_authenticate, which sets DRF's wrapped-request user directly and
    never exercises this fallback) - logs in for a real access token, then
    posts with only that Authorization header, exactly like the frontend
    does."""
    admin_user = _make_admin("REALJWT")

    client = APIClient()
    login = client.post(
        "/api/auth/login/", {"phone": admin_user.phone, "pin": "1234"}, format="json"
    )
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    response = client.post(
        "/api/expenses/",
        {
            "category": "transport",
            "amount": "50000.00",
            "calculation_method": "FIXED",
            "date": "2026-08-27",
        },
    )
    assert response.status_code == 201, response.data

    log = AuditLog.objects.get(
        content_type=ContentType.objects.get_for_model(Expense), object_id=response.data["id"]
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
    # Bug fix (2026-09-03 recette manuelle): PAID here, not the default
    # UNPAID - Expense.is_locked_for_deletion() now carves out UNPAID as a
    # genuine "no accounting impact yet" draft state (its own dedicated
    # test: apps/finance/tests.py::test_unpaid_expense_can_be_hard_deleted),
    # same pattern as TransportDeduction's DRAFT carve-out. This test
    # covers everything past that point, which still stays blocked.
    expense = Expense.objects.create(
        category=Expense.Category.ROAD,
        amount=Decimal("50000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-08-18",
        status=Expense.Status.PAID,
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


# ---------------------------------------------------------------------------
# Human-readable summary (docs/edit.md UI pass 2026-08-26, Journal d'audit) -
# describe() resolves FK ids captured in a snapshot to a readable module,
# reference and related party so the frontend never has to show raw
# `finance.treasurytransaction` / object ids.
# ---------------------------------------------------------------------------

from apps.audit.labels import describe  # noqa: E402


@pytest.mark.django_db
def test_describe_supplier_order_resolves_module_reference_and_supplier_name():
    _admin_user, order = _make_supplier_order("DESCRIBE-SO")
    log = _audit_logs_for(order).latest("id")

    summary = describe(log)

    assert summary["module_key"] == "supplier_order"
    assert summary["reference"] == order.reference
    assert summary["related_party"] == order.supplier.name


@pytest.mark.django_db
def test_describe_supplier_payment_resolves_supplier_name_and_account():
    admin_user = _make_admin("DESCRIBE-SP")
    supplier = Supplier.objects.create(name="Supplier DESCRIBE-SP", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash DESCRIBE-SP")
    payment = SupplierPayment.objects.create(
        supplier=supplier,
        amount=Decimal("100000.00"),
        payment_date="2026-08-18",
        method=SupplierPayment.Method.CASH,
        cash_account=cash_account,
        recorded_by=admin_user,
    )
    log = _audit_logs_for(payment).latest("id")

    summary = describe(log)

    assert summary["module_key"] == "supplier_payment"
    assert summary["related_party"] == "Supplier DESCRIBE-SP"
    assert summary["account_label"] == "Main Cash DESCRIBE-SP"
    assert summary["amount"] == "100000.00"


@pytest.mark.django_db
def test_describe_treasury_transaction_resolves_account_and_amount():
    admin_user = _make_admin("DESCRIBE-TT")
    cash_account = CashAccount.objects.create(name="Main Cash DESCRIBE-TT")
    txn = TreasuryTransaction.objects.create(
        cash_account=cash_account,
        type=TreasuryTransaction.Type.MONEY_IN,
        amount=Decimal("22500000.00"),
        date="2026-08-18",
        recorded_by=admin_user,
    )
    log = _audit_logs_for(txn).latest("id")

    summary = describe(log)

    assert summary["module_key"] == "treasury"
    assert summary["account_label"] == "Main Cash DESCRIBE-TT"
    assert summary["amount"] == "22500000.00"


@pytest.mark.django_db
def test_describe_shareholder_contribution_resolves_module_key_and_amount():
    """UI recette fix (2026-09-05): finance.shareholdercontribution was
    missing from MODULE_KEYS, so Journal d'audit showed the raw
    "finance.shareholdercontribution" content-type string instead of a
    translated label - client's own example: "finance.shareholdercontribution
    3 000 000 XOF" instead of "Apport en capital - 3 000 000 XOF"."""
    admin_user = _make_admin("DESCRIBE-SHCONTRIB")
    shareholder = Shareholder.objects.create(
        name="Actionnaire DESCRIBE-SHCONTRIB", participation_percent=Decimal("10.00")
    )
    cash_account = CashAccount.objects.create(name="Caisse DESCRIBE-SHCONTRIB")
    contribution = ShareholderContribution.objects.create(
        shareholder=shareholder,
        amount=Decimal("3000000.00"),
        date="2026-08-18",
        cash_account=cash_account,
        recorded_by=admin_user,
    )
    log = _audit_logs_for(contribution).latest("id")

    summary = describe(log)

    assert summary["module_key"] == "shareholder_contribution"
    assert summary["amount"] == "3000000.00"


@pytest.mark.django_db
def test_describe_supplier_advance_resolves_module_key_supplier_and_account():
    """Bug fix (found 2026-09-06): SupplierAdvance IS AuditableModel (real
    audit rows are written for it) but was missing from MODULE_KEYS -
    Journal d'audit showed the raw "finance.supplieradvance" content-type
    string with no related supplier/account, same bug class already fixed
    for shareholdercontribution above."""
    admin_user = _make_admin("DESCRIBE-SADV")
    supplier = Supplier.objects.create(name="Supplier DESCRIBE-SADV", country="Senegal")
    cash_account = CashAccount.objects.create(name="Caisse DESCRIBE-SADV")
    advance = SupplierAdvance.objects.create(
        supplier=supplier,
        amount=Decimal("500000.00"),
        date="2026-08-18",
        reference="AV-SADV-1",
        cash_account=cash_account,
        recorded_by=admin_user,
    )
    log = _audit_logs_for(advance).latest("id")

    summary = describe(log)

    assert summary["module_key"] == "supplier_advance"
    assert summary["related_party"] == "Supplier DESCRIBE-SADV"
    assert summary["reference"] == "AV-SADV-1"
    assert summary["account_label"] == "Caisse DESCRIBE-SADV"
    assert summary["amount"] == "500000.00"


@pytest.mark.django_db
def test_describe_transporter_advance_resolves_module_key_and_transporter():
    """Same bug fix as supplier_advance above, for TransporterAdvance."""
    admin_user = _make_admin("DESCRIBE-TADV")
    transporter = Transporter.objects.create(name="Transporteur DESCRIBE-TADV")
    cash_account = CashAccount.objects.create(name="Caisse DESCRIBE-TADV")
    advance = TransporterAdvance.objects.create(
        transporter=transporter,
        amount=Decimal("300000.00"),
        date="2026-08-18",
        reference="AV-TADV-1",
        cash_account=cash_account,
        recorded_by=admin_user,
    )
    log = _audit_logs_for(advance).latest("id")

    summary = describe(log)

    assert summary["module_key"] == "transporter_advance"
    assert summary["related_party"] == "Transporteur DESCRIBE-TADV"
    assert summary["reference"] == "AV-TADV-1"
    assert summary["account_label"] == "Caisse DESCRIBE-TADV"
    assert summary["amount"] == "300000.00"


def test_module_keys_cover_transport_payment_and_trip():
    """finance.transportpayment/trips.trip aren't AuditableModel today (no
    real audit row currently carries either content type), but the client's
    recette explicitly asked for both translations - kept here as a plain
    dict assertion (no audit row to construct) so the mapping doesn't
    silently regress if either model becomes audited later."""
    from apps.audit.labels import MODULE_KEYS

    assert MODULE_KEYS["finance.transportpayment"] == "transport_payment"
    assert MODULE_KEYS["trips.trip"] == "trip"


@pytest.mark.django_db
def test_describe_falls_back_gracefully_when_related_row_is_gone():
    """A snapshot always survives even if the FK'd row it referenced is
    later deleted - describe() must degrade to no label, never raise."""
    admin_user, order = _make_supplier_order("DESCRIBE-GONE")
    original_supplier = order.supplier
    replacement_supplier = Supplier.objects.create(
        name="Supplier DESCRIBE-GONE-2", country="Senegal"
    )
    # Move the live row off the original supplier so it's no longer
    # PROTECTed, then delete it - only the CREATE log still points to it.
    order.supplier = replacement_supplier
    order.save(user=admin_user)
    create_log = _audit_logs_for(order).filter(action=AuditLog.Action.CREATE).latest("id")
    original_supplier.delete()

    summary = describe(create_log)

    assert summary["module_key"] == "supplier_order"
    assert summary["related_party"] is None

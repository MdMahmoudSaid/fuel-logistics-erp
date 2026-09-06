# SupplierPaymentCancellationService / SupplierPaymentViewSet.cancel tests
# (Task 6, client business decision confirmed 2026-09-06): a wrongly-entered
# SupplierPayment is corrected by contre-passation - an offsetting treasury
# entry plus an is_reversed flag - never a plain edit or a hard delete.

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.finance.models import BankAccount, SupplierPayment, TreasuryTransaction
from apps.finance.services import (
    ControlledDebtPaymentService,
    SupplierPaymentCancellationError,
    SupplierPaymentCancellationService,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role)


def _make_loaded_supplier_order(suffix, admin_user, *, quantity=Decimal("1000.00"), unit_price=Decimal("600.0000")):
    """A CONFIRMED SupplierOrder fully loaded onto a Trip, so its debt
    (client business rule, confirmed 2026-09-06) equals quantity x
    unit_price - the case a supplier payment is normally recorded against."""
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    order = SupplierOrder.objects.create(
        reference=f"SO-CANCEL-{suffix}", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=quantity, unit_price=unit_price,
        status=SupplierOrder.Status.CONFIRMED, created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-CANCEL-{suffix}", supplier_order=order,
        authorized_quantity=quantity, issue_date="2026-08-18", created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-{suffix[-16:]}", tractor_registration=f"{suffix[-16:]}-TRAC",
        tanker_registration=f"{suffix[-16:]}-TANK", capacity_litres=Decimal("45000.00"),
    )
    transporter = Transporter.objects.create(name=f"Transporteur {suffix}")
    Trip.objects.create(
        reference=f"TRIP-CANCEL-{suffix}", truck=truck, transporter=transporter,
        supplier=supplier, supplier_order=order, cession_letter=cession, product=product,
        quantity_loaded=quantity, loading_date="2026-08-18",
        bl_reference=f"BL-CANCEL-{suffix}", created_by=admin_user,
    )
    return supplier, order


@pytest.mark.django_db
def test_cancel_supplier_payment_restores_treasury_balance_and_debt():
    admin_user = _make_admin("CANCEL-BASIC")
    supplier, order = _make_loaded_supplier_order("CANCEL-BASIC", admin_user)
    bank_account = BankAccount.objects.create(
        name="Bank Cancel Basic", opening_balance=Decimal("5000000.00")
    )

    result = ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER,
        debt_id=supplier.id,
        bank_account_id=bank_account.id,
        amount=Decimal("200000.00"),
        date="2026-08-20",
        reference="PAY-CANCEL-BASIC",
        actor=admin_user,
    )
    payment = result["sources"][0]
    bank_account.refresh_from_db()
    assert bank_account.current_balance == Decimal("4800000.00")
    debt_after_payment = ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"]
    assert debt_after_payment == Decimal("400000.00")  # 600000 - 200000

    cancelled = SupplierPaymentCancellationService.cancel_supplier_payment(payment, admin_user)

    assert cancelled.is_reversed is True
    bank_account.refresh_from_db()
    assert bank_account.current_balance == Decimal("5000000.00")  # fully restored
    debt_after_cancel = ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"]
    assert debt_after_cancel == Decimal("600000.00")  # back to the full loaded debt

    # The offsetting entry is linked back to the same payment, distinct
    # from the original MONEY_OUT.
    content_type = ContentType.objects.get_for_model(SupplierPayment)
    transactions = TreasuryTransaction.objects.filter(
        source_content_type=content_type, source_object_id=payment.id
    ).order_by("id")
    assert transactions.count() == 2
    assert transactions[0].type == TreasuryTransaction.Type.MONEY_OUT
    assert transactions[1].type == TreasuryTransaction.Type.MONEY_IN
    assert transactions[1].amount == Decimal("200000.00")


@pytest.mark.django_db
def test_cancel_supplier_payment_twice_is_rejected():
    admin_user = _make_admin("CANCEL-TWICE")
    supplier, order = _make_loaded_supplier_order("CANCEL-TWICE", admin_user)
    bank_account = BankAccount.objects.create(
        name="Bank Cancel Twice", opening_balance=Decimal("5000000.00")
    )
    result = ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER,
        debt_id=supplier.id, bank_account_id=bank_account.id,
        amount=Decimal("100000.00"), date="2026-08-20",
        reference="PAY-CANCEL-TWICE", actor=admin_user,
    )
    payment = result["sources"][0]

    SupplierPaymentCancellationService.cancel_supplier_payment(payment, admin_user)

    with pytest.raises(SupplierPaymentCancellationError):
        SupplierPaymentCancellationService.cancel_supplier_payment(payment, admin_user)

    # Only one offsetting entry was ever created, not two.
    content_type = ContentType.objects.get_for_model(SupplierPayment)
    assert TreasuryTransaction.objects.filter(
        source_content_type=content_type, source_object_id=payment.id,
        type=TreasuryTransaction.Type.MONEY_IN,
    ).count() == 1


@pytest.mark.django_db
def test_cancelled_supplier_payment_excluded_from_total_paid_aggregates():
    admin_user = _make_admin("CANCEL-TOTALS")
    supplier, order = _make_loaded_supplier_order("CANCEL-TOTALS", admin_user)
    bank_account = BankAccount.objects.create(
        name="Bank Cancel Totals", opening_balance=Decimal("5000000.00")
    )
    result = ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER,
        debt_id=supplier.id, bank_account_id=bank_account.id,
        amount=Decimal("150000.00"), date="2026-08-20",
        reference="PAY-CANCEL-TOTALS", actor=admin_user,
    )
    payment = result["sources"][0]
    SupplierPaymentCancellationService.cancel_supplier_payment(payment, admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get(f"/api/suppliers/{supplier.id}/")
    assert response.status_code == 200
    assert response.data["total_paid"] == "0.00"
    assert response.data["outstanding_balance"] == "600000.00"


@pytest.mark.django_db
def test_cancel_supplier_payment_via_api():
    admin_user = _make_admin("CANCEL-API")
    supplier, order = _make_loaded_supplier_order("CANCEL-API", admin_user)
    bank_account = BankAccount.objects.create(
        name="Bank Cancel API", opening_balance=Decimal("5000000.00")
    )
    result = ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER,
        debt_id=supplier.id, bank_account_id=bank_account.id,
        amount=Decimal("100000.00"), date="2026-08-20",
        reference="PAY-CANCEL-API", actor=admin_user,
    )
    payment = result["sources"][0]

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.post(f"/api/supplier-payments/{payment.id}/cancel/")

    assert response.status_code == 200, response.data
    assert response.data["is_reversed"] is True

    second = client.post(f"/api/supplier-payments/{payment.id}/cancel/")
    assert second.status_code == 400


@pytest.mark.django_db
def test_supplier_payment_cancel_requires_finance_cancel_permission():
    admin_user = _make_admin("CANCEL-PERM")
    supplier, order = _make_loaded_supplier_order("CANCEL-PERM", admin_user)
    bank_account = BankAccount.objects.create(
        name="Bank Cancel Perm", opening_balance=Decimal("5000000.00")
    )
    result = ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER,
        debt_id=supplier.id, bank_account_id=bank_account.id,
        amount=Decimal("100000.00"), date="2026-08-20",
        reference="PAY-CANCEL-PERM", actor=admin_user,
    )
    payment = result["sources"][0]

    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)
    ops_user = User.objects.create_user(phone="+222CANCELPERM1", pin="1234", role=ops_role)
    client = APIClient()
    client.force_authenticate(ops_user)

    response = client.post(f"/api/supplier-payments/{payment.id}/cancel/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_supplier_payment_still_blocks_plain_edit_and_delete_after_cancellation_feature():
    # Task 6 didn't loosen the existing "no silent edit, no hard delete"
    # rule (Task 5) - cancellation is the only correction path.
    admin_user = _make_admin("CANCEL-STILL-BLOCKED")
    supplier, order = _make_loaded_supplier_order("CANCEL-STILL-BLOCKED", admin_user)
    bank_account = BankAccount.objects.create(
        name="Bank Cancel Still Blocked", opening_balance=Decimal("5000000.00")
    )
    result = ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER,
        debt_id=supplier.id, bank_account_id=bank_account.id,
        amount=Decimal("100000.00"), date="2026-08-20",
        reference="PAY-CANCEL-STILL-BLOCKED", actor=admin_user,
    )
    payment = result["sources"][0]

    client = APIClient()
    client.force_authenticate(admin_user)
    edit_response = client.patch(
        f"/api/supplier-payments/{payment.id}/", {"amount": "999999.00"}
    )
    assert edit_response.status_code == 400

    delete_response = client.delete(f"/api/supplier-payments/{payment.id}/")
    assert delete_response.status_code == 405

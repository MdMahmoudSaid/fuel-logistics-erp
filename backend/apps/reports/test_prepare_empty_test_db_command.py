from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import override_settings

from apps.accounts.models import Role, User
from apps.core.models import LossToleranceConfig, Product
from apps.customers.models import Customer
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    ExpenseCategory,
    Shareholder,
    ShareholderContribution,
    TreasuryTransaction,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import CustomerOrder
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


@pytest.mark.django_db
def test_prepare_empty_test_db_requires_explicit_reset():
    with pytest.raises(CommandError, match="--reset"):
        call_command("prepare_empty_test_db")


@pytest.mark.django_db
def test_prepare_empty_test_db_refuses_production_like_database_name(monkeypatch):
    monkeypatch.setitem(connection.settings_dict, "NAME", "fuel_erp_production")
    monkeypatch.setitem(connection.settings_dict, "HOST", "localhost")

    with override_settings(DEBUG=False):
        with pytest.raises(CommandError, match="Refus"):
            call_command("prepare_empty_test_db", "--reset")


@pytest.mark.django_db
def test_prepare_empty_test_db_resets_domain_data_to_zero_without_admin():
    admin_role, _ = Role.objects.update_or_create(
        name=Role.NAME_ADMIN,
        defaults={"permissions": {module: Role.ACTIONS for module in Role.MODULES}},
    )
    old_user = User.objects.create_user(
        phone="+222OLDQA", pin="1234", role=admin_role
    )
    old_product = Product.objects.create(name="Old gasoil", code="old-gasoil")
    old_supplier = Supplier.objects.create(name="Old supplier")
    old_customer = Customer.objects.create(name="Old customer")
    old_transporter = Transporter.objects.create(name="Old transporter")
    old_truck = Truck.objects.create(
        internal_id="OLD-TRUCK",
        tractor_registration="OLD-TRACTOR",
        tanker_registration="OLD-TANKER",
        capacity_litres=Decimal("45000.00"),
        owner_transporter=old_transporter,
    )
    order = SupplierOrder.objects.create(
        reference="OLD-SO",
        supplier=old_supplier,
        product=old_product,
        purchase_date="2026-08-01",
        quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("500.0000"),
        created_by=old_user,
    )
    cession = CessionLetter.objects.create(
        reference="OLD-CL",
        supplier_order=order,
        authorized_quantity=Decimal("1000.00"),
        issue_date="2026-08-01",
        created_by=old_user,
    )
    customer_order = CustomerOrder.objects.create(
        customer=old_customer,
        product=old_product,
        quantity_ordered=Decimal("1000.00"),
    )
    Trip.objects.create(
        reference="OLD-TRIP",
        truck=old_truck,
        transporter=old_transporter,
        supplier=old_supplier,
        supplier_order=order,
        cession_letter=cession,
        product=old_product,
        quantity_loaded=Decimal("1000.00"),
        client=old_customer,
        customer_order=customer_order,
        loading_date="2026-08-01",
        bl_reference="OLD-BL",
        created_by=old_user,
    )
    BankAccount.objects.create(name="Old bank", opening_balance=Decimal("1.00"))
    CashAccount.objects.create(name="Old cash", opening_balance=Decimal("1.00"))
    LossToleranceConfig.objects.create(tolerance_litres=Decimal("100.00"), updated_by=old_user)
    # Phase 3 (dépenses générales) / Phase 1 (apport en capital) additions -
    # both were missing from the reset/count lists until now.
    old_category = ExpenseCategory.objects.create(name="Old custom category", code="old-category")
    old_shareholder = Shareholder.objects.create(
        name="Old shareholder", participation_percent=Decimal("100.00")
    )
    old_contribution_cash = CashAccount.objects.create(
        name="Old contribution cash", opening_balance=Decimal("0.00")
    )
    ShareholderContribution.objects.create(
        shareholder=old_shareholder,
        amount=Decimal("1000000.00"),
        date="2026-08-01",
        cash_account=old_contribution_cash,
        recorded_by=old_user,
    )

    out = StringIO()
    call_command("prepare_empty_test_db", "--reset", stdout=out)

    output = out.getvalue()
    assert "Base vide prete" in output
    assert "Donnees metier: 0" in output
    assert "Utilisateurs: 0" in output

    assert User.objects.count() == 0
    assert Product.objects.count() == 0
    assert LossToleranceConfig.objects.count() == 0
    assert Supplier.objects.count() == 0
    assert Customer.objects.count() == 0
    assert Transporter.objects.count() == 0
    assert Truck.objects.count() == 0
    assert BankAccount.objects.count() == 0
    assert CashAccount.objects.count() == 0
    assert TreasuryTransaction.objects.count() == 0
    assert Trip.objects.count() == 0
    assert SupplierOrder.objects.count() == 0
    assert CessionLetter.objects.count() == 0
    assert CustomerOrder.objects.count() == 0
    assert CustomerPayment.objects.count() == 0
    assert ExpenseCategory.objects.count() == 0
    assert Shareholder.objects.count() == 0
    assert ShareholderContribution.objects.count() == 0
    assert not ExpenseCategory.objects.filter(pk=old_category.pk).exists()


@pytest.mark.django_db
def test_prepare_empty_test_db_can_create_login_admin_without_business_data():
    out = StringIO()
    call_command("prepare_empty_test_db", "--reset", "--with-admin", stdout=out)

    admin = User.objects.get(phone="+22200000000")
    assert admin.full_name == "Admin/Test Vide"
    assert admin.role.name == Role.NAME_ADMIN
    assert admin.is_staff is True
    assert admin.is_superuser is True
    assert Product.objects.count() == 0
    assert BankAccount.objects.count() == 0
    assert Supplier.objects.count() == 0
    assert Trip.objects.count() == 0
    assert "Admin cree: +22200000000 / PIN 1234" in out.getvalue()

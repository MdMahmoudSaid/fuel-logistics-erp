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
    Shareholder,
    TreasuryTransaction,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import CustomerOrder
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


@pytest.mark.django_db
def test_seed_production_like_scenario_requires_explicit_reset():
    with pytest.raises(CommandError, match="--reset"):
        call_command("seed_production_like_scenario")


@pytest.mark.django_db
def test_seed_production_like_scenario_refuses_production_like_database_name(monkeypatch):
    monkeypatch.setitem(connection.settings_dict, "NAME", "fuel_erp_production")
    monkeypatch.setitem(connection.settings_dict, "HOST", "localhost")

    with override_settings(DEBUG=False):
        with pytest.raises(CommandError, match="Refus"):
            call_command("seed_production_like_scenario", "--reset")


@pytest.mark.django_db
def test_seed_production_like_scenario_resets_business_data_and_recreates_minimal_seed():
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

    out = StringIO()
    call_command("seed_production_like_scenario", "--reset", stdout=out)

    output = out.getvalue()
    assert "Banque initiale: 200000000.00 XOF" in output
    assert "Caisse initiale: 5000000.00 XOF" in output
    assert "Confirmation: aucune donnee metier ancienne ne reste" in output

    admin = User.objects.get(phone="+22200000000")
    assert admin.full_name == "Admin/Test QA"
    assert admin.role.name == Role.NAME_ADMIN
    assert admin.is_staff is True
    assert Product.objects.get(code="gasoil").name == "Gasoil"
    assert LossToleranceConfig.objects.get(pk=1).tolerance_litres == Decimal("100.00")

    bank = BankAccount.objects.get(name="Banque principale")
    cash = CashAccount.objects.get(name="Caisse principale")
    assert bank.current_balance == Decimal("200000000.00")
    assert cash.current_balance == Decimal("5000000.00")
    assert TreasuryTransaction.objects.count() == 0

    assert Supplier.objects.get(name="Fournisseur Test")
    assert Customer.objects.get(name="Client Test")
    transporter = Transporter.objects.get(name="Transporteur Test")
    truck = Truck.objects.get(internal_id="CAMION-TEST")
    assert truck.owner_transporter == transporter
    assert truck.capacity_litres == Decimal("45000.00")

    assert list(
        Shareholder.objects.order_by("name").values_list(
            "name", "participation_percent", "contribution"
        )
    ) == [
        ("Abdou", Decimal("10.00"), Decimal("10000000.00")),
        ("Sidi", Decimal("80.00"), Decimal("80000000.00")),
        ("Yacoub", Decimal("10.00"), Decimal("10000000.00")),
    ]

    assert Trip.objects.count() == 0
    assert SupplierOrder.objects.count() == 0
    assert CessionLetter.objects.count() == 0
    assert CustomerOrder.objects.count() == 0
    assert CustomerPayment.objects.count() == 0

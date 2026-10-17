# Situation financiere: what the company owns vs what it owes (2026-10-17).

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.finance.models import BankAccount, CashAccount, Shareholder
from apps.finance.services import ControlledDebtPaymentService, ShareholderContributionService
from apps.finance.test_working_capital import _make_supplier_order_with_status
from apps.purchasing.models import SupplierOrder
from apps.reports.services.financial_position import FinancialPositionService

D = Decimal


def _lines(side):
    return {line["key"]: line for line in side["lines"]}


@pytest.mark.django_db
def test_position_lists_treasury_and_net_result_is_assets_minus_liabilities():
    BankAccount.objects.create(name="B1", opening_balance=D("1000.00"))
    CashAccount.objects.create(name="C1", opening_balance=D("500.00"))
    BankAccount.objects.create(name="Old", opening_balance=D("999.00"), is_active=False)

    position = FinancialPositionService.get_position()

    assets = _lines(position["assets"])
    assert assets["banks"]["amount"] == D("1000.00")
    assert [c["label"] for c in assets["banks"]["children"]] == ["B1"]  # inactive account left out
    assert assets["cash"]["amount"] == D("500.00")
    assert position["assets"]["total"] == D("1500.00")
    assert position["liabilities"]["total"] == D("0.00")
    assert position["net_result"] == D("1500.00")


@pytest.mark.django_db
def test_unpaid_purchase_is_neutral_and_paying_the_supplier_does_not_change_the_net_result():
    """A confirmed purchase is a debt in full AND the fuel it covers stands on
    the asset side in full, so buying on credit - and later paying - moves the
    net result by nothing (paying only swaps treasury for a smaller debt)."""
    admin, supplier, order = _make_supplier_order_with_status(
        "POS-SUP", SupplierOrder.Status.CONFIRMED, quantity=D("1000.00"), unit_price=D("1000.0000"),
    )
    bank = BankAccount.objects.create(name="B1", opening_balance=D("5000000.00"))

    before = FinancialPositionService.get_position()
    assert _lines(before["liabilities"])["supplier_debts"]["amount"] == D("1000000.00")
    stock = _lines(before["assets"])["fuel_stock"]
    assert stock["amount"] == D("1000000.00")  # nothing loaded yet: all of it still at the supplier
    assert {c["key"]: c["amount"] for c in stock["children"]}["at_supplier"] == D("1000000.00")
    assert before["net_result"] == D("5000000.00")

    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER, debt_id=supplier.id,
        bank_account_id=bank.id, amount=D("400000.00"), date="2026-10-10", reference="", actor=admin,
    )
    after = FinancialPositionService.get_position()

    assert _lines(after["assets"])["banks"]["amount"] == D("4600000.00")
    assert _lines(after["liabilities"])["supplier_debts"]["amount"] == D("600000.00")
    assert after["net_result"] == before["net_result"]


@pytest.mark.django_db
def test_a_capital_contribution_is_neutral_money_in_and_owed_back():
    from apps.accounts.models import Role, User

    admin = User.objects.create_user(
        phone="+22299000022", pin="1234", role=Role.objects.get(name=Role.NAME_ADMIN)
    )
    bank = BankAccount.objects.create(name="B1")
    associate = Shareholder.objects.create(
        name="Assoc", participation_percent=D("100"), contribution=D("0")
    )

    ShareholderContributionService.record_contribution(
        shareholder_id=associate.id, amount=D("1000000.00"), date="2026-10-01", actor=admin,
        attachment=SimpleUploadedFile("p.jpg", b"x", content_type="image/jpeg"),
        bank_account_id=bank.id,
    )
    position = FinancialPositionService.get_position()

    assert _lines(position["assets"])["banks"]["amount"] == D("1000000.00")
    dues = _lines(position["liabilities"])["shareholder_dues"]
    assert dues["amount"] == D("1000000.00")
    assert [(c["label"], c["amount"]) for c in dues["children"]] == [("Assoc", D("1000000.00"))]
    assert position["net_result"] == D("0.00")  # the money belongs to the associate
    assert position["capital"] == D("1000000.00")


@pytest.mark.django_db
def test_financial_position_endpoint_returns_the_position_as_strings():
    from apps.accounts.models import Role, User

    admin = User.objects.create_user(
        phone="+22299000023", pin="1234", role=Role.objects.get(name=Role.NAME_ADMIN)
    )
    BankAccount.objects.create(name="B1", opening_balance=D("42.00"))
    client = APIClient()
    client.force_authenticate(admin)

    response = client.get("/api/dashboard/financial-position/")

    assert response.status_code == 200
    data = response.json()
    assert data["assets"]["total"] == "42.00"
    assert data["net_result"] == "42.00"

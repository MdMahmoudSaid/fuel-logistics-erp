# Situation financiere: what the company owns vs what it owes (2026-10-17).
# Client rule: the net result is ALWAYS the distributable net profit of the
# Benefices page, and nothing is shown on both sides.

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from apps.finance.models import (
    BankAccount,
    CashAccount,
    Expense,
    ExpenseAllocation,
    Shareholder,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import (
    ControlledDebtPaymentService as Debts,
)
from apps.finance.services import (
    ShareholderContributionService,
    ShareholderDistributionService,
    ShareholderWithdrawalService,
)
from apps.finance.test_working_capital import _make_supplier_order_with_status
from apps.purchasing.models import SupplierOrder
from apps.reports.services.financial_position import FinancialPositionService
from apps.reports.test_queries import _deliver_trip_with_transporter_loss, _make_admin, _make_full_trip
from apps.trips.models import Trip

D = Decimal


def _lines(side):
    return {line["key"]: line for line in side["lines"]}


def _position():
    return FinancialPositionService.get_position()


def _assert_net_is_the_distributable_profit():
    position = _position()
    assert position["gap"] == D("0.00"), position
    assert position["net_result"] == position["distributable_result"] + position["starting_funds"]
    return position


def _contribute(admin, bank, amount):
    shareholder = Shareholder.objects.create(name="S", participation_percent=D("100"))
    ShareholderContributionService.record_contribution(
        shareholder_id=shareholder.id, amount=D(amount), date="2026-08-01", actor=admin,
        attachment=None, bank_account_id=bank.id,
    )
    return shareholder


@pytest.mark.django_db
def test_position_lists_treasury_and_starting_funds_net_to_zero():
    BankAccount.objects.create(name="B1", opening_balance=D("1000.00"))
    CashAccount.objects.create(name="C1", opening_balance=D("500.00"))
    BankAccount.objects.create(name="Old", opening_balance=D("999.00"), is_active=False)

    position = _assert_net_is_the_distributable_profit()

    assets = _lines(position["assets"])
    assert assets["banks"]["amount"] == D("1000.00")
    assert [c["label"] for c in assets["banks"]["children"]] == ["B1"]  # inactive account left out
    assert assets["cash"]["amount"] == D("500.00")
    # The money the accounts were opened with is the starting funds, not profit:
    # never a liability line, the net result carries it as a reconciliation.
    assert "starting_funds" not in _lines(position["liabilities"])
    assert position["starting_funds"] == D("1500.00")
    assert position["net_result"] == D("1500.00")
    assert position["distributable_result"] == D("0.00")


@pytest.mark.django_db
def test_unsold_unpaid_fuel_is_matched_by_its_debt_and_cancels_in_the_result():
    _, supplier, order = _make_supplier_order_with_status(
        "POS-UNP", SupplierOrder.Status.CONFIRMED, quantity=D("1000.00"), unit_price=D("1000.0000"),
    )

    position = _assert_net_is_the_distributable_profit()

    # The debt is shown in full (same figure as the Fond de roulement and the
    # "Dettes a payer" report); the fuel it covers stands on the other side.
    assert _lines(position["liabilities"])["supplier_debts"]["amount"] == D("1000000.00")
    assert _lines(position["assets"])["unsold_fuel_paid"]["amount"] == D("0.00")
    assert _lines(position["assets"])["unsold_unpaid_covered"]["amount"] == D("1000000.00")
    assert position["net_result"] == D("0.00")


@pytest.mark.django_db
def test_paying_for_unsold_fuel_moves_it_to_the_asset_side_without_changing_the_result():
    admin = _make_admin("POSPAID")
    bank = BankAccount.objects.create(name="B1", opening_balance=D("5000000.00"))
    _, supplier, order = _make_supplier_order_with_status(
        "POS-PAID", SupplierOrder.Status.CONFIRMED, quantity=D("1000.00"), unit_price=D("1000.0000"),
    )

    Debts.record_payment(
        debt_type=Debts.SUPPLIER, debt_id=supplier.id, bank_account_id=bank.id,
        amount=D("400000.00"), date="2026-10-10", reference="", actor=admin,
    )
    position = _assert_net_is_the_distributable_profit()

    assert _lines(position["assets"])["banks"]["amount"] == D("4600000.00")
    stock = _lines(position["assets"])["unsold_fuel_paid"]
    assert stock["amount"] == D("400000.00")  # the "Paye : ..." figure of the Fond de roulement
    assert {c["key"]: c["amount"] for c in stock["children"]}["at_supplier"] == D("400000.00")
    assert _lines(position["liabilities"])["supplier_debts"]["amount"] == D("600000.00")  # what is left to pay
    covered = _lines(position["assets"])["unsold_unpaid_covered"]
    assert covered["amount"] == D("600000.00")
    # Same three places as the "Paye : ..." lines: 400,000 paid + 600,000 not yet
    # paid = the 1,000,000 of fuel still at the supplier.
    assert {c["key"]: c["amount"] for c in covered["children"]} == {
        "unpaid_company_stock": D("0.00"), "unpaid_in_transit": D("0.00"),
        "unpaid_at_supplier": D("600000.00"), "unpaid_costs": D("0.00"),
    }


@pytest.mark.django_db
def test_costs_engaged_on_an_unsold_trip_are_an_asset_only_for_what_is_paid():
    admin = _make_admin("POSCOST")
    bank = BankAccount.objects.create(name="B1", opening_balance=D("100000000.00"))
    fx = _make_full_trip("POSCOST", admin, status=Trip.Status.LOADED, with_sale=False)
    TransportPayment.objects.create(
        trip=fx["trip"], transporter=fx["transporter"],
        calculation_method=TransportPayment.CalculationMethod.FIXED, base_amount=D("5000000.00"),
    )
    expense = Expense.objects.create(
        category=Expense.Category.CUSTOMS, amount=D("1000000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL, date="2026-08-18",
    )
    ExpenseAllocation.objects.create(
        expense=expense, content_type=ContentType.objects.get_for_model(Trip),
        object_id=fx["trip"].id, allocated_amount=D("1000000.00"),
    )
    _assert_net_is_the_distributable_profit()  # all unpaid: nothing on either side

    Debts.record_payment(
        debt_type=Debts.TRANSPORTER, debt_id=fx["transporter"].id, bank_account_id=bank.id,
        amount=D("2000000.00"), date="2026-08-20", reference="", actor=admin,
    )
    Debts.record_payment(
        debt_type=Debts.CUSTOMS, debt_id=0, bank_account_id=bank.id,
        amount=D("400000.00"), date="2026-08-20", reference="", actor=admin,
    )
    position = _assert_net_is_the_distributable_profit()

    assert _lines(position["assets"])["unsold_costs_paid"]["amount"] == D("2400000.00")
    # What is still unpaid on that trip stays a debt, matched on the asset side.
    assert _lines(position["liabilities"])["transporter_debts"]["amount"] == D("3000000.00")
    assert _lines(position["liabilities"])["trip_fee_debts"]["amount"] == D("600000.00")
    covered = _lines(position["assets"])["unsold_unpaid_covered"]["amount"]
    assert covered >= D("3600000.00")


@pytest.mark.django_db
def test_a_sold_trip_debts_stay_on_the_liability_side_and_the_result_is_the_profit():
    admin = _make_admin("POSSOLD")
    bank = BankAccount.objects.create(name="B1", opening_balance=D("10000000.00"))
    _contribute(admin, bank, "50000000.00")
    fx = _deliver_trip_with_transporter_loss(
        "POSSOLD", admin, received_qty=D("44600.00"), base_amount=D("5000000.00"),
    )

    position = _assert_net_is_the_distributable_profit()
    assert position["distributable_result"] == D("8410000.00")
    assert _lines(position["liabilities"])["supplier_debts"]["amount"] == D("27000000.00")
    assert _lines(position["assets"])["customer_receivables"]["amount"] == D("40140000.00")

    Debts.record_payment(
        debt_type=Debts.SUPPLIER, debt_id=fx["supplier"].id, bank_account_id=bank.id,
        amount=D("10000000.00"), date="2026-08-19", reference="", actor=admin,
    )
    _assert_net_is_the_distributable_profit()  # paying a debt does not change the profit


@pytest.mark.django_db
def test_a_capital_contribution_does_not_change_the_result():
    admin = _make_admin("POSCAP")
    bank = BankAccount.objects.create(name="B1")

    _contribute(admin, bank, "1000000.00")
    position = _assert_net_is_the_distributable_profit()

    assert _lines(position["assets"])["banks"]["amount"] == D("1000000.00")
    dues = _lines(position["liabilities"])["shareholder_dues"]
    assert [(c["label"], c["amount"]) for c in dues["children"]] == [("S", D("1000000.00"))]
    assert position["net_result"] == D("0.00")  # the money belongs to the associate
    assert position["capital"] == D("1000000.00")


@pytest.mark.django_db
def test_general_expense_distribution_and_withdrawals_keep_the_result_equal_to_the_profit():
    admin = _make_admin("POSDIST")
    bank = BankAccount.objects.create(name="B1", opening_balance=D("10000000.00"))
    shareholder = _contribute(admin, bank, "50000000.00")
    _deliver_trip_with_transporter_loss(
        "POSDIST", admin, received_qty=D("44600.00"), base_amount=D("5000000.00"),
    )

    expense = Expense.objects.create(
        category=Expense.Category.UNLOADING, amount=D("700000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL, date="2026-08-18",
        status=Expense.Status.PAID,
    )
    TreasuryTransaction.objects.create(
        bank_account=bank, type="MONEY_OUT", amount=D("700000.00"), date="2026-08-18",
        source_content_type=ContentType.objects.get_for_model(Expense), source_object_id=expense.id,
        recorded_by=admin,
    )
    assert _assert_net_is_the_distributable_profit()["distributable_result"] == D("7710000.00")

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-08-01", period_end="2026-08-31", total_profit=D("3000000.00"), actor=admin,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, admin)
    assert _assert_net_is_the_distributable_profit()["distributable_result"] == D("4710000.00")

    for amount in ("2000000.00", "4000000.00"):  # the second one dips into capital
        ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=shareholder.id, amount=D(amount), date="2026-09-01", actor=admin,
            bank_account_id=bank.id,
        )
        _assert_net_is_the_distributable_profit()


@pytest.mark.django_db
def test_every_fond_de_roulement_figure_is_found_with_the_same_value_and_the_origins_add_up():
    from apps.finance.services import WorkingCapitalService

    admin = _make_admin("POSFDR")
    bank = BankAccount.objects.create(name="B1", opening_balance=D("10000000.00"))
    _contribute(admin, bank, "50000000.00")
    _deliver_trip_with_transporter_loss(
        "POSFDR", admin, received_qty=D("44600.00"), base_amount=D("5000000.00"),
    )
    _make_supplier_order_with_status(
        "POS-FDR2", SupplierOrder.Status.CONFIRMED, quantity=D("1000.00"), unit_price=D("1000.0000"),
    )

    position = _assert_net_is_the_distributable_profit()
    wc = WorkingCapitalService.get_working_capital()
    assets, liabilities = _lines(position["assets"]), _lines(position["liabilities"])

    assert assets["banks"]["amount"] + assets["cash"]["amount"] == wc["treasury_available"]
    assert assets["customer_receivables"]["amount"] == wc["customer_receivables"]
    assert liabilities["supplier_debts"]["amount"] == wc["supplier_debt_total"]
    assert liabilities["transporter_debts"]["amount"] == wc["transporter_debt_total"]
    assert liabilities["trip_fee_debts"]["amount"] == wc["other_debts"]
    assert liabilities["shareholder_dues"]["amount"] == wc["shareholder_dues"]
    stock = {c["key"]: c["amount"] for c in assets["unsold_fuel_paid"]["children"]}
    assert stock == {
        "company_stock": wc["supplier_company_stock_value"],
        "in_transit": wc["supplier_in_transit_value"],
        "at_supplier": wc["supplier_reliquat_value"],
    }
    assert position["working_capital_total"] == wc["total"]
    # The Fond de roulement is treasury + receivables + the open debts + the paid fuel.
    assert wc["total"] == (
        assets["banks"]["amount"] + assets["cash"]["amount"] + assets["customer_receivables"]["amount"]
        + liabilities["supplier_debts"]["amount"] + liabilities["transporter_debts"]["amount"]
        + liabilities["trip_fee_debts"]["amount"] + assets["unsold_fuel_paid"]["amount"]
    )

    # Where the treasury comes from adds up to the treasury shown.
    origins = {o["key"]: o["amount"] for o in position["treasury_origins"]}
    assert origins["opening_balances"] == D("10000000.00")
    assert origins["shareholdercontribution"] == D("50000000.00")
    assert sum(origins.values(), D("0.00")) == assets["banks"]["amount"] + assets["cash"]["amount"]


@pytest.mark.django_db
def test_old_debts_are_starting_funds_not_profit():
    """A "Nouvelle dette" is money that moved before the app: what a customer
    already owed (asset) or what the company already owed (liability) is part
    of the starting position, and collecting / paying it changes nothing."""
    from apps.customers.models import Customer
    from apps.finance.models import CustomerPayment, OpeningDebt
    from apps.finance.services import PaymentAllocationService
    from apps.suppliers.models import Supplier

    admin = _make_admin("POSOLD")
    bank = BankAccount.objects.create(name="B1")
    customer = Customer.objects.create(name="Old customer")
    OpeningDebt.objects.create(customer=customer, amount=D("4000.00"), date="2026-10-11", recorded_by=admin)
    OpeningDebt.objects.create(
        supplier=Supplier.objects.create(name="Old supplier", country="SN"),
        amount=D("1500.00"), date="2026-10-11", recorded_by=admin,
    )

    position = _assert_net_is_the_distributable_profit()
    assert _lines(position["assets"])["customer_receivables"]["amount"] == D("4000.00")
    assert _lines(position["liabilities"])["supplier_debts"]["amount"] == D("1500.00")
    assert position["starting_funds"] == D("2500.00")  # 4000 - 1500

    payment = CustomerPayment.objects.create(
        customer=customer, amount=D("3000.00"), payment_date="2026-10-11",
        method=CustomerPayment.Method.BANK_TRANSFER, destination=CustomerPayment.Destination.BANK,
        bank_account=bank, recorded_by=admin,
    )
    from apps.finance.services import FinancePostingService

    FinancePostingService.record_customer_payment_treasury(payment)
    _assert_net_is_the_distributable_profit()  # collecting 3,000 of it changes nothing


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
    assert data["net_result"] == "42.00"  # the opening balance is not profit...
    assert data["starting_funds"] == "42.00"  # ...and is shown as such, not as a debt
    assert data["gap"] == "0.00"


@pytest.mark.django_db
@pytest.mark.parametrize("lang", ["fr", "en", "ar"])
def test_financial_position_pdf_endpoint_returns_a_pdf(lang):
    from apps.accounts.models import Role, User

    admin = User.objects.create_user(
        phone="+22299000024", pin="1234", role=Role.objects.get(name=Role.NAME_ADMIN)
    )
    BankAccount.objects.create(name="B1", opening_balance=D("42.00"))
    client = APIClient()
    client.force_authenticate(admin)

    response = client.get(f"/api/dashboard/financial-position-pdf/?lang={lang}")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "situation-financiere.pdf" in response["Content-Disposition"]

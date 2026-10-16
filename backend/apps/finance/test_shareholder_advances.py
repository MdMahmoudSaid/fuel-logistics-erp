"""Shareholder advances from the company or from another associate (client
request 2026-10-11). A company advance moves no treasury when granted - like
a profit distribution it is shown in the grand livre and becomes
withdrawable; money only leaves treasury when he withdraws it. It is deducted
automatically from his next validated profit share."""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.finance.labels import describe_treasury_transaction
from apps.finance.models import (
    BankAccount,
    ShareholderWithdrawal,
    CashAccount,
    Shareholder,
    ShareholderLoan,
    ShareholderLoanRepayment,
    ShareholderProfitShare,
    ShareholderWithdrawalAllocation,
    TreasuryTransaction,
)
from apps.finance.services import (
    ShareholderDistributionService,
    ShareholderLedgerService,
    ShareholderLoanError,
    ShareholderLoanService,
    ShareholderProfitPeriodService,
    ShareholderWithdrawalError,
    ShareholderWithdrawalService,
)
from apps.finance.testing_helpers import seed_net_profit
from apps.reports.queries.shareholder_statement import ShareholderStatementQuery


def _admin(suffix):
    role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=f"+224{suffix}"[:20], pin="1234", role=role)


@pytest.fixture
def admin_client():
    client = APIClient()
    client.force_authenticate(_admin("API"))
    return client


def _associates(*percents):
    return [
        Shareholder.objects.create(name=f"Associe {i}", participation_percent=Decimal(p))
        for i, p in enumerate(percents)
    ]


def _cash(balance="5000000.00", name="Caisse avances"):
    return CashAccount.objects.create(name=name, opening_balance=Decimal(balance))


def _company_advance(borrower, amount, actor, date="2026-08-01"):
    return ShareholderLoanService.create_loan(
        borrower_id=borrower.id,
        amount=Decimal(amount),
        date=date,
        source=ShareholderLoan.Source.COMPANY,
        actor=actor,
    )


def _withdraw(shareholder, amount, cash, actor, date="2026-08-05"):
    return ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id, amount=Decimal(amount), date=date,
        cash_account_id=cash.id, actor=actor,
    )


def _distribute(total, actor, start="2026-09-01", end="2026-09-30"):
    distribution = ShareholderDistributionService.create_distribution(
        period_start=start, period_end=end, total_profit=Decimal(total), actor=actor
    )
    return ShareholderDistributionService.validate_distribution(distribution.id, actor)


def _share(distribution, shareholder):
    return ShareholderProfitShare.objects.get(distribution=distribution, shareholder=shareholder)


# --- Granting a company advance ----------------------------------------------


@pytest.mark.django_db
def test_granting_a_company_advance_moves_no_treasury_and_shows_in_the_ledger():
    actor = _admin("ADV1")
    (ahmed,) = _associates("100")
    cash = _cash("1000000.00")

    loan = _company_advance(ahmed, "300000.00", actor)

    assert loan.source == ShareholderLoan.Source.COMPANY
    assert loan.lender is None
    assert not TreasuryTransaction.objects.exists()
    cash.refresh_from_db()
    assert cash.current_balance == Decimal("1000000.00")

    # Like a distribution: the advance credits his balance and he can
    # withdraw it; what he owes the company is shown apart.
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("300000.00")
    assert ShareholderLedgerService.get_withdrawable_balance(ahmed.id) == Decimal("300000.00")
    summary = ShareholderLedgerService.get_shareholder_summary(ahmed.id)
    assert summary["company_advance_debt"] == Decimal("300000.00")
    assert summary["company_advance_undrawn"] == Decimal("300000.00")
    assert summary["withdrawable_balance"] == Decimal("300000.00")
    row = summary["loans_borrowed"][0]
    assert row["source"] == "COMPANY"
    assert row["undrawn_amount"] == Decimal("300000.00")
    assert row["lender_name"] is None


@pytest.mark.django_db
def test_company_advance_has_no_lender():
    actor = _admin("ADV3")
    ahmed, sidi = _associates("50", "50")

    with pytest.raises(ShareholderLoanError, match="pas d'associe preteur"):
        ShareholderLoanService.create_loan(
            borrower_id=ahmed.id, lender_id=sidi.id, amount="1000", date="2026-08-01",
            source=ShareholderLoan.Source.COMPANY, actor=actor,
        )


@pytest.mark.django_db
def test_inactive_associates_can_neither_borrow_lend_nor_withdraw():
    actor = _admin("ADV4")
    ahmed, sidi = _associates("50", "0")
    sidi.is_active = False
    sidi.save()
    cash = _cash()

    with pytest.raises(ShareholderLoanError, match="inactif"):
        _company_advance(sidi, "1000.00", actor)
    with pytest.raises(ShareholderLoanError, match="inactif"):
        ShareholderLoanService.create_loan(
            borrower_id=ahmed.id, lender_id=sidi.id, amount="1000", date="2026-08-01"
        )
    with pytest.raises(ShareholderWithdrawalError, match="inactif"):
        _withdraw(sidi, "1000", cash, actor)


# --- Withdrawing the advance: the only treasury movement -----------------------


@pytest.mark.django_db
def test_withdrawing_the_advance_takes_money_out_of_treasury():
    actor = _admin("ADV5")
    (ahmed,) = _associates("100")
    cash = _cash("1000000.00")
    loan = _company_advance(ahmed, "300000.00", actor)

    withdrawal = _withdraw(ahmed, "200000.00", cash, actor)

    allocation = ShareholderWithdrawalAllocation.objects.get(withdrawal=withdrawal)
    assert allocation.advance == loan
    loan.refresh_from_db()
    assert loan.amount_drawn == Decimal("200000.00")
    assert loan.undrawn_amount == Decimal("100000.00")
    cash.refresh_from_db()
    assert cash.current_balance == Decimal("800000.00")
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("100000.00")
    assert ShareholderLedgerService.get_withdrawable_balance(ahmed.id) == Decimal("100000.00")

    with pytest.raises(ShareholderWithdrawalError):
        _withdraw(ahmed, "100000.01", cash, actor)
    _withdraw(ahmed, "100000.00", cash, actor)
    loan.refresh_from_db()
    assert loan.undrawn_amount == Decimal("0.00")
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("0.00")
    assert ShareholderLedgerService.get_withdrawable_balance(ahmed.id) == Decimal("0.00")


@pytest.mark.django_db
def test_withdrawal_uses_profit_first_then_advance_then_capital():
    actor = _admin("ADV6")
    (ahmed,) = _associates("100")
    seed_net_profit(Decimal("10000000.00"))
    cash = _cash("5000000.00")
    _distribute("100000.00", actor, "2026-07-01", "2026-07-31")
    loan = _company_advance(ahmed, "300000.00", actor)

    withdrawal = _withdraw(ahmed, "250000.00", cash, actor)

    sources = [
        ("share" if a.profit_share_id else "advance" if a.advance_id else "capital", a.amount)
        for a in withdrawal.allocations.all()
    ]
    assert sources == [("share", Decimal("100000.00")), ("advance", Decimal("150000.00"))]
    loan.refresh_from_db()
    assert loan.amount_drawn == Decimal("150000.00")


@pytest.mark.django_db
def test_an_advance_is_a_credit_line_he_cannot_exceed():
    """He can withdraw his own money plus the advance, never more."""
    actor = _admin("ADV7")
    (ahmed,) = _associates("100")
    cash = _cash("5000000.00")
    from apps.finance.models import ShareholderContribution

    ShareholderContribution.objects.create(
        shareholder=ahmed, amount=Decimal("1000000.00"), date="2026-06-01",
        cash_account=cash, recorded_by=actor,
    )
    _company_advance(ahmed, "300000.00", actor)
    _withdraw(ahmed, "300000.00", cash, actor)

    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("1000000.00")
    assert ShareholderLedgerService.get_withdrawable_balance(ahmed.id) == Decimal("1000000.00")
    with pytest.raises(ShareholderWithdrawalError):
        _withdraw(ahmed, "1000000.01", cash, actor)
    _withdraw(ahmed, "1000000.00", cash, actor)
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("0.00")


# --- Automatic deduction from the next profit share ------------------------


@pytest.mark.django_db
def test_validated_distribution_deducts_the_company_advance_from_the_share():
    actor = _admin("ADV8")
    ahmed, sidi = _associates("80", "20")
    seed_net_profit(Decimal("10000000.00"))
    cash = _cash()
    loan = _company_advance(ahmed, "300000.00", actor)
    _withdraw(ahmed, "300000.00", cash, actor)
    balance_before = ShareholderLedgerService.get_available_balance(ahmed.id)

    distribution = _distribute("1000000.00", actor)

    loan.refresh_from_db()
    assert loan.status == ShareholderLoan.Status.REPAID
    share = _share(distribution, ahmed)
    assert share.amount_due == Decimal("800000.00")
    assert share.amount_withdrawn == Decimal("300000.00")
    assert share.remaining_due == Decimal("500000.00")
    deduction = ShareholderLoanRepayment.objects.get(loan=loan)
    assert deduction.method == ShareholderLoanRepayment.Method.PROFIT_SHARE
    assert deduction.profit_share == share
    # The share adds only what is left once the advance is paid back.
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == balance_before + Decimal(
        "500000.00"
    )
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("500000.00")
    assert _share(distribution, sidi).amount_withdrawn == Decimal("0.00")
    # Only the withdrawal ever touched treasury.
    assert TreasuryTransaction.objects.filter(cash_account=cash).count() == 1


@pytest.mark.django_db
def test_an_advance_never_withdrawn_is_still_deducted_and_stays_withdrawable():
    actor = _admin("ADV9")
    (ahmed,) = _associates("100")
    seed_net_profit(Decimal("10000000.00"))
    cash = _cash()
    loan = _company_advance(ahmed, "300000.00", actor)

    _distribute("1000000.00", actor)

    loan.refresh_from_db()
    assert loan.status == ShareholderLoan.Status.REPAID
    assert loan.undrawn_amount == Decimal("300000.00")
    # 1 000 000 earned in total: 700 000 left on the share + 300 000 of
    # advance not yet taken.
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("1000000.00")
    _withdraw(ahmed, "1000000.00", cash, actor)
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("0.00")


@pytest.mark.django_db
def test_advance_larger_than_the_share_is_carried_to_the_next_distribution_oldest_first():
    actor = _admin("ADV10")
    (ahmed,) = _associates("100")
    seed_net_profit(Decimal("10000000.00"))
    older = _company_advance(ahmed, "600000.00", actor, date="2026-07-01")
    newer = _company_advance(ahmed, "200000.00", actor, date="2026-08-01")

    first = _distribute("500000.00", actor, "2026-09-01", "2026-09-15")
    older.refresh_from_db()
    newer.refresh_from_db()
    assert older.amount_repaid == Decimal("500000.00")
    assert newer.amount_repaid == Decimal("0.00")
    assert _share(first, ahmed).remaining_due == Decimal("0.00")

    second = _distribute("1000000.00", actor, "2026-09-16", "2026-09-30")
    older.refresh_from_db()
    newer.refresh_from_db()
    assert older.status == ShareholderLoan.Status.REPAID
    assert newer.status == ShareholderLoan.Status.REPAID
    assert _share(second, ahmed).remaining_due == Decimal("700000.00")


@pytest.mark.django_db
def test_associate_advance_is_never_deducted_from_a_distribution():
    actor = _admin("ADV11")
    ahmed, sidi = _associates("50", "50")
    seed_net_profit(Decimal("10000000.00"))
    _distribute("400000.00", actor, "2026-07-01", "2026-07-31")
    loan = ShareholderLoanService.create_loan(
        borrower_id=sidi.id, lender_id=ahmed.id, amount="100000", date="2026-08-01", actor=actor
    )

    distribution = _distribute("400000.00", actor)

    loan.refresh_from_db()
    assert loan.amount_repaid == Decimal("0.00")
    assert _share(distribution, sidi).amount_withdrawn == Decimal("0.00")


@pytest.mark.django_db
def test_cancelling_the_distribution_puts_the_advance_back_as_a_debt():
    actor = _admin("ADV12")
    (ahmed,) = _associates("100")
    seed_net_profit(Decimal("10000000.00"))
    cash = _cash()
    loan = _company_advance(ahmed, "300000.00", actor)
    _withdraw(ahmed, "300000.00", cash, actor)
    distribution = _distribute("1000000.00", actor)

    ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    loan.refresh_from_db()
    assert loan.amount_repaid == Decimal("0.00")
    assert loan.status == ShareholderLoan.Status.OPEN
    assert not ShareholderLoanRepayment.objects.filter(loan=loan).exists()
    assert _share(distribution, ahmed).amount_withdrawn == Decimal("0.00")
    # Withdrawn and owed again: nothing left to withdraw.
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("0.00")
    assert ShareholderLedgerService.get_company_advance_debt(ahmed.id) == Decimal("300000.00")


@pytest.mark.django_db
def test_closing_a_profit_period_deducts_the_advance():
    actor = _admin("ADV13")
    (ahmed,) = _associates("100")
    seed_net_profit(Decimal("2000000.00"))
    period = ShareholderProfitPeriodService.open_period("2020-01-01", actor)
    loan = _company_advance(ahmed, "250000.00", actor)

    period = ShareholderProfitPeriodService.close_period(period.id, timezone.localdate(), actor)

    loan.refresh_from_db()
    assert period.distribution is not None
    assert loan.status == ShareholderLoan.Status.REPAID
    assert _share(period.distribution, ahmed).amount_withdrawn == Decimal("250000.00")


# --- Repayments --------------------------------------------------------------


@pytest.mark.django_db
def test_company_advance_repaid_into_treasury():
    actor = _admin("ADV14")
    (ahmed,) = _associates("100")
    cash = _cash("1000000.00")
    bank = BankAccount.objects.create(name="Banque BOA", opening_balance=Decimal("0.00"))
    loan = _company_advance(ahmed, "300000.00", actor)
    _withdraw(ahmed, "300000.00", cash, actor)

    with pytest.raises(ShareholderLoanError, match="Un compte"):
        ShareholderLoanService.record_repayment(loan.id, "100000", actor=actor)

    ShareholderLoanService.record_repayment(
        loan.id, "100000", date="2026-08-10", bank_account_id=bank.id, notes="Virement", actor=actor
    )

    loan.refresh_from_db()
    assert loan.status == ShareholderLoan.Status.PARTIALLY_REPAID
    assert loan.remaining_amount == Decimal("200000.00")
    assert loan.repayments.get().method == ShareholderLoanRepayment.Method.TREASURY
    txn = TreasuryTransaction.objects.get(bank_account=bank)
    assert txn.type == "MONEY_IN"
    assert txn.amount == Decimal("100000.00")
    assert describe_treasury_transaction(txn)["counterparty"] == "Remboursement avance - Associe 0"
    # Paid from his own pocket: his balance does not move, his debt does.
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("0.00")
    assert ShareholderLedgerService.get_company_advance_debt(ahmed.id) == Decimal("200000.00")


@pytest.mark.django_db
def test_associate_advance_is_repaid_directly_without_treasury():
    actor = _admin("ADV15")
    ahmed, sidi = _associates("50", "50")
    seed_net_profit(Decimal("10000000.00"))
    _distribute("1000000.00", actor, "2026-07-01", "2026-07-31")
    cash = _cash()
    loan = ShareholderLoanService.create_loan(
        borrower_id=sidi.id, lender_id=ahmed.id, amount="200000", date="2026-08-01", actor=actor
    )
    assert ShareholderLedgerService.get_shareholder_summary(sidi.id)["shareholder_loan_debt"] == (
        Decimal("200000.00")
    )

    with pytest.raises(ShareholderLoanError, match="directement"):
        ShareholderLoanService.record_repayment(loan.id, "50000", cash_account_id=cash.id)
    ShareholderLoanService.record_repayment(loan.id, "50000", date="2026-08-05", actor=actor)

    loan.refresh_from_db()
    assert loan.repayments.get().method == ShareholderLoanRepayment.Method.DIRECT
    assert loan.remaining_amount == Decimal("150000.00")
    assert not TreasuryTransaction.objects.exists()
    assert ShareholderLedgerService.get_shareholder_summary(ahmed.id)[
        "shareholder_loan_receivable"
    ] == Decimal("150000.00")


@pytest.mark.django_db
def test_repayment_cannot_exceed_what_is_still_owed():
    actor = _admin("ADV16")
    (ahmed,) = _associates("100")
    cash = _cash()
    loan = _company_advance(ahmed, "100000.00", actor)

    with pytest.raises(ShareholderLoanError, match="au-dela du principal"):
        ShareholderLoanService.record_repayment(
            loan.id, "100000.01", cash_account_id=cash.id, actor=actor
        )


# --- Statement report --------------------------------------------------------


@pytest.mark.django_db
def test_statement_shows_the_advance_and_matches_the_balance():
    actor = _admin("ADV17")
    (ahmed,) = _associates("100")
    seed_net_profit(Decimal("10000000.00"))
    cash = _cash()
    first = _company_advance(ahmed, "300000.00", actor, date="2026-07-01")
    _company_advance(ahmed, "900000.00", actor, date="2026-07-02")
    _withdraw(ahmed, "1000000.00", cash, actor, date="2026-07-03")
    ShareholderLoanService.record_repayment(
        first.id, "100000", date="2026-07-05", cash_account_id=cash.id, actor=actor
    )
    _distribute("1000000.00", actor)

    rows = ShareholderStatementQuery.run(shareholder_id=ahmed.id)

    assert [r["type"] for r in rows] == [
        "COMPANY_ADVANCE", "COMPANY_ADVANCE", "WITHDRAWAL", "LOAN_REPAYMENT", "PROFIT_SHARE",
        "ADVANCE_DEDUCTION", "ADVANCE_DEDUCTION",
    ]
    # The advance credits his balance, like a profit share.
    assert (rows[0]["debit"], rows[0]["credit"]) == (None, Decimal("300000.00"))
    assert rows[0]["balance"] == Decimal("300000.00")
    # The cash repayment clears debt only: both columns, balance unchanged.
    assert rows[3]["debit"] == rows[3]["credit"] == Decimal("100000.00")
    # The share pays what is still owed (200 000 + 900 000), oldest advance
    # first, up to the 1 000 000 share.
    deductions = [(r["debit"], r["credit"]) for r in rows if r["type"] == "ADVANCE_DEDUCTION"]
    assert deductions == [(Decimal("200000.00"), None), (Decimal("800000.00"), None)]
    assert "Distribution 2026-09-01 - 2026-09-30" in rows[-1]["reference"]
    assert rows[2]["reference"] == f"WD-{ShareholderWithdrawal.objects.get().id} · Caisse avances"
    assert rows[-1]["balance"] == ShareholderLedgerService.get_available_balance(ahmed.id)
    # Advances 1 200 000 + earned 1 000 000 - withdrawn 1 000 000 - deducted
    # 1 000 000: the 200 000 of advance not yet taken; 100 000 still owed.
    assert rows[-1]["balance"] == Decimal("200000.00")
    assert ShareholderLedgerService.get_company_advance_debt(ahmed.id) == Decimal("100000.00")


# --- API ---------------------------------------------------------------------


@pytest.mark.django_db
def test_api_company_advance_withdrawal_repayment_and_archiving_guard(admin_client):
    (ahmed,) = _associates("100")
    cash = _cash()

    created = admin_client.post(
        "/api/shareholder-loans/",
        {
            "source": "COMPANY", "borrower": ahmed.id,
            "amount": "250000.00", "date": "2026-08-01", "notes": "Avance sur benefices",
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["source"] == "COMPANY"
    assert created.data["undrawn_amount"] == "250000.00"
    assert not TreasuryTransaction.objects.exists()

    blocked = admin_client.patch(
        f"/api/shareholders/{ahmed.id}/", {"is_active": False}, format="json"
    )
    assert blocked.status_code == 400
    assert "is_active" in blocked.data

    edit = admin_client.patch(
        f"/api/shareholder-loans/{created.data['id']}/", {"amount": "1"}, format="json"
    )
    assert edit.status_code == 400

    withdrawn = admin_client.post(
        "/api/shareholder-withdrawals/",
        {"shareholder": ahmed.id, "amount": "250000.00", "date": "2026-08-02",
         "cash_account": cash.id},
        format="json",
    )
    assert withdrawn.status_code == 201, withdrawn.data
    assert withdrawn.data["allocations"][0]["advance"] == created.data["id"]

    repaid = admin_client.post(
        f"/api/shareholder-loans/{created.data['id']}/record-repayment/",
        {"amount": "250000.00", "date": "2026-08-20", "cash_account": cash.id},
        format="json",
    )
    assert repaid.status_code == 200, repaid.data
    assert repaid.data["status"] == "REPAID"
    assert repaid.data["amount_drawn"] == "250000.00"
    assert repaid.data["repayments"][0]["method"] == "TREASURY"
    assert repaid.data["repayments"][0]["account_name"] == "Caisse avances"

    ledger = admin_client.get(f"/api/shareholders/{ahmed.id}/ledger/")
    assert ledger.status_code == 200
    assert ledger.data["loans_borrowed"][0]["repayments"][0]["amount"] == "250000.00"

    archived = admin_client.patch(
        f"/api/shareholders/{ahmed.id}/", {"is_active": False}, format="json"
    )
    assert archived.status_code == 200, archived.data


@pytest.mark.django_db
def test_api_associate_advance_still_works_without_source(admin_client):
    actor = _admin("ADV18")
    ahmed, sidi = _associates("50", "50")
    seed_net_profit(Decimal("10000000.00"))
    _distribute("1000000.00", actor, "2026-07-01", "2026-07-31")

    created = admin_client.post(
        "/api/shareholder-loans/",
        {"borrower": sidi.id, "lender": ahmed.id, "amount": "100000.00", "date": "2026-08-01"},
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["source"] == "SHAREHOLDER"

    repaid = admin_client.post(
        f"/api/shareholder-loans/{created.data['id']}/record-repayment/",
        {"amount": "40000.00"},
        format="json",
    )
    assert repaid.status_code == 200, repaid.data
    assert repaid.data["repayments"][0]["method"] == "DIRECT"


# --- Associate advance: part of the lender's balance moves to the borrower ---
# (client correction 2026-10-11)


@pytest.mark.django_db
def test_associate_advance_moves_balance_from_lender_to_borrower():
    actor = _admin("ADV19")
    ahmed, mohamed = _associates("80", "20")
    seed_net_profit(Decimal("10000000.00"))
    _distribute("1000000.00", actor, "2026-07-01", "2026-07-31")  # 800k / 200k

    ShareholderLoanService.create_loan(
        borrower_id=mohamed.id, lender_id=ahmed.id, amount="300000", date="2026-08-01",
        actor=actor,
    )

    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("500000.00")
    assert ShareholderLedgerService.get_available_balance(mohamed.id) == Decimal("500000.00")
    ahmed_summary = ShareholderLedgerService.get_shareholder_summary(ahmed.id)
    mohamed_summary = ShareholderLedgerService.get_shareholder_summary(mohamed.id)
    assert ahmed_summary["shareholder_loan_receivable"] == Decimal("300000.00")
    assert ahmed_summary["net_loan_balance"] == Decimal("-300000.00")
    assert mohamed_summary["shareholder_loan_debt"] == Decimal("300000.00")
    assert mohamed_summary["net_loan_balance"] == Decimal("300000.00")
    assert not TreasuryTransaction.objects.exists()


@pytest.mark.django_db
def test_borrower_withdraws_the_advance_and_lender_cannot_reuse_it():
    actor = _admin("ADV20")
    ahmed, mohamed = _associates("80", "20")
    seed_net_profit(Decimal("10000000.00"))
    _distribute("1000000.00", actor, "2026-07-01", "2026-07-31")
    cash = _cash("5000000.00")
    loan = ShareholderLoanService.create_loan(
        borrower_id=mohamed.id, lender_id=ahmed.id, amount="300000", date="2026-08-01",
        actor=actor,
    )

    withdrawal = _withdraw(mohamed, "500000.00", cash, actor)

    sources = [
        ("share" if a.profit_share_id else "advance" if a.advance_id else "capital", a.amount)
        for a in withdrawal.allocations.all()
    ]
    assert sources == [("share", Decimal("200000.00")), ("advance", Decimal("300000.00"))]
    loan.refresh_from_db()
    assert loan.amount_drawn == Decimal("300000.00")
    assert ShareholderLedgerService.get_available_balance(mohamed.id) == Decimal("0.00")
    with pytest.raises(ShareholderWithdrawalError):
        _withdraw(ahmed, "500000.01", cash, actor)
    _withdraw(ahmed, "500000.00", cash, actor)
    cash.refresh_from_db()
    # 800k + 200k earned, all of it out - nothing more.
    assert cash.current_balance == Decimal("4000000.00")


@pytest.mark.django_db
def test_repayment_moves_the_money_back_and_needs_the_borrower_balance():
    actor = _admin("ADV21")
    ahmed, mohamed = _associates("80", "20")
    seed_net_profit(Decimal("10000000.00"))
    _distribute("1000000.00", actor, "2026-07-01", "2026-07-31")
    cash = _cash("5000000.00")
    loan = ShareholderLoanService.create_loan(
        borrower_id=mohamed.id, lender_id=ahmed.id, amount="300000", date="2026-08-01",
        actor=actor,
    )
    _withdraw(mohamed, "450000.00", cash, actor)  # only 50k left on his account

    with pytest.raises(ShareholderLoanError, match="insuffisant"):
        ShareholderLoanService.record_repayment(loan.id, "50000.01", actor=actor)
    ShareholderLoanService.record_repayment(loan.id, "50000", actor=actor)

    assert ShareholderLedgerService.get_available_balance(mohamed.id) == Decimal("0.00")
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("550000.00")
    loan.refresh_from_db()
    assert loan.remaining_amount == Decimal("250000.00")
    # His next profit lets him repay the rest.
    _distribute("1250000.00", actor, "2026-09-01", "2026-09-30")  # +250k for him
    ShareholderLoanService.record_repayment(loan.id, "250000", actor=actor)
    loan.refresh_from_db()
    assert loan.status == ShareholderLoan.Status.REPAID
    assert ShareholderLedgerService.get_available_balance(mohamed.id) == Decimal("0.00")
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("1800000.00")


@pytest.mark.django_db
def test_giving_back_an_advance_not_withdrawn_simply_cancels_it():
    actor = _admin("ADV22")
    ahmed, mohamed = _associates("80", "20")
    seed_net_profit(Decimal("10000000.00"))
    _distribute("1000000.00", actor, "2026-07-01", "2026-07-31")
    loan = ShareholderLoanService.create_loan(
        borrower_id=mohamed.id, lender_id=ahmed.id, amount="300000", date="2026-08-01",
        actor=actor,
    )

    ShareholderLoanService.record_repayment(loan.id, "300000", actor=actor)

    loan.refresh_from_db()
    assert loan.undrawn_amount == Decimal("0.00")
    assert ShareholderLedgerService.get_available_balance(ahmed.id) == Decimal("800000.00")
    assert ShareholderLedgerService.get_available_balance(mohamed.id) == Decimal("200000.00")


@pytest.mark.django_db
def test_statement_of_an_associate_advance_matches_both_balances():
    actor = _admin("ADV23")
    ahmed, mohamed = _associates("80", "20")
    seed_net_profit(Decimal("10000000.00"))
    _distribute("1000000.00", actor, "2026-07-01", "2026-07-31")
    cash = _cash("5000000.00")
    loan = ShareholderLoanService.create_loan(
        borrower_id=mohamed.id, lender_id=ahmed.id, amount="300000", date="2026-08-01",
        actor=actor,
    )
    _withdraw(mohamed, "400000.00", cash, actor, date="2026-08-02")
    ShareholderLoanService.record_repayment(loan.id, "100000", date="2026-08-03", actor=actor)

    for associate in (ahmed, mohamed):
        rows = ShareholderStatementQuery.run(shareholder_id=associate.id)
        assert rows[-1]["balance"] == ShareholderLedgerService.get_available_balance(associate.id)
    ahmed_rows = ShareholderStatementQuery.run(shareholder_id=ahmed.id)
    assert [(r["type"], r["debit"], r["credit"]) for r in ahmed_rows[1:]] == [
        ("LOAN_GIVEN", Decimal("300000.00"), None),
        ("LOAN_REPAYMENT_RECEIVED", None, Decimal("100000.00")),
    ]


# --- Treasury only moves for real money (client correction 2026-10-11) -------


def _treasury_in_for_repayments():
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(ShareholderLoanRepayment)
    return sum(
        (t.amount for t in TreasuryTransaction.objects.filter(source_content_type=ct)),
        Decimal("0"),
    )


@pytest.mark.django_db
def test_repaying_an_advance_never_withdrawn_cancels_it_without_any_cash():
    actor = _admin("ADV30")
    (mohamed,) = _associates("100")
    cash = _cash("1000000.00")
    loan = _company_advance(mohamed, "1000000.00", actor)

    # Even with an account given, nothing may enter treasury.
    ShareholderLoanService.record_repayment(
        loan.id, "1000000", cash_account_id=cash.id, actor=actor
    )

    loan.refresh_from_db()
    assert loan.status == ShareholderLoan.Status.REPAID
    assert loan.amount_cancelled == Decimal("1000000.00")
    assert loan.repayments.get().method == ShareholderLoanRepayment.Method.CANCEL
    assert not TreasuryTransaction.objects.exists()
    cash.refresh_from_db()
    assert cash.current_balance == Decimal("1000000.00")
    assert ShareholderLedgerService.get_available_balance(mohamed.id) == Decimal("0.00")
    assert ShareholderLedgerService.get_withdrawable_balance(mohamed.id) == Decimal("0.00")
    rows = ShareholderStatementQuery.run(shareholder_id=mohamed.id)
    assert [(r["type"], r["debit"], r["credit"], r["balance"]) for r in rows] == [
        ("COMPANY_ADVANCE", None, Decimal("1000000.00"), Decimal("1000000.00")),
        ("ADVANCE_CANCELLED", Decimal("1000000.00"), None, Decimal("0.00")),
    ]


@pytest.mark.django_db
def test_partly_withdrawn_advance_cancels_the_rest_and_only_the_withdrawn_part_comes_back():
    actor = _admin("ADV31")
    (mohamed,) = _associates("100")
    cash = _cash("5000000.00")
    loan = _company_advance(mohamed, "1000000.00", actor)
    _withdraw(mohamed, "600000.00", cash, actor)
    assert loan.__class__.objects.get(id=loan.id).cash_outstanding == Decimal("600000.00")

    ShareholderLoanService.record_repayment(
        loan.id, "1000000", cash_account_id=cash.id, actor=actor
    )

    loan.refresh_from_db()
    methods = {r.method: r.amount for r in loan.repayments.all()}
    assert methods == {"CANCEL": Decimal("400000.00"), "TREASURY": Decimal("600000.00")}
    assert _treasury_in_for_repayments() == Decimal("600000.00")
    cash.refresh_from_db()
    assert cash.current_balance == Decimal("5000000.00")  # 600k out, 600k back
    assert ShareholderLedgerService.get_available_balance(mohamed.id) == Decimal("0.00")


@pytest.mark.django_db
def test_cash_repayment_never_exceeds_what_was_withdrawn():
    actor = _admin("ADV32")
    (mohamed,) = _associates("100")
    seed_net_profit(Decimal("10000000.00"))
    cash = _cash("5000000.00")
    loan = _company_advance(mohamed, "1000000.00", actor)
    _withdraw(mohamed, "1000000.00", cash, actor)
    _distribute("300000.00", actor)  # 300k of the withdrawn cash covered by profit

    loan.refresh_from_db()
    assert loan.remaining_amount == Decimal("700000.00")
    assert loan.cash_outstanding == Decimal("700000.00")
    with pytest.raises(ShareholderLoanError):
        ShareholderLoanService.record_repayment(
            loan.id, "700000.01", cash_account_id=cash.id, actor=actor
        )
    ShareholderLoanService.record_repayment(
        loan.id, "700000", cash_account_id=cash.id, actor=actor
    )
    cash.refresh_from_db()
    # 1 000 000 out, 700 000 back; 300 000 paid by his profit share.
    assert cash.current_balance == Decimal("4700000.00")
    assert ShareholderLedgerService.get_available_balance(mohamed.id) == Decimal("0.00")


@pytest.mark.django_db
def test_deducted_but_never_withdrawn_advance_repays_without_cash():
    actor = _admin("ADV33")
    (mohamed,) = _associates("100")
    seed_net_profit(Decimal("10000000.00"))
    cash = _cash("5000000.00")
    loan = _company_advance(mohamed, "1000000.00", actor)
    _distribute("300000.00", actor)  # deducts 300k, the advance is untouched

    loan.refresh_from_db()
    assert loan.cash_outstanding == Decimal("0.00")
    ShareholderLoanService.record_repayment(
        loan.id, "700000", cash_account_id=cash.id, actor=actor
    )

    loan.refresh_from_db()
    assert loan.status == ShareholderLoan.Status.REPAID
    assert not TreasuryTransaction.objects.exists()
    # He keeps what he earned (300k), withdrawable from the advance left.
    assert ShareholderLedgerService.get_available_balance(mohamed.id) == Decimal("300000.00")
    _withdraw(mohamed, "300000.00", cash, actor)
    cash.refresh_from_db()
    assert cash.current_balance == Decimal("4700000.00")


@pytest.mark.django_db
def test_api_repayment_of_unwithdrawn_advance_needs_no_account(admin_client):
    (mohamed,) = _associates("100")
    created = admin_client.post(
        "/api/shareholder-loans/",
        {"source": "COMPANY", "borrower": mohamed.id, "amount": "500000.00", "date": "2026-08-01"},
        format="json",
    )
    repaid = admin_client.post(
        f"/api/shareholder-loans/{created.data['id']}/record-repayment/",
        {"amount": "500000.00"},
        format="json",
    )
    assert repaid.status_code == 200, repaid.data
    assert repaid.data["amount_cancelled"] == "500000.00"
    assert repaid.data["repayments"][0]["method"] == "CANCEL"
    assert not TreasuryTransaction.objects.exists()


@pytest.mark.django_db
def test_statement_document_shows_the_advance_cards_in_its_summary():
    from apps.reports.services.report_document import build_report_document

    actor = _admin("ADV40")
    ahmed, mohamed = _associates("80", "20")
    seed_net_profit(Decimal("10000000.00"))
    _distribute("1000000.00", actor, "2026-07-01", "2026-07-31")
    cash = _cash()
    _company_advance(mohamed, "300000.00", actor)
    _withdraw(mohamed, "250000.00", cash, actor)  # 200k share + 50k of the advance
    ShareholderLoanService.create_loan(
        borrower_id=mohamed.id, lender_id=ahmed.id, amount="100000", date="2026-08-01",
        actor=actor,
    )
    params = {"shareholder_id": mohamed.id}
    rows = ShareholderStatementQuery.run(**params)
    document = build_report_document(
        "shareholder-statement", rows, params, "fr",
        statement_context=ShareholderStatementQuery.statement_context(**params),
    )

    summary = {line["key"]: (line["label"], line["value"]) for line in document["summary"]}
    assert summary["company_advance_debt"] == ("Dette envers l'entreprise (à ce jour)", Decimal("300000.00"))
    assert summary["company_advance_undrawn"][1] == Decimal("250000.00")
    assert summary["shareholder_loan_debt"][1] == Decimal("100000.00")
    assert summary["shareholder_loan_receivable"][1] == Decimal("0.00")
    assert summary["withdrawable_balance"][1] == ShareholderLedgerService.get_withdrawable_balance(
        mohamed.id
    )
    assert summary["closing_balance"][1] == ShareholderLedgerService.get_available_balance(mohamed.id)
    type_labels = document["tables"][0]["columns"][1]["enum_labels"]
    assert type_labels["ADVANCE_DEDUCTION"] == "Avance déduite de la part"
    assert type_labels["ADVANCE_CANCELLED"] == "Avance annulée (jamais retirée)"


@pytest.mark.django_db
def test_bank_statement_names_the_associate_when_no_reference(admin_client):
    from apps.reports.queries.treasury_statement import TreasuryStatementQuery

    actor = _admin("ADV41")
    (mohamed,) = _associates("100")
    cash = _cash("1000000.00")
    loan = _company_advance(mohamed, "300000.00", actor)
    _withdraw(mohamed, "300000.00", cash, actor)
    ShareholderLoanService.record_repayment(loan.id, "100000", cash_account_id=cash.id, actor=actor)

    rows = TreasuryStatementQuery.run(cash_account_id=cash.id)

    # The account's opening balance is now the statement's first line.
    assert rows[0]["kind"] == "opening"
    assert [r["reference"] for r in rows[1:]] == [
        "Retrait associe - Associe 0",
        f"AVANCE-{loan.id}",
    ]

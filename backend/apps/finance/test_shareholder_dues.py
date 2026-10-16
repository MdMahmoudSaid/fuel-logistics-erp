# Money the company owes its associates and they have not drawn yet (client
# decision 2026-10-16): capital contributions not given back + validated profit
# shares not withdrawn. An open debt: listed per associate in the "Dettes a
# payer" report and added to the Fond de roulement like every other debt.

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Role, User
from apps.finance.models import BankAccount, Shareholder, ShareholderContribution
from apps.finance.services import (
    ShareholderContributionService,
    ShareholderLedgerService,
    WorkingCapitalService,
)
from apps.reports.queries.debts_summary_report import DebtsSummaryReportQuery


def _admin():
    return User.objects.create_user(
        phone="+22299000011", pin="1234", role=Role.objects.get(name=Role.NAME_ADMIN)
    )


def _contribute(shareholder, bank, admin, amount):
    return ShareholderContributionService.record_contribution(
        shareholder_id=shareholder.id, amount=Decimal(amount), date="2026-10-01", actor=admin,
        attachment=SimpleUploadedFile("p.jpg", b"x", content_type="image/jpeg"),
        bank_account_id=bank.id,
    )


@pytest.mark.django_db
def test_company_dues_are_the_capital_not_given_back_per_associate():
    admin = _admin()
    bank = BankAccount.objects.create(name="Dues Bank")
    a = Shareholder.objects.create(name="Assoc A", participation_percent=Decimal("50"), contribution=Decimal("0"))
    b = Shareholder.objects.create(name="Assoc B", participation_percent=Decimal("50"), contribution=Decimal("0"))
    Shareholder.objects.create(name="Assoc C", participation_percent=Decimal("0"), contribution=Decimal("0"))
    contribution = _contribute(a, bank, admin, "1000000.00")
    _contribute(b, bank, admin, "250000.00")
    ShareholderContribution.objects.filter(pk=contribution.pk).update(amount_returned=Decimal("400000.00"))

    dues = ShareholderLedgerService.get_company_dues()

    # C owes nothing and is not listed; A's drawn capital is no longer owed.
    assert [(r["name"], r["amount"]) for r in dues["shareholders"]] == [
        ("Assoc A", Decimal("600000.00")),
        ("Assoc B", Decimal("250000.00")),
    ]
    assert dues["total"] == Decimal("850000.00")


@pytest.mark.django_db
def test_dues_are_information_in_the_working_capital_and_listed_in_the_debts_report():
    admin = _admin()
    bank = BankAccount.objects.create(name="Dues Bank 2")
    a = Shareholder.objects.create(name="Assoc A", participation_percent=Decimal("100"), contribution=Decimal("0"))
    _contribute(a, bank, admin, "1000000.00")

    wc = WorkingCapitalService.get_working_capital()

    assert wc["shareholder_dues"] == Decimal("1000000.00")
    # A 1,000,000 contribution reads as 1,000,000 (the treasury), never 2,000,000.
    assert wc["total"] == wc["gross"] == Decimal("1000000.00")
    rows = DebtsSummaryReportQuery.run()
    assert {"party_type": "shareholder", "party": "Assoc A", "amount": Decimal("1000000.00")} in rows


@pytest.mark.django_db
def test_dues_match_the_raw_rows_and_no_other_fond_de_roulement_line_changes_with_them():
    """Proof that the "Dettes envers les associes" line is counted once:
    it equals an independent sum over the raw capital / profit-share rows, the
    total is exactly the sum of its distinct lines, and validating a profit
    share (which raises the dues) moves no other line."""
    from django.db.models import F, Sum

    from apps.finance.models import (
        ShareholderProfitDistribution,
        ShareholderProfitShare,
    )
    from apps.finance.services import ShareholderDistributionService, ShareholderWithdrawalService
    from apps.finance.testing_helpers import seed_net_profit

    admin = _admin()
    bank = BankAccount.objects.create(name="Proof Bank")
    a = Shareholder.objects.create(name="A", participation_percent=Decimal("60"), contribution=Decimal("0"))
    b = Shareholder.objects.create(name="B", participation_percent=Decimal("40"), contribution=Decimal("0"))
    _contribute(a, bank, admin, "1000000.00")
    _contribute(b, bank, admin, "500000.00")
    seed_net_profit(Decimal("10000000.00"))

    def lines():
        wc = WorkingCapitalService.get_working_capital()
        parts = ("treasury_available", "customer_receivables", "supplier_debt_total",
                 "transporter_debt_total", "other_debts",
                 "supplier_reliquat_value", "supplier_in_transit_value", "supplier_company_stock_value")
        # Each component appears once in the total; "capital" and "shareholder_dues"
        # are information only (that money is already in treasury).
        assert wc["total"] == sum((wc[k] for k in parts), Decimal("0.00"))
        return wc

    def raw_dues():
        capital = ShareholderContribution.objects.filter(cancelled_at__isnull=True).aggregate(
            t=Sum(F("amount") - F("amount_returned")))["t"] or Decimal("0.00")
        profit = ShareholderProfitShare.objects.filter(
            distribution__status=ShareholderProfitDistribution.Status.VALIDATED
        ).aggregate(t=Sum(F("amount_due") - F("amount_withdrawn")))["t"] or Decimal("0.00")
        return capital + profit

    before = lines()
    assert before["shareholder_dues"] == raw_dues() == Decimal("1500000.00")

    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31", total_profit=Decimal("1000000.00"), actor=admin,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, admin)
    after = lines()
    # Profit validated: only the dues move (+1,000,000); treasury, every other
    # line and the TOTAL are untouched (no money has moved).
    assert after["total"] == before["total"]
    assert after["shareholder_dues"] == raw_dues() == Decimal("2500000.00")
    for key in ("treasury_available", "customer_receivables", "supplier_debt_total",
                "transporter_debt_total", "other_debts", "supplier_reliquat_value",
                "supplier_in_transit_value", "supplier_company_stock_value", "capital"):
        assert after[key] == before[key], key

    # A withdraws 700,000: it takes his 600,000 profit share first, then 100,000 of capital.
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=a.id, amount=Decimal("700000.00"), date="2026-10-10", actor=admin,
        bank_account_id=bank.id,
    )
    final = lines()
    # The cash really left treasury: the total drops by exactly 700,000, once.
    assert final["total"] == after["total"] - Decimal("700000.00")
    assert final["shareholder_dues"] == raw_dues() == Decimal("1800000.00")
    assert [(r["name"], r["amount"]) for r in ShareholderLedgerService.get_company_dues()["shareholders"]] == [
        ("A", Decimal("900000.00")),  # 1,000,000 capital - 100,000 drawn; profit fully drawn
        ("B", Decimal("900000.00")),  # 500,000 capital + 400,000 profit, nothing drawn
    ]

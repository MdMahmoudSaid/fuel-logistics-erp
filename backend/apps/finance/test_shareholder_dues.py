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
def test_dues_are_added_to_the_working_capital_and_listed_in_the_debts_report():
    admin = _admin()
    bank = BankAccount.objects.create(name="Dues Bank 2")
    a = Shareholder.objects.create(name="Assoc A", participation_percent=Decimal("100"), contribution=Decimal("0"))
    _contribute(a, bank, admin, "1000000.00")

    wc = WorkingCapitalService.get_working_capital()

    assert wc["shareholder_dues"] == Decimal("1000000.00")
    assert wc["total"] == wc["gross"] + Decimal("1000000.00")  # no other debt exists
    rows = DebtsSummaryReportQuery.run()
    assert {"party_type": "shareholder", "party": "Assoc A", "amount": Decimal("1000000.00")} in rows

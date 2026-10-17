# Profit brought from the previous application (client request 2026-10-17):
# counted in the all-time net profit, i.e. in "Benefice net apres depenses
# generales" and in what the first period closure distributes; no treasury
# movement; the Situation financiere check turns green.

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.core.models import CompanyProfile
from apps.finance.models import BankAccount, Shareholder, TreasuryTransaction
from apps.finance.services import (
    ShareholderProfitPeriodService,
    ShareholderProfitPreviewService,
)
from apps.reports.services.financial_position import FinancialPositionService
from apps.trips.tests import _setup_fixtures

D = Decimal


def _set(amount):
    profile = CompanyProfile.load()
    profile.brought_forward_profit = D(amount)
    profile.save()


@pytest.mark.django_db
def test_brought_forward_profit_is_the_net_profit_and_the_distributable_result():
    _set("92358500.00")

    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["net_profit"] == D("92358500.00")
    assert preview["distributable_result"] == D("92358500.00")
    assert preview["all_time_net_profit"] == D("92358500.00")
    # A dated window never hides it (it is all-time like every other term).
    dated = ShareholderProfitPreviewService.get_preview(date_from="2026-09-01", date_to="2026-09-30")
    assert dated["net_profit"] == D("92358500.00")


@pytest.mark.django_db
def test_open_period_reconciliation_includes_it_until_the_first_closure():
    _set("1000.00")

    preview = ShareholderProfitPreviewService.get_preview(
        date_from="2026-09-01", date_to=timezone.localdate(), since_last_closure=True
    )

    assert preview["brought_forward_profit"] == D("1000.00")
    assert (
        preview["operational_profit"]
        - preview["general_expenses_paid"]
        + preview["carried_over"]
        + preview["brought_forward_profit"]
        - preview["distributions_since_closure"]
    ) == preview["distributable_result"]


@pytest.mark.django_db
def test_closing_the_period_distributes_it_to_the_shareholders():
    fx = _setup_fixtures()
    _set("1000.00")
    shareholder = Shareholder.objects.create(name="A", participation_percent=D("100.00"))
    period = ShareholderProfitPeriodService.open_period("2026-08-01", fx["admin_user"])

    closed = ShareholderProfitPeriodService.close_period(period.id, "2026-08-31", fx["admin_user"])

    assert closed.net_profit == D("1000.00")
    assert closed.distribution.total_profit == D("1000.00")
    assert closed.distribution.shares.get(shareholder=shareholder).amount_due == D("1000.00")
    after = ShareholderProfitPreviewService.get_preview()
    assert after["distributable_result"] == D("0.00")  # distributed once, never twice
    reopened = ShareholderProfitPreviewService.get_preview(
        date_from="2026-09-01", date_to=timezone.localdate(), since_last_closure=True
    )
    assert reopened["brought_forward_profit"] == D("0.00")  # now behind the closure


@pytest.mark.django_db
def test_no_treasury_movement_and_the_financial_position_check_turns_green():
    BankAccount.objects.create(name="B1", opening_balance=D("92358500.00"))
    before = FinancialPositionService.get_position()
    assert before["gap"] == D("92358500.00")  # opening money, not yet counted as profit

    _set("92358500.00")
    after = FinancialPositionService.get_position()

    assert after["gap"] == D("0.00")
    assert after["net_result"] == after["distributable_result"] == D("92358500.00")
    assert TreasuryTransaction.objects.count() == 0


@pytest.mark.django_db
def test_set_command_dry_run_then_apply_and_negative_refused():
    out = StringIO()
    call_command("set_brought_forward_profit", "500", stdout=out)
    assert CompanyProfile.load().brought_forward_profit == D("0.00")  # dry run writes nothing

    call_command("set_brought_forward_profit", "500", "--apply", stdout=out)
    assert CompanyProfile.load().brought_forward_profit == D("500.00")

    with pytest.raises(CommandError):
        call_command("set_brought_forward_profit", "-1", "--apply", stdout=out)

# Profit added by hand (client request 2026-10-17): counts in the net profit,
# is posted to the chosen account so the treasury / Situation financiere stay
# balanced, is shared by the next period closure, and can be cancelled until
# it has been distributed.

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.finance.models import BankAccount, ManualProfit, Shareholder, TreasuryTransaction
from apps.finance.services import (
    ManualProfitError,
    ManualProfitService,
    ShareholderProfitPeriodService,
    ShareholderProfitPreviewService,
)
from apps.reports.services.financial_position import FinancialPositionService
from apps.trips.tests import _setup_fixtures

D = Decimal
TODAY = timezone.localdate()


def _admin():
    return User.objects.create_user(
        phone="+22299000077", pin="1234", role=Role.objects.get(name=Role.NAME_ADMIN)
    )


@pytest.mark.django_db
def test_with_an_account_it_is_profit_and_treasury_and_the_position_stays_balanced():
    admin = _admin()
    bank = BankAccount.objects.create(name="B1", opening_balance=D("0.00"))
    before = FinancialPositionService.get_position()

    ManualProfitService.record(
        amount="5000", date=TODAY, note="Cadeau", actor=admin, bank_account_id=bank.id
    )

    preview = ShareholderProfitPreviewService.get_preview()
    assert preview["net_profit"] == preview["distributable_result"] == D("5000.00")
    assert bank.current_balance == D("5000.00")
    after = FinancialPositionService.get_position()
    assert after["gap"] == before["gap"]  # treasury and profit moved together
    assert after["net_result"] == before["net_result"] + D("5000.00")


@pytest.mark.django_db
def test_an_account_is_required():
    with pytest.raises(ManualProfitError):
        ManualProfitService.record(amount="100", date=TODAY, note="x", actor=_admin())
    assert ManualProfit.objects.count() == 0


@pytest.mark.django_db
def test_the_reference_in_the_statement_is_the_reason():
    from apps.reports.queries.treasury_statement import TreasuryStatementQuery

    admin = _admin()
    bank = BankAccount.objects.create(name="B1", opening_balance=D("0.00"))
    ManualProfitService.record(
        amount="900", date=TODAY, note="Don de Moussa", actor=admin, bank_account_id=bank.id
    )

    rows = TreasuryStatementQuery.run(bank_account_id=bank.id)

    assert any(r["reference"] == "Don de Moussa" for r in rows)


@pytest.mark.django_db
def test_validation_and_admin_only():
    admin = _admin()
    bank = BankAccount.objects.create(name="B2", opening_balance=D("0.00"))
    with pytest.raises(ManualProfitError):
        ManualProfitService.record(amount="0", date=TODAY, note="x", actor=admin, bank_account_id=bank.id)
    with pytest.raises(ManualProfitError):
        ManualProfitService.record(amount="10", date=TODAY, note="  ", actor=admin, bank_account_id=bank.id)
    ops = User.objects.create_user(
        phone="+22299000078", pin="1234", role=Role.objects.get(name=Role.NAME_OPERATIONS)
    )
    with pytest.raises(ManualProfitError):
        ManualProfitService.record(amount="10", date=TODAY, note="x", actor=ops, bank_account_id=bank.id)


@pytest.mark.django_db
def test_cancel_reverses_profit_and_treasury():
    admin = _admin()
    bank = BankAccount.objects.create(name="B1", opening_balance=D("0.00"))
    profit = ManualProfitService.record(
        amount="700", date=TODAY, note="x", actor=admin, bank_account_id=bank.id
    )

    ManualProfitService.cancel(profit, admin, "erreur")

    assert ShareholderProfitPreviewService.get_preview()["net_profit"] == D("0.00")
    assert bank.current_balance == D("0.00")
    with pytest.raises(ManualProfitError):
        ManualProfitService.cancel(profit, admin, "encore")


@pytest.mark.django_db
def test_closing_the_period_shares_it_and_then_it_cannot_be_cancelled():
    fx = _setup_fixtures()
    admin = fx["admin_user"]
    shareholder = Shareholder.objects.create(name="A", participation_percent=D("100.00"))
    period = ShareholderProfitPeriodService.open_period("2026-08-01", admin)
    bank = BankAccount.objects.create(name="B1", opening_balance=D("0.00"))
    profit = ManualProfitService.record(
        amount="1000", date=TODAY, note="x", actor=admin, bank_account_id=bank.id
    )

    open_view = ShareholderProfitPreviewService.get_preview(
        date_from="2026-08-01", date_to=TODAY, since_last_closure=True
    )
    assert open_view["manual_profit"] == D("1000.00")

    closed = ShareholderProfitPeriodService.close_period(period.id, TODAY, admin)
    assert closed.distribution.shares.get(shareholder=shareholder).amount_due == D("1000.00")
    assert ShareholderProfitPreviewService.get_preview()["distributable_result"] == D("0.00")
    with pytest.raises(ManualProfitError):
        ManualProfitService.cancel(profit, admin, "trop tard")

    # behind the closure now: the next open period starts again from zero
    next_view = ShareholderProfitPreviewService.get_preview(
        date_from=TODAY, date_to=TODAY, since_last_closure=True
    )
    assert next_view["manual_profit"] == D("0.00")


@pytest.mark.django_db
def test_api_create_list_cancel():
    admin = _admin()
    bank = BankAccount.objects.create(name="B1", opening_balance=D("0.00"))
    client = APIClient()
    client.force_authenticate(admin)

    created = client.post(
        "/api/manual-profits/",
        {"amount": "250.00", "date": str(TODAY), "note": "Don", "bank_account": bank.id},
        format="json",
    )
    assert created.status_code == 201, created.content
    assert client.get("/api/manual-profits/").json()["results"][0]["amount"] == "250.00"
    assert client.delete(f"/api/manual-profits/{created.json()['id']}/").status_code == 405

    cancelled = client.post(
        f"/api/manual-profits/{created.json()['id']}/cancel/", {"reason": "oops"}, format="json"
    )
    assert cancelled.status_code == 200
    assert ManualProfit.objects.get().is_cancelled

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.finance.models import (
    CashAccount,
    Expense,
    Shareholder,
    ShareholderProfitDistribution,
    ShareholderProfitPeriod,
    TreasuryTransaction,
)
from apps.finance.services import (
    ShareholderProfitPeriodError,
    ShareholderProfitPeriodService,
)
from apps.finance.testing_helpers import seed_net_profit


def actor(suffix="PERIOD"):
    role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=f"+22271{suffix}"[:20], pin="1234", role=role)


@pytest.mark.django_db
def test_flexible_period_closes_and_validates_exact_profit_split():
    user = actor("CLOSE")
    shareholder = Shareholder.objects.create(
        name="Associe periode", participation_percent=Decimal("100.00")
    )
    seed_net_profit(Decimal("4850000.00"))

    period = ShareholderProfitPeriodService.open_period("2026-01-01", user)
    period = ShareholderProfitPeriodService.close_period(period.id, "2026-04-30", user)

    assert period.status == ShareholderProfitPeriod.Status.CLOSED
    assert period.net_profit == Decimal("4850000.00")
    assert period.distribution.status == ShareholderProfitDistribution.Status.VALIDATED
    share = period.distribution.shares.get(shareholder=shareholder)
    assert share.amount_due == Decimal("4850000.00")


@pytest.mark.django_db
def test_closed_period_blocks_financial_writes_until_audited_reopen():
    user = actor("LOCK")
    Shareholder.objects.create(name="Associe verrou", participation_percent=Decimal("100.00"))
    seed_net_profit(Decimal("1000.00"))
    period = ShareholderProfitPeriodService.open_period("2026-02-01", user)
    period = ShareholderProfitPeriodService.close_period(period.id, "2026-05-31", user)
    account = CashAccount.objects.create(name="Caisse periode")

    with pytest.raises(ValidationError, match="cloturee"):
        Expense.objects.create(
            category=Expense.Category.OTHER,
            amount=Decimal("1.00"),
            calculation_method=Expense.CalculationMethod.MANUAL,
            date="2026-03-15",
        )

    # A cash movement that does not alter profit remains legal; this is
    # required for paying an associate after their share was distributed.
    TreasuryTransaction.objects.create(
        cash_account=account,
        type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("1.00"),
        date="2026-03-15",
        recorded_by=user,
    )

    old_distribution_id = period.distribution_id
    period = ShareholderProfitPeriodService.reopen_period(
        period.id, "Correction d'une vente oubliee", user
    )
    assert period.status == ShareholderProfitPeriod.Status.OPEN
    assert period.end_date is None
    assert period.reopen_count == 1
    assert ShareholderProfitDistribution.objects.get(pk=old_distribution_id).status == "CANCELLED"
    audit = AuditLog.objects.filter(
        content_type__model="shareholderprofitperiod", object_id=period.id
    ).first()
    assert audit.reason == "Correction d'une vente oubliee"

    Expense.objects.create(
        category=Expense.Category.OTHER,
        amount=Decimal("1.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-03-15",
    )


@pytest.mark.django_db
def test_only_latest_closed_period_can_reopen_and_reason_is_required():
    user = actor("LATEST")
    Shareholder.objects.create(name="Associe historique", participation_percent=Decimal("100.00"))
    # No distribution is needed for this transition-only test; keeping the
    # result at zero isolates the latest-period/reason rules.
    seed_net_profit(Decimal("0.00"))
    first = ShareholderProfitPeriodService.open_period("2026-01-01", user)
    first = ShareholderProfitPeriodService.close_period(first.id, "2026-01-31", user)
    second = ShareholderProfitPeriodService.open_period("2026-02-01", user)
    ShareholderProfitPeriodService.close_period(second.id, "2026-02-28", user)

    with pytest.raises(ShareholderProfitPeriodError, match="derniere"):
        ShareholderProfitPeriodService.reopen_period(first.id, "Ancienne correction", user)
    with pytest.raises(ShareholderProfitPeriodError, match="Expliquez"):
        ShareholderProfitPeriodService.reopen_period(second.id, "non", user)


@pytest.mark.django_db
def test_automatic_rollover_waits_until_next_day_and_is_idempotent():
    user = actor("AUTO")
    Shareholder.objects.create(name="Associe auto", participation_percent=Decimal("100.00"))
    period = ShareholderProfitPeriodService.open_period("2026-06-01", user)
    ShareholderProfitPeriodService.close_period(period.id, "2026-06-30", user)

    pending, created = ShareholderProfitPeriodService.ensure_current_period(
        user, as_of=date(2026, 6, 30)
    )
    assert pending is None
    assert created is False

    successor, created = ShareholderProfitPeriodService.ensure_current_period(
        user, as_of=date(2026, 7, 1)
    )
    assert created is True
    assert successor.start_date == date(2026, 7, 1)
    assert successor.status == ShareholderProfitPeriod.Status.OPEN

    same_successor, created = ShareholderProfitPeriodService.ensure_current_period(
        user, as_of=date(2026, 7, 2)
    )
    assert created is False
    assert same_successor.id == successor.id
    assert ShareholderProfitPeriod.objects.filter(status="OPEN").count() == 1

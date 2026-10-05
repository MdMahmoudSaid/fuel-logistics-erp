from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
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
def test_closed_period_never_blocks_writes_and_reopen_is_audited():
    # Client decision (2026-10-05): closing only distributes and resets the
    # counters - a write dated inside a closed period still goes through
    # (it flows into the open period / next distribution).
    user = actor("LOCK")
    Shareholder.objects.create(name="Associe verrou", participation_percent=Decimal("100.00"))
    seed_net_profit(Decimal("1000.00"))
    period = ShareholderProfitPeriodService.open_period("2026-02-01", user)
    period = ShareholderProfitPeriodService.close_period(period.id, "2026-05-31", user)
    account = CashAccount.objects.create(name="Caisse periode")

    Expense.objects.create(
        category=Expense.Category.OTHER,
        amount=Decimal("1.00"),
        calculation_method=Expense.CalculationMethod.MANUAL,
        date="2026-03-15",
    )

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
    # close_period auto-opens the next period (2026-02-01) - no manual
    # open_period call needed or possible here anymore.
    second = ShareholderProfitPeriod.objects.get(status=ShareholderProfitPeriod.Status.OPEN)
    assert second.start_date == date(2026, 2, 1)
    ShareholderProfitPeriodService.close_period(second.id, "2026-02-28", user)

    with pytest.raises(ShareholderProfitPeriodError, match="derniere"):
        ShareholderProfitPeriodService.reopen_period(first.id, "Ancienne correction", user)
    with pytest.raises(ShareholderProfitPeriodError, match="Expliquez"):
        ShareholderProfitPeriodService.reopen_period(second.id, "non", user)


@pytest.mark.django_db
def test_close_period_auto_opens_the_next_period():
    user = actor("AUTOOPEN")
    Shareholder.objects.create(name="Associe auto", participation_percent=Decimal("100.00"))
    seed_net_profit(Decimal("0.00"))
    period = ShareholderProfitPeriodService.open_period("2026-01-01", user)
    ShareholderProfitPeriodService.close_period(period.id, "2026-01-31", user)

    successor = ShareholderProfitPeriod.objects.get(status=ShareholderProfitPeriod.Status.OPEN)
    assert successor.start_date == date(2026, 2, 1)
    assert successor.end_date is None


@pytest.mark.django_db
def test_close_period_through_today_still_auto_opens_tomorrow():
    # The common case: closing a period almost always ends it today (you
    # close the books up through now), not through some already-finished
    # day - open_period's "at most tomorrow" allowance is what makes
    # auto-open succeed here instead of leaving operations stuck.
    user = actor("AUTOTODAY")
    Shareholder.objects.create(name="Associe jour", participation_percent=Decimal("100.00"))
    seed_net_profit(Decimal("0.00"))
    today = timezone.localdate()
    period = ShareholderProfitPeriodService.open_period(
        (today - timedelta(days=1)).isoformat(), user
    )
    ShareholderProfitPeriodService.close_period(period.id, today.isoformat(), user)

    successor = ShareholderProfitPeriod.objects.get(
        status=ShareholderProfitPeriod.Status.OPEN
    )
    assert successor.start_date == today + timedelta(days=1)


@pytest.mark.django_db
def test_open_period_rejects_a_start_date_more_than_one_day_ahead():
    user = actor("TOOFAR")
    today = timezone.localdate()
    with pytest.raises(ShareholderProfitPeriodError, match="demain"):
        ShareholderProfitPeriodService.open_period(
            (today + timedelta(days=2)).isoformat(), user
        )


@pytest.mark.django_db
def test_reopening_latest_period_retracts_its_auto_opened_successor():
    user = actor("RETRACT")
    Shareholder.objects.create(name="Associe retrait", participation_percent=Decimal("100.00"))
    seed_net_profit(Decimal("0.00"))
    period = ShareholderProfitPeriodService.open_period("2026-01-01", user)
    period = ShareholderProfitPeriodService.close_period(period.id, "2026-01-31", user)
    successor_id = ShareholderProfitPeriod.objects.get(
        status=ShareholderProfitPeriod.Status.OPEN
    ).id

    period = ShareholderProfitPeriodService.reopen_period(
        period.id, "Correction necessaire", user
    )

    assert period.status == ShareholderProfitPeriod.Status.OPEN
    assert not ShareholderProfitPeriod.objects.filter(pk=successor_id).exists()
    assert (
        ShareholderProfitPeriod.objects.filter(
            status=ShareholderProfitPeriod.Status.OPEN
        ).count()
        == 1
    )

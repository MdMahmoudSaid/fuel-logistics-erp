from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import Role, User
from apps.finance.models import (
    BankAccount,
    CashAccount,
    Shareholder,
    ShareholderContribution,
    ShareholderWithdrawal,
    ShareholderWithdrawalAllocation,
)


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=(f"+223{suffix}")[:20], pin="1234", role=admin_role)


def _make_shareholder(suffix, percent=Decimal("100.00")):
    return Shareholder.objects.create(name=f"Shareholder {suffix}", participation_percent=percent)


def _seed_distributable(amount=Decimal("10000000.00"), name="Seed Till"):
    """Same helper as apps/finance/tests.py:_seed_distributable - copied
    rather than imported across test modules (tests.py is a test file, not
    a shared fixtures module). Gives the company enough treasury that
    validate_distribution's hard amount block (2026-09-08 review) clears,
    for tests where that guard is not what is under test."""
    return CashAccount.objects.create(name=name, opening_balance=Decimal(str(amount)))


@pytest.mark.django_db
def test_allocation_requires_exactly_one_source():
    admin_user = _make_admin("ALLOC-MODEL-1")
    shareholder = _make_shareholder("ALLOC-MODEL-1")
    cash = CashAccount.objects.create(name="Alloc Cash 1", opening_balance=Decimal("1000000.00"))
    withdrawal = ShareholderWithdrawal.objects.create(
        shareholder=shareholder, amount=Decimal("1000.00"), date="2026-09-15",
        cash_account=cash, recorded_by=admin_user,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ShareholderWithdrawalAllocation.objects.create(
                withdrawal=withdrawal, amount=Decimal("1000.00"),
            )


@pytest.mark.django_db
def test_allocation_rejects_both_sources_set():
    admin_user = _make_admin("ALLOC-MODEL-2")
    shareholder = _make_shareholder("ALLOC-MODEL-2")
    bank = BankAccount.objects.create(name="Alloc Bank 2", opening_balance=Decimal("0.00"))
    cash = CashAccount.objects.create(name="Alloc Cash 2", opening_balance=Decimal("1000000.00"))
    withdrawal = ShareholderWithdrawal.objects.create(
        shareholder=shareholder, amount=Decimal("1000.00"), date="2026-09-15",
        cash_account=cash, recorded_by=admin_user,
    )
    contribution = ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("5000.00"), date="2026-09-01",
        bank_account=bank, recorded_by=admin_user,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ShareholderWithdrawalAllocation.objects.create(
                withdrawal=withdrawal, contribution=contribution,
                profit_share_id=999999, amount=Decimal("1000.00"),
            )


@pytest.mark.django_db
def test_allocation_amount_must_be_positive():
    admin_user = _make_admin("ALLOC-MODEL-3")
    shareholder = _make_shareholder("ALLOC-MODEL-3")
    bank = BankAccount.objects.create(name="Alloc Bank 3", opening_balance=Decimal("0.00"))
    cash = CashAccount.objects.create(name="Alloc Cash 3", opening_balance=Decimal("1000000.00"))
    withdrawal = ShareholderWithdrawal.objects.create(
        shareholder=shareholder, amount=Decimal("1000.00"), date="2026-09-15",
        cash_account=cash, recorded_by=admin_user,
    )
    contribution = ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("5000.00"), date="2026-09-01",
        bank_account=bank, recorded_by=admin_user,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ShareholderWithdrawalAllocation.objects.create(
                withdrawal=withdrawal, contribution=contribution, amount=Decimal("0.00"),
            )


@pytest.mark.django_db
def test_backfill_migration_creates_one_allocation_per_existing_withdrawal():
    from django.apps import apps as django_apps
    from django.db.migrations.executor import MigrationExecutor
    from django.db import connection

    admin_user = _make_admin("BACKFILL-1")
    shareholder = _make_shareholder("BACKFILL-1")
    cash = CashAccount.objects.create(name="Backfill Cash", opening_balance=Decimal("1000000.00"))

    executor = MigrationExecutor(connection)
    executor.migrate([("finance", "0023_shareholderwithdrawalallocation")])
    old_apps = executor.loader.project_state(
        [("finance", "0023_shareholderwithdrawalallocation")]
    ).apps
    OldShareholderProfitDistribution = old_apps.get_model("finance", "ShareholderProfitDistribution")
    OldShareholderProfitShare = old_apps.get_model("finance", "ShareholderProfitShare")
    OldShareholderWithdrawal = old_apps.get_model("finance", "ShareholderWithdrawal")

    # Note: historical models from old_apps are dynamically-built classes
    # distinct from the real current-app model classes, so a FK from a
    # historical model to a real-app instance (admin_user, shareholder,
    # cash) must be set via its `_id` kwarg - assigning the object
    # directly fails Django's isinstance check on the FK descriptor.
    distribution = OldShareholderProfitDistribution.objects.create(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("100000.00"), status="VALIDATED", created_by_id=admin_user.id,
    )
    share = OldShareholderProfitShare.objects.create(
        distribution=distribution, shareholder_id=shareholder.id,
        percent_snapshot=Decimal("100.00"), amount_due=Decimal("100000.00"),
    )
    old_withdrawal = OldShareholderWithdrawal.objects.create(
        shareholder_id=shareholder.id, profit_share=share, amount=Decimal("40000.00"),
        date="2026-08-01", cash_account_id=cash.id, recorded_by_id=admin_user.id,
    )

    # Every FK constraint in this schema is DEFERRABLE INITIALLY DEFERRED
    # (verified via `\d finance_shareholderwithdrawal` - a project-wide
    # convention, not something this test introduces), so the FK check
    # queued by the INSERT above stays pending until end of transaction
    # instead of firing immediately. Left alone, that queued check makes
    # the DROP COLUMN in migration 0025 (applied below via the leaf-nodes
    # migrate at the end of this test) fail with "cannot ALTER TABLE ...
    # because it has pending trigger events", since Django fuses its own
    # "SET CONSTRAINTS ... IMMEDIATE; ALTER TABLE ... DROP CONSTRAINT"
    # into one round trip that doesn't reliably flush it first. Running
    # `SET CONSTRAINTS ALL IMMEDIATE` here as its own separate round trip
    # settles it, so this test can stay on the default rollback-based
    # django_db fixture rather than `transaction=True` - the latter would
    # flush the test DB (this codebase's finance/tests.py documents that
    # even `serialized_rollback=True` does not reliably restore the
    # Role/Product rows a data migration seeds, starving whichever test
    # runs next in the same session).
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    executor = MigrationExecutor(connection)
    executor.migrate([("finance", "0024_backfill_withdrawal_allocations")])

    new_apps = executor.loader.project_state(
        [("finance", "0024_backfill_withdrawal_allocations")]
    ).apps
    NewShareholderWithdrawalAllocation = new_apps.get_model("finance", "ShareholderWithdrawalAllocation")
    allocations = list(NewShareholderWithdrawalAllocation.objects.filter(withdrawal_id=old_withdrawal.id))

    assert len(allocations) == 1
    assert allocations[0].profit_share_id == share.id
    assert allocations[0].contribution_id is None
    assert allocations[0].amount == Decimal("40000.00")

    # Bring the DB back to the latest migration so later tests run against
    # the final schema, matching how pytest-django expects to find it.
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())

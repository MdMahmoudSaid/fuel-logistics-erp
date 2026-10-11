from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import Role, User
from apps.finance.models import (
    BankAccount,
    CashAccount,
    Shareholder,
    ShareholderContribution,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
    ShareholderWithdrawalAllocation,
)
from apps.finance.testing_helpers import seed_net_profit
from apps.finance.services import (
    ShareholderDistributionService,
    ShareholderLedgerService,
    ShareholderLoanService,
    ShareholderWithdrawalError,
    ShareholderWithdrawalService,
)


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=(f"+223{suffix}")[:20], pin="1234", role=admin_role)


def _make_shareholder(suffix, percent=Decimal("100.00")):
    return Shareholder.objects.create(name=f"Shareholder {suffix}", participation_percent=percent)


def _seed_distributable(amount=Decimal("10000000.00"), name="Seed Till"):
    """Same helper as apps/finance/tests.py:_seed_distributable - seeds a
    computed net profit (validate_distribution's amount guard, 2026-09-25)
    plus the treasury the withdrawals then draw on."""
    seed_net_profit(amount)
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

    # Rolling back 0029 drops foreign keys to accounts_user, which the
    # pending (deferred) FK check of the user created above would block -
    # same fix as before the forward migrate below.
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

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


@pytest.mark.django_db
def test_get_available_balance_includes_capital_remaining():
    """Direct regression test for the additive formula (design doc
    2026-09-15-capital-associe-retrait-design.md): profit due and capital
    remaining must both count, independently of any withdrawal."""
    shareholder = _make_shareholder("BALANCE-FORMULA")
    actor = _make_admin("BALANCE-FORMULA")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("300000.00"), actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    bank = BankAccount.objects.create(name="Bank Balance Formula", opening_balance=Decimal("0.00"))
    ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("500000.00"), date="2026-07-15",
        bank_account=bank, recorded_by=actor,
    )

    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("800000.00")


@pytest.mark.django_db
def test_withdrawal_within_profit_due_allocates_only_to_profit():
    shareholder = _make_shareholder("ALLOC-PROFIT-ONLY")
    actor = _make_admin("ALLOC-PROFIT-ONLY")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("100000.00"), actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    cash = CashAccount.objects.create(name="Cash Profit Only", opening_balance=Decimal("100000.00"))

    withdrawal = ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id, amount=Decimal("60000.00"), date="2026-08-01",
        cash_account_id=cash.id, actor=actor,
    )

    allocations = list(withdrawal.allocations.all())
    assert len(allocations) == 1
    assert allocations[0].profit_share_id is not None
    assert allocations[0].contribution_id is None
    assert allocations[0].amount == Decimal("60000.00")


@pytest.mark.django_db
def test_withdrawal_exceeding_profit_due_overflows_into_capital():
    """The client's own example: 100M profit due, a 700K withdrawal request
    (well within total available_balance once capital counts) must draw
    the profit pool dry then take the rest from capital."""
    shareholder = _make_shareholder("ALLOC-OVERFLOW")
    actor = _make_admin("ALLOC-OVERFLOW")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("500000.00"), actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    bank = BankAccount.objects.create(name="Bank Overflow", opening_balance=Decimal("0.00"))
    ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("1000000.00"), date="2026-07-15",
        bank_account=bank, recorded_by=actor,
    )
    cash = CashAccount.objects.create(name="Cash Overflow", opening_balance=Decimal("1000000.00"))

    withdrawal = ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id, amount=Decimal("700000.00"), date="2026-08-01",
        cash_account_id=cash.id, actor=actor,
    )

    allocations = {a.profit_share_id is not None: a for a in withdrawal.allocations.all()}
    assert len(withdrawal.allocations.all()) == 2
    profit_allocation = next(a for a in withdrawal.allocations.all() if a.profit_share_id)
    capital_allocation = next(a for a in withdrawal.allocations.all() if a.contribution_id)
    assert profit_allocation.amount == Decimal("500000.00")
    assert capital_allocation.amount == Decimal("200000.00")

    share = ShareholderProfitShare.objects.get(distribution=distribution, shareholder=shareholder)
    contribution = ShareholderContribution.objects.get(shareholder=shareholder)
    assert share.remaining_due == Decimal("0.00")
    assert contribution.remaining_capital == Decimal("800000.00")


@pytest.mark.django_db
def test_withdrawal_consumes_oldest_profit_share_first():
    shareholder = _make_shareholder("ALLOC-FIFO-PROFIT")
    actor = _make_admin("ALLOC-FIFO-PROFIT")
    _seed_distributable()
    older = ShareholderDistributionService.create_distribution(
        period_start="2026-06-01", period_end="2026-06-30",
        total_profit=Decimal("100000.00"), actor=actor,
    )
    ShareholderDistributionService.validate_distribution(older.id, actor)
    newer = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("100000.00"), actor=actor,
    )
    ShareholderDistributionService.validate_distribution(newer.id, actor)
    cash = CashAccount.objects.create(name="Cash FIFO Profit", opening_balance=Decimal("1000000.00"))

    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id, amount=Decimal("120000.00"), date="2026-08-01",
        cash_account_id=cash.id, actor=actor,
    )

    older_share = ShareholderProfitShare.objects.get(distribution=older, shareholder=shareholder)
    newer_share = ShareholderProfitShare.objects.get(distribution=newer, shareholder=shareholder)
    assert older_share.remaining_due == Decimal("0.00")
    assert newer_share.remaining_due == Decimal("80000.00")


@pytest.mark.django_db
def test_withdrawal_consumes_oldest_contribution_first():
    shareholder = _make_shareholder("ALLOC-FIFO-CAPITAL")
    actor = _make_admin("ALLOC-FIFO-CAPITAL")
    bank = BankAccount.objects.create(name="Bank FIFO Capital", opening_balance=Decimal("0.00"))
    older_contribution = ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("100000.00"), date="2026-06-01",
        bank_account=bank, recorded_by=actor,
    )
    newer_contribution = ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("100000.00"), date="2026-07-01",
        bank_account=bank, recorded_by=actor,
    )
    cash = CashAccount.objects.create(name="Cash FIFO Capital", opening_balance=Decimal("1000000.00"))

    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id, amount=Decimal("120000.00"), date="2026-08-01",
        cash_account_id=cash.id, actor=actor,
    )

    older_contribution.refresh_from_db()
    newer_contribution.refresh_from_db()
    assert older_contribution.remaining_capital == Decimal("0.00")
    assert newer_contribution.remaining_capital == Decimal("80000.00")


@pytest.mark.django_db
def test_withdrawal_never_touches_another_shareholders_capital():
    """The exact isolation rule the client insisted on: hamada's withdrawal
    must never be able to reach abdoul's capital, even though the pooled
    company capital would technically cover it."""
    hamada = _make_shareholder("ISOLATION-A", percent=Decimal("50.00"))
    abdoul = _make_shareholder("ISOLATION-B", percent=Decimal("50.00"))
    actor = _make_admin("ISOLATION")
    bank = BankAccount.objects.create(name="Bank Isolation", opening_balance=Decimal("0.00"))
    ShareholderContribution.objects.create(
        shareholder=hamada, amount=Decimal("100000.00"), date="2026-07-01",
        bank_account=bank, recorded_by=actor,
    )
    ShareholderContribution.objects.create(
        shareholder=abdoul, amount=Decimal("100000.00"), date="2026-07-01",
        bank_account=bank, recorded_by=actor,
    )
    cash = CashAccount.objects.create(name="Cash Isolation", opening_balance=Decimal("1000000.00"))

    with pytest.raises(ShareholderWithdrawalError):
        ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=hamada.id, amount=Decimal("150000.00"), date="2026-08-01",
            cash_account_id=cash.id, actor=actor,
        )

    abdoul_contribution = ShareholderContribution.objects.get(shareholder=abdoul)
    assert abdoul_contribution.remaining_capital == Decimal("100000.00")
    assert not ShareholderWithdrawal.objects.filter(shareholder=hamada).exists()


@pytest.mark.django_db
def test_lender_cannot_withdraw_what_he_advanced_but_the_borrower_can():
    """Client correction 2026-10-11: an associate advance moves part of the
    lender's balance to the borrower - the lender can no longer withdraw
    it, the borrower can."""
    lender = _make_shareholder("CEILING-LENDER")
    borrower = _make_shareholder("CEILING-BORROWER", percent=Decimal("0.00"))
    actor = _make_admin("CEILING")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("100000.00"), actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    ShareholderLoanService.create_loan(
        lender_id=lender.id, borrower_id=borrower.id, amount=Decimal("50000.00"), date="2026-08-01",
    )
    cash = CashAccount.objects.create(name="Cash Ceiling", opening_balance=Decimal("1000000.00"))

    assert ShareholderLedgerService.get_available_balance(lender.id) == Decimal("50000.00")
    assert ShareholderLedgerService.get_available_balance(borrower.id) == Decimal("50000.00")

    with pytest.raises(ShareholderWithdrawalError):
        ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=lender.id, amount=Decimal("50000.01"), date="2026-08-02",
            cash_account_id=cash.id, actor=actor,
        )
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=borrower.id, amount=Decimal("50000.00"), date="2026-08-02",
        cash_account_id=cash.id, actor=actor,
    )
    assert ShareholderLedgerService.get_available_balance(borrower.id) == Decimal("0.00")

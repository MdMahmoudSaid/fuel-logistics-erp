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

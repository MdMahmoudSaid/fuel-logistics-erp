from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction

from apps.accounts.models import Role, User
from apps.finance.models import BankAccount, CashAccount, Shareholder, ShareholderContribution


def _proof_file(name="proof.jpg"):
    return SimpleUploadedFile(name, b"fake-proof-bytes", content_type="image/jpeg")


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role)


def _make_shareholder(suffix, contribution=Decimal("0.00")):
    return Shareholder.objects.create(
        name=f"Shareholder {suffix}", participation_percent=Decimal("50.00"), contribution=contribution,
    )


@pytest.mark.django_db
def test_shareholder_contribution_requires_exactly_one_account():
    admin_user = _make_admin("CONTRIB-MODEL-1")
    shareholder = _make_shareholder("CONTRIB-MODEL-1")
    bank = BankAccount.objects.create(name="Bank A", opening_balance=Decimal("0.00"))
    cash = CashAccount.objects.create(name="Cash A", opening_balance=Decimal("0.00"))

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ShareholderContribution.objects.create(
                shareholder=shareholder, amount=Decimal("1000.00"), date="2026-09-02",
                bank_account=bank, cash_account=cash, recorded_by=admin_user,
            )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ShareholderContribution.objects.create(
                shareholder=shareholder, amount=Decimal("1000.00"), date="2026-09-02",
                recorded_by=admin_user,
            )


@pytest.mark.django_db
def test_shareholder_contribution_amount_must_be_positive():
    admin_user = _make_admin("CONTRIB-MODEL-2")
    shareholder = _make_shareholder("CONTRIB-MODEL-2")
    bank = BankAccount.objects.create(name="Bank B", opening_balance=Decimal("0.00"))

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ShareholderContribution.objects.create(
                shareholder=shareholder, amount=Decimal("0.00"), date="2026-09-02",
                bank_account=bank, recorded_by=admin_user,
            )

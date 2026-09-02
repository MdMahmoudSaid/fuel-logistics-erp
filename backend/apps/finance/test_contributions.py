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


from django.contrib.contenttypes.models import ContentType

from apps.finance.models import TreasuryTransaction
from apps.finance.services import ShareholderContributionError, ShareholderContributionService


@pytest.mark.django_db
def test_record_contribution_posts_one_treasury_transaction_and_document():
    admin_user = _make_admin("CONTRIB-SVC-1")
    shareholder = _make_shareholder("CONTRIB-SVC-1")
    bank = BankAccount.objects.create(name="Bank C", opening_balance=Decimal("5000000.00"))

    contribution = ShareholderContributionService.record_contribution(
        shareholder_id=shareholder.id, amount=Decimal("10000000.00"), date="2026-09-02",
        actor=admin_user, attachment=_proof_file(), bank_account_id=bank.id,
        reference="APPORT-1", notes="Apport initial",
    )

    assert contribution.document_id is not None
    bank.refresh_from_db()
    assert bank.current_balance == Decimal("15000000.00")

    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(ShareholderContribution),
        source_object_id=contribution.id,
    )
    assert txn.type == TreasuryTransaction.Type.MONEY_IN
    assert txn.amount == Decimal("10000000.00")
    assert txn.document_id == contribution.document_id
    assert TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(ShareholderContribution),
        source_object_id=contribution.id,
    ).count() == 1


@pytest.mark.django_db
def test_record_contribution_requires_attachment():
    admin_user = _make_admin("CONTRIB-SVC-2")
    shareholder = _make_shareholder("CONTRIB-SVC-2")
    cash = CashAccount.objects.create(name="Cash C", opening_balance=Decimal("0.00"))

    with pytest.raises(ShareholderContributionError):
        ShareholderContributionService.record_contribution(
            shareholder_id=shareholder.id, amount=Decimal("100000.00"), date="2026-09-02",
            actor=admin_user, attachment=None, cash_account_id=cash.id,
        )
    assert ShareholderContribution.objects.filter(shareholder=shareholder).count() == 0


@pytest.mark.django_db
def test_record_contribution_requires_exactly_one_account():
    admin_user = _make_admin("CONTRIB-SVC-3")
    shareholder = _make_shareholder("CONTRIB-SVC-3")
    bank = BankAccount.objects.create(name="Bank D", opening_balance=Decimal("0.00"))
    cash = CashAccount.objects.create(name="Cash D", opening_balance=Decimal("0.00"))

    with pytest.raises(ShareholderContributionError):
        ShareholderContributionService.record_contribution(
            shareholder_id=shareholder.id, amount=Decimal("100000.00"), date="2026-09-02",
            actor=admin_user, attachment=_proof_file(),
            bank_account_id=bank.id, cash_account_id=cash.id,
        )
    with pytest.raises(ShareholderContributionError):
        ShareholderContributionService.record_contribution(
            shareholder_id=shareholder.id, amount=Decimal("100000.00"), date="2026-09-02",
            actor=admin_user, attachment=_proof_file(),
        )


@pytest.mark.django_db
def test_get_total_capital_sums_opening_balance_and_contributions():
    admin_user = _make_admin("CONTRIB-CAP-1")
    shareholder_a = _make_shareholder("CONTRIB-CAP-1A", contribution=Decimal("2000000.00"))
    _make_shareholder("CONTRIB-CAP-1B", contribution=Decimal("3000000.00"))
    bank = BankAccount.objects.create(name="Bank E", opening_balance=Decimal("0.00"))

    assert ShareholderContributionService.get_total_capital() == Decimal("5000000.00")

    ShareholderContributionService.record_contribution(
        shareholder_id=shareholder_a.id, amount=Decimal("10000000.00"), date="2026-09-02",
        actor=admin_user, attachment=_proof_file(), bank_account_id=bank.id,
    )

    assert ShareholderContributionService.get_total_capital() == Decimal("15000000.00")

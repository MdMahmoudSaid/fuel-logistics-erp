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
def test_record_contribution_succeeds_without_attachment():
    """Task 13 (2026-09-04 recette corrections): no justificatif is ever
    mandatory - a contribution with attachment=None must succeed and
    leave document_id null, with the treasury posting still happening."""
    admin_user = _make_admin("CONTRIB-SVC-2")
    shareholder = _make_shareholder("CONTRIB-SVC-2")
    cash = CashAccount.objects.create(name="Cash C", opening_balance=Decimal("0.00"))

    contribution = ShareholderContributionService.record_contribution(
        shareholder_id=shareholder.id, amount=Decimal("100000.00"), date="2026-09-02",
        actor=admin_user, attachment=None, cash_account_id=cash.id,
    )

    assert contribution.document_id is None
    cash.refresh_from_db()
    assert cash.current_balance == Decimal("100000.00")
    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(ShareholderContribution),
        source_object_id=contribution.id,
    )
    assert txn.document_id is None


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


from rest_framework.test import APIClient


def _authed_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_contribution_api_create_succeeds_without_attachment():
    """Task 13 (2026-09-04 recette corrections): no justificatif is ever
    mandatory - a contribution submitted with no attachment must succeed."""
    admin_user = _make_admin("CONTRIB-API-1")
    shareholder = _make_shareholder("CONTRIB-API-1")
    bank = BankAccount.objects.create(name="Bank F", opening_balance=Decimal("0.00"))
    client = _authed_client(admin_user)

    response = client.post(
        "/api/shareholder-contributions/",
        {
            "shareholder": shareholder.id, "amount": "500000.00", "date": "2026-09-02",
            "bank_account": bank.id,
        },
        format="multipart",
    )
    assert response.status_code == 201, response.data
    assert response.data["proof_url"] is None
    bank.refresh_from_db()
    assert bank.current_balance == Decimal("500000.00")


@pytest.mark.django_db
def test_contribution_api_create_succeeds_with_attachment():
    admin_user = _make_admin("CONTRIB-API-2")
    shareholder = _make_shareholder("CONTRIB-API-2")
    bank = BankAccount.objects.create(name="Bank G", opening_balance=Decimal("0.00"))
    client = _authed_client(admin_user)

    response = client.post(
        "/api/shareholder-contributions/",
        {
            "shareholder": shareholder.id, "amount": "500000.00", "date": "2026-09-02",
            "bank_account": bank.id, "attachment": _proof_file(),
        },
        format="multipart",
    )
    assert response.status_code == 201, response.data
    assert response.data["proof_url"] is not None
    bank.refresh_from_db()
    assert bank.current_balance == Decimal("500000.00")


@pytest.mark.django_db
def test_shareholder_list_exposes_total_contributed():
    """Bug fix (2026-09-03 recette manuelle): the Associes page's
    "contribution" column reads Shareholder.contribution (a static
    opening-balance figure set at creation, never touched by a new
    ShareholderContribution) - so a real 10M XOF apport looked invisible
    there even though the treasury was correctly updated. total_contributed
    is the new, live field the frontend must use instead."""
    admin_user = _make_admin("CONTRIB-LIST-1")
    shareholder = _make_shareholder("CONTRIB-LIST-1")
    other = _make_shareholder("CONTRIB-LIST-1B")
    bank = BankAccount.objects.create(name="Bank I", opening_balance=Decimal("0.00"))
    client = _authed_client(admin_user)

    list_before = client.get("/api/shareholders/")
    row_before = next(r for r in list_before.data["results"] if r["id"] == shareholder.id)
    assert row_before["total_contributed"] == "0.00"
    assert row_before["contribution"] == "0.00"

    ShareholderContributionService.record_contribution(
        shareholder_id=shareholder.id, amount=Decimal("10000000.00"), date="2026-09-02",
        actor=admin_user, attachment=_proof_file(), bank_account_id=bank.id,
    )

    list_after = client.get("/api/shareholders/")
    row_after = next(r for r in list_after.data["results"] if r["id"] == shareholder.id)
    assert row_after["total_contributed"] == "10000000.00"
    # Static opening-balance field is untouched by a new contribution.
    assert row_after["contribution"] == "0.00"
    other_row = next(r for r in list_after.data["results"] if r["id"] == other.id)
    assert other_row["total_contributed"] == "0.00"


@pytest.mark.django_db
def test_shareholder_ledger_exposes_total_contributed_without_mixing_into_available_balance():
    """total_contributed must show the real apport, but never move
    available_balance (capital is not distributable profit - design doc
    2026-09-02-business-corrections-6-phases-design.md Phase 1)."""
    admin_user = _make_admin("CONTRIB-LEDGER-1")
    shareholder = _make_shareholder("CONTRIB-LEDGER-1")
    bank = BankAccount.objects.create(name="Bank J", opening_balance=Decimal("0.00"))
    client = _authed_client(admin_user)

    before = client.get(f"/api/shareholders/{shareholder.id}/ledger/")
    assert before.data["total_contributed"] == "0.00"
    assert before.data["available_balance"] == "0.00"

    ShareholderContributionService.record_contribution(
        shareholder_id=shareholder.id, amount=Decimal("10000000.00"), date="2026-09-02",
        actor=admin_user, attachment=_proof_file(), bank_account_id=bank.id,
    )

    after = client.get(f"/api/shareholders/{shareholder.id}/ledger/")
    assert after.data["total_contributed"] == "10000000.00"
    assert after.data["available_balance"] == "0.00"


@pytest.mark.django_db
def test_contribution_api_rejects_update_and_hard_delete():
    admin_user = _make_admin("CONTRIB-API-3")
    shareholder = _make_shareholder("CONTRIB-API-3")
    bank = BankAccount.objects.create(name="Bank H", opening_balance=Decimal("0.00"))
    contribution = ShareholderContributionService.record_contribution(
        shareholder_id=shareholder.id, amount=Decimal("100000.00"), date="2026-09-02",
        actor=admin_user, attachment=_proof_file(), bank_account_id=bank.id,
    )
    client = _authed_client(admin_user)

    patch_response = client.patch(
        f"/api/shareholder-contributions/{contribution.id}/", {"amount": "999999.00"}, format="json",
    )
    assert patch_response.status_code == 400

    delete_response = client.delete(f"/api/shareholder-contributions/{contribution.id}/")
    # destroy() raises MethodNotAllowed, but HasModulePermission rejects "destroy" (mapped to "cancel",
    # a permission no role has on the "shareholders" module — see 0005_seed_shareholder_permissions)
    # before destroy() is ever reached, so the actual response is 403, not 405. Matches
    # ShareholderWithdrawalViewSet's identical (if latent) behavior.
    assert delete_response.status_code == 403

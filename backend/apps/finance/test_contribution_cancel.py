from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.finance.models import (
    BankAccount,
    Shareholder,
    ShareholderContribution,
    TreasuryTransaction,
)
from apps.finance.services import (
    ShareholderContributionError,
    ShareholderContributionService,
    ShareholderLedgerService,
)


def _user(suffix, role_name):
    return User.objects.create_user(
        phone=f"+224{suffix}"[:20], pin="1234", role=Role.objects.get(name=role_name)
    )


def _holder(name="A"):
    return Shareholder.objects.create(name=name, participation_percent=Decimal("50.00"))


def _contribute(holder, bank, admin, amount="179000000.00"):
    return ShareholderContributionService.record_contribution(
        shareholder_id=holder.id, amount=Decimal(amount), date="2026-10-01",
        actor=admin, attachment=None, bank_account_id=bank.id, reference="R1", notes="n1",
    )


@pytest.fixture
def setup(db):
    admin = _user("CC-ADMIN-1", Role.NAME_ADMIN)
    bank = BankAccount.objects.create(name="BankCC", opening_balance=Decimal("100000000.00"))
    return admin, bank, _holder("A"), _holder("B")


def test_cancel_restores_balance_and_excludes_from_totals(setup):
    admin, bank, a, _b = setup
    c = _contribute(a, bank, admin)
    assert bank.current_balance == Decimal("279000000.00")
    assert ShareholderContributionService.get_total_capital() == Decimal("179000000.00")

    ShareholderContributionService.cancel_contribution(c, admin, "Mauvais associe")

    c.refresh_from_db()
    assert c.is_cancelled and c.cancelled_by == admin and c.cancel_reason == "Mauvais associe"
    assert bank.current_balance == Decimal("100000000.00")
    assert ShareholderContributionService.get_total_capital() == Decimal("0.00")
    assert ShareholderLedgerService.get_available_balance(a.id) == Decimal("0.00")
    # history kept: original MONEY_IN + offsetting MONEY_OUT
    kinds = sorted(
        TreasuryTransaction.objects.filter(
            source_content_type=ContentType.objects.get_for_model(ShareholderContribution),
            source_object_id=c.id,
        ).values_list("type", flat=True)
    )
    assert kinds == [TreasuryTransaction.Type.MONEY_IN, TreasuryTransaction.Type.MONEY_OUT]


def test_cancel_requires_admin_and_reason(setup):
    admin, bank, a, _b = setup
    c = _contribute(a, bank, admin)
    finance = _user("CC-FIN-1", Role.NAME_FINANCE)
    with pytest.raises(ShareholderContributionError, match="administrateur"):
        ShareholderContributionService.cancel_contribution(c, finance, "x")
    with pytest.raises(ShareholderContributionError, match="motif"):
        ShareholderContributionService.cancel_contribution(c, admin, "  ")


def test_cancel_refused_twice_and_when_partly_withdrawn(setup):
    admin, bank, a, _b = setup
    c = _contribute(a, bank, admin)
    ShareholderContributionService.cancel_contribution(c, admin, "oops")
    with pytest.raises(ShareholderContributionError, match="deja annule"):
        ShareholderContributionService.cancel_contribution(c, admin, "again")

    c2 = _contribute(a, bank, admin, "1000.00")
    ShareholderContribution.objects.filter(pk=c2.pk).update(amount_returned=Decimal("10.00"))
    with pytest.raises(ShareholderContributionError, match="retiree"):
        ShareholderContributionService.cancel_contribution(c2, admin, "oops")


def test_cancel_refused_when_account_no_longer_holds_the_money(setup):
    admin, bank, a, _b = setup
    c = _contribute(a, bank, admin, "50000000.00")
    TreasuryTransaction.objects.create(
        bank_account=bank, type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("120000000.00"), date="2026-10-02", recorded_by=admin,
    )
    with pytest.raises(ShareholderContributionError, match="solde"):
        ShareholderContributionService.cancel_contribution(c, admin, "oops")
    c.refresh_from_db()
    assert not c.is_cancelled


def test_update_moves_contribution_to_other_shareholder_and_syncs_treasury(setup):
    admin, bank, a, b = setup
    c = _contribute(a, bank, admin)
    balance = bank.current_balance

    ShareholderContributionService.update_contribution(
        c, admin, reason="Saisi sur le mauvais associe", shareholder_id=b.id,
        date=__import__("datetime").date(2026, 10, 3), reference="R2", notes="n2",
    )
    c.refresh_from_db()
    assert c.shareholder_id == b.id and str(c.date) == "2026-10-03"
    assert bank.current_balance == balance
    tx = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(ShareholderContribution),
        source_object_id=c.id,
    )
    assert str(tx.date) == "2026-10-03" and tx.reference == "R2" and tx.note == "n2"
    assert ShareholderLedgerService.get_available_balance(b.id) == Decimal("179000000.00")
    assert ShareholderLedgerService.get_available_balance(a.id) == Decimal("0.00")


def test_update_sensitive_fields_need_reason_and_untouched_contribution(setup):
    admin, bank, a, b = setup
    c = _contribute(a, bank, admin)
    with pytest.raises(ShareholderContributionError, match="motif"):
        ShareholderContributionService.update_contribution(c, admin, shareholder_id=b.id)
    # notes/reference alone need no reason
    ShareholderContributionService.update_contribution(c, admin, notes="corrige")
    ShareholderContribution.objects.filter(pk=c.pk).update(amount_returned=Decimal("5.00"))
    with pytest.raises(ShareholderContributionError, match="retiree"):
        ShareholderContributionService.update_contribution(
            c, admin, reason="x", shareholder_id=b.id
        )
    ShareholderContributionService.update_contribution(c, admin, notes="encore")


def test_update_refused_on_cancelled(setup):
    admin, bank, a, _b = setup
    c = _contribute(a, bank, admin)
    ShareholderContributionService.cancel_contribution(c, admin, "oops")
    with pytest.raises(ShareholderContributionError, match="annule"):
        ShareholderContributionService.update_contribution(c, admin, notes="x")


def test_api_cancel_admin_only_and_amount_change_needs_a_reason(setup):
    admin, bank, a, b = setup
    c = _contribute(a, bank, admin)
    finance = _user("CC-FIN-2", Role.NAME_FINANCE)

    client = APIClient()
    client.force_authenticate(finance)
    denied = client.post(f"/api/shareholder-contributions/{c.id}/cancel/", {"reason": "x"})
    assert denied.status_code in (400, 403)
    c.refresh_from_db()
    assert not c.is_cancelled

    client.force_authenticate(admin)
    locked = client.patch(f"/api/shareholder-contributions/{c.id}/", {"amount": "1.00"})
    assert locked.status_code == 400
    moved = client.patch(
        f"/api/shareholder-contributions/{c.id}/", {"shareholder": b.id, "reason": "erreur"}
    )
    assert moved.status_code == 200, moved.data
    assert moved.data["shareholder"] == b.id

    done = client.post(f"/api/shareholder-contributions/{c.id}/cancel/", {"reason": "annule"})
    assert done.status_code == 200, done.data
    assert done.data["is_cancelled"] is True
    again = client.post(f"/api/shareholder-contributions/{c.id}/cancel/", {"reason": "annule"})
    assert again.status_code == 400
    listing = client.get("/api/shareholders/")
    assert all(Decimal(row["total_contributed"]) == 0 for row in listing.data["results"])


def test_amount_decrease_posts_correcting_entry_and_keeps_history(setup):
    admin, bank, a, _b = setup
    c = _contribute(a, bank, admin, amount="2000000.00")
    assert bank.current_balance == Decimal("102000000.00")

    ShareholderContributionService.update_contribution(
        c, admin, amount=Decimal("1000000.00"), reason="Erreur de saisie"
    )

    c.refresh_from_db()
    assert c.amount == Decimal("1000000.00")
    assert bank.current_balance == Decimal("101000000.00")
    assert ShareholderContributionService.get_total_capital() == Decimal("1000000.00")
    assert ShareholderLedgerService.get_available_balance(a.id) == Decimal("1000000.00")
    kinds = sorted(
        TreasuryTransaction.objects.filter(
            source_content_type=ContentType.objects.get_for_model(ShareholderContribution),
            source_object_id=c.id,
        ).values_list("type", "amount")
    )
    assert kinds == [("MONEY_IN", Decimal("2000000.00")), ("MONEY_OUT", Decimal("1000000.00"))]


def test_amount_increase_posts_money_in(setup):
    admin, bank, a, _b = setup
    c = _contribute(a, bank, admin, amount="1000000.00")
    ShareholderContributionService.update_contribution(
        c, admin, amount=Decimal("3000000.00"), reason="Montant oublie"
    )
    assert bank.current_balance == Decimal("103000000.00")
    assert ShareholderContributionService.get_total_capital() == Decimal("3000000.00")


def test_amount_change_controls(setup):
    admin, bank, a, _b = setup
    c = _contribute(a, bank, admin, amount="2000000.00")
    finance = _user("CC-FIN-3", Role.NAME_FINANCE)
    # reason mandatory
    with pytest.raises(ShareholderContributionError, match="motif"):
        ShareholderContributionService.update_contribution(c, admin, amount=Decimal("1.00"))
    # admin only
    with pytest.raises(ShareholderContributionError, match="administrateur"):
        ShareholderContributionService.update_contribution(
            c, finance, amount=Decimal("1.00"), reason="x"
        )
    # positive
    with pytest.raises(ShareholderContributionError, match="superieur"):
        ShareholderContributionService.update_contribution(
            c, admin, amount=Decimal("0"), reason="x"
        )
    # already (partly) withdrawn: locked, like the cancellation
    ShareholderContribution.objects.filter(pk=c.pk).update(amount_returned=Decimal("5.00"))
    with pytest.raises(ShareholderContributionError, match="retiree"):
        ShareholderContributionService.update_contribution(
            c, admin, amount=Decimal("1000000.00"), reason="x"
        )
    c.refresh_from_db()
    assert c.amount == Decimal("2000000.00")


def test_amount_decrease_refused_when_account_no_longer_holds_the_money(setup):
    admin, bank, a, _b = setup
    c = _contribute(a, bank, admin, amount="2000000.00")
    TreasuryTransaction.objects.create(
        bank_account=bank, type=TreasuryTransaction.Type.MONEY_OUT,
        amount=Decimal("101500000.00"), date="2026-10-02", recorded_by=admin,
    )
    with pytest.raises(ShareholderContributionError, match="solde"):
        ShareholderContributionService.update_contribution(
            c, admin, amount=Decimal("1000000.00"), reason="x"
        )
    c.refresh_from_db()
    assert c.amount == Decimal("2000000.00")


def test_api_amount_edit_and_account_locked(setup):
    admin, bank, a, _b = setup
    c = _contribute(a, bank, admin, amount="2000000.00")
    client = APIClient()
    client.force_authenticate(admin)
    done = client.patch(
        f"/api/shareholder-contributions/{c.id}/", {"amount": "1000000.00", "reason": "erreur"}
    )
    assert done.status_code == 200, done.data
    assert Decimal(done.data["amount"]) == Decimal("1000000.00")
    assert bank.current_balance == Decimal("101000000.00")

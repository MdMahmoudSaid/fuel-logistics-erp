"""Associates: active / legacy ("Ancien") / inactive, and the rules that keep
an unsettled associate from being archived."""
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.finance.models import (
    BankAccount,
    Shareholder,
    ShareholderContribution,
    ShareholderLoan,
)
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter


@pytest.fixture
def admin():
    return User.objects.create_user(
        phone="+2228880001", pin="1234", role=Role.objects.get(name=Role.NAME_ADMIN)
    )


@pytest.fixture
def api(admin):
    client = APIClient()
    client.force_authenticate(admin)
    return client


def _shareholder(name, percent="10.00", **kwargs):
    return Shareholder.objects.create(name=name, participation_percent=Decimal(percent), **kwargs)


@pytest.mark.django_db
def test_status_filter_and_legacy_forces_inactive(api):
    _shareholder("A-active")
    _shareholder("B-legacy", is_active=False, is_legacy=True)
    _shareholder("C-inactive", is_active=False)

    def names(status):
        return sorted(
            r["name"] for r in api.get("/api/shareholders/", {"status": status}).data["results"]
        )

    assert names("active") == ["A-active"]
    assert names("legacy") == ["B-legacy"]
    assert names("inactive") == ["C-inactive"]

    s = _shareholder("D")
    resp = api.patch(f"/api/shareholders/{s.id}/", {"is_legacy": True}, format="json")
    assert resp.status_code == 200 and resp.data["is_active"] is False


@pytest.mark.django_db
def test_associate_with_capital_balance_cannot_be_deactivated_but_can_go_legacy(api, admin):
    s = _shareholder("Has capital")
    bank = BankAccount.objects.create(name="Bank", opening_balance=Decimal("0.00"))
    ShareholderContribution.objects.create(
        shareholder=s, amount=Decimal("1000.00"), date=date.today(),
        bank_account=bank, recorded_by=admin,
    )
    resp = api.patch(f"/api/shareholders/{s.id}/", {"is_active": False}, format="json")
    assert resp.status_code == 400 and "solde" in str(resp.data)

    resp = api.patch(f"/api/shareholders/{s.id}/", {"is_legacy": True}, format="json")
    assert resp.status_code == 200 and resp.data["is_legacy"] is True


@pytest.mark.django_db
def test_associate_with_an_open_advance_cannot_be_deactivated(api, admin):
    s = _shareholder("Borrower")
    ShareholderLoan.objects.create(
        source=ShareholderLoan.Source.COMPANY, borrower=s, amount=Decimal("500.00"),
        date=date.today(), recorded_by=admin,
    )
    resp = api.patch(f"/api/shareholders/{s.id}/", {"is_active": False}, format="json")
    assert resp.status_code == 400 and "avances" in str(resp.data)


@pytest.mark.django_db
def test_settled_associate_can_be_deactivated_and_is_then_refused_for_new_advances(api):
    s = _shareholder("Settled")
    other = _shareholder("Other", percent="20.00")
    assert api.patch(f"/api/shareholders/{s.id}/", {"is_active": False}, format="json").status_code == 200
    resp = api.post(
        "/api/shareholder-loans/",
        {
            "source": "SHAREHOLDER",
            "borrower": s.id,
            "lender": other.id,
            "amount": "10.00",
            "date": "2026-11-05",
        },
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_legacy_parties_stay_in_the_debt_and_balance_figures(api, admin):
    supplier = Supplier.objects.create(name="Legacy supplier", is_active=False, is_legacy=True)
    transporter = Transporter.objects.create(name="Legacy transporter", is_active=False, is_legacy=True)
    gone = Supplier.objects.create(name="Archived supplier", is_active=False)
    from apps.finance.models import OpeningDebt

    OpeningDebt.objects.create(supplier=supplier, amount="700.00", date=date.today(), recorded_by=admin)

    debts = api.get("/api/treasury-transactions/party-balances/", {"debt_type": "supplier"}).data
    rows = debts if isinstance(debts, list) else debts.get("results", debts.get("rows", []))
    ids = {r.get("id") or r.get("supplier_id") or r.get("party_id") for r in rows}
    assert supplier.id in ids and gone.id not in ids
    rows = api.get("/api/treasury-transactions/party-balances/", {"debt_type": "transporter"}).data
    rows = rows if isinstance(rows, list) else rows.get("results", rows.get("rows", []))
    assert transporter.id in {r.get("id") or r.get("transporter_id") or r.get("party_id") for r in rows}

    legacy_share = _shareholder("Legacy share", is_active=False, is_legacy=True)
    balances = api.get("/api/shareholders/balances/").data
    assert legacy_share.id in {row["id"] for row in balances["shareholders"]}

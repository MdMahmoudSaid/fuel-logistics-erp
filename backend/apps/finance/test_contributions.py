from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction

from apps.accounts.models import Role, User
from apps.finance.models import BankAccount, CashAccount, Shareholder, ShareholderContribution
from apps.finance.models import ShareholderWithdrawal


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
def test_shareholder_create_ignores_submitted_contribution():
    """Bug fix (2026-09-10, reported via the Associes "Ajouter" form): a
    user could type any amount into the "Contribution" field with no
    linked bank/cash account, and it silently reduced distributable_result
    via ShareholderContributionService.get_total_capital() with no money
    ever entering treasury. `contribution` is now read-only via the API -
    a submitted value must be ignored, never persisted."""
    admin_user = _make_admin("CONTRIB-RO-1")
    client = _authed_client(admin_user)

    response = client.post(
        "/api/shareholders/",
        {"name": "New Shareholder", "participation_percent": "10.00", "contribution": "1000000000.00"},
    )
    assert response.status_code == 201, response.data
    assert response.data["contribution"] == "0.00"
    shareholder = Shareholder.objects.get(id=response.data["id"])
    assert shareholder.contribution == Decimal("0.00")


@pytest.mark.django_db
def test_shareholder_update_ignores_submitted_contribution():
    """Same bug, via the "Modifier" form: `contribution` must stay frozen
    across an update even when the request tries to change it."""
    admin_user = _make_admin("CONTRIB-RO-2")
    shareholder = _make_shareholder("CONTRIB-RO-2", contribution=Decimal("500.00"))
    client = _authed_client(admin_user)

    response = client.patch(
        f"/api/shareholders/{shareholder.id}/", {"contribution": "999999999.00"},
    )
    assert response.status_code == 200, response.data
    assert response.data["contribution"] == "500.00"
    shareholder.refresh_from_db()
    assert shareholder.contribution == Decimal("500.00")


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
    # destroy() unconditionally raises MethodNotAllowed (405). Before
    # 0006_grant_shareholder_cancel_permission, no role had the "cancel"
    # tier on the "shareholders" module, so HasModulePermission rejected
    # "destroy" (mapped to "cancel" via ACTION_MAP's default fallback)
    # with 403 before destroy() was ever reached. Now that Admin/Management
    # hold "cancel" on "shareholders" (so they can hit the new distribution
    # cancel action), an admin's DELETE clears the permission check and
    # reaches destroy() itself, which still refuses the hard delete — just
    # with 405 instead of 403.
    assert delete_response.status_code == 405


@pytest.mark.django_db
def test_profit_preview_endpoint_reachable_by_a_role_with_shareholders_view_permission():
    """Bug fix (found 2026-09-06 code audit): GET /api/shareholders/
    profit-preview/ was unreachable for every non-superuser role, no
    matter what permissions they held - the `profit_preview` action name
    was missing from accounts.permissions.ACTION_MAP, so HasModulePermission
    fell back to checking for a literal "profit_preview" tier that can
    never exist in any role's permission list (only "view", "create",
    "edit", "validate", "cancel", "export" - see Role.ACTIONS). Every prior
    manual recette ran as a superuser, which bypasses this check entirely,
    so the bug was invisible from the UI.

    Admin role has ["view", "create", "edit", "validate", "export"] on the
    "shareholders" module (0005_seed_shareholder_permissions) - "view" is
    enough for this read-only endpoint."""
    admin_user = _make_admin("PROFIT-PREVIEW-OK")
    client = _authed_client(admin_user)

    response = client.get("/api/shareholders/profit-preview/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_profit_preview_endpoint_still_blocked_for_a_role_with_no_shareholders_permission():
    """Operations gets nothing on the "shareholders" module (same seed
    migration) - the fix above must not turn this into an open endpoint."""
    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)
    ops_user = User.objects.create_user(phone="+222PROFITPREVIEWNO", pin="1234", role=ops_role)
    client = _authed_client(ops_user)

    response = client.get("/api/shareholders/profit-preview/")

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/shareholders/profit-preview/pdf/ (client request 2026-09-06): a
# real structured PDF export of the Benefices page, respecting the same
# period filter as profit_preview above - never a screenshot.
# ---------------------------------------------------------------------------


def _make_trip_with_sale(suffix, admin_user, *, loading_date):
    from apps.core.models import Product
    from apps.customers.models import Customer
    from apps.purchasing.models import CessionLetter, SupplierOrder
    from apps.sales.models import Sale
    from apps.suppliers.models import Supplier
    from apps.transport.models import Transporter, Truck
    from apps.trips.models import Trip

    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    order = SupplierOrder.objects.create(
        reference=f"SO-PDF-{suffix}", supplier=supplier, product=product,
        purchase_date=loading_date, quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("500.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-PDF-{suffix}", supplier_order=order,
        authorized_quantity=Decimal("45000.00"), issue_date=loading_date,
        created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-PDF-{suffix}", tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER", capacity_litres=Decimal("45000.00"),
    )
    customer = Customer.objects.create(name=f"Client {suffix}")
    trip = Trip.objects.create(
        reference=f"TRIP-PDF-{suffix}", truck=truck, transporter=transporter,
        supplier=supplier, supplier_order=order, cession_letter=cession, product=product,
        quantity_loaded=Decimal("45000.00"), client=customer, loading_date=loading_date,
        bl_reference=f"BL-PDF-{suffix}", status=Trip.Status.DELIVERED, created_by=admin_user,
    )
    Sale.objects.create(
        trip=trip, customer=customer, product=product,
        delivered_quantity=Decimal("45000.00"), unit_selling_price=Decimal("900.0000"),
    )
    return trip


@pytest.mark.django_db
def test_profit_preview_pdf_endpoint_returns_a_real_pdf():
    admin_user = _make_admin("PROFIT-PDF-OK")
    _make_trip_with_sale("PROFIT-PDF-OK", admin_user, loading_date="2026-08-18")
    client = _authed_client(admin_user)

    response = client.get(
        "/api/shareholders/profit-preview/pdf/", {"from": "2026-08-01", "to": "2026-08-31"}
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "rapport-benefices.pdf" in response["Content-Disposition"]


@pytest.mark.django_db
def test_profit_preview_pdf_endpoint_respects_the_requested_period():
    """Same trip, two requests - only the one whose period actually covers
    the trip's loading date gets the per-trip detail table, which makes a
    real, measurable difference in the exported file's size. A black-box
    proof (no PDF-parsing dependency in this project) that the date filter
    the page's own DateRangeFilter sends is actually applied here, not
    silently ignored."""
    admin_user = _make_admin("PROFIT-PDF-PERIOD")
    _make_trip_with_sale("PROFIT-PDF-PERIOD", admin_user, loading_date="2026-08-18")
    client = _authed_client(admin_user)

    with_trip = client.get(
        "/api/shareholders/profit-preview/pdf/", {"from": "2026-08-01", "to": "2026-08-31"}
    )
    without_trip = client.get(
        "/api/shareholders/profit-preview/pdf/", {"from": "2026-09-01", "to": "2026-09-30"}
    )

    assert with_trip.status_code == 200
    assert without_trip.status_code == 200
    assert len(with_trip.content) > len(without_trip.content)


@pytest.mark.django_db
def test_profit_preview_pdf_endpoint_still_blocked_for_a_role_with_no_shareholders_permission():
    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)
    ops_user = User.objects.create_user(phone="+222PROFITPDFNO", pin="1234", role=ops_role)
    client = _authed_client(ops_user)

    response = client.get("/api/shareholders/profit-preview/pdf/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_contribution_remaining_capital_defaults_to_full_amount():
    admin_user = _make_admin("CONTRIB-REMAIN-1")
    shareholder = _make_shareholder("CONTRIB-REMAIN-1")
    bank = BankAccount.objects.create(name="Bank Remain 1", opening_balance=Decimal("0.00"))
    contribution = ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("1000000.00"), date="2026-09-15",
        bank_account=bank, recorded_by=admin_user,
    )

    assert contribution.amount_returned == Decimal("0.00")
    assert contribution.remaining_capital == Decimal("1000000.00")


@pytest.mark.django_db
def test_contribution_amount_returned_cannot_exceed_amount():
    admin_user = _make_admin("CONTRIB-REMAIN-2")
    shareholder = _make_shareholder("CONTRIB-REMAIN-2")
    bank = BankAccount.objects.create(name="Bank Remain 2", opening_balance=Decimal("0.00"))
    contribution = ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("1000.00"), date="2026-09-15",
        bank_account=bank, recorded_by=admin_user,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            contribution.amount_returned = Decimal("1000.01")
            contribution.save()


@pytest.mark.django_db
def test_sync_amount_returned_recomputes_from_allocations():
    """sync_amount_returned() is the only writer - it must always recompute
    from actual ShareholderWithdrawalAllocation rows, never drift."""
    from apps.finance.models import ShareholderWithdrawalAllocation

    admin_user = _make_admin("CONTRIB-REMAIN-3")
    shareholder = _make_shareholder("CONTRIB-REMAIN-3")
    bank = BankAccount.objects.create(name="Bank Remain 3", opening_balance=Decimal("0.00"))
    cash = CashAccount.objects.create(name="Cash Remain 3", opening_balance=Decimal("1000000.00"))
    contribution = ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("1000000.00"), date="2026-09-15",
        bank_account=bank, recorded_by=admin_user,
    )
    withdrawal = ShareholderWithdrawal.objects.create(
        shareholder=shareholder, amount=Decimal("300000.00"), date="2026-09-16",
        cash_account=cash, recorded_by=admin_user,
    )
    ShareholderWithdrawalAllocation.objects.create(
        withdrawal=withdrawal, contribution=contribution, amount=Decimal("300000.00"),
    )

    result = contribution.sync_amount_returned()

    assert result == Decimal("300000.00")
    contribution.refresh_from_db()
    assert contribution.amount_returned == Decimal("300000.00")
    assert contribution.remaining_capital == Decimal("700000.00")

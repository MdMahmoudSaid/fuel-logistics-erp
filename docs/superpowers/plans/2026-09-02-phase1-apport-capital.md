# Phase 1 — Apport en capital depuis Actionnaires / Associés — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user record a real capital contribution from a shareholder/associate (bank or cash), posting exactly one treasury inflow, visible on the shareholder's page, without touching any existing withdrawal/loan/distribution logic.

**Architecture:** New `ShareholderContribution` model (mirrors `SupplierAdvance`: `AuditableModel`, exclusive bank/cash FK, mandatory proof `Document`). A new `ShareholderContributionService.record_contribution` creates the row, the `Document`, and the `TreasuryTransaction` (`MONEY_IN`) in one atomic block — copied directly from `AdvanceService.create_supplier_advance` (`backend/apps/finance/services.py:549-587`), not from `FinancePostingService`/`ShareholderWithdrawalService` (those two only fit flows where the proof is optional). A standalone `ContributionForm.vue` (mirrors `AdvanceForm.vue`) is embedded as a modal in `ShareholderView.vue`, both from the associates list (free choice of shareholder) and from the per-shareholder ledger tab (locked to that shareholder, same pattern `TransporterLedgerView.vue` uses for `AdvanceForm`).

**Tech Stack:** Django 5 / DRF (backend/apps/finance), Vue 3 `<script setup>` + Vitest (frontend/src/modules/finance), pytest-django for backend tests.

**Spec:** `docs/superpowers/specs/2026-09-02-business-corrections-6-phases-design.md` (Phase 1 section) — read it alongside this plan; it carries the validated business rules this plan implements.

## Global Constraints

- Justificatif (proof image) is **mandatory** on every new `ShareholderContribution` — no exception, unlike withdrawals.
- Exactly one of `bank_account` / `cash_account` must be set — never both, never neither (same DB-level constraint pattern as `ShareholderWithdrawal`/`SupplierAdvance`).
- `ShareholderContribution` is never edited or hard-deleted after creation (same `update()` rejection pattern as `SupplierAdvanceSerializer`, same `destroy()` → `MethodNotAllowed` pattern as `ShareholderWithdrawalViewSet`).
- Do not touch `ShareholderStatementQuery`'s running balance, `ShareholderLedgerService.get_available_balance()`, or any existing withdrawal/loan/distribution code path — contributions are capital, not distributable equity.
- Do not create a "total capital" UI anywhere in this phase — `get_total_capital()` is a backend building block Phase 2 will wire into the Dashboard; this phase only needs it correct and unit-tested.
- No new Python dependency, no refactor of `AdvanceService`/`FinancePostingService` — copy the pattern, don't touch the originals.

---

## File Structure

- **Modify** `backend/apps/finance/models.py` — add `ShareholderContribution` model (near `ShareholderWithdrawal`, line ~1013).
- **Create** `backend/apps/finance/migrations/0013_shareholdercontribution.py` — via `makemigrations` (Task 1).
- **Modify** `backend/apps/finance/services.py` — add `ShareholderContributionError`, `ShareholderContributionService` (near `ShareholderWithdrawalService`, line ~1489).
- **Modify** `backend/apps/finance/serializers.py` — add `ShareholderContributionSerializer` (near `ShareholderWithdrawalSerializer`, line ~951).
- **Modify** `backend/apps/finance/views.py` — add `ShareholderContributionViewSet` (near `ShareholderWithdrawalViewSet`, line ~477).
- **Modify** `backend/apps/finance/urls.py` — register `shareholder-contributions` route.
- **Create** `backend/apps/finance/test_contributions.py` — backend tests (model constraints, service, serializer/view via APIClient).
- **Modify** `frontend/src/modules/finance/types.ts` — add `ShareholderContribution` interface (near `ShareholderWithdrawal`, line ~444).
- **Modify** `frontend/src/modules/finance/api.ts` — add `shareholderContributionResource` + `createShareholderContribution()` (near the advance helpers, line ~180-231).
- **Create** `frontend/src/modules/finance/ContributionForm.vue` — new standalone form component.
- **Create** `frontend/src/modules/finance/__tests__/ContributionForm.spec.ts`.
- **Modify** `frontend/src/modules/finance/ShareholderView.vue` — "Nouvel apport" button + modal, in the `associates` tab (free) and the `ledger` tab (locked).
- **Modify** `frontend/src/locales/fr.json`, `en.json`, `ar.json` — add `finance.contributionForm.*` keys.

---

## Task 1: `ShareholderContribution` model + migration

**Files:**
- Modify: `backend/apps/finance/models.py`
- Create: `backend/apps/finance/migrations/0013_shareholdercontribution.py` (generated)
- Test: `backend/apps/finance/test_contributions.py`

**Interfaces:**
- Produces: `ShareholderContribution` model with fields `shareholder`, `amount`, `bank_account`, `cash_account`, `date`, `reference`, `notes`, `document`, `recorded_by`, `created_at`, `updated_at`. Constraints: `finance_shareholdercontribution_amount_positive`, `finance_shareholdercontribution_single_account`, `finance_shareholdercontribution_requires_account`.

- [ ] **Step 1: Write the failing model test**

Create `backend/apps/finance/test_contributions.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python manage.py test apps.finance.test_contributions -v 2`
Expected: FAIL with `ImportError`/`AttributeError` — `ShareholderContribution` does not exist yet.

- [ ] **Step 3: Add the model**

In `backend/apps/finance/models.py`, immediately after the `ShareholderWithdrawal` class (after its `__str__`, ends around line 1016), add:

```python
class ShareholderContribution(AuditableModel, TimeStampedModel):
    """Real cash injected into the company by a shareholder/associate
    (Phase 1, docs/superpowers/specs/2026-09-02-business-corrections-6-phases-design.md).

    Mirrors SupplierAdvance rather than ShareholderWithdrawal: the proof
    document is mandatory here (a capital injection is a notable, real
    money-in event), so creation goes through
    ShareholderContributionService.record_contribution, copied from
    AdvanceService.create_supplier_advance rather than routed through
    FinancePostingService (which only fits flows where the document stays
    optional). Never contributes to
    ShareholderLedgerService.get_available_balance() or
    ShareholderStatementQuery's running balance - it is capital, not
    distributable profit.
    """

    shareholder = models.ForeignKey(
        Shareholder, on_delete=models.PROTECT, related_name="contributions"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="shareholder_contributions",
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="shareholder_contributions",
    )
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="shareholder_contributions",
    )
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="shareholder_contributions_recorded"
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_shareholdercontribution_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=True) | models.Q(cash_account__isnull=True),
                name="finance_shareholdercontribution_single_account",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=False) | models.Q(cash_account__isnull=False),
                name="finance_shareholdercontribution_requires_account",
            ),
        ]
        indexes = [
            models.Index(fields=["shareholder", "date"], name="finance_shrcontrib_shr_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.shareholder}: {self.amount} ({self.date})"
```

- [ ] **Step 4: Generate and apply the migration**

Run: `cd backend && python manage.py makemigrations finance`
Expected: creates `apps/finance/migrations/0013_shareholdercontribution.py`. Open it and confirm it only adds the new model/table/constraints/indexes — no changes to any other model.

Run: `cd backend && python manage.py migrate finance`
Expected: applies cleanly.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python manage.py test apps.finance.test_contributions -v 2`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/models.py backend/apps/finance/migrations/0013_shareholdercontribution.py backend/apps/finance/test_contributions.py
git commit -m "feat(finance): add ShareholderContribution model"
```

---

## Task 2: `ShareholderContributionService.record_contribution` + `get_total_capital()`

**Files:**
- Modify: `backend/apps/finance/services.py`
- Test: `backend/apps/finance/test_contributions.py`

**Interfaces:**
- Consumes: `ShareholderContribution` model (Task 1), `Document` (`apps.documents.models`), `validate_image_upload` (`apps.documents.validators`), `TreasuryTransaction`, `BankAccount`, `CashAccount`, `Shareholder` (already imported in `services.py`).
- Produces:
  - `ShareholderContributionError(ValueError)`.
  - `ShareholderContributionService.record_contribution(*, shareholder_id, amount, date, actor, attachment, bank_account_id=None, cash_account_id=None, reference="", notes="") -> ShareholderContribution`.
  - `ShareholderContributionService.get_total_capital() -> Decimal` — `Shareholder.objects.aggregate(Sum("contribution"))["contribution__sum"] or ZERO` **+** `ShareholderContribution.objects.aggregate(Sum("amount"))["amount__sum"] or ZERO`.

- [ ] **Step 1: Write the failing service tests**

Append to `backend/apps/finance/test_contributions.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python manage.py test apps.finance.test_contributions -v 2`
Expected: FAIL — `ImportError: cannot import name 'ShareholderContributionError'`.

- [ ] **Step 3: Implement the service**

In `backend/apps/finance/services.py`, immediately after `ShareholderWithdrawalService` (after `record_withdrawal`'s `return withdrawal`, before `class ShareholderLoanError`), add:

```python
class ShareholderContributionError(ValueError):
    """Raised when a capital contribution is missing its mandatory proof
    image or has an invalid account selection."""


class ShareholderContributionService:
    """Owns ShareholderContribution creation (Phase 1, docs/superpowers/
    specs/2026-09-02-business-corrections-6-phases-design.md) - copied
    from AdvanceService.create_supplier_advance's shape (Document +
    TreasuryTransaction created directly, in one atomic block) rather than
    ShareholderWithdrawalService's (which delegates posting to
    FinancePostingService._post_treasury): the proof document is mandatory
    here, exactly like an advance, unlike a withdrawal.
    """

    @staticmethod
    @transaction.atomic
    def record_contribution(
        *,
        shareholder_id,
        amount,
        date,
        actor,
        attachment,
        bank_account_id=None,
        cash_account_id=None,
        reference="",
        notes="",
    ) -> ShareholderContribution:
        if bank_account_id and cash_account_id:
            raise ShareholderContributionError("Un seul compte (banque OU caisse) peut etre renseigne.")
        if not bank_account_id and not cash_account_id:
            raise ShareholderContributionError("Un compte de tresorerie (banque ou caisse) est requis.")
        if not attachment:
            raise ShareholderContributionError(
                "Un justificatif image est obligatoire pour enregistrer un apport."
            )

        shareholder = Shareholder.objects.select_for_update().get(pk=shareholder_id)
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= ZERO:
            raise ShareholderContributionError("Le montant de l'apport doit etre superieur a zero.")

        bank_account = None
        cash_account = None
        if bank_account_id:
            bank_account = BankAccount.objects.select_for_update().get(pk=bank_account_id)
        else:
            cash_account = CashAccount.objects.select_for_update().get(pk=cash_account_id)

        contribution = ShareholderContribution.objects.create(
            shareholder=shareholder, bank_account=bank_account, cash_account=cash_account,
            amount=amount, date=date, reference=reference, notes=notes, recorded_by=actor,
        )
        document = Document.objects.create(
            file=attachment, document_type="shareholder_contribution_proof", reference=reference,
            uploaded_by=actor, content_type=ContentType.objects.get_for_model(ShareholderContribution),
            object_id=contribution.id,
        )
        contribution.document = document
        contribution.save(update_fields=["document", "updated_at"])
        TreasuryTransaction.objects.create(
            bank_account=bank_account, cash_account=cash_account,
            type=TreasuryTransaction.Type.MONEY_IN, amount=amount, date=date,
            reference=reference, note=notes,
            source_content_type=ContentType.objects.get_for_model(ShareholderContribution),
            source_object_id=contribution.id, document=document, recorded_by=actor,
        )
        return contribution

    @staticmethod
    def get_total_capital() -> Decimal:
        opening_balances = Shareholder.objects.aggregate(total=Sum("contribution"))["total"] or ZERO
        contributions = ShareholderContribution.objects.aggregate(total=Sum("amount"))["total"] or ZERO
        return opening_balances + contributions
```

Confirm `Document` (`from apps.documents.models import Document`) and `Sum` (`from django.db.models import Sum`) are already imported at the top of `services.py` — both are used by `AdvanceService`/other services already in this file, so no new import should be needed; if either is missing, add it next to the existing `django.db.models`/`apps.documents.models` imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python manage.py test apps.finance.test_contributions -v 2`
Expected: PASS (6 tests total).

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/finance/test_contributions.py
git commit -m "feat(finance): add ShareholderContributionService.record_contribution and get_total_capital"
```

---

## Task 3: `ShareholderContributionSerializer`

**Files:**
- Modify: `backend/apps/finance/serializers.py`
- Test: `backend/apps/finance/test_contributions.py`

**Interfaces:**
- Consumes: `ShareholderContributionService.record_contribution`/`ShareholderContributionError` (Task 2), `ShareholderContribution` model (Task 1), `validate_image_upload` (already imported in `serializers.py`), `ShareholderBriefSerializer`, `UserSerializer` (already defined/imported in `serializers.py`).
- Produces: `ShareholderContributionSerializer` — fields `id, shareholder, shareholder_detail, amount, date, bank_account, cash_account, reference, notes, attachment, proof_url, recorded_by, recorded_by_detail, created_at, updated_at`.

- [ ] **Step 1: Write the failing serializer/API test**

Append to `backend/apps/finance/test_contributions.py`:

```python
from rest_framework.test import APIClient


def _authed_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_contribution_api_create_requires_attachment():
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
    assert response.status_code == 400
    assert "attachment" in response.data


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
    assert delete_response.status_code == 405
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python manage.py test apps.finance.test_contributions -v 2`
Expected: FAIL — 404s (no URL registered yet)/`ImportError`.

- [ ] **Step 3: Implement the serializer**

In `backend/apps/finance/serializers.py`, immediately after `ShareholderWithdrawalSerializer` (after its `update()` method, ends around line 953), add:

```python
class ShareholderContributionSerializer(serializers.ModelSerializer):
    """Creation is delegated to
    ShareholderContributionService.record_contribution() (Phase 1) - it,
    not this serializer, owns the Document creation and the
    TreasuryTransaction(MONEY_IN) posting, both under one row lock."""

    shareholder_detail = ShareholderBriefSerializer(source="shareholder", read_only=True)
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)
    attachment = serializers.FileField(write_only=True, required=False, allow_null=True, default=None)
    proof_url = serializers.SerializerMethodField()

    class Meta:
        model = ShareholderContribution
        fields = [
            "id", "shareholder", "shareholder_detail", "amount", "date",
            "bank_account", "cash_account", "reference", "notes", "attachment", "proof_url",
            "recorded_by", "recorded_by_detail", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "recorded_by", "created_at", "updated_at"]

    def get_proof_url(self, obj) -> str | None:
        if not obj.document_id or not obj.document.file:
            return None
        return obj.document.file.url

    def validate_attachment(self, value):
        if value is None:
            return value
        return validate_image_upload(value)

    def validate(self, data):
        bank_account = data.get("bank_account")
        cash_account = data.get("cash_account")
        if bank_account and cash_account:
            raise serializers.ValidationError("Un seul compte (banque OU caisse) peut etre renseigne.")
        if not bank_account and not cash_account:
            raise serializers.ValidationError("Un compte de tresorerie (banque ou caisse) est requis.")
        if not data.get("attachment"):
            raise serializers.ValidationError(
                {"attachment": "Un justificatif image est obligatoire pour enregistrer un apport."}
            )
        return data

    def create(self, validated_data):
        actor = self.context["request"].user
        bank_account = validated_data.get("bank_account")
        cash_account = validated_data.get("cash_account")
        try:
            return ShareholderContributionService.record_contribution(
                shareholder_id=validated_data["shareholder"].id,
                amount=validated_data["amount"],
                date=validated_data["date"],
                actor=actor,
                attachment=validated_data["attachment"],
                bank_account_id=bank_account.id if bank_account else None,
                cash_account_id=cash_account.id if cash_account else None,
                reference=validated_data.get("reference", ""),
                notes=validated_data.get("notes", ""),
            )
        except ShareholderContributionError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError("Un apport enregistre ne peut pas etre modifie.")
```

Add `ShareholderContribution` to the model import block near the top of `serializers.py` (same block that already imports `ShareholderWithdrawal`), and `ShareholderContributionError, ShareholderContributionService` to the services import block (same block that already imports `ShareholderWithdrawalError, ShareholderWithdrawalService`).

- [ ] **Step 4: Wire the ViewSet and URL so the API tests can run**

This serializer alone won't answer HTTP requests yet — Task 4 adds the ViewSet/URL. Run the tests now anyway to confirm the *serializer-level* pieces (import wiring) are correct — they'll still fail on 404 until Task 4, which is expected. Do not mark this task's tests green yet; proceed to Task 4 and come back to verify both together.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/serializers.py backend/apps/finance/test_contributions.py
git commit -m "feat(finance): add ShareholderContributionSerializer"
```

---

## Task 4: `ShareholderContributionViewSet` + URL routing

**Files:**
- Modify: `backend/apps/finance/views.py`
- Modify: `backend/apps/finance/urls.py`
- Test: `backend/apps/finance/test_contributions.py` (Task 3's tests now go green)

**Interfaces:**
- Consumes: `ShareholderContributionSerializer` (Task 3), `ShareholderContribution` model (Task 1), `HasModulePermission`, `MethodNotAllowed`, `_NO_HARD_DELETE_DETAIL` (already defined in `views.py`).
- Produces: `ShareholderContributionViewSet` registered at `/api/shareholder-contributions/`.

- [ ] **Step 1: Implement the ViewSet**

In `backend/apps/finance/views.py`, immediately after `ShareholderWithdrawalViewSet` (after its `destroy()` method, ends around line 477), add:

```python
class ShareholderContributionViewSet(viewsets.ModelViewSet):
    queryset = ShareholderContribution.objects.select_related(
        "shareholder", "bank_account", "cash_account", "recorded_by"
    ).all()
    serializer_class = ShareholderContributionSerializer
    filterset_fields = ["shareholder"]
    permission_classes = [HasModulePermission]
    module = "shareholders"

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)
```

Add `ShareholderContribution` to the model import block at the top of `views.py` (same block importing `ShareholderWithdrawal`), and `ShareholderContributionSerializer` to the serializer import block (same block importing `ShareholderWithdrawalSerializer`).

- [ ] **Step 2: Register the URL**

In `backend/apps/finance/urls.py`, add the import next to `ShareholderWithdrawalViewSet` and register right after the `shareholder-withdrawals` line:

```python
router.register(
    "shareholder-contributions", ShareholderContributionViewSet, basename="shareholdercontribution"
)
```

- [ ] **Step 3: Run all contribution tests**

Run: `cd backend && python manage.py test apps.finance.test_contributions -v 2`
Expected: PASS (all 9 tests from Tasks 1-4).

- [ ] **Step 4: Run the full finance test suite to check for regressions**

Run: `cd backend && python manage.py test apps.finance -v 1`
Expected: PASS, same pass count as before this phase plus the 9 new tests — no existing test broken.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/views.py backend/apps/finance/urls.py backend/apps/finance/test_contributions.py
git commit -m "feat(finance): expose ShareholderContribution via /api/shareholder-contributions/"
```

---

## Task 5: Frontend types + API client

**Files:**
- Modify: `frontend/src/modules/finance/types.ts`
- Modify: `frontend/src/modules/finance/api.ts`

**Interfaces:**
- Produces:
  - `ShareholderContribution` TS interface.
  - `shareholderContributionResource: ResourceApi<ShareholderContribution>` (for listing, e.g. a future "Capital" history section).
  - `createShareholderContribution(payload): Promise<ShareholderContribution>`.

- [ ] **Step 1: Add the type**

In `frontend/src/modules/finance/types.ts`, immediately after the `ShareholderWithdrawal` interface (ends around line 456), add:

```typescript
export interface ShareholderContribution {
  id: number
  shareholder: number
  shareholder_detail: ShareholderBrief | null
  amount: string
  date: string
  bank_account: number | null
  cash_account: number | null
  reference: string
  notes: string
  proof_url: string | null
  recorded_by: number | null
  recorded_by_detail: UserBrief | null
  created_at: string
  updated_at: string
}
```

- [ ] **Step 2: Add the resource + create helper**

In `frontend/src/modules/finance/api.ts`, add the import (extend the existing `import type { ... } from './types'` block with `ShareholderContribution`), then add right after `shareholderWithdrawalResource` (line ~231):

```typescript
export const shareholderContributionResource = createResourceApi<ShareholderContribution>(
  '/shareholder-contributions/',
)

export function createShareholderContribution(payload: {
  shareholder: number
  bank_account?: number | null
  cash_account?: number | null
  amount: string
  date: string
  reference?: string
  notes?: string
  attachment: File
}): Promise<ShareholderContribution> {
  const { attachment, ...fields } = payload
  return apiClient
    .post<ShareholderContribution>('/shareholder-contributions/', buildAdvanceForm(fields, attachment), {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}
```

`buildAdvanceForm` is already defined in this file (line 171) and generic (field-name-agnostic) — reuse it as-is, do not duplicate it.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: no new type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/modules/finance/types.ts frontend/src/modules/finance/api.ts
git commit -m "feat(finance): add ShareholderContribution frontend types and API client"
```

---

## Task 6: `ContributionForm.vue`

**Files:**
- Create: `frontend/src/modules/finance/ContributionForm.vue`
- Create: `frontend/src/modules/finance/__tests__/ContributionForm.spec.ts`
- Modify: `frontend/src/locales/fr.json`, `en.json`, `ar.json`

**Interfaces:**
- Consumes: `createShareholderContribution` (Task 5), `shareholderResource` (already exported from `./api`), `IMAGE_UPLOAD_ACCEPT`/`isAllowedImageFile` (`@/utils/imageUpload`).
- Produces: `ContributionForm.vue` component with props `initialShareholderId?: number | null`, `lockShareholder?: boolean`; emits `success`, `cancel`.

- [ ] **Step 1: Add locale keys**

In `frontend/src/locales/fr.json`, immediately after the `advanceForm` block (ends around line 765, right before `"partyLedger"`), add:

```json
    "contributionForm": {
      "title": "Nouvel apport en capital",
      "shareholder": "Actionnaire / Associé",
      "accountKind": "Type de compte",
      "bank": "Banque",
      "cash": "Caisse",
      "amount": "Montant de l'apport",
      "date": "Date",
      "reference": "Référence",
      "note": "Note",
      "attachment": "Justificatif (image)",
      "submit": "Enregistrer l'apport",
      "imageOnlyError": "Seules les images JPG, JPEG, PNG ou WEBP sont autorisées.",
      "loadError": "Impossible de charger les actionnaires.",
      "saveError": "Impossible d'enregistrer cet apport.",
      "errors": {
        "shareholderRequired": "Choisissez un actionnaire.",
        "accountRequired": "Choisissez un compte.",
        "positiveAmount": "Le montant doit être supérieur à zéro.",
        "proofRequired": "Un justificatif image est obligatoire pour enregistrer cet apport."
      }
    },
```

In `frontend/src/locales/en.json`, add the equivalent block after `advanceForm` (English wording, same key structure — e.g. `"title": "New capital contribution"`, `"shareholder": "Shareholder / Associate"`, `"amount": "Contribution amount"`, etc., mirroring the English wording style already used for the sibling `advanceForm` block in that file).

In `frontend/src/locales/ar.json`, add the equivalent block after `advanceForm` (Arabic wording, same key structure, mirroring the Arabic wording style already used for the sibling `advanceForm` block in that file).

- [ ] **Step 2: Write the failing component test**

Create `frontend/src/modules/finance/__tests__/ContributionForm.spec.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ContributionForm from '../ContributionForm.vue'

const createShareholderContribution = vi.fn()

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    createShareholderContribution: (...args: unknown[]) => createShareholderContribution(...args),
    shareholderResource: {
      list: vi.fn(async () => ({
        count: 2,
        next: null,
        previous: null,
        results: [
          { id: 10, name: 'Ahmed', participation_percent: '50.00', contribution: '0.00', phone: '', notes: '', is_active: true, created_at: '', updated_at: '' },
          { id: 11, name: 'Fatima', participation_percent: '50.00', contribution: '0.00', phone: '', notes: '', is_active: true, created_at: '', updated_at: '' },
        ],
      })),
    },
  }
})

vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({
    list: vi.fn(async () => ({
      count: 1,
      next: null,
      previous: null,
      results: [{ id: 1, name: 'BIM', current_balance: '500000.00' }],
    })),
  }),
}))

describe('ContributionForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    createShareholderContribution.mockResolvedValue({ id: 1 })
  })

  it('lists all shareholders when not locked', async () => {
    const wrapper = mount(ContributionForm)
    await flushPromises()

    const select = wrapper.find('select#shareholder')
    expect(select.text()).toContain('Ahmed')
    expect(select.text()).toContain('Fatima')
    expect((select.element as HTMLSelectElement).disabled).toBe(false)
  })

  it('locks the shareholder when opened from a ledger page', async () => {
    const wrapper = mount(ContributionForm, {
      props: { initialShareholderId: 11, lockShareholder: true },
    })
    await flushPromises()

    const select = wrapper.find('select#shareholder')
    expect((select.element as HTMLSelectElement).disabled).toBe(true)
    expect((select.element as HTMLSelectElement).value).toBe('11')
  })

  it('requires an image proof before submitting', async () => {
    const wrapper = mount(ContributionForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('form').trigger('submit')

    expect(createShareholderContribution).not.toHaveBeenCalled()
  })

  it('rejects a non-image attachment client-side', async () => {
    const wrapper = mount(ContributionForm)
    await flushPromises()

    const file = new File(['doc'], 'proof.pdf', { type: 'application/pdf' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('form').trigger('submit')

    expect(createShareholderContribution).not.toHaveBeenCalled()
  })

  it('submits a contribution with the chosen account and attachment', async () => {
    const wrapper = mount(ContributionForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('10000000')
    const file = new File(['receipt'], 'recu.jpg', { type: 'image/jpeg' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createShareholderContribution).toHaveBeenCalledWith(
      expect.objectContaining({ shareholder: 10, amount: '10000000', attachment: file }),
    )
  })
})
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ContributionForm.spec.ts`
Expected: FAIL — `ContributionForm.vue` does not exist.

- [ ] **Step 4: Implement `ContributionForm.vue`**

Create `frontend/src/modules/finance/ContributionForm.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import Button from '@/components/ui/Button.vue'
import { createShareholderContribution, shareholderResource } from './api'
import type { Shareholder } from './types'
import { IMAGE_UPLOAD_ACCEPT, isAllowedImageFile } from '@/utils/imageUpload'

const emit = defineEmits<{
  success: []
  cancel: []
}>()

const props = withDefaults(
  defineProps<{
    initialShareholderId?: number | null
    lockShareholder?: boolean
  }>(),
  {
    initialShareholderId: null,
    lockShareholder: false,
  },
)

const { t } = useI18n()

interface AccountOption {
  id: number
  name: string
  current_balance: string
}

const bankAccountResource = createResourceApi<AccountOption>('/bank-accounts/')
const cashAccountResource = createResourceApi<AccountOption>('/cash-accounts/')

const shareholders = ref<Shareholder[]>([])
const shareholderId = ref('')
const accountKind = ref<'bank' | 'cash'>('bank')
const bankAccountId = ref('')
const cashAccountId = ref('')
const amount = ref('')
const reference = ref('')
const note = ref('')
const attachment = ref<File | null>(null)
const attachmentError = ref('')
const date = ref(new Date().toISOString().slice(0, 10))

const banks = ref<AccountOption[]>([])
const cashAccounts = ref<AccountOption[]>([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')

const selectedShareholder = computed(
  () => shareholders.value.find((s) => s.id === Number(shareholderId.value)) ?? null,
)
const selectedAccount = computed(() =>
  accountKind.value === 'bank'
    ? (banks.value.find((bank) => bank.id === Number(bankAccountId.value)) ?? null)
    : (cashAccounts.value.find((account) => account.id === Number(cashAccountId.value)) ?? null),
)
const amountNumber = computed(() => Number(amount.value || 0))

function onAttachmentChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (file && !isAllowedImageFile(file)) {
    attachment.value = null
    input.value = ''
    attachmentError.value = t('finance.contributionForm.imageOnlyError')
    return
  }
  attachment.value = file
  attachmentError.value = ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [shareholderData, bankData, cashData] = await Promise.all([
      shareholderResource.list(),
      bankAccountResource.list(),
      cashAccountResource.list(),
    ])
    shareholders.value = shareholderData.results
    banks.value = bankData.results
    cashAccounts.value = cashData.results
    bankAccountId.value = banks.value[0]?.id ? String(banks.value[0].id) : ''
    cashAccountId.value = cashAccounts.value[0]?.id ? String(cashAccounts.value[0].id) : ''

    if (props.lockShareholder && props.initialShareholderId) {
      shareholderId.value = String(props.initialShareholderId)
    } else {
      const initial = shareholders.value.find((s) => s.id === props.initialShareholderId)
      shareholderId.value = initial ? String(initial.id) : (shareholders.value[0]?.id ? String(shareholders.value[0].id) : '')
    }
  } catch {
    error.value = t('finance.contributionForm.loadError')
  } finally {
    loading.value = false
  }
}

function validate(): boolean {
  error.value = ''
  if (!selectedShareholder.value) {
    error.value = t('finance.contributionForm.errors.shareholderRequired')
    return false
  }
  if (!selectedAccount.value) {
    error.value = t('finance.contributionForm.errors.accountRequired')
    return false
  }
  if (amountNumber.value <= 0) {
    error.value = t('finance.contributionForm.errors.positiveAmount')
    return false
  }
  if (!attachment.value) {
    error.value = t('finance.contributionForm.errors.proofRequired')
    return false
  }
  return true
}

async function submit() {
  if (!validate() || !selectedShareholder.value || !selectedAccount.value || !attachment.value) return
  saving.value = true
  try {
    await createShareholderContribution({
      shareholder: selectedShareholder.value.id,
      bank_account: accountKind.value === 'bank' ? Number(bankAccountId.value) : null,
      cash_account: accountKind.value === 'cash' ? Number(cashAccountId.value) : null,
      amount: String(amount.value),
      date: date.value,
      reference: reference.value,
      notes: note.value,
      attachment: attachment.value,
    })
    emit('success')
  } catch (err: unknown) {
    const data = (err as { response?: { data?: Record<string, unknown> } }).response?.data
    const detail =
      (data?.detail as string | undefined) ??
      (Array.isArray(data?.non_field_errors) ? (data!.non_field_errors as string[])[0] : undefined)
    error.value = detail ?? t('finance.contributionForm.saveError')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <form class="space-y-5" @submit.prevent="submit">
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else>
      <label class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.shareholder') }}</span>
        <select
          id="shareholder"
          v-model="shareholderId"
          class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          :disabled="lockShareholder"
        >
          <option v-for="shareholder in shareholders" :key="shareholder.id" :value="String(shareholder.id)">
            {{ shareholder.name }}
          </option>
        </select>
      </label>

      <div class="grid gap-4 sm:grid-cols-3">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.accountKind') }}</span>
          <select v-model="accountKind" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm">
            <option value="bank">{{ t('finance.contributionForm.bank') }}</option>
            <option value="cash">{{ t('finance.contributionForm.cash') }}</option>
          </select>
        </label>
        <label v-if="accountKind === 'bank'" class="space-y-1.5 sm:col-span-2">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.bank') }}</span>
          <select v-model="bankAccountId" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm">
            <option v-for="bank in banks" :key="bank.id" :value="String(bank.id)">{{ bank.name }}</option>
          </select>
        </label>
        <label v-else class="space-y-1.5 sm:col-span-2">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.cash') }}</span>
          <select v-model="cashAccountId" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm">
            <option v-for="account in cashAccounts" :key="account.id" :value="String(account.id)">
              {{ account.name }}
            </option>
          </select>
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.amount') }}</span>
          <input
            id="amount"
            v-model="amount"
            min="0.01"
            step="0.01"
            type="number"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          />
        </label>
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.date') }}</span>
          <input v-model="date" type="date" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm" />
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.reference') }}</span>
          <input v-model="reference" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm" />
        </label>
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.note') }}</span>
          <textarea v-model="note" rows="2" class="border-ligne w-full rounded-lg border px-3 py-2 text-sm" />
        </label>
      </div>

      <label class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.attachment') }}</span>
        <input
          type="file"
          required
          :accept="IMAGE_UPLOAD_ACCEPT"
          class="border-ligne w-full rounded-lg border px-3 py-2 text-sm"
          @change="onAttachmentChange"
        />
        <span v-if="attachment" class="text-texte-2 block text-xs">{{ attachment.name }}</span>
        <span v-if="attachmentError" class="text-critique block text-xs">{{ attachmentError }}</span>
      </label>

      <div class="flex justify-end gap-2">
        <Button variant="ghost" type="button" @click="emit('cancel')">{{ t('common.cancel') }}</Button>
        <Button variant="primary" type="submit" :loading="saving">
          {{ t('finance.contributionForm.submit') }}
        </Button>
      </div>
    </template>
  </form>
</template>
```

Confirm `Shareholder` is already exported from `./types` (it is — `ShareholderView.vue` already imports it) and `shareholderResource` is already exported from `./api` (it is, line ~230).

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ContributionForm.spec.ts`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/finance/ContributionForm.vue frontend/src/modules/finance/__tests__/ContributionForm.spec.ts frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json
git commit -m "feat(finance): add ContributionForm component"
```

---

## Task 7: Wire "Nouvel apport" into `ShareholderView.vue`

**Files:**
- Modify: `frontend/src/modules/finance/ShareholderView.vue`
- Modify: `frontend/src/modules/finance/__tests__/ShareholderView.spec.ts`

**Interfaces:**
- Consumes: `ContributionForm.vue` (Task 6).
- Produces: a "Nouvel apport" button in the `associates` tab (opens `ContributionForm` unlocked) and one in the `ledger` tab (opens it locked to `ledger.value.shareholder.id`), both via the existing `Modal` component (same pattern as `TransporterLedgerView.vue`'s `AdvanceForm` modal).

- [ ] **Step 1: Write the failing test**

Read the existing `frontend/src/modules/finance/__tests__/ShareholderView.spec.ts` first (already open in this plan's investigation) to match its `vi.mock('../api', ...)` shape exactly — add `shareholderContributionResource: { list: vi.fn(async () => emptyList()) }` and `createShareholderContribution: vi.fn()` to that mock object (it currently mocks `shareholderResource`, `shareholderLoanResource`, `shareholderWithdrawalResource`, `shareholderDistributionResource`, `fetchShareholderLedger`, `fetchShareholderProfitPreview`, `validateShareholderDistribution`, `recordShareholderLoanRepayment` — extend that same object, do not create a second mock).

Append a new test to that file:

```typescript
it('opens the contribution form from the associates tab', async () => {
  const wrapper = mount(ShareholderView, { global: { plugins: [i18n] } })
  await flushPromises()

  await wrapper.find('[data-testid="new-contribution-button"]').trigger('click')
  await flushPromises()

  expect(wrapper.findComponent({ name: 'ContributionForm' }).exists()).toBe(true)
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ShareholderView.spec.ts`
Expected: FAIL — `data-testid="new-contribution-button"` not found.

- [ ] **Step 3: Wire the component**

In `frontend/src/modules/finance/ShareholderView.vue`:

1. Add the import near the top, next to other component imports: `import ContributionForm from './ContributionForm.vue'`.
2. Add local state near the withdrawal section's `ref`s (around line 270): `const showContributionForm = ref(false)`.
3. In the `associates` tab card (the `<Card v-if="activeTab === 'associates'" ...>` block, around line 426), add a button next to whatever "add shareholder" control already exists there:

```html
<Button
  data-testid="new-contribution-button"
  variant="primary"
  @click="showContributionForm = true"
>
  {{ t('finance.contributionForm.title') }}
</Button>
```

4. In the `ledger` tab card (around line 899, inside `<Card v-if="activeTab === 'ledger'" ...>`, in the `<template v-else-if="ledger">` block where the summary tiles are), add a locked variant:

```html
<Button
  data-testid="new-contribution-button-ledger"
  variant="primary"
  @click="showLedgerContributionForm = true"
>
  {{ t('finance.contributionForm.title') }}
</Button>
```

and its own `const showLedgerContributionForm = ref(false)` next to `showContributionForm`.

5. Add the two modals near the end of the template, alongside any existing `<Modal>` blocks (follow `TransporterLedgerView.vue`'s exact structure for the `AdvanceForm` modal):

```html
<Modal
  v-if="showContributionForm"
  :title="t('finance.contributionForm.title')"
  max-width="max-w-2xl"
  @close="showContributionForm = false"
>
  <ContributionForm
    @success="showContributionForm = false"
    @cancel="showContributionForm = false"
  />
</Modal>

<Modal
  v-if="showLedgerContributionForm && ledger"
  :title="t('finance.contributionForm.title')"
  max-width="max-w-2xl"
  @close="showLedgerContributionForm = false"
>
  <ContributionForm
    :initial-shareholder-id="ledger.shareholder.id"
    lock-shareholder
    @success="() => { showLedgerContributionForm = false; loadLedger(ledger!.shareholder.id) }"
    @cancel="showLedgerContributionForm = false"
  />
</Modal>
```

Confirm `Modal` is already imported in this file (it must be, since other tabs presumably use modals elsewhere in this large page — if not already imported, add `import Modal from '@/components/ui/Modal.vue'` matching `TransporterLedgerView.vue`'s import path).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ShareholderView.spec.ts`
Expected: PASS.

- [ ] **Step 5: Run the full frontend test suite to check for regressions**

Run: `cd frontend && npx vitest run`
Expected: PASS, no existing test broken.

- [ ] **Step 6: Manual smoke check**

Start the dev server (`cd frontend && npm run dev`, backend already running), open the Actionnaires/Associés page, click "Nouvel apport", fill the form with a test image, submit, and confirm: (a) the bank/cash balance shown elsewhere in the app increased, (b) no console errors, (c) the modal closes and the page doesn't crash.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/finance/ShareholderView.vue frontend/src/modules/finance/__tests__/ShareholderView.spec.ts
git commit -m "feat(finance): wire ContributionForm into ShareholderView (associates + ledger tabs)"
```

---

## Self-Review Notes (already applied above)

- **Spec coverage:** model+constraints (Task 1), service+capital total (Task 2), serializer validation incl. mandatory attachment (Task 3), API exposure incl. no-hard-delete/no-edit (Task 4), frontend plumbing (Task 5), form incl. required proof (Task 6), UI wiring from both associates list and per-shareholder ledger (Task 7) — matches every bullet in the spec's Phase 1 section except the "Grand livre affiche l'apport" display, which the spec now explicitly defers (contribution history stays a separate read, not merged into `ShareholderStatementQuery`) — out of scope for this plan; note it as a follow-up if the client wants a dedicated "Capital" tab before Phase 2 ships.
- **Type consistency:** `ShareholderContributionService.record_contribution`'s parameter names (`shareholder_id`, `bank_account_id`, `cash_account_id`, `attachment`, `actor`) are used identically in Task 3's serializer `create()`. `ContributionForm.vue`'s emitted payload field names (`shareholder`, `bank_account`, `cash_account`, `amount`, `date`, `reference`, `notes`, `attachment`) match `createShareholderContribution`'s payload type in Task 5 exactly.
- **Known follow-up for the reviewer:** Task 7 assumes `Modal` is already imported in `ShareholderView.vue` and that the `associates`/`ledger` tab markup has the shape described (based on investigation, not a fresh read at execution time) — re-read the actual current file before editing, since other in-flight UI changes (visible in `git status`) may have shifted line numbers or structure.

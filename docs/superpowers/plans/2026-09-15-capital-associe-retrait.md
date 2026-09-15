# Capital Associé Comme Filet De Sécurité Du Solde — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a shareholder withdrawal draw on that shareholder's own remaining capital once their profit share is exhausted, while every franc stays traceable to its exact source (a specific profit share or a specific capital contribution) and strictly isolated per shareholder.

**Architecture:** Replace `ShareholderWithdrawal`'s single `profit_share` FK with a new child table, `ShareholderWithdrawalAllocation`, so one withdrawal can be funded by several profit shares and/or several capital contributions. `ShareholderWithdrawalService.record_withdrawal` takes a plain amount and allocates it automatically: all VALIDATED profit shares (oldest first) then, only if still short, the shareholder's own capital contributions (oldest first, and only that shareholder's own rows — never another shareholder's). `ShareholderLedgerService.get_available_balance` gains a `capital_remaining` term. Everywhere else that read `ShareholderWithdrawal.profit_share` moves to reading `ShareholderWithdrawalAllocation`.

**Tech Stack:** Django 5 / DRF (backend, `backend/apps/finance`), Vue 3 + TypeScript + Vitest (frontend, `frontend/src/modules/finance`), pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-09-15-capital-associe-retrait-design.md`

## Global Constraints

- A withdrawal draws from profit due first; only once that is exhausted does it draw from capital (spec Goal 1).
- A shareholder can only draw down **his own** contributed capital — enforced by `.filter(shareholder_id=shareholder_id)` on `ShareholderContribution`, never a cross-shareholder or pooled query (spec Goal 5).
- `%` participation is never touched by a capital withdrawal.
- `ShareholderLoan` behavior and `ShareholderContributionService.record_contribution` (creating a contribution) are unchanged — this plan only touches what happens when capital is later drawn back down.
- No manual "pick this specific share/contribution" UI — allocation is always automatic, oldest-first.
- Every money amount is a `Decimal`; never use floats.
- All backend money-moving code runs inside `transaction.atomic()` under `select_for_update()`, matching the existing pattern in `ShareholderWithdrawalService.record_withdrawal`.

---

## File Structure

Backend (`backend/apps/finance/`):
- `models.py` — modify `ShareholderContribution` (add `amount_returned`, `remaining_capital`, `sync_amount_returned()`); add `ShareholderWithdrawalAllocation`; modify `ShareholderWithdrawal` (drop `profit_share` FK).
- `migrations/0022_shareholdercontribution_amount_returned.py` — new field + constraint.
- `migrations/0023_shareholderwithdrawalallocation.py` — new table.
- `migrations/0024_backfill_withdrawal_allocations.py` — data migration.
- `migrations/0025_remove_shareholderwithdrawal_profit_share.py` — drop old column.
- `services.py` — rewrite `ShareholderWithdrawalService.record_withdrawal`; add `ShareholderLedgerService.get_profit_and_capital_remaining`; update `get_available_balance`, `get_shareholder_summary`; update `ShareholderDistributionService.cancel_distribution`; update `ShareholderProfitShare.sync_amount_withdrawn`'s caller expectations (the method itself lives on the model).
- `serializers.py` — add `ShareholderWithdrawalAllocationSerializer`; update `ShareholderWithdrawalSerializer` and `ShareholderContributionSerializer`.
- `views.py` — update `ShareholderWithdrawalViewSet`.
- `test_capital_withdrawal.py` — **new file**, all tests for the allocation algorithm (kept separate from the already-6000-line `tests.py`, matching the "split when a file has grown unwieldy" guidance).
- `test_contributions.py` — add tests for `amount_returned`/`remaining_capital`.
- `tests.py` — fix existing call sites broken by the `record_withdrawal` signature change; replace two now-obsolete tests.

Backend (`backend/apps/reports/`):
- `queries/shareholder_statement.py` — add a `CONTRIBUTION` credit event; enrich the `WITHDRAWAL` reference with the allocation breakdown.
- `test_queries.py`, `test_views.py`, `test_production_like_scenario.py` — fix call sites; add one new statement test for the capital event.

Frontend (`frontend/src/modules/finance/`):
- `types.ts` — replace `profit_share`/`profit_share_id` with `allocations` on `ShareholderWithdrawal` and `ShareholderLedgerWithdrawal`; add `ShareholderWithdrawalAllocation` type; add `capital_returned`/`capital_remaining` to `ShareholderLedger`.
- `ShareholderView.vue` — remove the profit-share picker from the withdrawal form; add an available-balance hint; render the allocation breakdown in both withdrawal tables; add a "Capital restant" line in the ledger's capital section.
- `__tests__/ShareholderView.spec.ts` — replace the obsolete profit-share-picker test; add coverage for the hint and the breakdown.

Frontend locales (`frontend/src/locales/{fr,en,ar}.json`): remove `finance.shareholder.withdrawal.profitShare`/`selectProfitShare`; add `finance.shareholder.withdrawal.availableBalanceHint`, `.sourceProfitShare`, `.sourceCapital`; add `finance.shareholder.capital.remaining`. **Do not** remove the unrelated `profit_share_id` audit-log field-label entries (~line 1665-1669 in each file) — those label historical `AuditLog` rows that may still reference the old field name.

---

### Task 1: `ShareholderContribution` gains `amount_returned` / `remaining_capital`

**Files:**
- Modify: `backend/apps/finance/models.py:1169-1229` (the `ShareholderContribution` class)
- Create: `backend/apps/finance/migrations/0022_shareholdercontribution_amount_returned.py`
- Test: `backend/apps/finance/test_contributions.py`

**Interfaces:**
- Produces: `ShareholderContribution.amount_returned` (Decimal field), `ShareholderContribution.remaining_capital` (property), `ShareholderContribution.sync_amount_returned()` (instance method, returns `Decimal`, only writer of `amount_returned`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/finance/test_contributions.py`:

```python
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
```

Add the two new imports at the top of `test_contributions.py`:

```python
from apps.finance.models import ShareholderWithdrawal, ShareholderWithdrawalAllocation
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_contributions.py -k "remaining_capital or amount_returned or sync_amount_returned" -v`
Expected: FAIL — `ShareholderContribution` has no `amount_returned`/`remaining_capital`, and `ShareholderWithdrawalAllocation` does not exist yet (this last one will keep failing until Task 2 — that's fine, note it and continue with Task 1's own model change first; re-run once Task 2 lands).

- [ ] **Step 3: Add the field, property and method**

In `backend/apps/finance/models.py`, inside the `ShareholderContribution` class (currently ends around line 1229, right after the `document`/`recorded_by` fields and before `class Meta`), add the field next to the existing fields:

```python
    amount_returned = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, editable=False
    )
```

Add to `Meta.constraints` (alongside the existing three):

```python
            models.CheckConstraint(
                condition=models.Q(amount_returned__gte=0),
                name="finance_shareholdercontribution_amount_returned_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_returned__lte=models.F("amount")),
                name="finance_shareholdercontribution_returned_not_exceeding_amount",
            ),
```

After `__str__`, add:

```python
    @property
    def remaining_capital(self) -> Decimal:
        return self.amount - self.amount_returned

    def sync_amount_returned(self) -> Decimal:
        """Recompute amount_returned from the actual
        ShareholderWithdrawalAllocation rows against this contribution -
        the only writer, so it can never silently drift (same pattern as
        ShareholderProfitShare.sync_amount_withdrawn)."""
        total = (
            self.withdrawal_allocations.aggregate(total=models.Sum("amount"))["total"]
            or Decimal("0.00")
        )
        self.amount_returned = total
        self.save(update_fields=["amount_returned", "updated_at"])
        return total
```

Update the class docstring (the paragraph starting "Never contributes to `ShareholderLedgerService.get_available_balance()`...") to:

```python
    """Real cash injected into the company by a shareholder/associate
    (Phase 1, docs/superpowers/specs/2026-09-02-business-corrections-6-phases-design.md).

    Its still-unreturned amount (`remaining_capital`) DOES contribute to
    `ShareholderLedgerService.get_available_balance()` (design doc
    2026-09-15-capital-associe-retrait-design.md): once a shareholder's
    profit share is exhausted, a withdrawal may draw down their own
    capital, oldest contribution first, tracked one
    ShareholderWithdrawalAllocation row at a time so it never drifts and
    never touches another shareholder's capital.

    The proof document is mandatory here (a capital injection is a
    notable, real money-in event), so creation goes through
    ShareholderContributionService.record_contribution, copied from
    AdvanceService.create_supplier_advance rather than routed through
    FinancePostingService (which only fits flows where the document stays
    optional).
    """
```

- [ ] **Step 4: Generate and inspect the migration**

Run: `cd backend && python manage.py makemigrations finance --name shareholdercontribution_amount_returned`
Expected: creates `apps/finance/migrations/0022_shareholdercontribution_amount_returned.py` adding the field and the two constraints. Open it and confirm it matches — no other unrelated changes should appear (if any do, another app's models drifted; investigate before continuing).

- [ ] **Step 5: Run tests to verify the model-only ones pass**

Run: `cd backend && python -m pytest apps/finance/test_contributions.py -k "remaining_capital or amount_returned_cannot_exceed" -v`
Expected: PASS for the first two tests. `test_sync_amount_returned_recomputes_from_allocations` still fails (no `ShareholderWithdrawalAllocation` yet) — expected until Task 2.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/models.py backend/apps/finance/migrations/0022_shareholdercontribution_amount_returned.py backend/apps/finance/test_contributions.py
git commit -m "feat(finance): let ShareholderContribution track its own returned capital"
```

---

### Task 2: `ShareholderWithdrawalAllocation` model

**Files:**
- Modify: `backend/apps/finance/models.py` (add new class, after `ShareholderContribution`)
- Create: `backend/apps/finance/migrations/0023_shareholderwithdrawalallocation.py`
- Test: `backend/apps/finance/test_capital_withdrawal.py` (new file)

**Interfaces:**
- Consumes: `ShareholderWithdrawal` (existing model, `backend/apps/finance/models.py:1109`), `ShareholderProfitShare` (existing, `:970`), `ShareholderContribution.remaining_capital`/`.sync_amount_returned()` (Task 1).
- Produces: `ShareholderWithdrawalAllocation` model with fields `withdrawal` (FK), `profit_share` (FK, nullable), `contribution` (FK, nullable), `amount` (Decimal); `related_name="allocations"` on `withdrawal`, `related_name="withdrawal_allocations"` on both `profit_share` and `contribution`.

- [ ] **Step 1: Write the failing tests**

Create `backend/apps/finance/test_capital_withdrawal.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_capital_withdrawal.py -v`
Expected: FAIL with `ImportError`/`AttributeError` — `ShareholderWithdrawalAllocation` doesn't exist.

- [ ] **Step 3: Add the model**

In `backend/apps/finance/models.py`, immediately after the `ShareholderContribution` class, add:

```python
class ShareholderWithdrawalAllocation(TimeStampedModel):
    """Which pool a withdrawal actually drew from - a profit share or a
    capital contribution, never both on the same row (design doc
    2026-09-15-capital-associe-retrait-design.md). One ShareholderWithdrawal
    (one treasury posting) can have several of these, e.g. a withdrawal
    that exhausts two profit shares and dips into one capital contribution
    produces three rows here. `ShareholderProfitShare.amount_withdrawn` and
    `ShareholderContribution.amount_returned` are both recomputed only from
    these rows (sync_amount_withdrawn/sync_amount_returned), so neither can
    drift from the actual allocation history.
    """

    withdrawal = models.ForeignKey(
        ShareholderWithdrawal, on_delete=models.CASCADE, related_name="allocations"
    )
    profit_share = models.ForeignKey(
        ShareholderProfitShare,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="withdrawal_allocations",
    )
    contribution = models.ForeignKey(
        ShareholderContribution,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="withdrawal_allocations",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_shrwithdrawalalloc_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(profit_share__isnull=False, contribution__isnull=True)
                    | models.Q(profit_share__isnull=True, contribution__isnull=False)
                ),
                name="finance_shrwithdrawalalloc_exactly_one_source",
            ),
        ]
        indexes = [
            models.Index(fields=["withdrawal"], name="finance_shrwdalloc_wd_idx"),
        ]

    def __str__(self) -> str:
        source = self.profit_share_id and f"share {self.profit_share_id}" or f"contribution {self.contribution_id}"
        return f"WD-{self.withdrawal_id}: {self.amount} from {source}"
```

Note: `ShareholderProfitShare` is defined earlier in the same file (line ~970), so no import is needed - it's a plain forward reference within the same module.

- [ ] **Step 4: Generate the migration**

Run: `cd backend && python manage.py makemigrations finance --name shareholderwithdrawalallocation`
Expected: creates `apps/finance/migrations/0023_shareholderwithdrawalallocation.py`. Open it and confirm the two `CheckConstraint`s and the FK `on_delete` values match what you wrote.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/test_capital_withdrawal.py -v`
Expected: PASS (all 3 tests).

Also re-run Task 1's last test:

Run: `cd backend && python -m pytest apps/finance/test_contributions.py -k sync_amount_returned -v`
Expected: PASS now that `ShareholderWithdrawalAllocation` exists.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/models.py backend/apps/finance/migrations/0023_shareholderwithdrawalallocation.py backend/apps/finance/test_capital_withdrawal.py
git commit -m "feat(finance): add ShareholderWithdrawalAllocation to trace multi-source withdrawals"
```

---

### Task 3: Migrate existing withdrawals onto allocations, drop the old FK

**Files:**
- Create: `backend/apps/finance/migrations/0024_backfill_withdrawal_allocations.py`
- Create: `backend/apps/finance/migrations/0025_remove_shareholderwithdrawal_profit_share.py`
- Modify: `backend/apps/finance/models.py` (`ShareholderWithdrawal` class, currently `:1109-1166`)
- Test: `backend/apps/finance/test_capital_withdrawal.py`

**Interfaces:**
- Consumes: `ShareholderWithdrawalAllocation` (Task 2).
- Produces: `ShareholderWithdrawal` with no `profit_share` field; every pre-existing withdrawal has exactly one matching `ShareholderWithdrawalAllocation(profit_share=<old value>, amount=<withdrawal.amount>)`.

- [ ] **Step 1: Write the failing test for the backfill migration**

Add to `backend/apps/finance/test_capital_withdrawal.py`:

```python
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

    distribution = OldShareholderProfitDistribution.objects.create(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("100000.00"), status="VALIDATED", created_by=admin_user,
    )
    share = OldShareholderProfitShare.objects.create(
        distribution=distribution, shareholder=shareholder,
        percent_snapshot=Decimal("100.00"), amount_due=Decimal("100000.00"),
    )
    old_withdrawal = OldShareholderWithdrawal.objects.create(
        shareholder=shareholder, profit_share=share, amount=Decimal("40000.00"),
        date="2026-08-01", cash_account=cash, recorded_by=admin_user,
    )

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
```

Note: this test manipulates migration state directly and is slower than the rest of the suite - that is expected for a data-migration test; keep it as the only one of its kind in this file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest apps/finance/test_capital_withdrawal.py::test_backfill_migration_creates_one_allocation_per_existing_withdrawal -v`
Expected: FAIL — migration `0024_backfill_withdrawal_allocations` does not exist yet.

- [ ] **Step 3: Write the backfill data migration**

Create `backend/apps/finance/migrations/0024_backfill_withdrawal_allocations.py`:

```python
from django.db import migrations


def backfill_allocations(apps, schema_editor):
    ShareholderWithdrawal = apps.get_model("finance", "ShareholderWithdrawal")
    ShareholderWithdrawalAllocation = apps.get_model("finance", "ShareholderWithdrawalAllocation")

    for withdrawal in ShareholderWithdrawal.objects.filter(profit_share__isnull=False):
        ShareholderWithdrawalAllocation.objects.create(
            withdrawal=withdrawal,
            profit_share_id=withdrawal.profit_share_id,
            amount=withdrawal.amount,
        )


def reverse_backfill(apps, schema_editor):
    ShareholderWithdrawalAllocation = apps.get_model("finance", "ShareholderWithdrawalAllocation")
    ShareholderWithdrawalAllocation.objects.filter(profit_share__isnull=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0023_shareholderwithdrawalallocation"),
    ]

    operations = [
        migrations.RunPython(backfill_allocations, reverse_backfill),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest apps/finance/test_capital_withdrawal.py::test_backfill_migration_creates_one_allocation_per_existing_withdrawal -v`
Expected: PASS.

- [ ] **Step 5: Drop the old `profit_share` field**

In `backend/apps/finance/models.py`, remove the `profit_share` field from `ShareholderWithdrawal` and update its docstring:

```python
class ShareholderWithdrawal(AuditableModel, TimeStampedModel):
    """Money paid out from company treasury to a shareholder (Task 7,
    client modifications plan). Which profit share(s) and/or capital
    contribution(s) it actually drew from is recorded on its `allocations`
    (ShareholderWithdrawalAllocation, design doc
    2026-09-15-capital-associe-retrait-design.md) - always at least one,
    computed automatically by ShareholderWithdrawalService.record_withdrawal
    (profit due first, oldest first; the shareholder's own capital next,
    oldest first).

    AuditableModel + the same bank_account/cash_account exclusivity
    constraint as SupplierPayment, since this is a real money-out event
    that must post to treasury exactly like a supplier payment does
    (ShareholderWithdrawalService.record_withdrawal /
    FinancePostingService.record_shareholder_withdrawal_treasury).
    """

    shareholder = models.ForeignKey(
        Shareholder, on_delete=models.PROTECT, related_name="withdrawals"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
```

(Remove the `profit_share = models.ForeignKey(...)` block that used to sit between `shareholder` and `amount`; everything below `amount` — `date`, `bank_account`, `cash_account`, `notes`, `recorded_by`, `Meta`, `__str__` — stays exactly as it is.)

- [ ] **Step 6: Generate the column-removal migration**

Run: `cd backend && python manage.py makemigrations finance --name remove_shareholderwithdrawal_profit_share`
Expected: creates `apps/finance/migrations/0025_remove_shareholderwithdrawal_profit_share.py` with a single `RemoveField`. Confirm its `dependencies` includes `0024_backfill_withdrawal_allocations` (Django orders this automatically since it's the latest migration at generation time).

- [ ] **Step 7: Run the full finance test suite to see the expected breakage**

Run: `cd backend && python -m pytest apps/finance/ apps/reports/ -v 2>&1 | tail -80`
Expected: many FAILures/ERRORs referencing `profit_share_id` unexpected keyword argument, or `ShareholderWithdrawal has no field profit_share` — this is expected; Tasks 4-10 fix every one of them. Do not try to fix them here; just confirm the failures are all of that shape (nothing unrelated broke) before moving on.

- [ ] **Step 8: Commit**

```bash
git add backend/apps/finance/models.py backend/apps/finance/migrations/0024_backfill_withdrawal_allocations.py backend/apps/finance/migrations/0025_remove_shareholderwithdrawal_profit_share.py backend/apps/finance/test_capital_withdrawal.py
git commit -m "feat(finance): backfill withdrawal allocations and drop the old profit_share FK"
```

---

### Task 4: Rewrite `record_withdrawal` with automatic profit-then-capital allocation

**Files:**
- Modify: `backend/apps/finance/services.py:1857-1956` (`ShareholderWithdrawalService`)
- Modify: `backend/apps/finance/models.py` (`ShareholderProfitShare.sync_amount_withdrawn`, currently reading `self.withdrawals`)
- Test: `backend/apps/finance/test_capital_withdrawal.py`

**Interfaces:**
- Consumes: `ShareholderWithdrawalAllocation` (Task 2/3), `ShareholderContribution.remaining_capital`/`.sync_amount_returned()` (Task 1).
- Produces: `ShareholderLedgerService.get_profit_and_capital_remaining(shareholder_id)` (new in this task, reused by both `get_available_balance` and `record_withdrawal`'s second ceiling check, both in this same task); `ShareholderWithdrawalService.record_withdrawal(*, shareholder_id, amount, date, actor, bank_account_id=None, cash_account_id=None, notes="")` — no more `profit_share_id` parameter.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/test_capital_withdrawal.py`:

```python
from apps.finance.models import ShareholderProfitDistribution, ShareholderProfitShare
from apps.finance.services import (
    ShareholderDistributionService,
    ShareholderLedgerService,
    ShareholderLoanService,
    ShareholderWithdrawalError,
    ShareholderWithdrawalService,
)


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
def test_withdrawal_rejects_amount_exceeding_profit_plus_capital_even_with_loan_credit():
    """Second ceiling from the design doc: loans_given_remaining inflates
    available_balance but is never an allocatable source, so a withdrawal
    request that only fits because of loan credit must still be rejected."""
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

    assert ShareholderLedgerService.get_available_balance(lender.id) == Decimal("150000.00")

    with pytest.raises(ShareholderWithdrawalError):
        ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=lender.id, amount=Decimal("120000.00"), date="2026-08-02",
            cash_account_id=cash.id, actor=actor,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_capital_withdrawal.py -k "withdrawal_within or withdrawal_exceeding or withdrawal_consumes or withdrawal_never or withdrawal_rejects_amount_exceeding_profit or get_available_balance_includes_capital_remaining" -v`
Expected: FAIL — `get_available_balance` doesn't yet include `capital_remaining`, and `record_withdrawal()` still requires `profit_share_id` and doesn't know about capital.

- [ ] **Step 3: Update `sync_amount_withdrawn` to read from allocations**

In `backend/apps/finance/models.py`, in `ShareholderProfitShare.sync_amount_withdrawn` (currently `:1030-1035`), change the source of the aggregate:

```python
    def sync_amount_withdrawn(self) -> Decimal:
        """Recompute amount_withdrawn from the actual
        ShareholderWithdrawalAllocation rows against this share - the only
        way this field is ever written, so it can never drift from
        withdrawal history (Task 7, client modifications plan: "avoid a
        field that can silently drift")."""
        total = (
            self.withdrawal_allocations.aggregate(total=models.Sum("amount"))["total"]
            or Decimal("0.00")
        )
        self.amount_withdrawn = total
        self.save(update_fields=["amount_withdrawn", "updated_at"])
        return total
```

(Only the `self.withdrawals.aggregate(...)` line changes to `self.withdrawal_allocations.aggregate(...)` — everything else is identical.)

- [ ] **Step 4: Add `get_profit_and_capital_remaining` and rewrite `record_withdrawal`**

In `backend/apps/finance/services.py`, inside `ShareholderLedgerService` (starts at `:2325`), add this new static method right before `get_available_balance`:

```python
    @staticmethod
    def get_profit_and_capital_remaining(shareholder_id) -> Decimal:
        """The two pools a withdrawal can actually be allocated against -
        deliberately excludes loan terms (design doc
        2026-09-15-capital-associe-retrait-design.md): a loan between
        shareholders is never a source ShareholderWithdrawalService draws
        from, so this is a narrower, allocation-safe figure than
        get_available_balance()."""
        shares_remaining = (
            ShareholderProfitShare.objects.filter(shareholder_id=shareholder_id)
            .filter(distribution__status=ShareholderProfitDistribution.Status.VALIDATED)
            .aggregate(total=Sum(F("amount_due") - F("amount_withdrawn")))["total"]
            or ZERO
        )
        capital_remaining = (
            ShareholderContribution.objects.filter(shareholder_id=shareholder_id)
            .aggregate(total=Sum(F("amount") - F("amount_returned")))["total"]
            or ZERO
        )
        return shares_remaining + capital_remaining
```

Update `get_available_balance` (`:2333-2374`) to reuse it:

```python
    @staticmethod
    def get_available_balance(shareholder_id) -> Decimal:
        """Single source of truth for how much a shareholder can withdraw
        or lend out right now (design docs
        2026-08-26-benefices-associes-refinement-design.md and
        2026-09-15-capital-associe-retrait-design.md):

            available_balance =
                profit_share_remaining_due
              + capital_remaining
              + loans_given_remaining
              - loans_received_remaining

        Lending money to another associate is a receivable - it stays this
        shareholder's equity, just claimed via an IOU instead of sitting in
        remaining_due, so it *adds* to the balance. Receiving an advance is
        a liability that must be repaid, so it *subtracts*. Called by both
        ShareholderWithdrawalService.record_withdrawal and
        ShareholderLoanService.create_loan so a withdrawal and a loan can
        never be validated against two different numbers.

        Only a VALIDATED distribution's shares count (2026-09-08 review,
        "modele metier definitif"): a DRAFT distribution is a preparatory
        proposal with no real debt to the shareholders, and a CANCELLED one
        no longer grants any right - neither may credit an available
        balance, everywhere that balance is used.

        A shareholder's own remaining capital (design doc
        2026-09-15) is included here, but a withdrawal never allocates
        against loan terms - see get_profit_and_capital_remaining, used as
        a narrower, allocation-safe ceiling by record_withdrawal.
        """
        pools_remaining = ShareholderLedgerService.get_profit_and_capital_remaining(shareholder_id)
        loans_given_remaining = sum(
            (loan.remaining_amount for loan in ShareholderLoan.objects.filter(lender_id=shareholder_id)),
            ZERO,
        )
        loans_received_remaining = sum(
            (
                loan.remaining_amount
                for loan in ShareholderLoan.objects.filter(borrower_id=shareholder_id)
            ),
            ZERO,
        )
        return pools_remaining + loans_given_remaining - loans_received_remaining
```

Now rewrite `ShareholderWithdrawalService.record_withdrawal` (currently `:1866-1956`) in full:

```python
    @staticmethod
    @transaction.atomic
    def record_withdrawal(
        *,
        shareholder_id,
        amount,
        date,
        actor,
        bank_account_id=None,
        cash_account_id=None,
        notes="",
    ) -> ShareholderWithdrawal:
        """Automatically allocates the requested amount across the
        shareholder's own pools - all VALIDATED profit shares (oldest
        first), then, only if still short, their own capital contributions
        (oldest first) - never another shareholder's (design doc
        2026-09-15-capital-associe-retrait-design.md). Loan terms are
        never allocated against; see
        ShareholderLedgerService.get_profit_and_capital_remaining.
        """
        shareholder = Shareholder.objects.select_for_update().get(pk=shareholder_id)
        amount_decimal = Decimal(str(amount))

        available_balance = ShareholderLedgerService.get_available_balance(shareholder_id)
        if amount_decimal > available_balance:
            raise ShareholderWithdrawalError("Solde associe insuffisant.")

        allocatable = ShareholderLedgerService.get_profit_and_capital_remaining(shareholder_id)
        if amount_decimal > allocatable:
            raise ShareholderWithdrawalError("Solde associe insuffisant.")

        if bank_account_id is not None:
            account = BankAccount.objects.select_for_update().get(pk=bank_account_id)
        else:
            account = CashAccount.objects.select_for_update().get(pk=cash_account_id)
        if amount_decimal > account.current_balance:
            raise ShareholderWithdrawalError("Solde bancaire insuffisant.")

        withdrawal = ShareholderWithdrawal.objects.create(
            shareholder=shareholder,
            amount=amount,
            date=date,
            bank_account_id=bank_account_id,
            cash_account_id=cash_account_id,
            notes=notes,
            recorded_by=actor,
        )

        amount_left = amount_decimal

        shares = (
            ShareholderProfitShare.objects.select_for_update()
            .filter(
                shareholder_id=shareholder_id,
                distribution__status=ShareholderProfitDistribution.Status.VALIDATED,
            )
            .order_by("distribution__period_end", "distribution_id")
        )
        for share in shares:
            if amount_left <= 0:
                break
            remaining = share.remaining_due
            if remaining <= 0:
                continue
            consumed = min(remaining, amount_left)
            ShareholderWithdrawalAllocation.objects.create(
                withdrawal=withdrawal, profit_share=share, amount=consumed,
            )
            share.sync_amount_withdrawn()
            amount_left -= consumed

        if amount_left > 0:
            contributions = (
                ShareholderContribution.objects.select_for_update()
                .filter(shareholder_id=shareholder_id)
                .order_by("date", "id")
            )
            for contribution in contributions:
                if amount_left <= 0:
                    break
                remaining = contribution.remaining_capital
                if remaining <= 0:
                    continue
                consumed = min(remaining, amount_left)
                ShareholderWithdrawalAllocation.objects.create(
                    withdrawal=withdrawal, contribution=contribution, amount=consumed,
                )
                contribution.sync_amount_returned()
                amount_left -= consumed

        if amount_left > 0:
            # The two ceiling checks above should make this unreachable -
            # if it triggers, something upstream (e.g. a future third
            # additive term on available_balance) broke the invariant that
            # allocatable always covers a request that passed both checks.
            raise ShareholderWithdrawalError(
                "Erreur interne : montant du retrait non entierement alloue."
            )

        FinancePostingService.record_shareholder_withdrawal_treasury(withdrawal)

        return withdrawal
```

Add `ShareholderWithdrawalAllocation` to the imports at the top of `services.py` if the models are imported individually there (check the existing `from apps.finance.models import (...)` block and add it alphabetically alongside `ShareholderWithdrawal`).

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/test_capital_withdrawal.py -v`
Expected: PASS for every test added in Step 1 of this task (the ones from Tasks 1-3 should already be passing).

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/models.py backend/apps/finance/services.py backend/apps/finance/test_capital_withdrawal.py
git commit -m "feat(finance): allocate withdrawals across profit shares then capital automatically"
```

---

### Task 5: Fix `ShareholderDistributionService.cancel_distribution`

**Files:**
- Modify: `backend/apps/finance/services.py:1833-1835`
- Test: `backend/apps/finance/tests.py` (existing tests, no new ones needed - this is a pure query-shape fix)

**Interfaces:**
- Consumes: `ShareholderWithdrawalAllocation` (Task 2).

- [ ] **Step 1: Confirm the existing tests currently fail here**

Run: `cd backend && python -m pytest apps/finance/tests.py -k "cancel_distribution_rejects_when_withdrawal" -v`
Expected: FAIL or ERROR — `ShareholderWithdrawal` has no field `profit_share` anymore, so the current `.filter(profit_share__distribution_id=...)` raises a `FieldError`.

- [ ] **Step 2: Fix the query**

In `backend/apps/finance/services.py`, change lines 1833-1835 from:

```python
        if ShareholderWithdrawal.objects.filter(
            profit_share__distribution_id=distribution.id
        ).exists():
```

to:

```python
        if ShareholderWithdrawalAllocation.objects.filter(
            profit_share__distribution_id=distribution.id
        ).exists():
```

- [ ] **Step 3: Fix the two call sites in `tests.py` that feed this path**

In `backend/apps/finance/tests.py`, in `test_distribution_cancel_action_rejects_when_withdrawal_exists` (`:3983-3990`) and `test_cancel_distribution_rejects_when_withdrawal_already_recorded` (`:4200-4207`), remove the `profit_share_id=share.id,` line from each `record_withdrawal(...)` call (both withdrawals already target the shareholder's only VALIDATED share, so automatic allocation reaches the exact same share with no other change needed).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/tests.py -k "cancel_distribution_rejects_when_withdrawal" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/finance/tests.py
git commit -m "fix(finance): cancel_distribution checks withdrawal allocations, not the removed FK"
```

---

### Task 6: `get_shareholder_summary` — capital totals and allocation breakdown

**Files:**
- Modify: `backend/apps/finance/services.py:2377-2485` (`ShareholderLedgerService.get_shareholder_summary`)
- Test: `backend/apps/finance/tests.py`

**Interfaces:**
- Produces: `get_shareholder_summary(shareholder_id)` dict gains `capital_returned`, `capital_remaining`; its `"withdrawals"` list entries gain `"allocations": [{"profit_share": id|None, "contribution": id|None, "amount": Decimal}]` and drop `"profit_share_id"`.

- [ ] **Step 1: Write the failing test**

Add to `backend/apps/finance/tests.py` (near the other `get_shareholder_summary`/ledger tests — search for `def test_get_available_balance` to find the right neighborhood, or append at the end of the file):

```python
@pytest.mark.django_db
def test_get_shareholder_summary_includes_capital_totals_and_allocation_breakdown():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("SUMMARY-CAPITAL")
    _seed_distributable()
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("100000.00"), actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    bank = BankAccount.objects.create(name="Summary Bank", opening_balance=Decimal("0.00"))
    ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("500000.00"), date="2026-07-15",
        bank_account=bank, recorded_by=actor,
    )
    cash = CashAccount.objects.create(name="Summary Cash", opening_balance=Decimal("1000000.00"))
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id, amount=Decimal("150000.00"), date="2026-08-01",
        cash_account_id=cash.id, actor=actor,
    )

    summary = ShareholderLedgerService.get_shareholder_summary(shareholder.id)

    assert summary["capital_returned"] == Decimal("50000.00")
    assert summary["capital_remaining"] == Decimal("450000.00")
    withdrawal_entry = summary["withdrawals"][0]
    assert "profit_share_id" not in withdrawal_entry
    allocations = withdrawal_entry["allocations"]
    assert len(allocations) == 2
    profit_alloc = next(a for a in allocations if a["profit_share"] is not None)
    capital_alloc = next(a for a in allocations if a["contribution"] is not None)
    assert profit_alloc["amount"] == Decimal("100000.00")
    assert capital_alloc["amount"] == Decimal("50000.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest apps/finance/tests.py -k test_get_shareholder_summary_includes_capital_totals -v`
Expected: FAIL — `KeyError: 'capital_returned'`.

- [ ] **Step 3: Update `get_shareholder_summary`**

In `backend/apps/finance/services.py`, in `get_shareholder_summary` (`:2377-2485`), after the existing `total_contributed` block (`:2441-2443`), add:

```python
        capital_returned = (
            shareholder.contributions.aggregate(total=Sum("amount_returned"))["total"] or ZERO
        )
        capital_remaining = total_contributed - capital_returned
```

Update the `withdrawals` select_related and serialization (`:2425-2428` and `:2473-2484`). Change:

```python
        withdrawals = list(
            shareholder.withdrawals.select_related("bank_account", "cash_account", "profit_share")
            .order_by("-date", "-id")
        )
```

to:

```python
        withdrawals = list(
            shareholder.withdrawals.select_related("bank_account", "cash_account")
            .prefetch_related("allocations")
            .order_by("-date", "-id")
        )
```

Change the return dict's `total_contributed` line and withdrawals block from:

```python
            "total_contributed": total_contributed,
            "withdrawals": [
                {
                    "id": w.id,
                    "amount": w.amount,
                    "date": w.date,
                    "profit_share_id": w.profit_share_id,
                    "bank_account_id": w.bank_account_id,
                    "cash_account_id": w.cash_account_id,
                    "notes": w.notes,
                }
                for w in withdrawals
            ],
```

to:

```python
            "total_contributed": total_contributed,
            "capital_returned": capital_returned,
            "capital_remaining": capital_remaining,
            "withdrawals": [
                {
                    "id": w.id,
                    "amount": w.amount,
                    "date": w.date,
                    "allocations": [
                        {
                            "profit_share": a.profit_share_id,
                            "contribution": a.contribution_id,
                            "amount": a.amount,
                        }
                        for a in w.allocations.all()
                    ],
                    "bank_account_id": w.bank_account_id,
                    "cash_account_id": w.cash_account_id,
                    "notes": w.notes,
                }
                for w in withdrawals
            ],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest apps/finance/tests.py -k test_get_shareholder_summary_includes_capital_totals -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/finance/tests.py
git commit -m "feat(finance): expose capital_remaining and allocation breakdown on shareholder summary"
```

---

### Task 7: Serializers and viewset

**Files:**
- Modify: `backend/apps/finance/serializers.py:1188-1247` (`ShareholderWithdrawalSerializer`), `:1254-1272` (`ShareholderContributionSerializer`)
- Modify: `backend/apps/finance/views.py:688-693` (`ShareholderWithdrawalViewSet`)
- Test: `backend/apps/finance/tests.py`

**Interfaces:**
- Produces: `ShareholderWithdrawalAllocationSerializer` (new, read-only, fields `profit_share`, `contribution`, `amount`); `ShareholderWithdrawalSerializer` with `allocations` (nested, read-only) instead of `profit_share`; `ShareholderContributionSerializer` gains read-only `amount_returned`, `remaining_capital`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/tests.py`:

```python
@pytest.mark.django_db
def test_shareholder_withdrawal_via_api_allocates_automatically(admin_client):
    shareholder = _make_shareholders([Decimal("100")])[0]
    api_actor = _make_admin_user("API-AUTO")
    _seed_distributable()
    api_distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("100000.00"), actor=api_actor,
    )
    ShareholderDistributionService.validate_distribution(api_distribution.id, api_actor)
    cash_account = CashAccount.objects.create(name="API Auto Cash", opening_balance=Decimal("100000.00"))

    response = admin_client.post(
        "/api/shareholder-withdrawals/",
        {
            "shareholder": shareholder.id,
            "amount": "25000.00",
            "date": "2026-08-01",
            "cash_account": cash_account.id,
        },
    )

    assert response.status_code == 201, response.data
    assert "profit_share" not in response.data
    assert len(response.data["allocations"]) == 1
    assert response.data["allocations"][0]["amount"] == "25000.00"


@pytest.mark.django_db
def test_shareholder_withdrawal_via_api_rejects_amount_exceeding_balance(admin_client):
    shareholder = _make_shareholders([Decimal("100")])[0]
    cash_account = CashAccount.objects.create(
        name="API Reject Cash", opening_balance=Decimal("100000.00")
    )

    response = admin_client.post(
        "/api/shareholder-withdrawals/",
        {
            "shareholder": shareholder.id,
            "amount": "25000.00",
            "date": "2026-08-01",
            "cash_account": cash_account.id,
        },
    )

    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_shareholder_contribution_serializer_exposes_remaining_capital(admin_client):
    shareholder = _make_shareholders([Decimal("100")])[0]
    bank = BankAccount.objects.create(name="Serializer Bank", opening_balance=Decimal("0.00"))
    admin_user = _make_admin_user("SER-CAP")
    ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("100000.00"), date="2026-08-01",
        bank_account=bank, recorded_by=admin_user,
    )

    response = admin_client.get(f"/api/shareholder-contributions/?shareholder={shareholder.id}")

    assert response.status_code == 200, response.data
    row = response.data["results"][0]
    assert row["amount_returned"] == "0.00"
    assert row["remaining_capital"] == "100000.00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/tests.py -k "via_api_allocates_automatically or via_api_rejects_amount_exceeding_balance or serializer_exposes_remaining_capital" -v`
Expected: FAIL — the serializer still requires `profit_share` and rejects the payload with 400 for the wrong reason (missing required field) on the first test, and `amount_returned`/`remaining_capital` are not yet serialized for the third.

- [ ] **Step 3: Update `ShareholderWithdrawalSerializer`**

In `backend/apps/finance/serializers.py`, add a new serializer just above `ShareholderWithdrawalSerializer`:

```python
class ShareholderWithdrawalAllocationSerializer(serializers.ModelSerializer):
    """Read-only - rows are only ever created by
    ShareholderWithdrawalService.record_withdrawal()'s automatic
    allocation (design doc 2026-09-15-capital-associe-retrait-design.md)."""

    class Meta:
        model = ShareholderWithdrawalAllocation
        fields = ["profit_share", "contribution", "amount"]
```

Replace the whole `ShareholderWithdrawalSerializer` class (currently `:1188-1247`) with:

```python
class ShareholderWithdrawalSerializer(serializers.ModelSerializer):
    shareholder_detail = ShareholderBriefSerializer(source="shareholder", read_only=True)
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)
    allocations = ShareholderWithdrawalAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = ShareholderWithdrawal
        fields = [
            "id", "shareholder", "shareholder_detail", "allocations", "amount", "date",
            "bank_account", "cash_account", "notes",
            "recorded_by", "recorded_by_detail", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "recorded_by", "created_at", "updated_at"]

    def validate(self, data):
        bank_account = data.get("bank_account", getattr(self.instance, "bank_account", None))
        cash_account = data.get("cash_account", getattr(self.instance, "cash_account", None))
        if bank_account and cash_account:
            raise serializers.ValidationError(
                "Un seul compte (banque OU caisse) peut etre renseigne."
            )
        if not bank_account and not cash_account:
            raise serializers.ValidationError(
                "Un compte de tresorerie (banque ou caisse) est requis."
            )
        return data

    def create(self, validated_data):
        actor = self.context["request"].user
        bank_account = validated_data.get("bank_account")
        cash_account = validated_data.get("cash_account")
        try:
            return ShareholderWithdrawalService.record_withdrawal(
                shareholder_id=validated_data["shareholder"].id,
                amount=validated_data["amount"],
                date=validated_data["date"],
                actor=actor,
                bank_account_id=bank_account.id if bank_account else None,
                cash_account_id=cash_account.id if cash_account else None,
                notes=validated_data.get("notes", ""),
            )
        except ShareholderWithdrawalError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError(
            "Un retrait enregistre ne peut pas etre modifie."
        )
```

(This drops the `profit_share`/`shareholder` cross-check validation entirely, since there is no client-supplied `profit_share` anymore - allocation happens entirely inside the service.)

Add `ShareholderWithdrawalAllocation` to the `from apps.finance.models import (...)` block at the top of `serializers.py`.

- [ ] **Step 4: Update `ShareholderContributionSerializer`**

In `backend/apps/finance/serializers.py`, in `ShareholderContributionSerializer.Meta.fields` (`:1267-1271`), add the two new read-only fields:

```python
        fields = [
            "id", "shareholder", "shareholder_detail", "amount", "amount_returned",
            "remaining_capital", "date",
            "bank_account", "cash_account", "reference", "notes", "attachment", "proof_url",
            "recorded_by", "recorded_by_detail", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "amount_returned", "remaining_capital", "recorded_by", "created_at", "updated_at"]
```

`remaining_capital` is a model `@property`, not a field, so DRF's `ModelSerializer` won't pick it up automatically for a Decimal-typed output — add it explicitly above `class Meta`:

```python
    remaining_capital = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
```

- [ ] **Step 5: Update `ShareholderWithdrawalViewSet`**

In `backend/apps/finance/views.py`, change lines 688-693 from:

```python
class ShareholderWithdrawalViewSet(viewsets.ModelViewSet):
    queryset = ShareholderWithdrawal.objects.select_related(
        "shareholder", "profit_share", "bank_account", "cash_account", "recorded_by"
    )
    serializer_class = ShareholderWithdrawalSerializer
    filterset_fields = ["shareholder", "profit_share"]
```

to:

```python
class ShareholderWithdrawalViewSet(viewsets.ModelViewSet):
    queryset = ShareholderWithdrawal.objects.select_related(
        "shareholder", "bank_account", "cash_account", "recorded_by"
    ).prefetch_related("allocations")
    serializer_class = ShareholderWithdrawalSerializer
    filterset_fields = ["shareholder"]
```

- [ ] **Step 6: Fix the other existing API test that still posts `"profit_share"`**

In `backend/apps/finance/tests.py`, `test_shareholder_withdrawal_via_api_posts_treasury` (`:4632-4661`): remove the `"profit_share": share.id,` line from the POST payload (it would now be silently ignored by DRF as an unknown field anyway, but the test should reflect the real form shape going forward).

Delete `test_shareholder_withdrawal_via_api_rejects_missing_profit_share` (`:4665-4684`) entirely — its premise ("the API must refuse a withdrawal with no profit_share") is now backwards; `test_shareholder_withdrawal_via_api_allocates_automatically` (added in Step 1 of this task) is its replacement.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/tests.py -k "via_api_allocates_automatically or via_api_rejects_amount_exceeding_balance or serializer_exposes_remaining_capital or via_api_posts_treasury" -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/apps/finance/serializers.py backend/apps/finance/views.py backend/apps/finance/tests.py
git commit -m "feat(finance): drop profit_share from the withdrawal API, expose allocations and remaining_capital"
```

---

### Task 8: Fix remaining broken call sites in `tests.py`

**Files:**
- Modify: `backend/apps/finance/tests.py`

**Interfaces:** none new - this task only restores green tests using signatures/behavior from Tasks 4-7.

- [ ] **Step 1: Run the full finance test file to see what's still red**

Run: `cd backend && python -m pytest apps/finance/tests.py -v 2>&1 | grep -E "FAILED|ERROR"`
Expected: a list including (at least) `test_shareholder_withdrawal_creates_treasury_transaction_and_reduces_remaining_due`, `test_shareholder_withdrawal_rejects_amount_exceeding_remaining_due`, `test_shareholder_withdrawal_requires_a_profit_share`, `test_shareholder_withdrawal_reduces_available_balance_permanently`, `test_shareholder_withdrawal_rejects_amount_exceeding_bank_balance`, `test_shareholder_withdrawal_rejects_profit_share_from_cancelled_distribution`, `test_draft_profit_share_blocks_withdrawal_and_loan`, `test_get_preview_already_distributed_nets_out_partial_withdrawal`.

- [ ] **Step 2: Drop `profit_share_id=...` from simple call sites**

In `backend/apps/finance/tests.py`, remove the `profit_share_id=share.id,` (or equivalent) line from each `record_withdrawal(...)` call in:
- `test_shareholder_withdrawal_creates_treasury_transaction_and_reduces_remaining_due` (`:4395-4402`)
- `test_shareholder_withdrawal_rejects_amount_exceeding_remaining_due` (`:4433-4440`) — also change the assertion context: this test now exercises the *aggregate* ceiling, not a single-share ceiling, so change `amount=Decimal("150000.00")` to stay as-is (it already exceeds the only share's 100000 due, with no capital to fall back on, so it still raises `ShareholderWithdrawalError` for the right structural reason)
- `test_shareholder_withdrawal_reduces_available_balance_permanently` (`:4498-4505`)
- `test_get_preview_already_distributed_nets_out_partial_withdrawal` (`:5004-5011`)

- [ ] **Step 3: Delete `test_shareholder_withdrawal_requires_a_profit_share`**

Remove the whole test (`:4443-4474`) - a withdrawal with no explicit share is now the normal, only way to call `record_withdrawal`; this exact behavior is already covered by `test_withdrawal_within_profit_due_allocates_only_to_profit` in `test_capital_withdrawal.py` (Task 4).

- [ ] **Step 4: Rewrite `test_shareholder_withdrawal_rejects_profit_share_from_cancelled_distribution`**

This test's premise (explicitly targeting a cancelled share via `profit_share_id`) no longer applies - there is no `profit_share_id` parameter to target with. Replace the whole test (`:4570-4613`) with one confirming automatic allocation simply never reaches a cancelled distribution's share, using the same setup:

```python
@pytest.mark.django_db
def test_withdrawal_never_allocates_against_a_cancelled_distributions_share():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("WDRAWCANCEL")
    _seed_distributable()
    cancelled_distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("100000.00"), actor=actor,
    )
    ShareholderDistributionService.validate_distribution(cancelled_distribution.id, actor)
    ShareholderDistributionService.cancel_distribution(cancelled_distribution.id, actor)
    cancelled_share = cancelled_distribution.shares.get(shareholder=shareholder)

    other_distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-08-01", period_end="2026-08-31",
        total_profit=Decimal("50000.00"), actor=actor,
    )
    ShareholderDistributionService.validate_distribution(other_distribution.id, actor)

    cash_account = CashAccount.objects.create(
        name="Gap Cash", opening_balance=Decimal("100000.00")
    )

    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id, amount=Decimal("30000.00"), date="2026-09-01",
        cash_account_id=cash_account.id, actor=actor,
    )

    cancelled_share.refresh_from_db()
    assert cancelled_share.amount_withdrawn == Decimal("0.00")
    assert not ShareholderWithdrawalAllocation.objects.filter(profit_share=cancelled_share).exists()
```

Add `ShareholderWithdrawalAllocation` to `tests.py`'s model imports if not already present from Task 5/6 edits.

- [ ] **Step 5: Fix `test_shareholder_withdrawal_rejects_amount_exceeding_bank_balance`**

Open it (`:4515-4540ish`) and remove its `profit_share_id=...` line the same way as Step 2 (check the exact surrounding lines when editing, since earlier edits in this task may have shifted line numbers - search for the test name instead of relying on the original line range).

- [ ] **Step 6: Fix `test_draft_profit_share_blocks_withdrawal_and_loan`**

In this test (originally `:4893-4928`), remove `profit_share_id=share.id,` from the `record_withdrawal` call, and change the final assertion from:

```python
    assert not ShareholderWithdrawal.objects.filter(profit_share=share).exists()
```

to:

```python
    assert not ShareholderWithdrawalAllocation.objects.filter(profit_share=share).exists()
```

- [ ] **Step 7: Run the full finance test file**

Run: `cd backend && python -m pytest apps/finance/tests.py -v 2>&1 | tail -40`
Expected: PASS for all tests in the file. If anything else is still red, it references `profit_share` somewhere not yet covered - grep for it (`grep -n "profit_share_id=" backend/apps/finance/tests.py`) and apply the same fix pattern (drop the kwarg).

- [ ] **Step 8: Commit**

```bash
git add backend/apps/finance/tests.py
git commit -m "test(finance): update shareholder withdrawal tests for automatic allocation"
```

---

### Task 9: `ShareholderStatementQuery` — capital contribution event

**Files:**
- Modify: `backend/apps/reports/queries/shareholder_statement.py`
- Test: `backend/apps/reports/test_queries.py`

**Interfaces:**
- Produces: a new `"CONTRIBUTION"` credit row type in `ShareholderStatementQuery.run()`'s output.

- [ ] **Step 1: Write the failing test**

Add to `backend/apps/reports/test_queries.py`, right after `test_shareholder_statement_lists_profit_shares_withdrawals_and_loans`:

```python
@pytest.mark.django_db
def test_shareholder_statement_includes_capital_contribution_and_stays_balanced():
    admin_user = _make_admin("SHRSTMTCAP")
    shareholder = Shareholder.objects.create(name="Assoc SHRSTMTCAP", participation_percent=Decimal("100"))
    bank = BankAccount.objects.create(name="Bank SHRSTMTCAP", opening_balance=Decimal("0.00"))
    cash_account = CashAccount.objects.create(
        name="Cash SHRSTMTCAP", opening_balance=Decimal("1000000.00")
    )

    ShareholderContribution.objects.create(
        shareholder=shareholder, amount=Decimal("500000.00"), date="2026-06-01",
        bank_account=bank, recorded_by=admin_user,
    )
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01", period_end="2026-07-31",
        total_profit=Decimal("100000.00"), actor=admin_user,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, admin_user)
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id, amount=Decimal("150000.00"), date="2026-08-01",
        cash_account_id=cash_account.id, actor=admin_user,
    )

    rows = ShareholderStatementQuery.run(shareholder_id=shareholder.id)

    assert [r["type"] for r in rows] == ["CONTRIBUTION", "PROFIT_SHARE", "WITHDRAWAL"]
    assert rows[0]["credit"] == Decimal("500000.00")
    assert rows[-1]["balance"] == ShareholderLedgerService.get_available_balance(shareholder.id)
```

Add `ShareholderContribution` and `ShareholderWithdrawalService` to this test file's imports if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest apps/reports/test_queries.py::test_shareholder_statement_includes_capital_contribution_and_stays_balanced -v`
Expected: FAIL — `rows` has no `"CONTRIBUTION"` entry, and the balance is off by the contribution amount.

- [ ] **Step 3: Add the contribution event**

In `backend/apps/reports/queries/shareholder_statement.py`, add `ShareholderContribution` to the imports:

```python
from apps.finance.models import (
    ShareholderContribution,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
)
```

In `ShareholderStatementQuery.run`, add a query for contributions right after `shares`:

```python
        contributions = ShareholderContribution.objects.filter(shareholder_id=shareholder_id)
```

Add a new entry list in the `entries = (...)` expression, right after the `shares` block and before `withdrawals`:

```python
            + [
                {
                    "date": contribution.date,
                    "type": "CONTRIBUTION",
                    "reference": f"APPORT-{contribution.id}",
                    "debit": None,
                    "credit": contribution.amount,
                    "sort_key": (contribution.date, 0, contribution.id),
                }
                for contribution in contributions
            ]
```

(Same `sort_key` slot `0` as `PROFIT_SHARE` - both are same-day credit events; ties break on id, which is fine since neither type depends on ordering relative to the other on the same date.)

Update the module docstring at the top of the file (currently listing "four event types") to mention the fifth:

```python
# Mirrors CustomerStatementQuery/SupplierStatementQuery's shape (one
# chronological ledger with a running balance) but sourced from the five
# event types that move a shareholder's equity (Task 7 / design doc
# 2026-09-15-capital-associe-retrait-design.md, apps.finance.services
# .ShareholderLedgerService):
#   - a ShareholderProfitShare being attributed (credit: it's now theirs)
#   - a ShareholderContribution (credit: capital they put in, still theirs)
#   - a ShareholderWithdrawal (debit: cash paid out, whatever pool - profit
#     or capital - it was allocated against; see
#     ShareholderWithdrawalAllocation)
#   - a ShareholderLoan where this shareholder is the lender (credit: an
#     IOU from another shareholder, still their equity)
#   - a ShareholderLoan where this shareholder is the borrower (debit: a
#     liability against their equity)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest apps/reports/test_queries.py::test_shareholder_statement_includes_capital_contribution_and_stays_balanced -v`
Expected: PASS.

- [ ] **Step 5: Fix the other broken call sites in the `reports` app**

In `backend/apps/reports/test_queries.py`, `test_shareholder_statement_lists_profit_shares_withdrawals_and_loans` (`:1037-1044`): remove `profit_share_id=share.id,`.

In `backend/apps/reports/test_views.py`, `test_dashboard_summary_includes_shareholders_summary_section` (`:277-284`): remove `profit_share_id=share.id,`.

In `backend/apps/reports/test_production_like_scenario.py` (`:604-611`): remove `profit_share_id=shares["Sidi Mohamed"].id,`. Leave the two `rejected(...)` blocks at `:728-750` untouched - they already omit `profit_share_id` and their assertions (rejection on amount) are unaffected by this change.

- [ ] **Step 6: Run the full reports test suite**

Run: `cd backend && python -m pytest apps/reports/ -v 2>&1 | tail -60`
Expected: PASS across the board.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/reports/queries/shareholder_statement.py backend/apps/reports/test_queries.py backend/apps/reports/test_views.py backend/apps/reports/test_production_like_scenario.py
git commit -m "feat(reports): add capital contributions to the shareholder statement ledger"
```

---

### Task 10: Full backend test suite and recette script

**Files:** none modified - verification only, plus any last stragglers it turns up.

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q 2>&1 | tail -60`
Expected: all green. If anything outside `apps/finance` or `apps/reports` fails, grep the failing test file for `profit_share` and apply the same "drop the kwarg / query via allocations" fix pattern used in Tasks 5-9.

- [ ] **Step 2: Check the recette/production-like seed commands are unaffected**

Run: `cd backend && python manage.py prepare_empty_test_db --help > /dev/null && python manage.py seed_production_like_scenario --help > /dev/null && echo OK`
Expected: `OK` - these commands only reference `ShareholderWithdrawal` in bulk-delete lists (already fine under `CASCADE` from `ShareholderWithdrawalAllocation`, no direct `profit_share=` construction was found in Task 0's investigation). If this step errors, read the traceback - it means one of these commands does construct a `ShareholderWithdrawal` with `profit_share=` somewhere not caught earlier; fix it the same way as Task 3's model change (drop the kwarg, or route through `ShareholderWithdrawalService.record_withdrawal` if it needs the allocation to exist).

- [ ] **Step 3: Run the full recette scenario test end to end**

Run: `cd backend && python -m pytest apps/reports/test_production_like_scenario.py -v`
Expected: PASS - every `report.check(...)` line succeeds (a failure prints its own label, e.g. "13. Retraits / avances", making it easy to trace back to the exact business rule affected).

- [ ] **Step 4: Commit (only if Step 1 or 2 turned up additional fixes)**

```bash
git add -A
git commit -m "test: fix remaining call sites after automatic withdrawal allocation"
```

If nothing needed fixing, skip this commit - there is nothing new to record.

---

### Task 11: Frontend types

**Files:**
- Modify: `frontend/src/modules/finance/types.ts:491-583`

**Interfaces:**
- Produces: `ShareholderWithdrawalAllocation` type; `ShareholderWithdrawal.allocations`; `ShareholderLedgerWithdrawal.allocations`; `ShareholderLedger.capital_returned`/`capital_remaining`.

- [ ] **Step 1: Update the types**

In `frontend/src/modules/finance/types.ts`, replace the `ShareholderWithdrawal` interface (`:491-505`):

```typescript
export interface ShareholderWithdrawalAllocation {
  profit_share: number | null
  contribution: number | null
  amount: string
}

export interface ShareholderWithdrawal {
  id: number
  shareholder: number
  shareholder_detail: ShareholderBrief | null
  allocations: ShareholderWithdrawalAllocation[]
  amount: string
  date: string
  bank_account: number | null
  cash_account: number | null
  notes: string
  recorded_by: number | null
  recorded_by_detail: UserBrief | null
  created_at: string
  updated_at: string
}
```

Add `amount_returned` and `remaining_capital` to `ShareholderContribution` (`:507-522`):

```typescript
export interface ShareholderContribution {
  id: number
  shareholder: number
  shareholder_detail: ShareholderBrief | null
  amount: string
  amount_returned: string
  remaining_capital: string
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

Replace `ShareholderLedgerWithdrawal` (`:549-557`):

```typescript
export interface ShareholderLedgerWithdrawal {
  id: number
  amount: string
  date: string
  allocations: ShareholderWithdrawalAllocation[]
  bank_account_id: number | null
  cash_account_id: number | null
  notes: string
}
```

Update the `ShareholderLedger` interface (`:559-583`) — add two fields and update the comment on `total_contributed`:

```typescript
export interface ShareholderLedger {
  shareholder: {
    id: number
    name: string
    participation_percent: string
    contribution?: string
    is_active: boolean
  }
  total_amount_due: string
  total_withdrawn: string
  remaining_due: string
  // ShareholderLedgerService.get_available_balance(): remaining_due +
  // capital_remaining + loans given (as lender, still receivable) - loans
  // received (as borrower, a liability) - the single number that gates
  // both a withdrawal and lending money to another associate.
  available_balance: string
  // Real cash injected via ShareholderContribution, gross/historical -
  // never decreases even once some of it is returned via a withdrawal.
  total_contributed: string
  // Sum of ShareholderContribution.amount_returned across all of this
  // shareholder's contributions.
  capital_returned: string
  // total_contributed - capital_returned - this is the part of
  // available_balance that comes from capital rather than profit.
  capital_remaining: string
  shares: ShareholderLedgerShare[]
  loans_borrowed: ShareholderLedgerLoan[]
  loans_lent: ShareholderLedgerLoan[]
  net_loan_balance: string
  withdrawals: ShareholderLedgerWithdrawal[]
}
```

- [ ] **Step 2: Run the TypeScript compiler**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: errors in `ShareholderView.vue` (still using `.profit_share`) - this is expected and fixed in Task 12. Confirm the errors are limited to that one file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/modules/finance/types.ts
git commit -m "feat(finance-ui): type the allocation breakdown and capital_remaining"
```

---

### Task 12: `ShareholderView.vue` — form, hint, breakdown, capital card

**Files:**
- Modify: `frontend/src/modules/finance/ShareholderView.vue`
- Modify: `frontend/src/locales/fr.json`, `frontend/src/locales/en.json`, `frontend/src/locales/ar.json`

**Interfaces:**
- Consumes: `ShareholderWithdrawal.allocations`, `ShareholderLedger.capital_remaining` (Task 11).

- [ ] **Step 1: Update the locale files**

In `frontend/src/locales/fr.json`, inside `finance.shareholder.withdrawal` (`:1011-1022`), remove `"profitShare"` and `"selectProfitShare"` and add:

```json
      "withdrawal": {
        "title": "Retrait d'argent de l'associé",
        "shareholder": "Actionnaire",
        "availableBalanceHint": "Solde disponible pour ce retrait",
        "amount": "Montant",
        "date": "Date",
        "accountType": "Type de compte",
        "account": "Compte",
        "record": "Enregistrer le retrait",
        "saveError": "Impossible d'enregistrer ce retrait — vérifiez les champs.",
        "sourceProfitShare": "bénéfices",
        "sourceCapital": "capital"
      },
```

Inside `finance.shareholder.capital` (`:1036-1048`), add `"remaining"`:

```json
      "capital": {
        "title": "Capital",
        "totalContributed": "Capital apporté (total)",
        "remaining": "Capital restant",
        "help": "Argent réellement injecté par l'associé — distinct du bénéfice distribuable.",
        "date": "Date",
        "amount": "Montant",
        "account": "Compte",
        "reference": "Référence",
        "notes": "Note",
        "proof": "Justificatif",
        "viewProof": "Voir",
        "empty": "Aucun apport en capital enregistré pour cet associé."
      },
```

Do the equivalent edit in `frontend/src/locales/en.json` (`:1012-1013` for the removal, same neighborhood for `capital`):

```json
      "withdrawal": {
        "title": "Shareholder withdrawal",
        "shareholder": "Shareholder",
        "availableBalanceHint": "Available balance for this withdrawal",
        "amount": "Amount",
        "date": "Date",
        "accountType": "Account type",
        "account": "Account",
        "record": "Record withdrawal",
        "saveError": "Could not record this withdrawal — check the fields.",
        "sourceProfitShare": "profit",
        "sourceCapital": "capital"
      },
```

(Keep whatever the existing English strings were for the untouched keys - copy them from the current file rather than retyping from scratch, only `profitShare`/`selectProfitShare` are removed and the two new keys added.)

And in `frontend/src/locales/ar.json`, same structural change, Arabic strings for the two new keys (e.g. `"availableBalanceHint": "الرصيد المتاح لهذا السحب"`, `"sourceProfitShare": "الأرباح"`, `"sourceCapital": "رأس المال"`), and `"remaining": "رأس المال المتبقي"` under `capital`.

Do **not** touch the `profit_share_id` keys near line 1665-1669 in any of the three files (audit-log field labels, unrelated).

- [ ] **Step 2: Remove the profit-share picker from the withdrawal form state**

In `frontend/src/modules/finance/ShareholderView.vue`, update the `withdrawalForm` ref (`:335-343`):

```typescript
const withdrawalForm = ref({
  shareholder: '',
  amount: '',
  date: today(),
  account_type: 'cash' as 'bank' | 'cash',
  account_id: '',
  notes: '',
})
```

Remove the `availableSharesForWithdrawal` computed (`:350-355`) entirely - it has no consumer once the picker is gone.

Update `onCreateWithdrawal` (`:359-395`) to drop `profit_share` from both the create payload and the reset object:

```typescript
async function onCreateWithdrawal() {
  savingWithdrawal.value = true
  withdrawalError.value = ''
  try {
    await shareholderWithdrawalResource.create({
      shareholder: Number(withdrawalForm.value.shareholder),
      amount: withdrawalForm.value.amount,
      date: withdrawalForm.value.date,
      bank_account:
        withdrawalForm.value.account_type === 'bank'
          ? Number(withdrawalForm.value.account_id)
          : null,
      cash_account:
        withdrawalForm.value.account_type === 'cash'
          ? Number(withdrawalForm.value.account_id)
          : null,
      notes: withdrawalForm.value.notes,
    })
    withdrawalForm.value = {
      shareholder: '',
      amount: '',
      date: today(),
      account_type: 'cash',
      account_id: '',
      notes: '',
    }
    await loadWithdrawals()
    if (ledger.value) await loadLedger(ledger.value.shareholder.id)
  } catch (e) {
    withdrawalError.value = extractErrorMessage(e, t('finance.shareholder.withdrawal.saveError'))
  } finally {
    savingWithdrawal.value = false
  }
}
```

Simplify `onWithdrawalShareholderChange` (`:453-458`) - it still loads the ledger (now used for the available-balance hint, Step 3), just drop the now-nonexistent `profit_share` reset:

```typescript
async function onWithdrawalShareholderChange() {
  const shareholderId = Number(withdrawalForm.value.shareholder)
  if (shareholderId) await loadLedger(shareholderId)
}
```

Add a small computed for the hint, right after `withdrawalAccountOptions` (`:346-348`):

```typescript
const withdrawalAvailableBalance = computed(() => {
  const shareholderId = Number(withdrawalForm.value.shareholder)
  if (!shareholderId || !ledger.value || ledger.value.shareholder.id !== shareholderId) return null
  return ledger.value.available_balance
})
```

Add a helper to render one withdrawal's allocation breakdown as a short string, near `contributionAccountLabel` (`:421-425`):

```typescript
function withdrawalAllocationSummary(w: ShareholderWithdrawal): string | null {
  const capitalAllocations = w.allocations.filter((a) => a.contribution !== null)
  if (capitalAllocations.length === 0) return null
  const profitTotal = w.allocations
    .filter((a) => a.profit_share !== null)
    .reduce((sum, a) => sum + Number(a.amount), 0)
  const capitalTotal = capitalAllocations.reduce((sum, a) => sum + Number(a.amount), 0)
  const parts = []
  if (profitTotal > 0) parts.push(`${formatMoney(String(profitTotal))} (${t('finance.shareholder.withdrawal.sourceProfitShare')})`)
  parts.push(`${formatMoney(String(capitalTotal))} (${t('finance.shareholder.withdrawal.sourceCapital')})`)
  return parts.join(' + ')
}
```

(Only withdrawals that actually touched capital get a breakdown line - a pure-profit withdrawal, the overwhelming majority, shows nothing extra, matching the existing single-amount display and avoiding clutter.)

- [ ] **Step 3: Update the withdrawal form template**

In the `<template>`, replace the "part de bénéfice" field block (`:995-1010`) with an available-balance hint next to the amount field. Remove the whole:

```html
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="wd_share">
            {{ t('finance.shareholder.withdrawal.profitShare') }}
          </label>
          <select
            id="wd_share"
            v-model="withdrawalForm.profit_share"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.shareholder.withdrawal.selectProfitShare') }}</option>
            <option v-for="share in availableSharesForWithdrawal" :key="share.id" :value="share.id">
              {{ share.period_start }} — {{ share.period_end }} ({{ share.remaining_due }})
            </option>
          </select>
        </div>
```

block, and instead add a hint right after the `wd_shareholder` field's closing `</div>` (after line 994):

```html
        <div v-if="withdrawalAvailableBalance" class="space-y-1.5">
          <p class="text-texte-2 text-sm font-medium">
            {{ t('finance.shareholder.withdrawal.availableBalanceHint') }}
          </p>
          <p class="flex h-12 items-center">
            <MonoValue :value="formatMoney(withdrawalAvailableBalance)" />
          </p>
        </div>
```

- [ ] **Step 4: Show the allocation breakdown in the Retraits history table**

In the withdrawal history table (`:1097-1104`), add the breakdown as a second line under the amount:

```html
            <tr v-for="w in withdrawals" :key="w.id" class="border-ligne border-b last:border-0">
              <td class="px-3 py-2.5">{{ w.shareholder_detail?.name }}</td>
              <td class="px-3 py-2.5">{{ w.date }}</td>
              <td class="px-3 py-2.5 text-end">
                <MonoValue :value="formatMoney(w.amount)" />
                <p v-if="withdrawalAllocationSummary(w)" class="text-texte-3 text-xs">
                  {{ withdrawalAllocationSummary(w) }}
                </p>
              </td>
            </tr>
```

- [ ] **Step 5: Add the "Capital restant" line to the Capital apporté section**

Note: `ledger.value.withdrawals` (`ShareholderLedgerWithdrawal[]`) is fetched by the backend but the Grand livre tab does not currently render a withdrawal table of its own at all — the only withdrawal history table in this page is the one in the Retraits tab, already handled in Step 4. Nothing to change here beyond the capital card below.

In the "Capital apporté" section (`:1200-1209`), add the remaining-capital line next to the existing total:

```html
        <section class="border-ligne mb-5 rounded-xl border p-4">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="text-texte font-semibold">{{ t('finance.shareholder.capital.title') }}</h3>
            <div class="text-end">
              <MonoValue
                class="text-lg font-semibold"
                align="left"
                :value="formatMoney(ledger.total_contributed)"
              />
              <p class="text-texte-3 text-xs">
                {{ t('finance.shareholder.capital.remaining') }}:
                <MonoValue :value="formatMoney(ledger.capital_remaining)" />
              </p>
            </div>
          </div>
          <p class="text-texte-3 mb-3 text-xs">{{ t('finance.shareholder.capital.help') }}</p>
```

(Only the `<h3>`'s sibling changes - the rest of that `<section>`, the contributions table below it, stays untouched.)

- [ ] **Step 6: Run the TypeScript compiler**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/finance/ShareholderView.vue frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json
git commit -m "feat(finance-ui): simplify the withdrawal form and show the profit/capital breakdown"
```

---

### Task 13: Frontend tests

**Files:**
- Modify: `frontend/src/modules/finance/__tests__/ShareholderView.spec.ts`

- [ ] **Step 1: Replace the obsolete profit-share-picker test**

Replace the test `offers a shareholder's withdrawable profit share as soon as they are picked in Retraits, without visiting Grand livre first` (`:430-473`) with a test for the new hint:

```typescript
  it('shows the shareholder\'s available balance as soon as they are picked in Retraits, without visiting Grand livre first', async () => {
    // Bug fix (2026-09-13 audit) still applies to the hint: picking a
    // shareholder directly in Retraits must load their ledger without
    // needing a prior visit to Grand livre.
    fetchShareholderLedger.mockResolvedValue({
      shareholder: { id: 1, name: 'Ahmed', participation_percent: '100.00', is_active: true },
      total_amount_due: '3528000.00',
      total_withdrawn: '0.00',
      remaining_due: '3528000.00',
      available_balance: '3528000.00',
      total_contributed: '0.00',
      capital_returned: '0.00',
      capital_remaining: '0.00',
      shares: [],
      loans_borrowed: [],
      loans_lent: [],
      net_loan_balance: '0.00',
      withdrawals: [],
    })

    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === 'Retraits')!.trigger('click')
    await flushPromises()

    await wrapper.find('#wd_shareholder').setValue('1')
    await flushPromises()

    expect(fetchShareholderLedger).toHaveBeenCalledWith(1)
    expect(wrapper.find('#wd_share').exists()).toBe(false)
    expect(wrapper.text()).toContain('3 528 000 XOF')
  })
```

- [ ] **Step 2: Add a test for the allocation breakdown**

Add a new test near the withdrawal-history rendering (search the file for where `withdrawals` mock data is set up on the `shareholderWithdrawalResource.list` mock, or add a fresh one):

```typescript
  it('shows a profit/capital breakdown only for withdrawals that touched capital', async () => {
    shareholderWithdrawalResource.list.mockResolvedValueOnce({
      count: 2,
      results: [
        {
          id: 1,
          shareholder: 1,
          shareholder_detail: { id: 1, name: 'Ahmed', participation_percent: '100.00', contribution: '0.00' },
          allocations: [
            { profit_share: 10, contribution: null, amount: '500000.00' },
            { profit_share: null, contribution: 20, amount: '200000.00' },
          ],
          amount: '700000.00',
          date: '2026-08-01',
          bank_account: null,
          cash_account: 1,
          notes: '',
          recorded_by: null,
          recorded_by_detail: null,
          created_at: '',
          updated_at: '',
        },
        {
          id: 2,
          shareholder: 1,
          shareholder_detail: { id: 1, name: 'Ahmed', participation_percent: '100.00', contribution: '0.00' },
          allocations: [{ profit_share: 11, contribution: null, amount: '60000.00' }],
          amount: '60000.00',
          date: '2026-08-02',
          bank_account: null,
          cash_account: 1,
          notes: '',
          recorded_by: null,
          recorded_by_detail: null,
          created_at: '',
          updated_at: '',
        },
      ],
    })

    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === 'Retraits')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('700 000 XOF')
    expect(wrapper.text()).toContain('capital')
    // The pure-profit withdrawal (id 2) shows its amount with no breakdown line.
    const rows = wrapper.findAll('tbody tr')
    const secondRow = rows.find((r) => r.text().includes('60 000'))
    expect(secondRow?.text()).not.toContain('capital')
  })
```

Check the exact mock shape/method name used elsewhere in the file for `shareholderWithdrawalResource.list` (search for `emptyList()` and any existing per-test override) and match its conventions rather than assuming `mockResolvedValueOnce` is available if the mock is set up differently (e.g. via a shared `vi.fn()` reassignment) — adapt Step 2's mock wiring to match the file's existing pattern exactly.

- [ ] **Step 3: Run the frontend test file**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ShareholderView.spec.ts`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/modules/finance/__tests__/ShareholderView.spec.ts
git commit -m "test(finance-ui): cover the available-balance hint and allocation breakdown"
```

---

### Task 14: Full suite verification

**Files:** none - verification only.

- [ ] **Step 1: Backend**

Run: `cd backend && python -m pytest -q`
Expected: all green.

- [ ] **Step 2: Frontend unit tests**

Run: `cd frontend && npx vitest run`
Expected: all green.

- [ ] **Step 3: Frontend type check**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Manual smoke test**

Start the dev server (`cd frontend && npm run dev`, backend already running) and, on the Actionnaires/Associés page:
1. Open Grand livre for a shareholder with both a validated profit distribution and a capital contribution.
2. Go to Retraits, pick that shareholder, confirm the "Solde disponible" hint appears (no profit-share dropdown).
3. Withdraw an amount larger than their remaining profit due but smaller than their total available balance.
4. Confirm: the withdrawal succeeds, the history row shows a "X (bénéfices) + Y (capital)" breakdown, and Grand livre's "Capital restant" dropped by exactly Y while "Capital apporté" stayed the same.
5. Try to withdraw more than `profit_share_remaining_due + capital_remaining` for that shareholder (even if another shareholder has spare capital) - confirm it is rejected.

- [ ] **Step 5: Final commit if the smoke test needs any fix**

```bash
git add -A
git commit -m "fix: address issues found in capital-withdrawal manual smoke test"
```

If nothing needed fixing, no commit is needed - the feature is complete.

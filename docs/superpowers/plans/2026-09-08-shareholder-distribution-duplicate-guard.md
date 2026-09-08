# Répartition des bénéfices : anti-doublon + annulation + montant réel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the same real profit from being distributed to shareholders more than once, make the "montant disponible pour répartition" actually shrink as distributions are created, and give managers a way to cancel a mistaken distribution.

**Architecture:** The declarative distribution model stays exactly as it is today (creating/validating a distribution never touches treasury — only a withdrawal does). Three additive changes close the gap: (1) `ShareholderDistributionService.create_distribution` refuses to create a distribution whose period overlaps any existing non-cancelled one; (2) a new `CANCELLED` status (with `cancelled_by`/`cancelled_at`) lets an admin void a mistaken DRAFT or VALIDATED distribution, as long as no withdrawal has touched it yet — this reverses the "Task 7 ruling 2" decision recorded in `ShareholderProfitDistribution`'s docstring, so a new migration grants the `cancel` permission tier back to Admin/Management on the `shareholders` module; (3) `ShareholderProfitPreviewService.get_preview` now subtracts everything already committed to shareholders (`amount_due - amount_withdrawn` on every non-cancelled `ShareholderProfitShare`) from `distributable_result`, and exposes that subtracted amount as `already_distributed` so the UI can show "bénéfice de la période / déjà réparti / reste à répartir" explicitly. `ShareholderLedgerService.get_available_balance` and the dashboard's `remaining_undistributed` are updated to exclude cancelled distributions' shares, so cancelling one actually frees the money back up everywhere it's counted.

**Tech Stack:** Django 5 / DRF (backend/apps/finance, backend/apps/accounts, backend/apps/reports), Vue 3 + TypeScript + vue-i18n (frontend/src/modules/finance), pytest, vitest.

**Spec:** This plan implements the bug report and the 4 decisions confirmed in conversation on 2026-09-08:
1. Keep the declarative model (no treasury movement at distribution creation/validation).
2. Hard-block distribution creation on period overlap with any existing non-cancelled distribution.
3. Add a real `CANCELLED` state (reversing the prior "no cancellation" ruling), blocked once a withdrawal exists against the distribution.
4. Clean up the 3 duplicate distributions already sitting in the Admin/Test Vide environment, after the code fix lands (Task 9, manual — not a coded task).

## Global Constraints

- French-language error messages and UI copy throughout (matches the rest of `backend/apps/finance/services.py` and `frontend/src/locales/fr.json`).
- No hard delete anywhere in this module — `ShareholderProfitDistributionViewSet.destroy()` already raises `MethodNotAllowed`; cancellation is the only way to void a distribution, and it must never delete `ShareholderProfitShare` rows (audit trail).
- Every service method that mutates a distribution wraps its work in `@transaction.atomic` and locks the row with `select_for_update()`, matching `validate_distribution`'s existing pattern.
- Money already committed to shareholders (`amount_due - amount_withdrawn` on a non-cancelled share) must be excluded consistently in exactly three places: `ShareholderLedgerService.get_available_balance`, `ShareholderProfitPreviewService.get_preview`'s `already_distributed`/`distributable_result`, and the dashboard's `shareholders_summary.remaining_undistributed` — all three must use the same `.exclude(distribution__status=ShareholderProfitDistribution.Status.CANCELLED)` filter so a cancelled distribution's money reappears everywhere at once, never partially.
- Backend tests: `docker compose exec -T backend python -m pytest -q --create-db`. Frontend tests: `cd frontend && npx vitest run`.

---

## File Structure

- Modify `backend/apps/finance/models.py` — add `CANCELLED` status + `cancelled_by`/`cancelled_at` fields to `ShareholderProfitDistribution`.
- Create `backend/apps/finance/migrations/0020_shareholderprofitdistribution_cancellation.py` — schema migration for the above (generated via `makemigrations`, verified against this plan's expected shape).
- Create `backend/apps/accounts/migrations/0006_grant_shareholder_cancel_permission.py` — grants the `cancel` permission tier back to Admin/Management on the `shareholders` module.
- Modify `backend/apps/finance/services.py` — overlap guard in `create_distribution`, new `cancel_distribution`, `already_distributed` in `get_preview`, CANCELLED-exclusion in `get_available_balance`.
- Modify `backend/apps/finance/views.py` — new `cancel` action on `ShareholderProfitDistributionViewSet`.
- Modify `backend/apps/finance/serializers.py` — expose `cancelled_by`/`cancelled_by_detail`/`cancelled_at` on `ShareholderProfitDistributionSerializer`.
- Modify `backend/apps/reports/views/dashboard.py` — CANCELLED-exclusion in `shareholders_summary.remaining_undistributed`.
- Modify `backend/apps/finance/tests.py` — new tests for overlap guard, cancellation, and the CANCELLED-exclusion in `get_available_balance`.
- Modify `backend/apps/reports/test_views.py` — new test for `already_distributed`/CANCELLED-exclusion in the dashboard summary.
- Modify `frontend/src/modules/finance/types.ts` — `'CANCELLED'` status, `cancelled_by`/`cancelled_by_detail`/`cancelled_at` fields, `already_distributed` on the preview type.
- Modify `frontend/src/modules/finance/api.ts` — `cancelShareholderDistribution()`.
- Modify `frontend/src/modules/finance/ShareholderView.vue` — "déjà réparti"/"reste à répartir" display, a visible success confirmation after creating a distribution, an "Annuler" button with confirmation, and a CANCELLED badge.
- Modify `frontend/src/locales/fr.json`, `en.json`, `ar.json` — new distribution/preview copy keys.
- Modify `frontend/src/modules/finance/__tests__/ShareholderView.spec.ts` — tests for the new banner line, success message, and cancel flow.

---

### Task 1: Model — CANCELLED status + cancellation fields

**Files:**
- Modify: `backend/apps/finance/models.py:857-907` (`ShareholderProfitDistribution`)
- Create: `backend/apps/finance/migrations/0020_shareholderprofitdistribution_cancellation.py`

**Interfaces:**
- Produces: `ShareholderProfitDistribution.Status.CANCELLED`, `ShareholderProfitDistribution.cancelled_by` (nullable FK to `accounts.User`), `ShareholderProfitDistribution.cancelled_at` (nullable `DateTimeField`) — consumed by Tasks 2-8.

- [ ] **Step 1: Update the model**

Replace the class docstring and `Status` choices, and add the two new fields, in `backend/apps/finance/models.py`:

```python
class ShareholderProfitDistribution(TimeStampedModel):
    """One profit-sharing period: a total company profit figure split
    across active shareholders as of the moment it is created (Task 7,
    client modifications plan).

    Created DRAFT with its ShareholderProfitShare rows already calculated
    (ShareholderDistributionService.create_distribution) so managers can
    review the split before committing to it; `validate` (mirroring
    Invoice's DRAFT -> VALIDATED flow) freezes it by stamping
    validated_by/validated_at.

    CANCELLED (added 2026-09-08, reversing "Task 7 ruling 2" - see the
    2026-09-08 recette bug where the same real profit was distributed
    three times because there was no way to undo a mistake): a DRAFT or
    VALIDATED distribution can be voided by
    ShareholderDistributionService.cancel_distribution as long as no
    ShareholderWithdrawal has ever been recorded against one of its
    shares. Cancelling never deletes the ShareholderProfitShare rows -
    they stay for audit history, but every downstream calculation
    (ShareholderLedgerService.get_available_balance,
    ShareholderProfitPreviewService.get_preview's already_distributed,
    the dashboard's remaining_undistributed) excludes a CANCELLED
    distribution's shares, so the money it wrongly committed becomes
    available again everywhere at once.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        VALIDATED = "VALIDATED", "Validated"
        CANCELLED = "CANCELLED", "Cancelled"

    period_start = models.DateField()
    period_end = models.DateField()
    total_profit = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="shareholder_distributions_created"
    )
    validated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="shareholder_distributions_validated",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="shareholder_distributions_cancelled",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-period_start", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_profit__gt=0),
                name="finance_shareholderprofitdistribution_total_profit_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["status"], name="finance_shrdist_status_idx"),
            models.Index(fields=["period_start", "period_end"], name="finance_shrdist_period_idx"),
        ]

    def __str__(self) -> str:
        return f"Distribution {self.period_start} - {self.period_end}: {self.total_profit}"
```

- [ ] **Step 2: Generate the migration**

Run:
```bash
docker compose exec -T backend python manage.py makemigrations finance
```

Expected: a new file `backend/apps/finance/migrations/0020_*.py` containing an `AlterField` for `status` (new choices) and two `AddField` operations for `cancelled_by` and `cancelled_at`.

- [ ] **Step 3: Rename the generated migration file**

Rename whatever `makemigrations` produced to `backend/apps/finance/migrations/0020_shareholderprofitdistribution_cancellation.py` (matching this app's convention of descriptive migration names, e.g. `0019_retire_transport_expense_category.py`), and update its internal class name if Django auto-named it after the field (`Migration` class name itself doesn't need to change, only the filename and the `dependencies` reference from any later migration, of which there are none yet).

- [ ] **Step 4: Apply the migration and verify**

Run:
```bash
docker compose exec -T backend python manage.py migrate finance
```

Expected: migration `0020` applies cleanly with no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/models.py backend/apps/finance/migrations/0020_shareholderprofitdistribution_cancellation.py
git commit -m "feat(finance): add CANCELLED status to ShareholderProfitDistribution"
```

---

### Task 2: Service — block overlapping-period distributions

**Files:**
- Modify: `backend/apps/finance/services.py:1606-1650` (`ShareholderDistributionService.create_distribution`)
- Test: `backend/apps/finance/tests.py`

**Interfaces:**
- Consumes: `ShareholderProfitDistribution.Status.CANCELLED` (Task 1).
- Produces: `create_distribution` now raises `ShareholderDistributionError` (already imported/used throughout `tests.py`) when the requested `[period_start, period_end]` overlaps any existing distribution whose status is not `CANCELLED`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/tests.py`, right after `test_create_distribution_raises_when_only_inactive_shareholders` (around line 3491):

```python
@pytest.mark.django_db
def test_create_distribution_rejects_exact_duplicate_period():
    """Recette bug (2026-09-08): the exact same period/benefice was
    distributed three times in a row because create_distribution never
    checked for an existing distribution covering the same period -
    shareholders ended up "owed" the same real profit 3x."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("DUP1")
    ShareholderDistributionService.create_distribution(
        period_start="2026-09-08",
        period_end="2026-09-08",
        total_profit=Decimal("9034000.00"),
        actor=actor,
    )

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.create_distribution(
            period_start="2026-09-08",
            period_end="2026-09-08",
            total_profit=Decimal("9034000.00"),
            actor=actor,
        )

    assert ShareholderProfitDistribution.objects.count() == 1


@pytest.mark.django_db
def test_create_distribution_rejects_partially_overlapping_period():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("DUP2")
    ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.create_distribution(
            period_start="2026-07-15",
            period_end="2026-08-15",
            total_profit=Decimal("50000.00"),
            actor=actor,
        )

    assert ShareholderProfitDistribution.objects.count() == 1


@pytest.mark.django_db
def test_create_distribution_allows_adjacent_non_overlapping_period():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("DUP3")
    ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    second = ShareholderDistributionService.create_distribution(
        period_start="2026-08-01",
        period_end="2026-08-31",
        total_profit=Decimal("50000.00"),
        actor=actor,
    )

    assert ShareholderProfitDistribution.objects.count() == 2
    assert second.period_start.isoformat() == "2026-08-01"


@pytest.mark.django_db
def test_create_distribution_ignores_cancelled_distribution_when_checking_overlap():
    """A cancelled distribution must never block re-creating a corrected
    one for the same period (that's the whole point of cancelling a
    mistake)."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("DUP4")
    first = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.cancel_distribution(first.id, actor)

    second = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("120000.00"),
        actor=actor,
    )

    assert ShareholderProfitDistribution.objects.filter(
        status=ShareholderProfitDistribution.Status.DRAFT
    ).count() == 1
    assert second.total_profit == Decimal("120000.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest apps/finance/tests.py -k "overlapping_period or duplicate_period or ignores_cancelled_distribution" -v --create-db`
Expected: FAIL — `test_create_distribution_rejects_exact_duplicate_period` and `_partially_overlapping_period` fail because no `ShareholderDistributionError` is raised (2 distributions get created instead of 1); `_ignores_cancelled_distribution` fails with `AttributeError: cancel_distribution` (doesn't exist yet — expected, Task 3 adds it. For now this test can stay red; it'll be re-run at the end of Task 3).

- [ ] **Step 3: Implement the overlap guard**

In `backend/apps/finance/services.py`, modify `create_distribution` (currently at line 1606):

```python
    @staticmethod
    @transaction.atomic
    def create_distribution(
        period_start, period_end, total_profit, actor
    ) -> ShareholderProfitDistribution:
        """Create a DRAFT distribution and immediately snapshot every
        active shareholder's current participation_percent into a
        ShareholderProfitShare row (percent_snapshot), with
        amount_due = total_profit * percent_snapshot / 100, quantized to
        the cent - so a later edit to Shareholder.participation_percent can
        never retroactively change this distribution's amounts.

        Raises ShareholderDistributionError before creating anything if:
        - the requested period overlaps any existing distribution whose
          status isn't CANCELLED (recette bug, 2026-09-08: the exact same
          period/benefice was distributed three times in a row with no
          guard at all - shareholders ended up "owed" the same real
          profit multiple times);
        - there is no active shareholder at all - a distribution with zero
          shares would otherwise be created (and even validated) while
          distributing nothing to nobody (recette bug, 2026-09-06).
        """
        overlapping_exists = (
            ShareholderProfitDistribution.objects.exclude(
                status=ShareholderProfitDistribution.Status.CANCELLED
            )
            .filter(period_start__lte=period_end, period_end__gte=period_start)
            .exists()
        )
        if overlapping_exists:
            raise ShareholderDistributionError(
                f"Une repartition existe deja pour une periode qui chevauche "
                f"{period_start} - {period_end} (statut different de Annulee) : "
                "impossible d'en creer une autre pour la meme periode."
            )

        active_shareholders = list(Shareholder.objects.filter(is_active=True))
        if not active_shareholders:
            raise ShareholderDistributionError(
                "Aucun actionnaire/associe actif : impossible de creer une "
                "repartition des benefices."
            )

        distribution = ShareholderProfitDistribution.objects.create(
            period_start=period_start,
            period_end=period_end,
            total_profit=total_profit,
            status=ShareholderProfitDistribution.Status.DRAFT,
            created_by=actor,
        )

        for shareholder in active_shareholders:
            percent_snapshot = shareholder.participation_percent
            amount_due = (
                Decimal(str(total_profit)) * percent_snapshot / Decimal("100")
            ).quantize(Decimal("0.01"))
            ShareholderProfitShare.objects.create(
                distribution=distribution,
                shareholder=shareholder,
                percent_snapshot=percent_snapshot,
                amount_due=amount_due,
            )

        return distribution
```

- [ ] **Step 4: Run tests to verify they pass (except the CANCELLED one, pending Task 3)**

Run: `docker compose exec -T backend python -m pytest apps/finance/tests.py -k "overlapping_period or duplicate_period" -v --create-db`
Expected: PASS for `test_create_distribution_rejects_exact_duplicate_period`, `test_create_distribution_rejects_partially_overlapping_period`, `test_create_distribution_allows_adjacent_non_overlapping_period`. `test_create_distribution_ignores_cancelled_distribution_when_checking_overlap` still fails (no `cancel_distribution` yet) — expected until Task 3.

- [ ] **Step 5: Run the full existing distribution test suite to confirm no regression**

Run: `docker compose exec -T backend python -m pytest apps/finance/tests.py -k distribution -v --create-db`
Expected: every pre-existing distribution test still passes (they each use distinct, non-overlapping periods already).

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/finance/tests.py
git commit -m "fix(finance): block creating a shareholder distribution for an already-covered period"
```

---

### Task 3: Service — cancel_distribution

**Files:**
- Modify: `backend/apps/finance/services.py` (add method to `ShareholderDistributionService`, after `validate_distribution` at line 1681)
- Test: `backend/apps/finance/tests.py`

**Interfaces:**
- Consumes: `ShareholderProfitDistribution.Status.CANCELLED`, `.cancelled_by`, `.cancelled_at` (Task 1); `ShareholderWithdrawal` (already imported in services.py).
- Produces: `ShareholderDistributionService.cancel_distribution(distribution_id, actor) -> ShareholderProfitDistribution`, consumed by Task 4 (view action) and by the Task 2 test written above.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/tests.py`, right after `test_validate_distribution_rejects_when_shares_became_empty` (find its end around line 3545, insert after):

```python
@pytest.mark.django_db
def test_cancel_distribution_from_draft():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("CANCEL1")
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    cancelled = ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    assert cancelled.status == ShareholderProfitDistribution.Status.CANCELLED
    assert cancelled.cancelled_by == actor
    assert cancelled.cancelled_at is not None
    # Shares stay for audit history, they're just excluded downstream.
    assert ShareholderProfitShare.objects.filter(distribution=distribution).count() == 1


@pytest.mark.django_db
def test_cancel_distribution_from_validated_releases_available_balance():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("CANCEL2")
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("100000.00")

    ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("0.00")


@pytest.mark.django_db
def test_cancel_distribution_rejects_when_withdrawal_already_recorded():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("CANCEL3")
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    share = distribution.shares.get(shareholder=shareholder)
    cash_account = CashAccount.objects.create(name="Cancel Cash", opening_balance=Decimal("100000.00"))
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("10000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=actor,
    )

    with pytest.raises(ShareholderDistributionError):
        ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    distribution.refresh_from_db()
    assert distribution.status == ShareholderProfitDistribution.Status.VALIDATED


@pytest.mark.django_db
def test_cancel_distribution_is_idempotent():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("CANCEL4")
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.cancel_distribution(distribution.id, actor)
    first_cancelled_at = distribution.cancelled_at

    result = ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    distribution.refresh_from_db()
    assert result.status == ShareholderProfitDistribution.Status.CANCELLED
    assert distribution.cancelled_at == first_cancelled_at
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest apps/finance/tests.py -k cancel_distribution -v --create-db`
Expected: FAIL with `AttributeError: type object 'ShareholderDistributionService' has no attribute 'cancel_distribution'`.

- [ ] **Step 3: Implement cancel_distribution**

In `backend/apps/finance/services.py`, add this method to `ShareholderDistributionService`, immediately after `validate_distribution` (after line 1681, before the `ShareholderWithdrawalError` class):

```python
    @staticmethod
    @transaction.atomic
    def cancel_distribution(distribution_id, actor) -> ShareholderProfitDistribution:
        """Void a DRAFT or VALIDATED distribution (reverses "Task 7 ruling
        2" - see the ShareholderProfitDistribution docstring - after the
        2026-09-08 recette bug where the same real profit was distributed
        three times with no way to undo any of them).

        Refuses to cancel once a ShareholderWithdrawal has been recorded
        against one of its shares - money that has already left treasury
        for a shareholder can't be un-committed by cancelling the
        distribution behind it. Never deletes the ShareholderProfitShare
        rows (audit trail); every downstream calculation
        (ShareholderLedgerService.get_available_balance,
        ShareholderProfitPreviewService.get_preview, the dashboard's
        remaining_undistributed) excludes a CANCELLED distribution's
        shares instead.

        Idempotent: cancelling an already-CANCELLED distribution is a
        no-op that returns it unchanged, mirroring
        validate_distribution's early return for an already-VALIDATED one.
        """
        distribution = ShareholderProfitDistribution.objects.select_for_update().get(
            pk=distribution_id
        )
        if distribution.status == ShareholderProfitDistribution.Status.CANCELLED:
            return distribution

        if ShareholderWithdrawal.objects.filter(
            profit_share__distribution_id=distribution.id
        ).exists():
            raise ShareholderDistributionError(
                "Impossible d'annuler cette repartition : au moins un retrait "
                "a deja ete effectue sur l'une de ses parts."
            )

        distribution.status = ShareholderProfitDistribution.Status.CANCELLED
        distribution.cancelled_by = actor
        distribution.cancelled_at = timezone.now()
        distribution.save(update_fields=["status", "cancelled_by", "cancelled_at", "updated_at"])
        return distribution
```

Note: `test_cancel_distribution_from_validated_releases_available_balance` will only pass once Task 5's `get_available_balance` CANCELLED-exclusion lands — that's expected; it's written now so Task 5's implementation step re-runs and confirms it.

- [ ] **Step 4: Run tests to verify the cancellation-mechanics tests pass**

Run: `docker compose exec -T backend python -m pytest apps/finance/tests.py -k "cancel_distribution_from_draft or rejects_when_withdrawal_already_recorded or cancel_distribution_is_idempotent or ignores_cancelled_distribution" -v --create-db`
Expected: PASS for all four (the `_releases_available_balance` one is deferred to Task 5, run separately below).

Run: `docker compose exec -T backend python -m pytest apps/finance/tests.py -k cancel_distribution_from_validated_releases_available_balance -v --create-db`
Expected: FAIL for now (Task 5 not done yet) — confirms the test is correctly wired to the not-yet-implemented behavior, not a false pass.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/finance/tests.py
git commit -m "feat(finance): add cancel_distribution to void a mistaken shareholder distribution"
```

---

### Task 4: View, serializer, and permission wiring for cancel

**Files:**
- Modify: `backend/apps/finance/views.py:575-602` (`ShareholderProfitDistributionViewSet`)
- Modify: `backend/apps/finance/serializers.py:1048-1091` (`ShareholderProfitDistributionSerializer`)
- Create: `backend/apps/accounts/migrations/0006_grant_shareholder_cancel_permission.py`
- Test: `backend/apps/finance/tests.py`

**Interfaces:**
- Consumes: `ShareholderDistributionService.cancel_distribution` (Task 3).
- Produces: `POST /api/shareholder-distributions/{id}/cancel/`, gated by the existing `HasModulePermission` (module `"shareholders"`, permission tier `"cancel"` — DRF maps `view.action == "cancel"` to that tier via `ACTION_MAP.get(view.action, view.action)`'s default fallback, same mechanism `destroy` already uses).

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/tests.py`, right after `test_distribution_validate_action_via_admin_api` (around line 3520):

```python
@pytest.mark.django_db
def test_distribution_cancel_action_via_admin_api(admin_client):
    _make_shareholders([Decimal("100")])

    created = admin_client.post(
        "/api/shareholder-distributions/",
        {"period_start": "2026-07-01", "period_end": "2026-07-31", "total_profit": "300000.00"},
    )
    assert created.status_code == 201, created.data

    cancelled = admin_client.post(f"/api/shareholder-distributions/{created.data['id']}/cancel/")
    assert cancelled.status_code == 200, cancelled.data
    assert cancelled.data["status"] == "CANCELLED"
    assert cancelled.data["cancelled_by"] is not None
    assert cancelled.data["cancelled_at"] is not None


@pytest.mark.django_db
def test_distribution_cancel_action_rejects_when_withdrawal_exists(admin_client):
    shareholder = _make_shareholders([Decimal("100")])[0]
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    actor = User.objects.create_user(phone="+2220000201", pin="1234", role=admin_role)

    created = admin_client.post(
        "/api/shareholder-distributions/",
        {"period_start": "2026-07-01", "period_end": "2026-07-31", "total_profit": "300000.00"},
    )
    admin_client.post(f"/api/shareholder-distributions/{created.data['id']}/validate/")
    share = ShareholderProfitShare.objects.get(distribution_id=created.data["id"])
    cash_account = CashAccount.objects.create(name="API Cash", opening_balance=Decimal("300000.00"))
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("1000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=actor,
    )

    response = admin_client.post(f"/api/shareholder-distributions/{created.data['id']}/cancel/")

    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_distribution_cancel_action_requires_cancel_permission():
    """Finance role only has view/create on the shareholders module (see
    backend/apps/accounts/migrations/0005_seed_shareholder_permissions.py)
    - it must not be able to cancel a distribution."""
    finance_role = Role.objects.get(name=Role.NAME_FINANCE)
    user = User.objects.create_user(phone="+2220000202", pin="1234", role=finance_role)
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+2220000203", pin="1234", role=admin_role)
    _make_shareholders([Decimal("100")])
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=admin_user,
    )

    client = APIClient()
    client.force_authenticate(user)
    response = client.post(f"/api/shareholder-distributions/{distribution.id}/cancel/")

    assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest apps/finance/tests.py -k distribution_cancel_action -v --create-db`
Expected: FAIL — 404 on the `/cancel/` URL (action doesn't exist yet).

- [ ] **Step 3: Add the cancel view action**

In `backend/apps/finance/views.py`, add to `ShareholderProfitDistributionViewSet` (after the `validate` action, line 602):

```python
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Void a DRAFT or VALIDATED distribution.

        POST /api/shareholder-distributions/{id}/cancel/
        """
        distribution = self.get_object()
        try:
            distribution = ShareholderDistributionService.cancel_distribution(
                distribution.id, request.user
            )
        except ShareholderDistributionError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(
            ShareholderProfitDistributionSerializer(distribution, context={"request": request}).data
        )
```

- [ ] **Step 4: Expose the cancellation fields on the serializer**

In `backend/apps/finance/serializers.py`, modify `ShareholderProfitDistributionSerializer` (line 1048):

```python
class ShareholderProfitDistributionSerializer(serializers.ModelSerializer):
    """docs/Task 7 (client modifications plan).

    Creation is delegated entirely to
    ShareholderDistributionService.create_distribution(): the client only
    ever sends period_start/period_end/total_profit, and the DRAFT
    distribution plus its snapshotted ShareholderProfitShare rows come back
    read-only in `shares`. Like SupplierPaymentSerializer, update() is
    blocked - once created, a distribution moves forward only via the
    dedicated `validate`/`cancel` actions, never a plain PATCH.
    """

    created_by_detail = UserSerializer(source="created_by", read_only=True)
    validated_by_detail = UserSerializer(source="validated_by", read_only=True)
    cancelled_by_detail = UserSerializer(source="cancelled_by", read_only=True)
    shares = ShareholderProfitShareSerializer(many=True, read_only=True)

    class Meta:
        model = ShareholderProfitDistribution
        fields = [
            "id", "period_start", "period_end", "total_profit", "status",
            "created_by", "created_by_detail", "validated_by", "validated_by_detail",
            "validated_at", "cancelled_by", "cancelled_by_detail", "cancelled_at",
            "shares", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "created_by", "validated_by", "validated_at",
            "cancelled_by", "cancelled_at", "created_at", "updated_at",
        ]

    def create(self, validated_data):
        actor = self.context["request"].user
        try:
            return ShareholderDistributionService.create_distribution(
                period_start=validated_data["period_start"],
                period_end=validated_data["period_end"],
                total_profit=validated_data["total_profit"],
                actor=actor,
            )
        except ShareholderDistributionError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError(
            "Une distribution ne peut pas etre modifiee ; utilisez l'action 'valider' ou 'annuler'."
        )
```

- [ ] **Step 5: Grant the `cancel` permission tier back on the shareholders module**

Create `backend/apps/accounts/migrations/0006_grant_shareholder_cancel_permission.py`:

```python
# Reverses "Task 7 ruling 2" (see 0005_seed_shareholder_permissions.py and
# ShareholderProfitDistribution's docstring): after the 2026-09-08 recette
# bug where the same real profit was distributed three times with no way
# to undo any of them, the shareholders module gained a cancel workflow
# (ShareholderDistributionService.cancel_distribution). Admin and
# Management get the "cancel" tier back; Finance stays view/create only,
# unchanged.

from django.db import migrations

ROLES_GAINING_CANCEL = ["Admin", "Management"]


def grant_shareholder_cancel(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for name in ROLES_GAINING_CANCEL:
        try:
            role = Role.objects.get(name=name)
        except Role.DoesNotExist:
            continue
        actions = list(role.permissions.get("shareholders", []))
        if "cancel" not in actions:
            actions.append("cancel")
        role.permissions = {**role.permissions, "shareholders": actions}
        role.save(update_fields=["permissions"])


def revoke_shareholder_cancel(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for name in ROLES_GAINING_CANCEL:
        try:
            role = Role.objects.get(name=name)
        except Role.DoesNotExist:
            continue
        actions = [a for a in role.permissions.get("shareholders", []) if a != "cancel"]
        role.permissions = {**role.permissions, "shareholders": actions}
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_seed_shareholder_permissions"),
        ("finance", "0020_shareholderprofitdistribution_cancellation"),
    ]
    operations = [migrations.RunPython(grant_shareholder_cancel, revoke_shareholder_cancel)]
```

(The `finance` dependency isn't strictly required by Django, but keeps this migration from running before the `CANCELLED` status it's granting permission for actually exists — apply migrations for both apps together.)

- [ ] **Step 6: Apply migrations and run tests**

Run:
```bash
docker compose exec -T backend python manage.py migrate
docker compose exec -T backend python -m pytest apps/finance/tests.py -k distribution_cancel_action -v --create-db
```
Expected: PASS for `test_distribution_cancel_action_via_admin_api`, `test_distribution_cancel_action_rejects_when_withdrawal_exists`, `test_distribution_cancel_action_requires_cancel_permission`.

- [ ] **Step 7: Run the full finance test suite**

Run: `docker compose exec -T backend python -m pytest apps/finance/tests.py -v --create-db`
Expected: all pass (723 previous + new ones from Tasks 2-4; `cancel_distribution_from_validated_releases_available_balance` from Task 3 still red — expected until Task 5).

- [ ] **Step 8: Commit**

```bash
git add backend/apps/finance/views.py backend/apps/finance/serializers.py backend/apps/accounts/migrations/0006_grant_shareholder_cancel_permission.py backend/apps/finance/tests.py
git commit -m "feat(finance): expose a cancel action for shareholder distributions"
```

---

### Task 5: The real fix — distributable_result subtracts what's already committed

**Files:**
- Modify: `backend/apps/finance/services.py:2036-2071` (`ShareholderLedgerService.get_available_balance`), `:2178-2284` (`ShareholderProfitPreviewService.get_preview`)
- Modify: `backend/apps/reports/views/dashboard.py:13-23,229-232` (`shareholders_summary`)
- Test: `backend/apps/finance/tests.py`, `backend/apps/reports/test_views.py`

**Interfaces:**
- Consumes: `ShareholderProfitDistribution.Status.CANCELLED` (Task 1).
- Produces: `ShareholderProfitPreviewService.get_preview()` return dict gains `"already_distributed": Decimal` and `distributable_result` is reduced by it; `ShareholderLedgerService.get_available_balance` and the dashboard's `shareholders_summary["remaining_undistributed"]` both exclude CANCELLED distributions' shares.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/services.py`'s import list at the top of `backend/apps/finance/tests.py` — `ShareholderProfitPreviewService` is not yet imported there. In the `from apps.finance.services import (...)` block (line 36), add `ShareholderProfitPreviewService` alphabetically:

```python
from apps.finance.services import (
    AdvanceConsumptionService,
    ControlledDebtPaymentError,
    ControlledDebtPaymentService,
    FinancePostingService,
    IndirectSettlementService,
    PaymentAllocationError,
    PaymentAllocationService,
    ShareholderDistributionError,
    ShareholderDistributionService,
    ShareholderLedgerService,
    ShareholderLoanError,
    ShareholderLoanService,
    ShareholderParticipationError,
    ShareholderProfitPreviewService,
    ShareholderService,
    ShareholderWithdrawalError,
    ShareholderWithdrawalService,
    TreasuryService,
    TreasuryTransferError,
)
```

Then add these tests to `backend/apps/finance/tests.py`, near `test_get_available_balance_loan_given_increases_loan_received_decreases` (around line 3861):

```python
@pytest.mark.django_db
def test_get_available_balance_excludes_cancelled_distribution_shares():
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("AVAILCANCEL")
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("100000.00")

    ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    assert ShareholderLedgerService.get_available_balance(shareholder.id) == Decimal("0.00")


@pytest.mark.django_db
def test_get_preview_subtracts_already_distributed_from_distributable_result():
    """Recette bug (2026-09-08): distributable_result never moved after
    creating a distribution, because it never subtracted what had already
    been committed to shareholders - the same real profit could be (and
    was) redistributed on top of itself."""
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("PREVIEWCOMMIT")

    before = ShareholderProfitPreviewService.get_preview()
    assert before["already_distributed"] == Decimal("0.00")

    ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )

    after = ShareholderProfitPreviewService.get_preview()
    assert after["already_distributed"] == Decimal("100000.00")
    assert after["distributable_result"] == before["distributable_result"] - Decimal("100000.00")


@pytest.mark.django_db
def test_get_preview_already_distributed_excludes_cancelled_distributions():
    _make_shareholders([Decimal("100")])
    actor = _make_admin_user("PREVIEWCANCEL")
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.cancel_distribution(distribution.id, actor)

    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["already_distributed"] == Decimal("0.00")


@pytest.mark.django_db
def test_get_preview_already_distributed_nets_out_partial_withdrawal():
    """Once part of a distribution has actually been withdrawn, that
    portion has left treasury already (working_capital reflects it) - only
    the still-unwithdrawn remainder must keep reducing distributable_result,
    or it would be subtracted twice."""
    shareholder = _make_shareholders([Decimal("100")])[0]
    actor = _make_admin_user("PREVIEWPARTIAL")
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=actor,
    )
    ShareholderDistributionService.validate_distribution(distribution.id, actor)
    share = distribution.shares.get(shareholder=shareholder)
    cash_account = CashAccount.objects.create(name="Partial Cash", opening_balance=Decimal("100000.00"))
    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholder.id,
        profit_share_id=share.id,
        amount=Decimal("40000.00"),
        date="2026-08-01",
        cash_account_id=cash_account.id,
        actor=actor,
    )

    preview = ShareholderProfitPreviewService.get_preview()

    assert preview["already_distributed"] == Decimal("60000.00")
```

Also add to `backend/apps/reports/test_views.py`, right after `test_dashboard_summary_includes_shareholders_summary_section` (around line 297, before the next test starts at line 303):

```python
@pytest.mark.django_db
def test_dashboard_summary_remaining_undistributed_excludes_cancelled_distribution():
    admin_user = _make_admin("DASHCANCEL")
    Shareholder.objects.create(name="Dash Cancel", participation_percent=Decimal("100"))
    distribution = ShareholderDistributionService.create_distribution(
        period_start="2026-07-01",
        period_end="2026-07-31",
        total_profit=Decimal("100000.00"),
        actor=admin_user,
    )
    ShareholderDistributionService.cancel_distribution(distribution.id, admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/dashboard/summary/")

    assert response.status_code == 200, response.data
    assert response.data["shareholders_summary"]["remaining_undistributed"] == "0.00"
```

Check the top of `backend/apps/reports/test_views.py` already imports `ShareholderDistributionService` and `Shareholder` — if not already present, add them to its existing `from apps.finance.services import (...)` / `from apps.finance.models import (...)` blocks the same way Task 5's finance-side import was added above.

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
docker compose exec -T backend python -m pytest apps/finance/tests.py -k "excludes_cancelled_distribution_shares or already_distributed" -v --create-db
docker compose exec -T backend python -m pytest apps/reports/test_views.py -k remaining_undistributed_excludes_cancelled -v --create-db
```
Expected: FAIL — `already_distributed` KeyError on the preview dict; `get_available_balance` and `remaining_undistributed` still count the cancelled distribution's share.

- [ ] **Step 3: Implement the fix in get_available_balance**

In `backend/apps/finance/services.py`, modify `ShareholderLedgerService.get_available_balance` (line 2036):

```python
    @staticmethod
    def get_available_balance(shareholder_id) -> Decimal:
        """Single source of truth for how much a shareholder can withdraw
        or lend out right now (design doc
        2026-08-26-benefices-associes-refinement-design.md):

            available_balance =
                profit_share_remaining_due
              + loans_given_remaining
              - loans_received_remaining

        Lending money to another associate is a receivable - it stays this
        shareholder's equity, just claimed via an IOU instead of sitting in
        remaining_due, so it *adds* to the balance. Receiving an advance is
        a liability that must be repaid, so it *subtracts*. Called by both
        ShareholderWithdrawalService.record_withdrawal and
        ShareholderLoanService.create_loan so a withdrawal and a loan can
        never be validated against two different numbers.

        A CANCELLED distribution's shares are excluded (2026-09-08 fix):
        cancelling a mistaken distribution must release the balance it
        wrongly granted, everywhere that balance is used.
        """
        shares_remaining = (
            ShareholderProfitShare.objects.filter(shareholder_id=shareholder_id)
            .exclude(distribution__status=ShareholderProfitDistribution.Status.CANCELLED)
            .aggregate(total=Sum(F("amount_due") - F("amount_withdrawn")))["total"]
            or ZERO
        )
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
        return shares_remaining + loans_given_remaining - loans_received_remaining
```

- [ ] **Step 4: Implement already_distributed in get_preview**

In `backend/apps/finance/services.py`, modify `ShareholderProfitPreviewService.get_preview` (the `working_capital`/`distributable_result` block starting at line 2240):

```python
        # Client modifications (2026-09-04, third pass - confirmed bug
        # during actual recette testing): working_capital["total"] now ADDS
        # open debts (see WorkingCapitalService), so "resultat distribuable
        # apres dettes et capital" must subtract them back out explicitly,
        # term by term, to reach the real distributable amount - written
        # out rather than simplified so the formula stays legible if any
        # one term changes later.
        working_capital = WorkingCapitalService.get_working_capital()

        # Recette bug (2026-09-08): the same real profit was distributed
        # three times because distributable_result never subtracted what
        # had already been committed to shareholders via an earlier
        # distribution - creating (or validating) a distribution never
        # touches treasury (the declarative model is intentional, see
        # ShareholderDistributionService's docstrings), so
        # working_capital["total"] still contains that money right up
        # until an actual ShareholderWithdrawal happens. already_distributed
        # is exactly the liability side of that: every non-cancelled
        # ShareholderProfitShare's still-unwithdrawn amount, company-wide,
        # not scoped by date_from/date_to (same "current outstanding
        # snapshot" contract as working_capital itself).
        already_distributed = (
            ShareholderProfitShare.objects.exclude(
                distribution__status=ShareholderProfitDistribution.Status.CANCELLED
            )
            .aggregate(total=Sum(F("amount_due") - F("amount_withdrawn")))["total"]
            or ZERO
        )
        distributable_result = (
            working_capital["total"]
            - working_capital["supplier_debt_total"]
            - working_capital["transporter_debt_total"]
            - working_capital["other_debts"]
            - working_capital["capital"]
            - already_distributed
        )
```

And update the returned dict (currently ending at line 2273-2284) to include the new field:

```python
        return {
            "period_start": date_from,
            "period_end": date_to,
            "current_profit": current_profit,
            "operational_profit": operational_profit,
            "general_expenses_paid": general_expenses_paid,
            "net_profit": net_profit,
            "total_company_absorbed_loss": total_company_absorbed_loss,
            "working_capital": working_capital,
            "already_distributed": already_distributed,
            "distributable_result": distributable_result,
            "shareholders": shareholders,
        }
```

- [ ] **Step 5: Implement the fix in the dashboard's remaining_undistributed**

In `backend/apps/reports/views/dashboard.py`, add `ShareholderProfitDistribution` to the existing `from apps.finance.models import (...)` block (line 13):

```python
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
    TransportPayment,
    TreasuryTransaction,
)
```

Then modify `shareholders_summary` (line 229):

```python
            "remaining_undistributed": ShareholderProfitShare.objects.exclude(
                distribution__status=ShareholderProfitDistribution.Status.CANCELLED
            ).aggregate(
                total=Sum(F("amount_due") - F("amount_withdrawn"))
            )["total"]
            or ZERO,
```

- [ ] **Step 6: Run all the new and previously-deferred tests**

Run:
```bash
docker compose exec -T backend python -m pytest apps/finance/tests.py -k "excludes_cancelled_distribution_shares or already_distributed or cancel_distribution_from_validated_releases_available_balance" -v --create-db
docker compose exec -T backend python -m pytest apps/reports/test_views.py -k "remaining_undistributed_excludes_cancelled or distributable_result" -v --create-db
```
Expected: PASS for every test listed, including the Task 3 test that was deliberately left red (`cancel_distribution_from_validated_releases_available_balance`).

- [ ] **Step 7: Run the complete backend test suite**

Run: `docker compose exec -T backend python -m pytest -q --create-db`
Expected: all tests pass (baseline 723 + ~14 new ones from this plan).

- [ ] **Step 8: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/reports/views/dashboard.py backend/apps/finance/tests.py backend/apps/reports/test_views.py
git commit -m "fix(finance): distributable_result now subtracts profit already committed to shareholders"
```

---

### Task 6: Frontend — types and API client

**Files:**
- Modify: `frontend/src/modules/finance/types.ts:435,450-464,608-632`
- Modify: `frontend/src/modules/finance/api.ts:401-409`

**Interfaces:**
- Consumes: the backend response shapes from Tasks 4-5 (`cancelled_by`/`cancelled_by_detail`/`cancelled_at` on a distribution, `already_distributed` on the preview, `'CANCELLED'` as a possible status).
- Produces: `ShareholderDistributionStatus` including `'CANCELLED'`; `ShareholderProfitDistribution.cancelled_by`/`cancelled_by_detail`/`cancelled_at`; `ShareholderProfitPreview.already_distributed`; `cancelShareholderDistribution(distributionId): Promise<ShareholderProfitDistribution>` — consumed by Tasks 7-8.

- [ ] **Step 1: Update types.ts**

In `frontend/src/modules/finance/types.ts`, change line 435:

```typescript
export type ShareholderDistributionStatus = 'DRAFT' | 'VALIDATED' | 'CANCELLED'
```

And the `ShareholderProfitDistribution` interface (lines 450-464):

```typescript
export interface ShareholderProfitDistribution {
  id: number
  period_start: string
  period_end: string
  total_profit: string
  status: ShareholderDistributionStatus
  created_by: number | null
  created_by_detail: UserBrief | null
  validated_by: number | null
  validated_by_detail: UserBrief | null
  validated_at: string | null
  cancelled_by: number | null
  cancelled_by_detail: UserBrief | null
  cancelled_at: string | null
  shares: ShareholderProfitShare[]
  created_at: string
  updated_at: string
}
```

And `ShareholderProfitPreview` (lines 608-632), adding `already_distributed` right before `distributable_result`:

```typescript
export interface ShareholderProfitPreview {
  period_start: string | null
  period_end: string | null
  current_profit: string
  operational_profit: string
  general_expenses_paid: string
  net_profit: string
  total_company_absorbed_loss: string
  working_capital: WorkingCapital
  // Sum of amount_due - amount_withdrawn across every non-cancelled
  // ShareholderProfitShare, company-wide (recette fix, 2026-09-08):
  // money already committed to shareholders via an earlier distribution,
  // even if not yet withdrawn - already subtracted into
  // distributable_result below, surfaced here so the distribution form
  // can show "deja reparti" / "reste a repartir" explicitly instead of a
  // figure that silently never moves.
  already_distributed: string
  distributable_result: string
  shareholders: ShareholderProfitPreviewShare[]
}
```

- [ ] **Step 2: Add cancelShareholderDistribution to api.ts**

In `frontend/src/modules/finance/api.ts`, add right after `validateShareholderDistribution` (line 409):

```typescript
// backend/apps/finance/services.py ShareholderDistributionService.cancel_distribution()
// is the sole authority on this transition (DRAFT/VALIDATED -> CANCELLED,
// stamps cancelled_by/cancelled_at, refuses if a withdrawal already
// exists against one of the distribution's shares) - this just posts the
// request.
export function cancelShareholderDistribution(
  distributionId: number,
): Promise<ShareholderProfitDistribution> {
  return apiClient
    .post<ShareholderProfitDistribution>(`/shareholder-distributions/${distributionId}/cancel/`)
    .then((r) => r.data)
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: no new type errors (the `ShareholderView.vue` template doesn't reference the new fields yet, so nothing should break; if it flags the `distributionResource`/mocked API test file for a missing `cancelShareholderDistribution` export, that's expected and fixed in Task 8).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/modules/finance/types.ts frontend/src/modules/finance/api.ts
git commit -m "feat(finance): add CANCELLED status and cancelShareholderDistribution to the frontend API layer"
```

---

### Task 7: Frontend — "déjà réparti / reste à répartir" + creation success feedback

**Files:**
- Modify: `frontend/src/modules/finance/ShareholderView.vue` (banner section ~433-457, `onCreateDistribution` ~205-225, template ~560-575)
- Modify: `frontend/src/locales/fr.json:1014-1018`, `en.json`, `ar.json` (preview block)
- Test: `frontend/src/modules/finance/__tests__/ShareholderView.spec.ts`

**Interfaces:**
- Consumes: `preview.already_distributed` (Task 6).
- Produces: a visible "déjà réparti" line in the preview banner whenever it's non-zero, and a dismissable success confirmation (period, amount, per-shareholder breakdown) shown right after `onCreateDistribution` succeeds.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/modules/finance/__tests__/ShareholderView.spec.ts`, right after the `it('shows distributable_result ...')` test (after line 167):

```typescript
  // Recette bug (2026-09-08): the banner never showed what had already
  // been committed to shareholders, so a manager had no way to tell the
  // displayed distributable_result already accounted for an earlier
  // distribution (it looked "stuck" instead).
  it('shows already_distributed in the preview banner when non-zero', async () => {
    fetchShareholderProfitPreview.mockResolvedValue({
      period_start: '2026-08-01',
      period_end: null,
      current_profit: '850000.00',
      operational_profit: '850000.00',
      general_expenses_paid: '100000.00',
      net_profit: '750000.00',
      working_capital: {
        capital: '250000.00',
        treasury_available: '600000.00',
        customer_receivables: '150000.00',
        supplier_debt_total: '0.00',
        transporter_debt_total: '0.00',
        other_debts: '0.00',
        gross: '750000.00',
        total: '750000.00',
      },
      already_distributed: '100000.00',
      distributable_result: '400000.00',
      shareholders: [
        {
          shareholder_id: 1,
          name: 'Ahmed',
          participation_percent: '80.00',
          indicative_share: '320000.00',
        },
      ],
    })

    const wrapper = mount(ShareholderView)
    await flushPromises()

    const banner = wrapper.findAll('.border-ecart').at(0)
    expect(banner!.text()).toContain('100 000 XOF')
  })

  it('does not show the already-distributed line when nothing has been distributed yet', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    expect(wrapper.find('[data-test="preview-already-distributed"]').exists()).toBe(false)
  })

  // Bug report (2026-09-08): creating a distribution gave no visible
  // confirmation at all, only a silently auto-expanded row easy to miss.
  it('shows a visible success confirmation with the per-shareholder breakdown after creating a distribution', async () => {
    shareholderDistributionResourceCreate.mockResolvedValue({
      id: 42,
      period_start: '2026-08-01',
      period_end: '2026-08-31',
      total_profit: '500000.00',
      status: 'DRAFT',
      shares: [
        {
          id: 1,
          distribution: 42,
          shareholder: 1,
          shareholder_detail: { id: 1, name: 'Ahmed' },
          percent_snapshot: '80.00',
          amount_due: '400000.00',
          amount_withdrawn: '0.00',
          remaining_due: '400000.00',
        },
      ],
    })
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Répartition des bénéfices')!
      .trigger('click')
    await flushPromises()
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    const success = wrapper.find('[data-test="distribution-success"]')
    expect(success.exists()).toBe(true)
    expect(success.text()).toContain('2026-08-01')
    expect(success.text()).toContain('500 000 XOF')
    expect(success.text()).toContain('Ahmed')
    expect(success.text()).toContain('400 000 XOF')
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run -t "already_distributed|already-distributed line|success confirmation"`
Expected: FAIL — `already_distributed` isn't rendered anywhere, and `[data-test="distribution-success"]` doesn't exist.

- [ ] **Step 3: Add the already_distributed line to the banner**

In `frontend/src/modules/finance/ShareholderView.vue`, modify the preview banner block (lines 440-457):

```vue
    <div v-if="preview" class="border-ecart bg-ecart-tint rounded-xl border p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <Badge variant="transit">{{ t('finance.shareholder.preview.badge') }}</Badge>
          <p class="text-texte-2 text-sm">{{ t('finance.shareholder.preview.notice') }}</p>
        </div>
        <MonoValue
          class="text-lg font-semibold"
          :value="formatMoney(preview.distributable_result)"
        />
      </div>
      <p
        v-if="Number(preview.already_distributed) > 0"
        data-test="preview-already-distributed"
        class="text-texte-2 mt-1 text-sm"
      >
        {{ t('finance.shareholder.preview.alreadyDistributed') }}:
        <MonoValue class="inline" :value="formatMoney(preview.already_distributed)" />
      </p>
      <div v-if="preview.shareholders.length" class="mt-3 flex flex-wrap gap-4">
        <div v-for="row in preview.shareholders" :key="row.shareholder_id" class="text-sm">
          <span class="text-texte-2">{{ row.name }} ({{ row.participation_percent }}%):</span>
          <MonoValue class="ms-1 inline" :value="formatMoney(row.indicative_share)" />
        </div>
      </div>
    </div>
```

- [ ] **Step 4: Add the success confirmation after creating a distribution**

In `frontend/src/modules/finance/ShareholderView.vue`, add a new ref near `distributionError` (line 180):

```typescript
const distributionError = ref('')
const distributionSuccess = ref<ShareholderProfitDistribution | null>(null)
```

Modify `onCreateDistribution` (lines 205-225):

```typescript
async function onCreateDistribution() {
  if (activeShareholders.value.length === 0) {
    distributionError.value = t('finance.shareholder.distribution.noActiveShareholder')
    return
  }
  savingDistribution.value = true
  distributionError.value = ''
  distributionSuccess.value = null
  try {
    const created = await shareholderDistributionResource.create(distributionForm.value)
    distributionForm.value = { period_start: today(), period_end: today(), total_profit: '' }
    expandedDistributionId.value = created.id
    distributionSuccess.value = created
    await loadDistributions()
    await loadPreview()
  } catch (e) {
    distributionError.value = extractErrorMessage(
      e,
      t('finance.shareholder.distribution.saveError'),
    )
  } finally {
    savingDistribution.value = false
  }
}
```

(`loadPreview` is called again after a successful create so the banner's `already_distributed`/`distributable_result` reflect the just-created distribution immediately, without a full page reload.)

Add the success banner in the template, right after the `distributionError` paragraph (line 564):

```vue
      <p v-if="distributionError" class="text-critique mb-3 text-sm">{{ distributionError }}</p>
      <div
        v-if="distributionSuccess"
        data-test="distribution-success"
        class="border-livre bg-livre-tint text-livre-texte mb-3 rounded-lg border p-3 text-sm"
      >
        <p class="font-medium">
          {{
            t('finance.shareholder.distribution.createdSuccess', {
              start: distributionSuccess.period_start,
              end: distributionSuccess.period_end,
              amount: formatMoney(distributionSuccess.total_profit),
            })
          }}
        </p>
        <ul class="mt-1.5 space-y-0.5">
          <li v-for="share in distributionSuccess.shares" :key="share.id">
            {{ share.shareholder_detail?.name }}:
            <MonoValue class="inline" :value="formatMoney(share.amount_due)" />
          </li>
        </ul>
      </div>
```

- [ ] **Step 5: Add the i18n keys**

In `frontend/src/locales/fr.json`, modify the `preview` block (lines 1014-1018):

```json
      "preview": {
        "badge": "Indicatif",
        "notice": "Montant disponible pour répartition après dettes et capital",
        "summaryLabel": "Résultat distribuable proposé",
        "alreadyDistributed": "Déjà réparti (non retiré)"
      }
```

And add `createdSuccess` to the `distribution` block (after `"saveError"` on line 956):

```json
        "saveError": "Impossible de créer cette répartition — vérifiez les champs.",
        "createdSuccess": "Répartition créée pour la période {start} — {end} : {amount} répartis entre les associés."
```

In `frontend/src/locales/en.json`, the `preview` block:

```json
      "preview": {
        "badge": "Indicative",
        "notice": "Amount available for distribution after debts and capital",
        "summaryLabel": "Proposed distributable result",
        "alreadyDistributed": "Already distributed (not withdrawn)"
      }
```

(Confirm the exact existing `badge`/`notice`/`summaryLabel` English wording by reading `en.json` before editing — copy it verbatim and only add `alreadyDistributed`.)

And `distribution.createdSuccess` in `en.json`:

```json
        "saveError": "Could not create this distribution — check the fields.",
        "createdSuccess": "Distribution created for period {start} — {end}: {amount} split among shareholders."
```

In `frontend/src/locales/ar.json`, the equivalent Arabic additions (read the existing `preview`/`distribution` blocks first to match tone, then add):

```json
      "preview": {
        "badge": "إرشادي",
        "notice": "المبلغ المتاح للتوزيع بعد الديون ورأس المال",
        "summaryLabel": "النتيجة القابلة للتوزيع المقترحة",
        "alreadyDistributed": "تم توزيعه بالفعل (غير مسحوب)"
      }
```

```json
        "saveError": "تعذر إنشاء هذا التوزيع — تحقق من الحقول.",
        "createdSuccess": "تم إنشاء توزيع للفترة {start} — {end}: تم توزيع {amount} على الشركاء."
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run frontend/src/modules/finance/__tests__/ShareholderView.spec.ts`
Expected: all pass, including the pre-existing tests (the added `await loadPreview()` call in `onCreateDistribution` means `fetchShareholderProfitPreview` is called an extra time after create — check `test('creates a distribution using the distributable_result default when submitted unchanged')` still passes since it only asserts what `create` was called with, not call counts).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/finance/ShareholderView.vue frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json frontend/src/modules/finance/__tests__/ShareholderView.spec.ts
git commit -m "feat(finance): show already-distributed amount and a success confirmation on the distributions tab"
```

---

### Task 8: Frontend — cancel button, confirmation, and CANCELLED badge

**Files:**
- Modify: `frontend/src/modules/finance/ShareholderView.vue` (imports, `onCancelDistribution`, template rows ~653-676)
- Modify: `frontend/src/locales/fr.json`, `en.json`, `ar.json` (distribution block)
- Test: `frontend/src/modules/finance/__tests__/ShareholderView.spec.ts`

**Interfaces:**
- Consumes: `cancelShareholderDistribution` (Task 6).
- Produces: an "Annuler" button per distribution row (hidden once CANCELLED), a `window.confirm` guard, a CANCELLED badge, and the backend's rejection message surfaced via the existing `distributionError` mechanism.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/modules/finance/__tests__/ShareholderView.spec.ts`. First, add `cancelShareholderDistribution` to the mocked `../api` module (line 49-69):

```typescript
const cancelShareholderDistribution = vi.fn()

vi.mock('../api', () => ({
  shareholderResource: {
    list: (...args: unknown[]) => shareholderResourceList(...args),
    create: vi.fn(),
    update: vi.fn(),
  },
  shareholderLoanResource: { list: vi.fn(async () => emptyList()) },
  shareholderWithdrawalResource: { list: vi.fn(async () => emptyList()) },
  shareholderDistributionResource: {
    list: vi.fn(async () => emptyList()),
    create: (payload: Record<string, unknown>) => shareholderDistributionResourceCreate(payload),
  },
  shareholderContributionResource: {
    list: (...args: unknown[]) => shareholderContributionResourceList(...args),
  },
  fetchShareholderLedger: (...args: unknown[]) => fetchShareholderLedger(...args),
  fetchShareholderProfitPreview: (...args: unknown[]) => fetchShareholderProfitPreview(...args),
  validateShareholderDistribution: vi.fn(),
  cancelShareholderDistribution: (...args: unknown[]) => cancelShareholderDistribution(...args),
  recordShareholderLoanRepayment: vi.fn(),
  createShareholderContribution: vi.fn(),
}))
```

Then add a test near the end of the `describe` block:

```typescript
  it('cancels a distribution after confirmation and refreshes the list', async () => {
    const listMock = vi.fn(async () => ({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 7,
          period_start: '2026-07-01',
          period_end: '2026-07-31',
          total_profit: '100000.00',
          status: 'DRAFT',
          shares: [],
        },
      ],
    }))
    vi.doMock('../api', async (importOriginal) => {
      const actual = await importOriginal<typeof import('../api')>()
      return actual
    })
    // Re-point the already-mocked resource's list() for this test only.
    const { shareholderDistributionResource } = await import('../api')
    shareholderDistributionResource.list = listMock
    cancelShareholderDistribution.mockResolvedValue({
      id: 7,
      status: 'CANCELLED',
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    const wrapper = mount(ShareholderView)
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Répartition des bénéfices')!
      .trigger('click')
    await flushPromises()

    const cancelButton = wrapper.find('[data-test="cancel-distribution-7"]')
    expect(cancelButton.exists()).toBe(true)
    await cancelButton.trigger('click')
    await flushPromises()

    expect(cancelShareholderDistribution).toHaveBeenCalledWith(7)
    expect(listMock).toHaveBeenCalled()
  })

  it('shows the backend error when cancellation is rejected (a withdrawal already exists)', async () => {
    const { shareholderDistributionResource } = await import('../api')
    shareholderDistributionResource.list = vi.fn(async () => ({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 8,
          period_start: '2026-07-01',
          period_end: '2026-07-31',
          total_profit: '100000.00',
          status: 'VALIDATED',
          shares: [],
        },
      ],
    }))
    cancelShareholderDistribution.mockRejectedValue({
      response: { data: { detail: "Impossible d'annuler cette repartition." } },
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    const wrapper = mount(ShareholderView)
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Répartition des bénéfices')!
      .trigger('click')
    await flushPromises()

    await wrapper.find('[data-test="cancel-distribution-8"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain("Impossible d'annuler cette repartition.")
  })
```

(These two tests mutate the shared mocked module's `list` per-test rather than adding another top-level mock function, since the distributions list needs different fixtures per test — check this pattern compiles against the project's vitest/mock setup; if `shareholderDistributionResource.list` isn't reassignable because the mock factory returns frozen objects, instead add a dedicated `shareholderDistributionResourceList = vi.fn(async () => emptyList())` at the top alongside the other list mocks, wire it into the `vi.mock('../api', ...)` factory's `list: (...args) => shareholderDistributionResourceList(...args)`, and call `.mockResolvedValueOnce(...)` per test — mirror exactly how `shareholderResourceList` is already done for the shareholders list.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run -t "cancels a distribution|cancellation is rejected"`
Expected: FAIL — no `data-test="cancel-distribution-*"` element exists yet, `cancelShareholderDistribution` isn't imported/called by the component.

- [ ] **Step 3: Implement the cancel button and handler**

In `frontend/src/modules/finance/ShareholderView.vue`, add the import (line 22, alongside `validateShareholderDistribution`):

```typescript
import {
  cancelShareholderDistribution,
  fetchShareholderLedger,
  fetchShareholderProfitPreview,
  recordShareholderLoanRepayment,
  shareholderContributionResource,
  shareholderDistributionResource,
  shareholderLoanResource,
  shareholderResource,
  shareholderWithdrawalResource,
  validateShareholderDistribution,
} from './api'
```

Add `onCancelDistribution` right after `onValidateDistribution` (line 237):

```typescript
async function onCancelDistribution(distribution: ShareholderProfitDistribution) {
  if (!window.confirm(t('finance.shareholder.distribution.cancelConfirm'))) return
  try {
    await cancelShareholderDistribution(distribution.id)
    await loadDistributions()
    await loadPreview()
  } catch (e) {
    distributionError.value = extractErrorMessage(
      e,
      t('finance.shareholder.distribution.cancelError'),
    )
  }
}
```

- [ ] **Step 4: Update the template — badge and buttons**

In `frontend/src/modules/finance/ShareholderView.vue`, modify the distributions table row (lines 662-675):

```vue
                <td class="px-3 py-2.5">
                  <Badge
                    :variant="
                      d.status === 'VALIDATED' ? 'livre' : d.status === 'CANCELLED' ? 'neutre' : 'transit'
                    "
                  >
                    {{ t(`finance.shareholder.distribution.statusValues.${d.status}`) }}
                  </Badge>
                </td>
                <td class="px-3 py-2.5 text-end">
                  <Button
                    v-if="d.status === 'DRAFT'"
                    variant="ghost"
                    @click.stop="onValidateDistribution(d)"
                  >
                    {{ t('finance.shareholder.distribution.validate') }}
                  </Button>
                  <Button
                    v-if="d.status !== 'CANCELLED'"
                    :data-test="`cancel-distribution-${d.id}`"
                    variant="danger"
                    @click.stop="onCancelDistribution(d)"
                  >
                    {{ t('finance.shareholder.distribution.cancel') }}
                  </Button>
                </td>
```

- [ ] **Step 5: Add the i18n keys**

In `frontend/src/locales/fr.json`, add to the `distribution` block (after `"validate": "Valider",` on line 951):

```json
        "validate": "Valider",
        "cancel": "Annuler",
        "cancelConfirm": "Annuler cette répartition ? Les parts déjà créditées aux associés seront retirées si aucun retrait n'a encore été effectué dessus.",
        "cancelError": "Impossible d'annuler cette répartition.",
```

Add the `CANCELLED` status label to `statusValues` (line 947-950):

```json
        "statusValues": {
          "DRAFT": "Brouillon",
          "VALIDATED": "Validée",
          "CANCELLED": "Annulée"
        },
```

Mirror both additions in `en.json`:

```json
        "validate": "Validate",
        "cancel": "Cancel",
        "cancelConfirm": "Cancel this distribution? Shares already credited to shareholders will be withdrawn if no withdrawal has been recorded against them yet.",
        "cancelError": "Could not cancel this distribution.",
```

```json
        "statusValues": {
          "DRAFT": "Draft",
          "VALIDATED": "Validated",
          "CANCELLED": "Cancelled"
        },
```

And in `ar.json`:

```json
        "validate": "مصادقة",
        "cancel": "إلغاء",
        "cancelConfirm": "إلغاء هذا التوزيع؟ ستُسحب الحصص التي أُضيفت بالفعل للشركاء إذا لم يتم أي سحب عليها بعد.",
        "cancelError": "تعذر إلغاء هذا التوزيع.",
```

```json
        "statusValues": {
          "DRAFT": "مسودة",
          "VALIDATED": "مصادق عليه",
          "CANCELLED": "ملغى"
        },
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run frontend/src/modules/finance/__tests__/ShareholderView.spec.ts`
Expected: all pass.

- [ ] **Step 7: Run the full frontend suite and type-check**

Run:
```bash
cd frontend && npx vitest run
cd frontend && npx vue-tsc --noEmit
```
Expected: all green, no type errors.

- [ ] **Step 8: Manual verification in the browser**

Start the dev server (or docker compose stack) and, as Admin/Test Vide, open Actionnaires/Associés → Répartition des bénéfices:
- Create a distribution → confirm the success banner appears with the per-shareholder breakdown, and the banner's "Montant disponible" line now shows a non-zero "Déjà réparti" and a reduced total.
- Try creating another distribution for the exact same period → confirm a clear French error appears and no second row is added to the table.
- Click "Annuler" on the just-created DRAFT distribution, confirm the dialog → confirm the row's badge becomes "Annulée", the "Déjà réparti" line disappears (back to 0), and the shareholder's ledger balance drops back down.
- Validate a distribution, record a withdrawal against one of its shares, then try to cancel it → confirm it's refused with a clear message and the row stays "Validée".

- [ ] **Step 9: Commit**

```bash
git add frontend/src/modules/finance/ShareholderView.vue frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json frontend/src/modules/finance/__tests__/ShareholderView.spec.ts
git commit -m "feat(finance): add a cancel action for shareholder distributions in the UI"
```

---

### Task 9: Clean up the 3 duplicate distributions in Admin/Test Vide (manual, not code)

This is a one-off data fix on the test environment described in the bug report, not something to script into the codebase — do it through the UI itself once Tasks 1-8 are deployed there, using the new `cancel` action so it goes through the exact same audited path as any other cancellation:

- [ ] Log into Admin/Test Vide (`+22200000000` / `1234`).
- [ ] Go to Actionnaires/Associés → Répartition des bénéfices.
- [ ] Confirm there are 3 identical `2026-09-08 → 2026-09-08`, `9 034 000 XOF` distributions, all "Validée", and that no withdrawal has been recorded against any of their shares (check each associate's Grand livre / withdrawals tab first — if a withdrawal already happened against one of the 3, cancelling that specific one will be refused by design, and it should be the one kept rather than cancelled).
- [ ] Keep exactly one of the three (arbitrarily, since they're identical — unless one has a withdrawal against it, in which case keep that one). Click "Annuler" on the other two, confirming each dialog.
- [ ] Verify each associate's available balance in the ledger now reflects only one 9 034 000 XOF distribution's worth of shares, and that the "Montant disponible pour répartition" banner and the "Résultat distribuable" card on the Bénéfices page both increased back to reflect the two cancellations.

---

## Self-Review

**Spec coverage:**
1. Keep the declarative model — Tasks 2-5 never add any treasury posting to `create_distribution`/`validate_distribution`; the fix is purely in the read-side calculations and a new opt-in cancel path. ✅
2. Hard-block on period overlap — Task 2. ✅
3. Add a real CANCELLED state, reversing the prior ruling — Tasks 1, 3, 4 (including the permission migration that explicitly reverses "Task 7 ruling 2"). ✅
4. Clean up the 3 duplicate distributions after the code fix — Task 9. ✅
5. "Le formulaire montre en clair : bénéfice de la période, déjà réparti, reste à répartir" — Task 7 (banner's `already_distributed` line; `distributable_result` itself is now the correct "reste à répartir"). ✅
6. "Un retour visible (toast / bandeau) confirme la prise en compte, avec le détail par associé" — Task 7 (`distribution-success` banner). ✅
7. "Prévoir un moyen d'annuler / corriger une répartition validée (au moins tant qu'aucun retrait n'a été effectué...)" — Tasks 3-4, 8. ✅

**Placeholder scan:** no TBD/TODO, every step has literal code or an exact shell command.

**Type consistency:** `ShareholderDistributionService.cancel_distribution(distribution_id, actor) -> ShareholderProfitDistribution` (Task 3) is called identically from the view action (Task 4) and from tests (Tasks 2, 3, 5); `already_distributed` is the same key name in the backend dict (Task 5), the TypeScript interface (Task 6), and the template/i18n (Task 7); `cancelShareholderDistribution(distributionId: number)` (Task 6) matches its usage in `onCancelDistribution` (Task 8).

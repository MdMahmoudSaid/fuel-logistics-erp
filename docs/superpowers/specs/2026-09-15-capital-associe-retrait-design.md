# Capital associé comme filet de sécurité du solde retirable — Design

**Builds on:** Task 7 (Shareholders/Associates domain), Phase 1 (`docs/superpowers/specs/2026-09-02-business-corrections-6-phases-design.md` — `ShareholderContribution`/"Nouvel apport en capital"), and the 2026-08-26/2026-09-08 corrective reviews that introduced the single `get_available_balance()` formula and made every withdrawal mandatorily traceable to one VALIDATED `ShareholderProfitShare`. This document does not reopen either of those reviews — it extends the same formula and the same traceability discipline to a second, independent pool: the shareholder's own capital.

## Context

Today, `ShareholderContribution` ("Nouvel apport en capital") is deliberately excluded from `ShareholderLedgerService.get_available_balance()` — it shows up only in its own "Capital apporté" column/section, never as part of the withdrawable "solde". That was the right call for a legally-formal capital-social model, but it does not match how this business actually treats capital: a shareholder's own deposited capital is still *his money*, and he must be able to reclaim it once his share of undistributed profit runs out — while still being able to see, separately, how much he originally put in versus how much he actually earned. Conversation with the client (2026-09-15) confirmed the exact rule wanted:

1. A withdrawal draws from **profit due first**; only once that is exhausted does it draw from **capital**.
2. A shareholder can only draw down **his own** contributed capital — never another shareholder's, never a shared/pooled "company capital" figure, regardless of the company's total capital being larger.
3. The two sources must stay distinguishable after the fact (what came from profit vs. what came from capital), not merged into one opaque number.

## Goals

1. `available_balance` gains a new additive term: the shareholder's own remaining (unreturned) capital.
2. A single withdrawal can now be funded by more than one source (several profit shares and/or several capital contributions) while remaining fully traceable, the same discipline the 2026-09-08 review established for profit shares alone.
3. The withdrawal form collects one amount; the system decides the allocation (profit first, oldest first; capital next, oldest first).
4. The ledger (`Actionnaires/Associés` → Grand livre) and per-shareholder summary show a "Capital restant" (net of returns) alongside the existing "Capital apporté" (gross, historical, unchanged).
5. Hard isolation: a shareholder's withdrawal can never reduce a `ShareholderContribution` belonging to a different shareholder — enforced by the query shape, not by a convention that could be forgotten.

## Available balance — updated formula

```
available_balance =
    profit_share_remaining_due       (unchanged: sum of ShareholderProfitShare.remaining_due, VALIDATED distributions only)
  + capital_remaining                (NEW: sum of ShareholderContribution.remaining_capital for THIS shareholder only)
  + loans_given_remaining            (unchanged)
  - loans_received_remaining         (unchanged)
```

`capital_remaining` per contribution = `amount - amount_returned`, mirroring `ShareholderProfitShare.remaining_due = amount_due - amount_withdrawn` exactly. Loans are untouched by this design — see "Explicitly out of scope".

## Data model changes (`backend/apps/finance/models.py`)

**`ShareholderContribution`** (currently L1169-1229) gains:

```python
amount_returned = models.DecimalField(max_digits=16, decimal_places=2, default=0, editable=False)
```

- `remaining_capital` property = `amount - amount_returned`.
- `sync_amount_returned()` method, same shape as `ShareholderProfitShare.sync_amount_withdrawn()` (L1030-1035): recomputes from `Sum(allocations against this contribution)`, the only writer, so it can never drift.
- New `CheckConstraint`: `amount_returned__gte=0` and `amount_returned__lte=F("amount")` (a contribution can never be over-returned).
- Update the class docstring (L1179-1182), which currently states contributions "never contribute to `get_available_balance()`" — that sentence becomes false and must be corrected to describe the new behavior.

**New model `ShareholderWithdrawalAllocation`** (replaces the direct `profit_share` FK on `ShareholderWithdrawal`):

```python
class ShareholderWithdrawalAllocation(TimeStampedModel):
    withdrawal = models.ForeignKey(ShareholderWithdrawal, on_delete=models.CASCADE, related_name="allocations")
    profit_share = models.ForeignKey(ShareholderProfitShare, on_delete=models.PROTECT, null=True, blank=True, related_name="withdrawal_allocations")
    contribution = models.ForeignKey(ShareholderContribution, on_delete=models.PROTECT, null=True, blank=True, related_name="withdrawal_allocations")
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        constraints = [
            CheckConstraint(condition=Q(amount__gt=0), name="...amount_positive"),
            CheckConstraint(
                condition=(
                    Q(profit_share__isnull=False, contribution__isnull=True)
                    | Q(profit_share__isnull=True, contribution__isnull=False)
                ),
                name="...exactly_one_source",
            ),
        ]
```

One `ShareholderWithdrawal` (the parent, one row, one treasury posting, unchanged posting mechanics) now has one-or-more `allocations` — one row per profit share and/or per contribution it actually drew from.

**`ShareholderWithdrawal`** (currently L1109-1166): drop the `profit_share` FK. The model docstring (L1109-1119) already describes a "general withdrawal not tied to any distribution (profit_share null)" case that the 2026-09-08 review's service-layer check made unreachable in practice — this design finally makes that docstring accurate again, by making every withdrawal's sourcing explicit through `allocations` instead of a single optional FK.

## Migration plan

1. Add `amount_returned` to `ShareholderContribution` (default 0 — no existing row is affected, since no capital has ever been returned before this feature).
2. Create `ShareholderWithdrawalAllocation`.
3. **Data migration**: for every existing `ShareholderWithdrawal` row, create exactly one `ShareholderWithdrawalAllocation(profit_share=<old FK value>, amount=<withdrawal.amount>)`. Every historical withdrawal was profit-only by construction (the 2026-09-08 review made `profit_share_id` mandatory), so this backfill is lossless and exact.
4. Drop the `profit_share` column from `ShareholderWithdrawal` in a separate, subsequent migration (standard two-step column removal), once the backfill migration has run.

## Allocation algorithm (`ShareholderWithdrawalService.record_withdrawal`, currently `services.py:1857-1956`)

New signature drops `profit_share_id` entirely — replaced by automatic allocation:

```python
record_withdrawal(*, shareholder_id, amount, date, actor, bank_account_id=None, cash_account_id=None, notes="")
```

Inside the existing `transaction.atomic` block, under `select_for_update()` on the shareholder (as today):

1. `available_balance = ShareholderLedgerService.get_available_balance(shareholder_id)`. Reject if `amount > available_balance` → `"Solde associé insuffisant."` (unchanged message).
2. **New second ceiling, narrower than `available_balance`**: reject with the same message if `amount > profit_share_remaining_due + capital_remaining` — the sum of the two pools this algorithm can actually allocate against. This is necessary because `available_balance` also includes `loans_given_remaining`/`loans_received_remaining` (see "Explicitly out of scope" — loans are never allocated against by a withdrawal). Before this design, a withdrawal was always capped by one single `profit_share`'s `remaining_due`, which made it structurally impossible to ever request more than the profit pool alone, so this gap was unreachable in practice. Once a withdrawal can span the full profit pool plus capital, that safety margin disappears — without this second check, a shareholder with a large `loans_given_remaining` could pass check 1 while still leaving `amount_left > 0` unallocated after the capital pass. Both checks run before any row is created.
3. Reject if `amount > selected_account.current_balance` → `"Solde bancaire insuffisant."` (unchanged).
4. Create the parent `ShareholderWithdrawal` row (no `profit_share` FK anymore).
5. **Profit pass**: lock and iterate `ShareholderProfitShare.objects.select_for_update().filter(shareholder_id=shareholder_id, distribution__status=VALIDATED).annotate(remaining=...).filter(remaining__gt=0).order_by("distribution__period_end", "distribution_id")` (oldest first). For each, consume `min(remaining, amount_left)`, create a `ShareholderWithdrawalAllocation(profit_share=share, amount=consumed)`, call `share.sync_amount_withdrawn()`, decrement `amount_left`. Stop early once `amount_left == 0`.
6. **Capital pass** (only if `amount_left > 0`): lock and iterate `ShareholderContribution.objects.select_for_update().filter(shareholder_id=shareholder_id).annotate(remaining=...).filter(remaining__gt=0).order_by("date", "id")` (oldest first, **scoped to this shareholder only** — this is the isolation guarantee from Goal 5). Same consume/allocate/sync pattern as step 5, using `contribution.sync_amount_returned()`.
7. By construction `amount_left` reaches exactly 0 here, because check 2 already proved `amount <= profit_share_remaining_due + capital_remaining`. If it doesn't (a future bug), raise rather than silently leaving an under-allocated withdrawal.
8. `FinancePostingService.record_shareholder_withdrawal_treasury(withdrawal)` — unchanged, one treasury posting for the whole withdrawal regardless of how many allocations back it.

### Call sites that must change alongside `record_withdrawal`

- `ShareholderWithdrawalSerializer` (`backend/apps/finance/serializers.py:1190-1245`): drop `profit_share` from `Meta.fields`, drop the "must select a profit_share" validation (the code comment there, "2026-09-08 review, point 5: ... there is no 'retrait general'", becomes the opposite of true — a general amount-only withdrawal is now exactly the point), and drop `profit_share_id=...` from the `record_withdrawal(...)` call in `create()`. Add a read-only nested `allocations` field for display, sourced from the new `ShareholderWithdrawalAllocation`.
- `ShareholderView.vue`: remove the "part de bénéfice" select (`profit_share` in the form state at L337/372/387/457, the field at L997-1001) from the withdrawal form entirely — only amount + account remain as inputs.

## Ledger consistency (`backend/apps/reports/queries/shareholder_statement.py`)

The module docstring (L14-20) states the running balance always equals `get_available_balance()` because both are built from the same event types. Since `available_balance` now includes `capital_remaining`, the statement must gain two new event types to keep that invariant true:

- `ShareholderContribution` → **credit**, on its `date` (capital coming in is now part of the balance it can later be drawn from).
- `ShareholderWithdrawalAllocation` where `contribution` is set → **debit**, on the parent withdrawal's `date` (capital going back out).

`ShareholderWithdrawalAllocation` where `profit_share` is set replaces the current direct `ShareholderWithdrawal` debit row — same event, same amount, just sourced through the allocation table instead of the withdrawal's old FK.

## Per-shareholder summary (`ShareholderLedgerService.get_shareholder_summary`, `services.py:2377-2485`)

Add, alongside the existing `total_contributed` (L2441-2443, stays gross/historical, unchanged):

- `capital_returned` — `Sum(ShareholderContribution.amount_returned)` for this shareholder.
- `capital_remaining` — `total_contributed - capital_returned`.

Replace the withdrawal serialization at L2473-2484 (`"profit_share_id": w.profit_share_id`) with the allocation breakdown:

```python
"allocations": [
    {"source": "profit_share", "id": a.profit_share_id, "amount": a.amount}
    if a.profit_share_id else
    {"source": "capital", "id": a.contribution_id, "amount": a.amount}
    for a in w.allocations.all()
]
```

## Frontend (`frontend/src/modules/finance/ShareholderView.vue`)

- Retrait form: drop the "part de bénéfice" selector (no longer needed — allocation is automatic); keep a single amount field plus account selection, unchanged otherwise.
- Withdrawal history / Grand livre rows: show the `allocations` breakdown under each withdrawal (e.g. "700 000 000 — dont 500 000 000 bénéfices, 200 000 000 capital") instead of a single opaque amount.
- Ledger summary cards (currently L1149-1193): add a "Capital restant" card next to the existing "Capital apporté" section (L1195-1210, unchanged) — same visual pattern as `availableBalance` vs. `total_contributed` today, just one more figure, clearly labeled so "apporté" (gross, lifetime) and "restant" (net, still his to reclaim) are never confused.
- Associés list (`s.contribution` / `s.total_contributed` columns, L591/L595): unchanged — this table keeps showing the gross historical figures, matching Goal 4.

## Testing (`backend/apps/finance/tests.py`)

- `get_available_balance` now includes `capital_remaining`; regression test with a shareholder who has both profit due and capital, asserting the additive formula.
- Withdrawal exactly equal to `profit_share_remaining_due` → allocates 100% to profit, zero capital allocations created.
- Withdrawal exceeding `profit_share_remaining_due` → allocates the overflow to capital, oldest contribution first; assert `ShareholderWithdrawalAllocation` rows and resulting `remaining_capital`/`remaining_due` match expected split.
- Withdrawal exceeding `profit_share_remaining_due + capital_remaining` (this shareholder's own capital only) → rejected with `"Solde associé insuffisant."`, **even when another shareholder's capital would have covered the difference** — the isolation test from Goal 5.
- FIFO ordering test: two profit shares / two contributions with different dates, assert the older one is consumed first and the newer one only touched once the older is exhausted.
- `ShareholderContribution.amount_returned` can never exceed `amount` (DB constraint test, matches the existing `amount_withdrawn` pattern's test).
- Data migration test: seed pre-migration-shaped `ShareholderWithdrawal` rows with a `profit_share` FK, run the backfill, assert one matching `ShareholderWithdrawalAllocation` per row with the same amount.
- `ShareholderStatementQuery` running balance still equals `get_available_balance()` for a shareholder with a mix of profit shares, a capital contribution, and a capital-sourced withdrawal (extends the existing invariant test for this query).

Frontend: `ShareholderView.spec.ts` updated for the single-amount withdrawal form and the allocation-breakdown display; new assertion that "Capital restant" decreases and "Capital apporté" stays fixed after a capital-sourced withdrawal.

## Explicitly out of scope

- `ShareholderLoan` behavior is untouched — `loans_given_remaining`/`loans_received_remaining` keep their exact current semantics and are never allocated against by a withdrawal (a pre-existing, separate characteristic of loans that this design does not change or attempt to fix).
- `participation_percent` is never derived from or affected by capital withdrawals (confirmed with the client: participation stays a fixed, contractual figure).
- No floor/minimum on `capital_remaining` — a shareholder may draw it down to exactly zero.
- No manual "pick this specific profit share / this specific contribution" UI — allocation is always automatic (oldest-first) per the client's explicit choice.
- No change to `distributable_result`, `ShareholderProfitDistribution` creation/validation, or the company-level "Reste disponible pour répartition" banner — this design only concerns an individual shareholder's own withdrawable pool.
- `ShareholderContributionService.record_contribution` (creating a new capital contribution) is unchanged — this design only touches what happens when capital is later drawn back down, not how it goes in.

# Bénéfices & Actionnaires/Associés — Refinement Design

**Source spec:** `docs/finances_edit.md`
**Builds on:** Task 7 (Shareholders/Associates domain) and Task 8 (Profit reporting by trip/period) from `docs/plan.md`, both already implemented and committed. Do not edit `docs/plan.md` — this document is a standalone refinement spec.

## Context

`docs/finances_edit.md` asks for a `Bénéfices` page and a complete `Actionnaires / Associés` flow in Trésorerie & Finance. Most of the domain already exists: `Shareholder`, `ShareholderProfitDistribution`/`ShareholderProfitShare`, `ShareholderLoan`, `ShareholderWithdrawal`, `ShareholderLedgerService`, `ShareholderView.vue`. Comparing the existing implementation against the new spec surfaced two real bugs and three missing pieces. This document specifies the fixes and additions only — no new models, no change to the DRAFT→VALIDATED distribution mechanism.

## Goals

1. Fix: shareholder withdrawal can currently exceed both the shareholder's available balance (when not tied to a `profit_share`) and the selected bank/cash balance — neither is checked today.
2. Fix: creating a `ShareholderLoan` never checks the lender has sufficient available balance.
3. Add: a single, explicit `available_balance` formula, reused everywhere (ledger, withdrawal check, loan check).
4. Add: a read-only "current profit" preview, clearly marked as indicative/not yet officially distributed, computed from the existing profit engine — no new stored figures.
5. Add: a dedicated `Bénéfices` page under Trésorerie & Finance (`/finance/profit`), reusing the existing per-trip cost breakdown (`MarginReportQuery` / `TripProfitService`) rather than recomputing profit in Vue.
6. Add: a small dashboard summary card; the `Bénéfices` page remains the single detailed source of truth.

## Available balance — single formula

```
available_balance =
    profit_share_remaining_due       (sum of ShareholderProfitShare.remaining_due across all shares)
  + loans_given_remaining            (sum of remaining_amount on loans where this shareholder is lender)
  - loans_received_remaining         (sum of remaining_amount on loans where this shareholder is borrower)
```

`profit_share_remaining_due` already nets out withdrawals (`amount_due - amount_withdrawn` per share), so withdrawals are not subtracted a second time.

Sign convention (explicit, because it is easy to get backwards): lending money to another associate is a receivable — it *increases* the lender's available balance (it is still their equity, just claimed by an IOU instead of sitting in remaining_due). Receiving an advance is a liability — it *decreases* the borrower's available balance, since that amount must be repaid and is not the borrower's own profit claim.

This is exactly the existing `net_loan_balance` computation in `ShareholderLedgerService.get_shareholder_summary` (`loans_lent_remaining - loans_borrowed_remaining`); no sign change needed there. The work is: (a) extract it into a named `get_available_balance(shareholder_id)` helper so the two validation call sites and the summary endpoint all call the same code, and (b) add tests that pin both directions of the sign convention so a future edit can't silently flip it.

## Fix 1 — Withdrawal validation

`ShareholderWithdrawalService.record_withdrawal` (services.py:1070-1127) must, unconditionally (whether or not `profit_share_id` is given):

- Reject if `amount > ShareholderLedgerService.get_available_balance(shareholder_id)` → `"Solde associé insuffisant."`
- Reject if `amount > selected_account.current_balance` (bank or cash, whichever was chosen) → `"Solde bancaire insuffisant."`

Keep the existing `profit_share`-specific check (amount vs. that share's `remaining_due`) as an additional, narrower constraint when a `profit_share_id` is passed — both checks apply together in that case.

All checks happen inside the existing `transaction.atomic` block, under the existing `select_for_update()` locks (add a lock on the selected bank/cash account row, matching `FinancePostingService.record_supplier_payment_treasury`'s pattern).

## Fix 2 — Loan creation validation

Add `ShareholderLoanService.create_loan(*, borrower_id, lender_id, amount, date, notes="")`:

- Reject if `borrower_id == lender_id` → already a DB constraint; keep the serializer-level message for a clean 400.
- Reject if `amount > ShareholderLedgerService.get_available_balance(lender_id)` → `"Solde disponible du prêteur insuffisant."`
- Create the `ShareholderLoan` row only. **No `TreasuryTransaction` is created** — this must stay true; the existing model docstring already states this invariant ("money that moves shareholder-to-shareholder never creates a TreasuryTransaction") and this refinement does not change it. The loan is visible only in `loans_given` / `loans_lent` on both associates' ledgers.

Wire `ShareholderLoanSerializer.create` to call this service instead of the default `ModelSerializer.create`.

## Addition — Live profit preview

New `ShareholderProfitPreviewService.get_preview(period_start=None, period_end=None)` in `apps/finance/services.py`:

- Delegates to the existing profit engine (`TripProfitService` via `MarginReportQuery`, same code Task 8 already uses) — never recomputes margin logic locally.
- Default period: since the `period_end` of the most recent VALIDATED `ShareholderProfitDistribution` (or all-time if none exist) through today.
- Returns `{period_start, period_end, current_profit, shareholders: [{shareholder_id, name, participation_percent, indicative_share}]}` where `indicative_share = current_profit * participation_percent / 100`, computed on the fly, not stored.
- New endpoint: `GET /api/shareholders/profit-preview/` (optionally with `?from=&to=` overrides).
- Frontend: displayed on both the `Bénéfices` page and the `Actionnaires/Associés` page, with a persistent, visually distinct label — e.g. a badge/banner reading "Indicatif — non distribué officiellement" — so it can never be mistaken for a confirmed `ShareholderProfitShare`. It does not feed into `available_balance` and does not gate withdrawals.
- When creating a new `ShareholderProfitDistribution`, the form pre-fills `total_profit` from this same preview for the chosen period (still an editable field — the manager may adjust before creating the DRAFT).

## Addition — `Bénéfices` page

- Route: `/finance/profit`, component `frontend/src/modules/finance/ProfitView.vue`.
- Sidebar: new entry `Bénéfices` under Trésorerie & Finance, gated on the existing `"shareholders"` module permission (`Role.MODULES`, `apps/accounts/models.py:17`) — the same one that already gates `ShareholderView`.
- Backend: a finance-facing endpoint (either a thin wrapper calling `MarginReportQuery`/`TripProfitService` directly from `apps/finance/views.py`, or exposing the existing reports query under a finance-friendly URL) — do not duplicate the cost-breakdown math from `apps/reports`.
- Content, per `docs/finances_edit.md`: period picker (reuse `DateRangeFilter`), bénéfice total actuel, bénéfice de la période, nombre de trajets, CA, coût fournisseur, commission transporteur, douane, transit, frontière, chargement, autres frais, bénéfice net, and the per-trip table (référence, client, produit, quantité, prix fournisseur/L, prix de revient/L, prix de vente/L, bénéfice/L, bénéfice total).
- Includes the live preview banner from the previous section at the top (informational).

## Addition — Dashboard summary

`apps/reports/views/dashboard.py`: add a small block —

- `current_profit` (from the preview service, all-time default)
- `total_withdrawn` (sum `ShareholderWithdrawal.amount`)
- `remaining_undistributed` (sum of `remaining_due` across all profit shares)
- `open_loans_total` (sum of `remaining_amount` for OPEN/PARTIALLY_REPAID loans)

`DashboardView.vue` renders this as one summary card, gated on the `"shareholders"` module permission, and links through to `/finance/profit` for detail. No per-trip or per-shareholder breakdown on the dashboard — that stays on the `Bénéfices` and `Actionnaires/Associés` pages.

## Testing

Backend (`apps/finance/tests.py`):
- `get_available_balance`: pins both signs — a loan given increases it, a loan received decreases it (regression test for the point explicitly flagged during design review).
- Withdrawal without `profit_share_id` exceeding `available_balance` → rejected with the exact French message.
- Withdrawal exceeding selected bank/cash balance → rejected with the exact French message.
- Loan creation exceeding lender's `available_balance` → rejected with the exact French message.
- Loan creation never produces a `TreasuryTransaction` (assert `TreasuryTransaction.objects.count()` unchanged).
- Preview service: returns figures consistent with `TripProfitService`/`MarginReportQuery` for a known period; does not write any DB rows.

Backend (`apps/reports` or wherever the profit/margin query lives): period-filtered `Bénéfices` page aggregate matches sum of per-trip rows (mirrors existing Task 8 test pattern).

Frontend: `ShareholderView.vue`/ledger tests updated for the corrected `available_balance` field and the new preview banner; new `ProfitView.spec.ts` covering period selection and per-trip table rendering; dashboard spec updated for the new summary card.

## Explicitly out of scope

- No change to the DRAFT/VALIDATED distribution creation/validation flow.
- No new models or migrations beyond what fixing the two service methods requires (none are expected — this is service-layer logic plus one new read endpoint).
- No edits to `docs/plan.md`.
- No cancel workflow for distributions (unchanged ruling from Task 7).

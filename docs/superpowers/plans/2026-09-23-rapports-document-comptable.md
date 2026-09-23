# Rapports — document comptable unifié — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax. Deliberately terse: **the spec is the source of truth** — read the cited section before each block, don't expect it repeated here.

**Goal:** Every Reports-page report renders as one accounting-style document (screen sheet, print, backend PDF) per the spec.
**Architecture:** Backend builds a `document` definition (opt-in `?document=1`) consumed by both a Vue `ReportSheet` and a shared ReportLab renderer. Spec §Architecture.
**Tech Stack:** Django/DRF, ReportLab 5.0.1, `arabic-reshaper` + `python-bidi` (new), `pypdf` (dev), Vue 3 + vue-i18n + vitest.
**Spec:** `docs/superpowers/specs/2026-09-23-rapports-document-comptable-design.md` (commit 7885359, validated). Decision ids D1–D10 below refer to it.

## Global Constraints

- Backend cmds from `backend/`: `.venv/bin/python -m pytest <path> -q` (pytest.ini already uses `--reuse-db`). Frontend cmds from `frontend/`: `npx vitest run <path>`.
- Currency XOF (D1). Backend is the only source of report labels (D2). Legacy response `{report_type, fields, rows}` unchanged without `?document=1` (D3).
- Commits: one per block, `git add` by explicit path only (never `-A`; workspace has unrelated changes: `docker-compose.yml`, `.claude/`, `reset_transactional_data.py` — leave untouched). Trailer `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. No push/merge (user decides).
- Work on branch `feature/rapports-document-comptable` cut from `main` (Task 0). Reuse existing helpers: `_safe_paragraph_text`, `_format_money/_quantity/_unit_money`, logo path, `DEFAULT_COMPANY_NAME` in `ledger_pdf.py`; `formatMoney/formatQuantity/formatUnitMoney` in `@/utils/currency`; `DateRangeFilter`, `Badge`, `.no-print`.
- Execution rhythm: run only the targeted tests named in each block; full suites only at the checkpoints marked ⛳ (once each, no reruns of an unchanged suite).

## Amendments to the spec (applied in Task 0)

- **D7 (user, 2026-09-23):** CANCELLED rows stay displayed but are excluded from amounts, quantities, margins **and operational counts**; the summary gets a line `cancelled_excluded` ("Annulés exclus : N", kind `count`, always shown on these reports, 0 allowed). Replaces the spec's "note only when N>0"; the `notes` field is therefore **dropped** from the payload, sheet and PDF. Applies to purchase-report (`SupplierOrder` CANCELLED), trip-report and truck-history (`Trip` CANCELLED), margin-report (rows carry no status → builder does one `Trip.objects.filter(reference__in=…)` lookup for statuses; no change to `FIELDS`/rows). sales-report, loss-report, expense-report (already excludes cancelled) are unaffected.
- **Arabic escaping order:** shape/bidi must run on the *raw* text, then XML-escape, then wrap runs (escaping first would let bidi reorder `&lt;`). Spec §Arabic wording "after escaping" is corrected to this.

## Review Focus

1. Hostile / very long / Arabic entity and party names (`<img src=x>`, `&`, 120-char name) in header and cells — no crash, no injection, wraps (Task 3.2, 4.1).
2. Statement whose period contains no entries but has a non-zero opening balance — opening row + empty text + closing = opening (Task 1.1, 2.1).
3. `None` cells (truck-history client/margin, fuel-stock TOTAL reference, unverified `verified_at`) render "—" and are ignored by sums (Task 2.1, 5.1).
4. `?document=1` with a missing / unknown / non-numeric entity id — same 4xx as the legacy call, never a 500 (Task 2.2).
5. Long tables (≥ 100 rows, margin with 3 tables) — header/title repeat, "Page n / N", no overflow (Task 3.2).

---

## Block 0 — Setup

### Task 0: Branch + spec amendments
- [ ] `git switch -c feature/rapports-document-comptable`
- [ ] Edit spec: D7 row, remove `notes` from payload/Sheet/PDF/tests mentions, Arabic escaping-order sentence (see Amendments). Commit spec + this plan file together: `docs(reports): amend spec (D7 cancelled counts, arabic escape order) and add implementation plan`.

---

## Block 1 — Statement queries: opening balance + reconciliation (spec §Statements)

### Task 1.1: customer / supplier / shareholder opening balance
**Files:** modify `apps/reports/queries/{customer,supplier,shareholder}_statement.py`; tests in `apps/reports/test_queries.py` (+ `test_queries_v2.py` if shareholder tests live there — check with `grep -n "Statement" apps/reports/test_queries*.py`).
**Change:** extract one private `_entries(<entity>_id)` (all history, unfiltered, with `sort_key`, existing sign convention); `run()` partitions by date and starts the running balance at `opening_balance`; add `opening_balance(*, <entity>_id, date_from=None, date_to=None) -> Decimal`. Keep `run()` signature and row shape. Shareholder: keep existing `_as_date` coercion and VALIDATED-only rule.
**Interfaces (produced):** `CustomerStatementQuery.opening_balance(customer_id=…, date_from=…)`, same for `SupplierStatementQuery(supplier_id)`, `ShareholderStatementQuery(shareholder_id)`.
**Tests:** new: entries before + inside period → opening = balance the unfiltered run showed before `date_from`; first row balance includes it; `opening + Σsigned == last balance`; no `date_from` → 0 and rows equal legacy; empty period with prior entries (Review Focus 2) → no rows, opening ≠ 0. Adapt: existing assertions that encoded zero-start balances under a date filter (find via failing run; list them in the commit body).
**Verify:** `.venv/bin/python -m pytest apps/reports/test_queries.py apps/reports/test_queries_v2.py -q -k "statement"`

### Task 1.2: treasury `statement_context`
**Files:** modify `apps/reports/queries/treasury_statement.py`; tests in `apps/reports/test_queries.py`.
**Change:** add `statement_context(*, bank_account_id=None, cash_account_id=None, date_from=None, date_to=None) -> dict` with keys `opening_balance, period_in, period_out, transfers_net, closing_balance` (definitions in spec §Internal transfers), computed by the same full-history walk as `run()` (factor the walk into one private helper both use; `run()` output unchanged).
**Tests:** transfer before / inside / after the period; negative `transfers_net`; no dates → opening = account opening balance; `opening + period_in − period_out + transfers_net == closing`; `period_in/out` equal sums of `run()` rows by type.
**Verify:** `.venv/bin/python -m pytest apps/reports/test_queries.py -q -k "treasury or bank or cash"`

- [ ] **Block 1 checkpoint:** `.venv/bin/python -m pytest apps/reports -q` (only if the -k runs above passed) → commit `feat(reports): statement opening balance and treasury reconciliation context`.

---

## Block 2 — Document builder + `?document=1` API (spec §Backend, §Per-report, §Compatibility)

### Task 2.1: `report_document.py` + label catalog
**Files:** create `apps/reports/services/report_document.py`, `apps/reports/test_report_document.py`.
**Change:** `REPORT_SPECS` (17 slugs; columns/kinds/orientation/entity_kind/period_mode/summarize per spec table, margin = 3 tables), `REPORT_LABELS` fr/en/ar (titles, field labels, enum values keyed `namespace.VALUE`, summary labels, fixed strings incl. `empty_text`, "Solde antérieur", "Situation au", "Toutes périodes", "Annulés exclus"), `build_report_document(...)`. All sums as `Decimal` from rows, `None` ignored. Reconciliation invariant + visible "Écart de rapprochement" line (spec §Internal transfers). D7 per Amendments. Fuel-stock: TOTAL row printed bold last, excluded from sums, gap line if sums ≠ TOTAL. Entity lookup: one query, missing entity → `entity.name = None` (no exception).
**Interfaces (produced):** `build_report_document(report_type: str, rows: list[dict], params: dict, lang: str, *, statement_context: dict | None = None) -> dict` (payload shape: spec §`document` payload minus `notes`, plus `cancelled_excluded` summary line); `REPORT_LABELS[lang][key]`; `REPORT_SPECS[slug]`.
**Tests (`test_report_document.py`, parametrized over the 17 slugs where possible):** header fields (translated title ≠ slug, company, date, period modes, XOF, orientation, no `_` in labels, entity names incl. optional filters); totals per family vs independently summed rows; D7 (mixed CANCELLED rows for purchase/trip/truck-history/margin → totals, counts and `cancelled_excluded` correct); opening/closing equations for the 4 statement families; treasury equation + gap-line only on stubbed inconsistency; empty rows for all 17; margin = 3 tables covering every `FIELDS` column; None cells (Review Focus 3); label catalog completeness for every enum used (models' `TextChoices` values) in fr/en/ar.
**Verify:** `.venv/bin/python -m pytest apps/reports/test_report_document.py -q`

### Task 2.2: API wiring + compatibility contract
**Files:** modify `apps/reports/views/reports.py`; tests in `apps/reports/test_views.py`.
**Change:** `retrieve` reads `document`, `lang` (excluded from `params` passed to `run()`, like `export`); when `document=1` builds `statement_context` (`opening_balance` for the 3 statements, `TreasuryStatementQuery.statement_context` for bank/cash) and returns `{report_type, fields, rows, document}`. Query errors keep the legacy 400/404 path (Review Focus 4). Export branch: pass `lang` through (used from Block 3).
**Tests:** for all 17 types without `document` response keys == `{report_type, fields, rows}`, `fields == QueryClass.FIELDS`, rows == serialized `run()` output; loss-report rows keep `verified_at`, margin rows keep `unit_profit/current_margin`; with `document=1` the three legacy keys are identical + `document` present; missing/unknown/non-numeric entity id with `document=1` → same status as without.
**Verify:** `.venv/bin/python -m pytest apps/reports/test_views.py -q -k "report"`

- [ ] **Block 2 checkpoint:** `.venv/bin/python -m pytest apps/reports -q` → commit `feat(reports): report document builder and ?document=1 API`.

---

## Block 3 — Shared PDF template + FR report PDF (spec §pdf_template, §report_pdf)

### Task 3.1: `pdf_template.py` and masthead delegation
**Files:** create `apps/reports/services/pdf_template.py`; modify `services/ledger_pdf.py` (`_pdf_masthead`, `DEFAULT_COMPANY_NAME`, `_safe_paragraph_text` → thin re-exports/delegates), `services/profit_pdf.py` (logo/company block only).
**Change:** move company constant, logo, `safe_text`, masthead flowables, numbered-canvas footer ("Page n / N", running title from page 2) into the template. `shape(text, lang)` is identity here (Arabic in Block 4). Do not change ledger/profit bodies.
**Interfaces (produced):** `DEFAULT_COMPANY_NAME`, `safe_text(value) -> str`, `masthead(company_name, doc_title, styles, heading_style) -> list`, `numbered_canvas_cls(title: str, lang: str)`, `shape(text: str, lang: str) -> str`.
**Test:** existing `test_ledger_pdf.py`, `test_profit_pdf.py` unchanged and green.
**Verify:** `.venv/bin/python -m pytest apps/reports/test_ledger_pdf.py apps/reports/test_profit_pdf.py -q`

### Task 3.2: `report_pdf.py`, export switch, remove `rows_to_pdf`
**Files:** create `apps/reports/services/report_pdf.py`, `apps/reports/test_report_pdf.py`; modify `apps/reports/export.py` (delete `rows_to_pdf` + unused imports), `views/reports.py` (`_export` pdf branch builds the document with `lang` and calls the renderer), `apps/reports/test_export.py` (drop the 2 `rows_to_pdf` tests; csv/xlsx tests stay).
**Change:** `render_report_pdf(document: dict, rows: list[dict], lang: str = "fr") -> bytes` per spec (masthead, info grid, tables with `repeatRows=1`, Paragraph cells + kind-based widths, ≥ 7 pt, opening row, summary grid with emphasized final line, empty row, A4 orientation). Reuse `_format_money/_quantity/_unit_money` from `ledger_pdf`; dates DD/MM/YYYY.
**Tests (pypdf — add `pypdf` to `requirements/dev.txt` and `.venv/bin/pip install pypdf` first):** FR text contains company, translated title, period, entity, headers, totals, "Page 1 / n"; 150-row report → ≥ 2 pages, header + title repeated on page 2, correct N; wide margin report: every table `wrap()` fits the frame, min font 7; empty report builds and shows `empty_text`; hostile/long names (Review Focus 1); `?export=pdf` end-to-end via API client (with/without `lang`, permission and unknown-format behaviour unchanged).
**Verify:** `.venv/bin/python -m pytest apps/reports/test_report_pdf.py apps/reports/test_export.py apps/reports/test_views.py -q -k "pdf or export"`

- [ ] **Block 3 checkpoint:** `.venv/bin/python -m pytest apps/reports apps/customers apps/suppliers apps/transport apps/finance -q -k "pdf or ledger or export or report"` → commit `feat(reports): shared PDF template and report PDF renderer`.

---

## Block 4 — Arabic (spec §Arabic / RTL)

### Task 4.1: fonts, shaping, RTL layout
**Files:** modify `requirements/base.txt` (+`arabic-reshaper`, `python-bidi`, pinned), `services/pdf_template.py`, `services/report_pdf.py`; create `apps/reports/assets/fonts/` (Noto Naskh Arabic Regular + Bold static TTF from the notofonts GitHub release + `OFL.txt`); tests in `test_report_pdf.py`.
**Change:** install deps in `.venv`; register both TTFs once; `shape()` for `ar`: reshape → `get_display` on raw text → `safe_text` → wrap non-Arabic runs (digits, Latin, `XOF`, refs, dates) in a Helvetica `<font>` span so LTR runs and "AZUR ÉNERGIE" stay intact, Arabic runs use Noto. `report_pdf`: reversed column order, right alignment, mirrored info/summary grids and footer. Applied only in `report_pdf`/`pdf_template` helpers (ledger/profit bodies keep their FR fallback).
**Tests:** ar PDF has embedded Noto font, extracted text contains Arabic presentation-form chars and no tofu, column order reversed, `23 576 205 XOF` and dates keep LTR order, hostile + Arabic entity names (Review Focus 1); fr output unchanged.
**Verify:** `.venv/bin/python -m pytest apps/reports/test_report_pdf.py -q -k "ar or arabic or rtl"`

- [ ] **⛳ Checkpoint (backend complete):** `.venv/bin/python -m pytest -q` (full backend, once) → commit `feat(reports): Arabic RTL support for report PDFs`.
- [ ] Confirm `git diff --stat --cached` shows only reports files before each commit (Docker picks the new deps up from `requirements/base.txt`).

---

## Block 5 — Frontend sheet (spec §Frontend)

### Task 5.1: types, api, cell helpers, `ReportSheet.vue`
**Files:** modify `frontend/src/modules/reports/{types.ts,api.ts}`; create `modules/reports/reportCells.ts`, `modules/reports/ReportSheet.vue`, `modules/reports/__tests__/ReportSheet.spec.ts`; date helper `formatDateDMY` in `@/utils/` (reuse an existing date util if `grep -rn "toLocaleDateString\|formatDate" src/utils` finds one).
**Change:** `ReportDocument` type mirrors the payload; `fetchReport(type, params, options?: {document?: boolean; lang?: string})` (no options → no extra params); `downloadReportExport` sends `lang`. Move the money/quantity/enum/badge/tone helpers out of `ReportsView.vue` into `reportCells.ts`, driven by `document.tables[].columns[].kind` and `enum_labels` (no client-side report translation, D2). Sheet: A4 width portrait/landscape inside `overflow-x-auto`, masthead (`assets/azur-energie-icon.png` + company), info grid, tables (`thead` repeat class), opening row, summary (emphasis), empty row, `dir` + reversed columns for `ar`.
**Interfaces (produced):** `<ReportSheet :document="ReportDocument" :rows="Record<string, unknown>[]" />` root element has class `report-sheet` and a ref-able root; `formatDateDMY(iso: string): string`.
**Tests:** masthead/info/period modes, formatted cells (DD/MM/YYYY, XOF, unit price 4 decimals), None → "—" (Review Focus 3), opening row, summary + `cancelled_excluded`, empty state, portrait vs landscape class, `ar` document (`dir="rtl"`, reversed headers), margin (3 tables); `fetchReport` without options sends no `document`/`lang`.
**Verify:** `npx vitest run src/modules/reports`

### Task 5.2: wire `ReportsView.vue`
**Files:** modify `modules/reports/ReportsView.vue`, `modules/reports/__tests__/ReportsView.spec.ts`.
**Change:** selection zone untouched; `runReport` calls `fetchReport(..., {document: true, lang: locale})`; render `<ReportSheet>` in place of the inline table; export sends locale. Remove helpers moved in 5.1.
**Test (adapt):** request carries `document=1` and `lang`; sheet rendered; print/PDF buttons still gated by `canExport` as before.
**Verify:** `npx vitest run src/modules/reports`

- [ ] **Block 5 checkpoint:** `npx vitest run src/modules/reports src/modules/trips src/modules/dashboard src/modules/finance` (covers TripDetail, DashboardView, ProfitView consumers — must pass **unmodified**) → commit `feat(reports-ui): ReportSheet document view`.

---

## Block 6 — Print scope + final verification (spec §Print, §Testing)

### Task 6.1: `usePrintScope`, print CSS, `@page`
**Files:** create `frontend/src/composables/usePrintScope.ts`, `frontend/src/composables/__tests__/usePrintScope.spec.ts`; modify `ReportsView.vue` (Print button → `usePrintScope(sheetEl).print()`), `frontend/src/style.css` (print block additions; existing `aside, header, .no-print` rules stay).
**Change:** as spec §Print: mark every off-chain sibling from sheet to `<body>` with `data-print-hidden`, ancestors with `data-print-chain`, inject `<style id="report-page-size">` (`@page { size: A4 portrait|landscape; margin: 12mm }` from `document.orientation`), call `window.print()`, clean up on `afterprint`, unmount and thrown error.
**Interfaces (produced):** `usePrintScope(sheet: Ref<HTMLElement | null>, orientation: Ref<'portrait' | 'landscape'>): { print: () => void }`.
**Tests:** DOM with sidebar/topbar/toast/selection/title siblings at several depths → all off-chain siblings hidden, sheet + ancestors not; markers + style removed after `afterprint`, on unmount, when `print` throws; orientation drives the `@page` value. Add a `ReportsView` assertion that clicking Print calls it.
**Verify:** `npx vitest run src/composables src/modules/reports`

### Task 6.2: final gate
- [ ] ⛳ `npx vitest run` (full frontend, once) · `npm run lint` · `npx vue-tsc -b` (once each).
- [ ] Backend already fully green at Block 4 checkpoint; rerun only `.venv/bin/python -m pytest apps/reports -q` if backend files changed since.
- [ ] Manual QA (browser automation as in Phase 6): one report per family in FR and AR — sheet layout, print preview portrait + landscape shows only the sheet with repeated table header, downloaded PDF structure, phone-width horizontal scroll. Fix any bug found with a regression test first.
- [ ] Commit `feat(reports-ui): print scope isolating the report sheet`; final report lists deviations (Amendments, updated legacy balance assertions) and what needs the user's eyes (manual QA items). No push/merge.

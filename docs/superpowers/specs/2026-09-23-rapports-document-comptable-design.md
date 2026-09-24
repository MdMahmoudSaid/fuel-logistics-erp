# Rapports — document comptable unifié (aperçu, impression, PDF) — Design

**Builds on:** `docs/PHASE_6_PLAN.md` Étapes 4–8 (17 report queries, `ReportViewSet`, `ReportsView.vue`), the 2026-09-06 PDF work (`ledger_pdf.py`, `profit_pdf.py`: logo + company masthead, `_safe_paragraph_text` escaping) and the client feedback of 2026-09-23 ("les rapports ne sont pas d'une façon très claire… ne contient pas les logos et les noms de l'entreprise avec la date"), which supplied a reference structure taken from an older accounting package (header → general info → detail table → opening balance line → period totals → final balance → pagination). This document does not touch the 3 party-ledger PDFs' bodies nor the "Bénéfices" PDF body; it only makes them share the masthead/footer helpers.

## Context

The Reports page (`ReportsView.vue`) renders every report as a bare table. Its PDF export, `rows_to_pdf()` in `backend/apps/reports/export.py`, receives only `fields`, `rows` and a technical title (`"customer-statement"`), so it prints raw column names (`Trip Reference`), raw values (`MONEY_IN`, ISO dates, un-formatted decimals), no logo, no company, no period, no entity, no totals, no page number. Print is a bare `window.print()` that hides only `aside`/`header`/`.no-print`.

Three findings from reading the code shape this design:

1. **Statement balances are wrong on partial periods.** `CustomerStatementQuery`, `SupplierStatementQuery` and `ShareholderStatementQuery` start `balance = 0` and filter entries by date *before* accumulating, so a statement from 2026-09-01 shows a running balance that ignores everything owed before that date. `TreasuryStatementQuery` already walks the full history correctly (starting from `opening_balance`) and only filters what it emits, but it silently skips `is_transfer` rows while still counting them in the balance, so displayed rows do not reconcile with the displayed balance.
2. **Arabic PDF is unsupported today.** `ledger_pdf.py` documents this as a known limitation: Helvetica has no Arabic glyphs and no shaping/bidi library is installed.
3. **Three PDF designs exist** (rows_to_pdf, ledger_pdf, profit_pdf), each with its own logo/heading code.

## Goals

1. All 17 report types render as the same accounting document: masthead (logo, AZUR ÉNERGIE, translated title), general-information block (generation date, period, entity), detail table(s) with translated headers, optional opening-balance row, summary block, page numbering — on screen, in print and in the backend PDF.
2. Columns, orientation and summary block vary per report; nothing is invented that is not in the API response.
3. Statements show a true **Solde antérieur**, computed by the business queries over the full history, and a reconciliation that always balances.
4. Real French and Arabic (true RTL, shaped, embedded font) output; English supported by the same catalog.
5. Existing consumers of the reports API (`TripDetail`, `DashboardView`, `ProfitView`) are provably unaffected.

## Non-goals

- No change to CSV/XLSX export (`rows_to_csv`, `rows_to_xlsx` stay; the endpoint keeps `?export=csv|xlsx`).
- No Arabic for the 3 party-ledger PDFs or the profit PDF bodies (they keep their documented FR-fallback); they only adopt the shared masthead/footer.
- No new report types, no new filters, no per-report charts.
- No reproduction of the old software's chrome (blue menus, Crystal Reports toolbar, grey background, Arabic strings).

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Currency is **XOF**, shown as the suffix on every money cell and in the header. | `frontend/src/utils/currency.ts`: official currency is XOF, "never use MRU" (docs/edit.md 2026-08-26). The brief allows another currency when one is actually configured. |
| D2 | The backend is the **single source of translated report labels** (title, columns, enum values, summary labels, empty-state text) in fr/en/ar. The Vue sheet renders what the API returns; it does not translate report content itself. | The PDF needs the catalog anyway; two catalogs would drift. |
| D3 | The enriched response is **opt-in** (`?document=1`). Without it the response is byte-for-byte what it is today. | `TripDetail`, `DashboardView`, `ProfitView` call `fetchReport` on hot paths without needing a document; also makes the compatibility contract trivially testable. |
| D4 | **Solde antérieur is computed inside each business query** over the full history (see §Statements). | User requirement (2026-09-23): it must not be reconstructed in the view/builder from a re-fetched row list. |
| D5 | Treasury **internal transfers enter a signed reconciliation equation** rather than being ignored (see §Statements). | User requirement (2026-09-23). |
| D6 | **Print hides everything outside `ReportSheet` explicitly** (see §Print). | User requirement (2026-09-23): a CSS list of known shell elements is not enough. |
| D7 | Rows with status `CANCELLED` stay visible but are **excluded from amounts, quantities, margins and operational counts**; the summary carries a `cancelled_excluded` line ("Annulés exclus : N", always shown on these reports, 0 allowed). Applies to purchase-report, trip-report, truck-history and margin-report (margin rows carry no status: the builder looks trip statuses up by `trip_reference`; `FIELDS`/rows unchanged). *(Validated by the user 2026-09-23.)* | A cancelled order inflating a total would make the summary misleading; the query itself includes them, so hiding them would break parity with the current screen. |
| D8 | Margin report prints as **three stacked tables** over the same rows (quantities & prices / costs / losses & margin), landscape. | 23 columns in one row cannot stay legible on A4 (≈12 mm each). Each table repeats trip and client. |
| D9 | No "chiffre d'affaires" line on the margin report. | Revenue is not a field of the margin response and margin ≠ revenue − displayed costs in every case (loss indemnities); we do not derive it. |
| D10 | Print = `window.print()` on the HTML sheet; PDF = backend document. Same structure and content, not pixel-identical. | Blob-iframe printing of a PDF is unreliable in Safari/Firefox; native print also handles Arabic natively. |

## Architecture

### Backend

**`apps/reports/services/report_document.py`** (new) — the report definition layer.

- `REPORT_SPECS: dict[str, ReportSpec]`, one entry per slug in `REPORT_REGISTRY` (17). A `ReportSpec` declares: `title_key`, `orientation` (`portrait|landscape`), `tables` (list of `TableSpec(title_key|None, columns)`), `entity_kind` (or `None`), `period_mode` (`range` | `as_of`), and a `summarize(rows, context) -> list[SummaryLine]` function. A `ColumnSpec` is `(field, kind, label_key)` with `kind ∈ date | text | ref | money | unit_money | quantity | enum(namespace) | status(namespace) | count`; alignment derives from kind (money/unit_money/quantity/count right, everything else start).
- `build_report_document(report_type, rows, params, lang, *, statement_context=None) -> dict` returns the `document` payload below. Pure function of its inputs (plus a single entity-name lookup); all totals are computed here from `rows`, so screen and PDF cannot disagree.
- **Label catalog** `REPORT_LABELS = {"fr": …, "en": …, "ar": …}` (titles, ~60 field labels, enum values keyed `namespace.VALUE`, summary labels, fixed strings: "Solde antérieur", "Aucune donnée pour la période sélectionnée.", "Page {n} / {total}", "Situation au", "Généré le", …). Enum values reuse the existing frontend namespaces' meaning (`statementType`, `transactionType`, `purchaseOrderStatus`, `expenseStatus`, `expenseCategory`, `expenseCalcMethod`, trip status). A test asserts every enum value present in the models' `TextChoices` used by a report has an entry in all three languages, so a new status cannot silently print raw.
- Unknown `lang` falls back to `fr` (same as the existing PDF views).

**`document` payload** (returned as `response["document"]` when `?document=1`; `lang` from `?lang=`):

```jsonc
{
  "title": "Relevé client",
  "company": {"name": "AZUR ÉNERGIE"},
  "generated_on": "2026-09-23",
  "lang": "fr", "direction": "ltr", "currency": "XOF",
  "orientation": "portrait",
  "period": {"mode": "range", "from": "2026-09-01", "to": "2026-09-23"},  // mode: range | open (no bounds → "Toutes périodes") | as_of ("Situation au <generated_on>")
  "entity": {"label": "Client", "name": "Ets Diallo & Frères"},           // null when the report has no entity; also set when an optional filter (supplier_id on purchases, customer_id on sales) is present
  "tables": [{"key": "main", "title": null,
              "columns": [{"field": "date", "label": "Date", "kind": "date", "align": "start"}, …,
                          {"field": "type", "kind": "enum", "enum_labels": {"INVOICE": "Facture", "PAYMENT": "Paiement"}}]}],
  "opening_balance": {"label": "Solde antérieur", "value": "125000.00", "column": "balance"},  // statements only, else null
  "summary": [{"key": "total_debit", "label": "Total débit", "value": "…", "kind": "money", "emphasis": false}, …],
  "empty_text": "Aucune donnée pour la période sélectionnée."
}
```

`rows` stays the raw list at the top level (same objects as today); each table's `columns` selects fields from it. Formatting of dates/money/quantities is done by the presenter (Vue helper / PDF renderer), not stored in `rows`.

**`apps/reports/services/pdf_template.py`** (new) — shared PDF building blocks: company constant (`DEFAULT_COMPANY_NAME`, moved here and re-exported from `ledger_pdf`), logo `Image` (same `assets/azur-energie-icon.png`, missing file never blocks an export), `masthead(...)`, `page_decorations(title, lang)` (running title on pages ≥ 2, "Page n / total" footer via a two-pass `NumberedCanvas`), `safe_text` (the existing `_safe_paragraph_text`), font registration, `shape(text, lang)`.
`ledger_pdf._pdf_masthead` and `profit_pdf`'s logo/company block are changed to call it; their bodies and their existing tests are untouched.

**`apps/reports/services/report_pdf.py`** (new) — `render_report_pdf(document, rows, lang) -> bytes`. Replaces `rows_to_pdf()` (removed from `export.py`; its two tests are rewritten against the new function). Layout: masthead → general-info block (2-column label/value grid: generation date, period, entity, currency) → horizontal rule → each table (`repeatRows=1`, Paragraph cells for wrapping, explicit column widths from kind weights: refs/dates/money fixed-ish, text columns take the remainder, never font < 7 pt) → opening-balance row inserted first in the table when present → summary block (right-aligned 2-column grid, emphasized final line). Empty rows: header kept + one spanning row `empty_text`, summary still printed (zeroes). A4 portrait or landscape from `orientation`.

**API** (`views/reports.py`): `retrieve` gains `?document=1&lang=`. When set, it additionally calls `query_class.statement_context(**params)` if defined, builds `document`, and returns `{report_type, fields, rows, document}`. `?export=pdf` now builds the document (always, lang from `?lang=`) and calls `render_report_pdf`; CSV/XLSX unchanged. Filename `f"{report_type}.pdf"` unchanged.

### Statement queries (`queries/*_statement.py`)

See §Statements. The `run()` signature and row shape are unchanged.

### Frontend

- `modules/reports/types.ts`: `ReportResponse` gains optional `document?: ReportDocument`; `ReportDocument` mirrors the payload. `api.ts`: `fetchReport(type, params, { document, lang })` (default off, so existing callers are unchanged); `downloadReportExport` passes `lang`.
- `modules/reports/ReportSheet.vue` (new): white sheet, `width: 210mm` (portrait) / `297mm` (landscape), centred, inside an `overflow-x-auto` wrapper so phones scroll horizontally; padding equivalent to print margins. Renders masthead (logo `assets/azur-energie-icon.png` + company text, matching the PDF), info grid, table(s) from `document.tables` with `<thead>` repeated in print (`display: table-header-group`), opening-balance row, summary block, empty row. Money/quantity/date formatting reuses `@/utils/currency` + a `formatDateDMY` helper (JJ/MM/AAAA); money tone colours from the current screen are kept for money cells only. `dir` comes from `document.direction`; in RTL the column order is reversed by the presenter exactly as the PDF renderer does.
- `ReportsView.vue`: selection zone unchanged (type, entity, period, generate, print, PDF). After generation it renders `<ReportSheet>` instead of the inline table; the badge/enum/tone helpers move into the sheet or a small `reportCells.ts`. Language passed = `useI18n().locale`. **Behaviour to note:** changing the UI language after generating does not re-translate the loaded report until the user regenerates (same as today for the run/export split); the export button always uses the current locale.

## Statements

### Opening balance — computed by the business queries over the full history (D4)

For customer, supplier and shareholder statements each query class is refactored so that a single private method builds **every** entry for the entity, unfiltered by date, with its `sort_key`:

- `run(...)` partitions those entries by `date_from`/`date_to` in Python and starts its running balance at `opening_balance`; the first emitted row's balance therefore includes everything before the period (**intentional behaviour change**: previously it started at 0).
- `opening_balance(*, <entity>_id, date_from=None, date_to=None) -> Decimal` (classmethod) sums the signed effect of the entries with `date < date_from` from the same list (0 when `date_from` is None).
- Sign conventions are the ones already in each query: customer and supplier `debit − credit`; shareholder `credit − debit`.
- Closing balance = `opening_balance + Σ signed rows` = the last row's balance (or the opening balance when there are no rows).

Customer/supplier previously filtered in the ORM; loading the full history of one entity is bounded and is what the ledger services already do.

`TreasuryStatementQuery` already walks the full history; it gains `statement_context(*, bank_account_id=None, cash_account_id=None, date_from=None, date_to=None) -> dict` computed in the *same* loop, so it is not a second implementation.

`TransporterStatementQuery` has no running balance and gets no opening balance (totals only).

### Internal transfers — signed reconciliation (D5)

`TreasuryStatementQuery.statement_context()` returns, from one walk of the full history:

```
opening_balance          account.opening_balance + Σ signed(all txns dated < date_from)   [= account opening balance if no date_from]
period_in                Σ amount of non-transfer MONEY_IN in [date_from, date_to]
period_out               Σ amount of non-transfer MONEY_OUT in [date_from, date_to]
transfers_net            Σ signed(amount) of is_transfer txns in [date_from, date_to]      (signed: MONEY_IN +, MONEY_OUT −; may be negative)
closing_balance          account.opening_balance + Σ signed(all txns dated ≤ date_to)      [all history if no date_to]
```

and the summary block prints, in this order, for bank and cash statements:

```
Solde antérieur                 opening_balance
+ Total entrées                 period_in
− Total sorties                 period_out
± Virements internes (net)      transfers_net        (always shown, signed, even when 0)
= Solde final                   closing_balance     (emphasized)
```

The invariant `opening_balance + period_in − period_out + transfers_net == closing_balance` holds by construction and is **asserted by the document builder**: if it ever fails, the summary adds a visible line "Écart de rapprochement" with the difference instead of printing an unbalanced statement silently (defensive; a test proves the line appears when a stubbed context is inconsistent and never appears on real data). `period_in`/`period_out` are computed from the same rows that are displayed, so they equal the column totals of the table.

For customer/supplier/shareholder the summary is: Solde antérieur, Total débit, Total crédit, Mouvement net de la période (with the statement's sign convention), Solde final — equation `opening + net = closing` checked the same way.

## Per-report definitions

Orientation rule: landscape when a report has ≥ 7 columns with amounts or ≥ 8 columns, and always for margin-report; otherwise portrait.

| Report | Columns (in order) | Orient. | Entity | Summary |
|---|---|---|---|---|
| customer-statement | Date · Type · Référence · Débit · Crédit · Solde | P | Client | opening, Σ débit, Σ crédit, net, closing |
| supplier-statement | same | P | Fournisseur | same |
| shareholder-statement | same | P | Associé | same (credit − debit) |
| bank-statement / cash-statement | Date · Type · Montant · Référence · Solde | P | Compte bancaire / Caisse | opening, Σ entrées, Σ sorties, virements internes (net), closing |
| transporter-statement | Date · Trajet · Montant brut · Retenue · Avance déduite · Montant net | P | Transporteur | Σ of the 4 amounts |
| truck-history | Trajet · Date de chargement · Statut · Qté chargée · Client · Marge | P | Camion (`internal_id` + registrations) | number of trips, Σ qté, Σ marge (trips with a sale) |
| trip-report | Trajet · Date · Statut · Camion · Transporteur · Fournisseur · Produit · Qté · Client | L | — | number of trips, Σ qté |
| purchase-report | Référence · Date · Fournisseur · Produit · Qté · Prix unitaire · Total · Statut | L | Fournisseur if filtered | Σ qté, Σ total, number of orders |
| sales-report | Trajet · Date · Client · Produit · Qté livrée · Prix de vente · Sous-total | L | Client if filtered | Σ qté livrée, Σ sous-total |
| expense-report | Date · Catégorie · Montant · Méthode de calcul · Statut | P | — | Σ montant, number of expenses |
| customer-outstanding / supplier-outstanding / transporter-outstanding | Client·Fournisseur·Transporteur · Montant restant | P | — (`as_of`) | Σ restant, number of parties |
| fuel-stock | Composant · Référence · Quantité | P | — (`as_of`) | Reliquat fournisseurs (Σ), Chargé non vendu (Σ), **Stock théorique total** (= the query's TOTAL row, printed bold as the last table row, never added to the sums); gap line if the two sums ≠ TOTAL |
| loss-report | Trajet · Date de contrôle · Qté chargée · Qté reçue · Perte · Tolérance · Perte facturable · Vérifié le · Notes | L | — | Σ chargée, Σ reçue, Σ perte, Σ perte facturable |
| margin-report | **T1** Trajet · Client · Produit · Qté · Qté chargée · Qté facturée · Perte transporteur (qté) · Perte société (qté) · Prix fournisseur · Prix de vente — **T2** Trajet · Client · Transport · Douane · Transit · Transit routier · Frontière · Chargement · Frais additionnels · Coût réel total — **T3** Trajet · Client · Indemnité transporteur · Perte absorbée · Coût unitaire · Profit unitaire · Marge | L | — | Σ qté chargée, Σ qté facturée, Σ coût réel total, Σ marge |

Notes: the transporter statement label for `advance_applied` is "Avance déduite"; "Frontière" is the label of the `road`/`border` cost (2026-09-08 taxonomy). Customer/supplier "date" columns use the entry date; `verified_at` is rendered as a date, or "—" when not verified. Long text (notes, product, party names) wraps; references and dates do not.

## Arabic / RTL

- **Dependencies:** `arabic-reshaper` and `python-bidi` added to `requirements/base.txt`; `pypdf` added to `requirements/dev.txt` (tests only). A Noto Naskh Arabic Regular + Bold font (SIL OFL) is committed under `apps/reports/assets/fonts/` with its licence file; registered once in `pdf_template`. French/English keep Helvetica.
- `shape(text, lang)` (ar only): `arabic_reshaper.reshape` then `bidi.get_display`, applied to the raw text first, then XML-escaped, then non-Arabic runs wrapped in a Helvetica `<font>` span (escaping before bidi would let it reorder `&lt;`). Numbers, references, dates and money stay LTR runs (isolated) so `23 576 205 XOF` is never reordered — same concern as `formatMoney`'s LRI/PDI wrapping.
- RTL layout: column order reversed, table and paragraphs right-aligned, info/summary grids mirrored, page footer mirrored. Arabic-Indic digits are **not** used (Western digits, consistent with the app).
- User-entered strings (entity/party names, notes, references) are always escaped with `safe_text` before being placed in a `Paragraph`.

## Print (D6)

`ReportSheet` is the only printable region of `ReportsView`.

- A composable `usePrintScope(sheetRef)` is invoked by the Print button. Immediately before `window.print()` it walks from the sheet up to `<body>` and sets `data-print-hidden` on **every sibling that is not on that ancestor chain** (sidebar, topbar, page title, selection zone, toasts/`AlertNotifications`, any future shell element, the `AppAlert`, the "loading" line). It also sets `data-print-chain` on the ancestors. On `afterprint` (and on component unmount, and if `print()` throws) it removes all markers.
- `style.css` print block adds: `[data-print-hidden] { display: none !important }`, `[data-print-chain] { padding: 0 !important; margin: 0 !important; max-width: none !important; overflow: visible !important; border: 0 !important; background: none !important }`, sheet `box-shadow: none; width: auto`.
- `@page` size follows `document.orientation`: a `<style id="report-page-size">` with `@page { size: A4 portrait|landscape; margin: 12mm }` is inserted for the duration of the print and removed after. Table header repeats (`thead { display: table-header-group }`), rows don't split (`tr { break-inside: avoid }`), and the repeated `thead` is what identifies the columns on pages ≥ 2. Browser print has no reliable running title or page numbering, so the backend PDF is the reference for those two.
- The existing generic print rules (`aside, header, .no-print`) stay for the other pages that use `window.print()` (ledgers, quotations).

## Compatibility contract (D3)

Without `?document=1` the response of `GET /api/reports/{type}/` is exactly `{report_type, fields, rows}` with `fields == QueryClass.FIELDS` and rows unchanged (fuel-stock keeps its TOTAL row; margin/loss rows keep all 23 / 9 fields including `verified_at`). Consumers:

- `TripDetail.vue` — `fetchReport('loss-report', {})`, reads `rows[].trip_reference/verified_at/…`.
- `DashboardView.vue` — `fetchReport('loss-report', {from, to})` → `aggregate.ts`.
- `ProfitView.vue` — `fetchReport('margin-report', params)` (`unit_profit`, `current_margin`, …).

Their existing specs must pass unmodified, and new contract tests (below) pin the shape. None of the three consumers uses a statement query, so the deliberate statement `balance` change (opening balance) reaches only the Reports page and `?export=` files.

## Testing

**Backend** (pytest, new files `test_report_document.py`, `test_report_pdf.py`; existing files adapted only where noted):

1. *Header*: for every one of the 17 slugs, `build_report_document` returns title (translated, never the slug), company `AZUR ÉNERGIE`, generated date, period (range / open / as_of as appropriate), currency `XOF`, orientation per the table, translated column labels with no `_` and no raw field name, entity name for the 7 entity reports (and for optional filters when given).
2. *Totals*: per family (financial statements, transporter, purchases/sales, expenses, stock incl. TOTAL row not double-counted, losses, margins, trips, outstanding) — summary values equal the sum of the displayed rows computed independently in the test; CANCELLED exclusion and `cancelled_excluded` line (D7).
3. *Opening balance*: customer/supplier/shareholder with entries before and inside the period: `opening_balance` equals the balance the unfiltered run showed just before `date_from`; first row balance includes it; `opening + net == closing == last row balance`; no `date_from` → opening 0, rows identical to the legacy run; empty period → summary shows opening = closing.
4. *Treasury reconciliation*: account with opening balance, in/out, and a transfer before, inside and after the period: the signed equation holds exactly; `transfers_net` negative case; the "Écart de rapprochement" line appears only for an inconsistent stubbed context.
5. *Empty case*: each of the 17 reports with zero rows → table header kept, `empty_text` present, summary present with zeroes, PDF builds.
6. *Wide tables*: margin-report → 3 tables, every column of `FIELDS` appears in exactly one table (except duplicated trip/client identifiers); landscape; PDF: no column narrower than the minimum, no flowable wider than the frame (checked with `wrap()` on the built table), fonts ≥ 7 pt.
7. *PDF end-to-end* (pypdf): FR — text contains company name, translated title, period and entity, column headers, totals, "Page 1 / n"; multi-page output (≥ 100 rows) repeats header text and title on page 2 with correct total page count; AR — Noto font embedded, extracted text contains Arabic-block/presentation-form characters and no `■` tofu, columns reversed, numbers intact; hostile names (`<img src=x>`, `&`, `<`) do not crash or inject.
8. *Label catalog*: every enum value used by a report exists in fr, en, ar.
9. *Compatibility*: `GET /reports/{type}/` without `document` returns exactly `{report_type, fields, rows}` for all 17 types, with `fields == FIELDS` and rows equal to `query_class.run(...)` output (serialized); `loss-report` and `margin-report` rows include the fields the three consumers read; with `?document=1` the same three keys are identical plus `document`. Existing `test_views.py` / `test_queries*.py` pass except the statement-balance assertions that encoded the old zero-start behaviour (updated deliberately and listed in the plan). Export: `?export=pdf` with and without `lang`, permission and unknown-format behaviours unchanged.
10. *Shared masthead*: `test_ledger_pdf.py` and `test_profit_pdf.py` pass unchanged after adopting `pdf_template`.

**Frontend** (vitest):

1. `ReportSheet.spec.ts`: masthead (company, title, date, period, entity), columns and formatted cells (DD/MM/YYYY, XOF), opening-balance row, summary lines, empty state, portrait vs landscape width class, RTL (`dir="rtl"`, reversed columns) for an `ar` document, several tables (margin).
2. `usePrintScope.spec.ts`: builds a DOM with sidebar/topbar/toast/selection/page-title siblings around the sheet at several depths; after `beforeprint` every off-chain sibling has `data-print-hidden`, the sheet and its ancestors do not; markers and the `@page` style are removed after `afterprint`, on unmount and when `print()` throws.
3. `ReportsView.spec.ts` (existing, adapted): passes `document=1` and `lang`, renders the sheet, print/PDF buttons still gated as before.
4. Compatibility: existing `TripDetail`, `DashboardView`, `ProfitView` specs pass unchanged; a new small spec asserts `fetchReport(type, params)` without options sends no `document`/`lang` params and returns the legacy shape typed as before.

**Manual QA (browser, per the Phase 6 pattern):** generate one report of each family in FR and AR; print preview in portrait and landscape confirms only the sheet prints, header repeats, and no sidebar/topbar/toast; downloaded PDF matches the sheet's structure; a phone-width viewport scrolls the sheet horizontally.

## Files

Backend — new: `services/report_document.py`, `services/report_pdf.py`, `services/pdf_template.py`, `assets/fonts/*` (+ licence), `test_report_document.py`, `test_report_pdf.py`. Modified: `export.py` (remove `rows_to_pdf`), `views/reports.py`, `queries/{customer,supplier,shareholder,treasury}_statement.py`, `services/ledger_pdf.py` and `services/profit_pdf.py` (masthead delegation only), `requirements/{base,dev}.txt`, `test_export.py`, and the statement balance assertions in existing tests.
Frontend — new: `modules/reports/ReportSheet.vue`, `modules/reports/reportCells.ts`, `composables/usePrintScope.ts`, specs. Modified: `ReportsView.vue`, `types.ts`, `api.ts`, `style.css` (print block), `locales` (only the chrome strings already in `reports.*`; report content labels live in the backend).

## Implementation blocks (for the plan)

1. Statement queries: opening balance + treasury `statement_context` + reconciliation (backend only, TDD).
2. `report_document.py` + label catalog + `?document=1` API + compatibility tests.
3. `pdf_template.py` + `report_pdf.py` (FR) + PDF export wiring + masthead delegation in ledger/profit PDFs.
4. Arabic: dependencies, font, shaping, RTL, tests.
5. Frontend: types/api, `ReportSheet.vue`, `ReportsView.vue` wiring, RTL.
6. Print scope: `usePrintScope`, print CSS, `@page`, tests, manual QA.

## Open points for review

- **Language change after generation** does not re-translate a loaded report until it is regenerated (cheap alternative: re-fetch on locale change — not planned).
- **Print vs PDF** are structurally identical but not pixel-identical (D10).

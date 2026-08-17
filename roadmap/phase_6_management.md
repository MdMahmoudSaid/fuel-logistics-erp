# Phase 6 — Management

Spec reference: `docs/ERP_Specification.md` §46 (Phase 6), §3, §32–37, §39.

## Goal

Turn the transactional data from Phases 1–5 into the "one source of truth" management view: theoretical stock, margin/profit at every level, the full dashboard, reports with exports, global search, and system-wide audit history. Almost nothing new is stored here — this phase is aggregation, search indexing, and export plumbing over existing tables.

## Models (`backend/apps/audit`, `backend/apps/reports`)

**`AuditLog`** — `user` (FK), `timestamp`, `action` (`CREATE`/`UPDATE`/`DELETE`/`CANCEL`/`REVERSE`), `content_type`/`object_id` (GenericForeignKey), `previous_value` (JSON), `new_value` (JSON), `reason` (nullable). Populated by a `django-simple-history`-style mixin or explicit signal handlers on the priority models named in §39: quantities, prices, payments, expenses, invoices, losses, bank/cash movements. Validated financial rows are never hard-deleted anywhere in the system (§39) — "delete" actions on `Invoice`, `Expense`, `CustomerPayment`, etc. are modeled as a `CANCELLED` status + reversal entry, and this is enforced at the model layer (`delete()` raises for those types once validated) rather than relying on UI discipline.

**No new domain models for stock/margin/dashboard** — these are service functions + serializers over existing data:

- `theoretical_stock()` = `Σ(SupplierOrder reliquat across active orders)` + `Σ(Trip.quantity_loaded where trip has no Sale yet)` (§32).
- `trip_margin(trip)` = `Sale.delivered_quantity × Sale.selling_price` − `(SupplierOrder.unit_price × Trip.quantity_loaded)` − `Σ(allocated Expenses)` − `TransportPayment.base_amount` (§33). Recomputed on read, not cached, so a late-added `Expense` automatically changes it (§33: "if a new expense is added later, margin recalculates automatically" — this falls out for free by never storing the result).

## API Endpoints

- `GET /api/dashboard/summary/?range=today|yesterday|week|month|year|custom&from=&to=` — returns the full §3 KPI tree (operations, fuel, sales, transport, finance, profit)
- `GET /api/reports/{report_type}/` where `report_type` ∈ the §37 list (customer-statement, supplier-statement, transporter-statement, truck-history, trip-report, purchase-report, sales-report, expense-report, customer-outstanding, supplier-outstanding, transporter-outstanding, fuel-stock, loss-report, margin-report, bank-statement, cash-statement), each accepting the same date-range params, each with `?export=xlsx|pdf|csv`
- `GET /api/search/?q=` — searches tractor/tanker registration, customer, supplier, transporter, BL, invoice, order, cession letter, trip reference in one call; truck matches return current status/trip/product/quantity/customer plus a history link (§36)
- `GET /api/audit-logs/?content_type=&object_id=`

## Vue Components

- `dashboard/DashboardView.vue` — the five KPI groups from §3 as separate cards/panels, shared `DateRangeFilter.vue` component reused across dashboard and every report
- `reports/ReportsView.vue` — report picker + date range + export buttons
- `search/GlobalSearchBar.vue` — omnipresent in `AppShell`, truck hits show the rich inline summary from §36
- `audit/AuditLogViewer.vue` — filterable by entity, mainly for Admin role

## Mandatory Integration Tests

- `theoretical_stock()` matches manual arithmetic across a fixture with several open supplier orders and several unsold loaded trips (§32).
- Adding an `Expense` allocated to an already-`Delivered` trip changes `trip_margin()` on the next read without any explicit recalculation call (§47 "Margin").
- Profit-by-customer / profit-by-truck / profit-by-order rollups sum to the same total as `Σ(trip_margin)` across all trips in the fixture (§34 consistency check).
- Global search for a known tractor registration returns current status, trip, product, quantity, customer, and a non-empty history list (§36).
- Cancelling a `VALIDATED` invoice does not delete the row — it flips to `CANCELLED` and an `AuditLog` entry exists with previous/new value (§39).
- Each of the 16 report types in §37 returns a non-empty response against the test fixture and supports at least one export format.

## Definition of Done (§48 acceptance criteria covered)

- #22 "Calculate theoretical stock."
- #23 "Calculate margin per trip."
- #24 "Calculate total business profit."
- #25 "Search any truck/client/order/payment."
- #26 "Export the important statements."

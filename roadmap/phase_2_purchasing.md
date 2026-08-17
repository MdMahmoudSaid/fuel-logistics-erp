# Phase 2 — Purchasing

Spec reference: `docs/ERP_Specification.md` §46 (Phase 2), §5–7.

## Goal

Model the purchase → cession → reliquat chain: a fuel purchase from a supplier, the cession letters that authorize loading against it, and the running "remaining" balance (reliquat) that must never silently disappear.

## Models (`backend/apps/purchasing`)

**`SupplierOrder`** (the fuel purchase, §5) — `supplier` (FK), `product` (FK), `purchase_date`, `quantity_litres` (`DecimalField(14,2)`), `unit_price` (`DecimalField(14,4)` — sub-unit precision matters at high volumes), `currency` (default `XOF`), `total_amount` (computed = quantity × price, stored + recalculated on save for query performance), `optional_costs` (`DecimalField`, nullable), `notes`, `status` (`DRAFT` / `CONFIRMED` / `CANCELLED`).

**`CessionLetter`** — `reference` (unique), `supplier_order` (FK → `SupplierOrder`), `authorized_quantity`, `issue_date`, `status` (`ACTIVE` / `EXHAUSTED` / `CANCELLED`), `notes`. **No stored `loaded_quantity`/`remaining_quantity` fields** — both are computed properties: `loaded_quantity = Σ(Trip.quantity_loaded where trip.cession_letter = self)`, `remaining_quantity = authorized_quantity − loaded_quantity`. Computing rather than caching avoids the two numbers ever drifting apart, at the cost of a query per read (acceptable at this data volume; revisit with a DB view if it becomes a bottleneck).

Supplier reliquat (§7) is **not a separate model** — it's `SupplierOrder.quantity_litres − Σ(CessionLetter.authorized_quantity for that order)`, exposed as a computed property. Any future cession letter can be issued against that remainder as long as it doesn't exceed it.

## Critical constraint

A `CessionLetter.authorized_quantity` cannot be created/edited such that `Σ(all cession letters' authorized_quantity for this order) > SupplierOrder.quantity_litres`. Enforced in the serializer's `validate()` (not just the DB) so the API returns a clear 400, plus a DB `CheckConstraint` as a last line of defense. Separately, in Phase 3, a `Trip` cannot be created with `quantity_loaded > cession_letter.remaining_quantity` — that check lives in the `Trip` serializer, not here, but depends on this model's computed properties.

## API Endpoints

- `GET|POST /api/supplier-orders/`, `GET|PATCH /api/supplier-orders/{id}/`
- `GET /api/supplier-orders/{id}/reliquat/` — remaining unallocated quantity on this purchase
- `GET|POST /api/cession-letters/`, `GET|PATCH /api/cession-letters/{id}/` (each response includes computed `loaded_quantity` / `remaining_quantity`)
- `GET /api/suppliers/{id}/ledger/` — purchase history + reliquat summary (payments/outstanding join in once Phase 5 exists; this endpoint's shape is fixed here, filled in later)

## Vue Components

- `purchasing/SupplierOrderList.vue`, `SupplierOrderForm.vue`
- `purchasing/CessionLetterList.vue` (nested under an order), `CessionLetterForm.vue` — shows a live authorized/loaded/remaining bar as the user types
- `suppliers/SupplierLedgerView.vue` — purchase history + reliquat per order

## Mandatory Integration Tests

- Creating a cession letter that would exceed `SupplierOrder.quantity_litres` across all its cession letters is rejected with 400.
- §6 worked example: authorized 200,000 L, 180,000 L already loaded (via Phase-3 trips in the test fixture) → remaining computed as 20,000 L, and a further 45,000 L trip is rejected.
- §7 worked example: purchased 1,000,000 L, loaded 990,000 L → reliquat of 10,000 L remains visible on the supplier order and can be drawn down by a later cession letter (§47 "Supplier Reliquat").
- Supplier ledger endpoint returns correct totals across multiple orders.

## Definition of Done (§48 acceptance criteria covered)

- #1 "Register a fuel purchase."
- #2 "Register supplier quantity."
- #3 "Add cession letters."
- #4 "See supplier remaining quantity."

# Phase 3 — Truck Operations

Spec reference: `docs/ERP_Specification.md` §46 (Phase 3), §2, §11–13, §42, §44.

## Goal

Implement the system's central architectural rule: **Truck ≠ Trip ≠ Client Order**. Customer orders are demand envelopes fulfilled by many independently-tracked trips, which may reuse the same physical truck repeatedly. This phase is the highest-risk part of the whole build — get the data model here wrong and every later phase (delivery, sales, finance, margin) inherits the bug.

## Models (`backend/apps/sales` for `CustomerOrder`, `backend/apps/trips` for `Trip`/`TripStatusHistory`)

**`CustomerOrder`** — `customer` (FK), `product` (FK), `quantity_ordered`, `expected_price` (nullable), `status` (`DRAFT` / `CONFIRMED` / `PARTIALLY_ASSIGNED` / `IN_PROGRESS` / `PARTIALLY_DELIVERED` / `DELIVERED` / `CLOSED` / `CANCELLED`), `notes`. `assigned_quantity`, `loaded_quantity`, `delivered_quantity`, `invoiced_quantity`, `remaining_quantity` are **all computed properties aggregated from child `Trip` rows** — never stored, never edited directly. Status transitions between the enum values above are derived from these aggregates by a service function, not set manually by users (prevents an order showing "Delivered" while trips disagree).

**`Trip`** — the record created every time a truck is loaded (§12). Design note: the spec's entity list (§42) names "Loading" separately from "Trip", but §12's field list for a Trip *is* the loading event (quantity loaded, cession letter, BL, loading date) — there is no independent lifecycle for "Loading" apart from "Trip". Modeling them as one table avoids a redundant 1:1 join; if a future requirement needs multi-stage loading (e.g. partial loads across two days), split this table then. Fields: `reference` (unique, auto-generated e.g. `TRIP-000123`), `truck` (FK), `transporter` (FK, defaults from `truck.owner_transporter`), `driver` (FK, nullable), `supplier` (FK), `supplier_order` (FK), `cession_letter` (FK), `product` (FK), `quantity_loaded`, `client` (FK → `Customer`, nullable — a trip can exist without a customer order per §11 Method B), `customer_order` (FK, nullable), `loading_date`, `bl_reference`, `status` (the 14-value enum from §13), `notes`.

**`TripStatusHistory`** — `trip` (FK), `previous_status`, `new_status`, `changed_by` (FK → `User`), `changed_at`, `notes`. **Append-only**: rows are created by a status-transition service method, never edited or deleted. `Trip.status` is a denormalized "current status" field kept in sync by that same service method — the history table is the source of truth for "how did we get here."

## Critical constraints

- Creating a `Trip` validates `quantity_loaded <= cession_letter.remaining_quantity` (from Phase 2's computed property) — reject with 400 otherwise.
- A `Truck` can have at most one `Trip` with an "active" status (anything before `Completed`/`Cancelled`/`Blocked`-resolved) at a time, unless an Admin-role user explicitly overrides (a `force=true` flag on the create endpoint, logged to `AuditLog`).
- Trip status can only move forward through the §13 sequence (or to `Blocked`/`Cancelled` from most states) — enforced by a transition table in the service layer, not left to the client to send arbitrary status values.
- When a trip completes/returns, `truck.status` flips back to `AVAILABLE`, making it eligible for a brand-new `Trip` row — never mutate the old trip.

## API Endpoints

- `GET|POST /api/customer-orders/`, `GET|PATCH /api/customer-orders/{id}/` (response includes computed assigned/loaded/delivered/remaining)
- `GET /api/customer-orders/{id}/trips/` — all trips fulfilling this order
- `GET|POST /api/trips/` (create = loading event), `GET|PATCH /api/trips/{id}/`
- `POST /api/trips/{id}/status/` — body `{new_status, notes}`, validates transition, writes `TripStatusHistory`, updates `Trip.status`
- `GET /api/trips/{id}/history/` — full status timeline
- `GET /api/trucks/{id}/trips/` — full trip history for a physical truck (used by Phase 6 global search too)

## Vue Components

- `sales/CustomerOrderList.vue`, `CustomerOrderForm.vue` — shows Ordered/Assigned/Delivered/Remaining progress bar (§2 dashboard example)
- `trips/TripForm.vue` — loading form; truck picker only shows `AVAILABLE` trucks (with an admin override toggle)
- `trips/TripStatusBoard.vue` — kanban-style view across the 14 statuses for ops staff
- `trips/TripDetail.vue` — trip fields + `TripStatusHistory` timeline, immutable/read-only history list
- `trucks/TruckHistoryView.vue` — all trips for one truck, newest first

## Mandatory Integration Tests

- **§44 worked scenario (mandatory):** a 450,000 L customer order fulfilled by 6 trucks in a first round (270,000 L) and 4 of those same trucks returning for a second round (180,000 L) — assert final `delivered_quantity = 450,000`, `remaining = 0`, `status = COMPLETED`, and that trucks used twice show two fully independent `Trip` rows with distinct references (§47 "Multiple Trucks", "Repeated Truck").
- A truck with an active trip cannot be assigned a second trip without the admin override flag; with the flag, it succeeds and is logged to `AuditLog`.
- `TripStatusHistory` rows are immutable — attempting to edit/delete one via the API is rejected (§13 "never overwrite the historical status").
- A `Trip` created without a `customer_order` (direct sale, §11 Method B) is valid and doesn't error.
- Partial delivery over multiple days: an order stays `PARTIALLY_DELIVERED` until every assigned trip reaches `Delivered`, then flips to `Delivered` (§47 "Partial Delivery").

## Definition of Done (§48 acceptance criteria covered)

- #6 "Create a customer order for several truckloads."
- #7 "Assign several trucks to that order."
- #8 "Reuse the same physical truck for another trip."
- #9 "Track every trip independently."
- #10 "Track border/customs/delivery status."

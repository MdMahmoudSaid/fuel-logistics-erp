# Phase 4 — Delivery & Sales

Spec reference: `docs/ERP_Specification.md` §46 (Phase 4), §14–17, §19–21.

## Goal

Close the loop from "truck arrived" to "invoice raised": record actual received quantity, compute loss against a configurable tolerance, deduct non-tolerated loss from the transporter, and invoice the customer on *received* quantity — never loaded quantity.

## Models (`backend/apps/trips` for `DeliveryControl`, `backend/apps/sales` for `Sale`/`Invoice`, `backend/apps/core` for `LossToleranceConfig`)

**`LossToleranceConfig`** — singleton-style settings row (or per-product override if needed later): `tolerance_litres` (default `100.00`), `updated_by`, `updated_at`. Read by the loss-calculation service, never hardcoded (§15: "must be configurable").

**`DeliveryControl`** — `trip` (FK, one-to-one), `quantity_received`, `control_date`, `controller` (FK → `User`), `method` (free text/choices, e.g. `MANUAL_GAUGE`, `METER`), `photo` (`Document` FK or direct FileField), `notes`, `anomaly_confirmed_by` (FK → `User`, nullable — set only when `quantity_received > trip.quantity_loaded` and an authorized user confirms the anomaly per §15). `loss_litres` and `chargeable_loss_litres` are computed properties: `loss = quantity_loaded - quantity_received` (can be negative, surfaced as the anomaly case above), `chargeable_loss = max(0, loss - tolerance_config.tolerance_litres)`.

**`Sale`** — `trip` (FK, one-to-one — one delivered trip produces exactly one sale line), `customer` (FK), `product` (FK), `delivered_quantity` (copied from `DeliveryControl.quantity_received` at creation time, immutable after — §19 "never automatically invoice loaded quantity"), `selling_price`, `customer_order` (FK, nullable).

**`Invoice`** — `sale` (FK, one-to-one) or, if invoices batch multiple sales, `sales` (M2M) — start with one-to-one per trip since that matches "sale is linked to a trip" (§19) and batching can be layered on without a schema break; `invoice_number` (unique, sequential), `status` (`DRAFT` / `VALIDATED` / `PARTIALLY_PAID` / `PAID` / `CANCELLED`), `total_amount` (computed from quantity × price), `issued_date`. A `VALIDATED` invoice's core fields (quantity, price, total) become read-only at the API layer; any correction must go through an explicit change-log entry (`previous_value`, `new_value`, `user`, `date`, `reason` per §21) rather than a silent update.

## Critical constraints

- `Sale.delivered_quantity` is always sourced from `DeliveryControl.quantity_received`, never from `Trip.quantity_loaded` — enforced by only ever setting it in the service that creates a `Sale` from a completed `DeliveryControl`.
- `DeliveryControl` creation where `quantity_received > quantity_loaded` is blocked by the API (422) unless the request includes `anomaly_confirmed_by`, per §15.
- Once an `Invoice` is `VALIDATED`, direct field edits are rejected by the serializer; use the correction/reason workflow instead.

## API Endpoints

- `GET|POST /api/trips/{id}/delivery-control/` (create triggers loss calculation)
- `GET|PATCH /api/settings/loss-tolerance/`
- `GET|POST /api/sales/`, `GET /api/sales/{id}/`
- `GET|POST /api/invoices/`, `GET /api/invoices/{id}/`, `POST /api/invoices/{id}/validate/`, `POST /api/invoices/{id}/correct/` (body: `field`, `new_value`, `reason`)

## Vue Components

- `trips/DeliveryControlForm.vue` — loaded qty shown read-only, received qty input, live loss/chargeable-loss preview, anomaly confirmation modal when received > loaded
- `trips/LossSummaryBadge.vue` — reusable badge shown on `TripDetail` and dashboards
- `sales/SaleForm.vue` / `InvoiceForm.vue` — price field pre-fills from the product's last selling price (§20), editable by authorized roles, and writes a price-history row on change
- `sales/InvoiceList.vue` — status filter, validate action

## Mandatory Integration Tests

- §14 worked example: loaded 45,000 L, received 44,850 L → `loss_litres = 150`.
- §15 worked example: loss 150 L, tolerance 100 L → `chargeable_loss_litres = 50` (§47 "Quantity Loss").
- `quantity_received > quantity_loaded` without `anomaly_confirmed_by` is rejected; with it, succeeds and is flagged in the response.
- Invoice quantity always equals `DeliveryControl.quantity_received`, confirmed by asserting a `Sale` built from the 45,000/44,850 example invoices exactly 44,850 L, never 45,000 (§47 "Quantity Loss", §19).
- Editing a `VALIDATED` invoice's total directly is rejected; using `/correct/` succeeds and produces an audit-style change record.
- Creating a second sale without changing the previous price defaults to the last-used price for that product.

## Definition of Done (§48 acceptance criteria covered)

- #11 "Record actual delivered quantity."
- #12 "Automatically calculate loss."
- #14 "Invoice based on received quantity."

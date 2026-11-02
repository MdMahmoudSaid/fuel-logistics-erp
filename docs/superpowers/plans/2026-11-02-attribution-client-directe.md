# Attribution directe d'un client — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From Ventes > "Attribuer un client", one popup links trips to a registered or walk-in customer, treats them as arrived, takes the selling price (with cost price + live profit/loss), optionally takes the received quantity, then creates the invoice (and a full cash payment for a walk-in).

**Architecture:** A new backend `DirectSaleService` composes the existing `TripCostService.assign_customers_group_for_sale`, `TripWorkflowService.transition_trip` (skip to ARRIVED_AT_CLIENT) and `DeliveryService.record_delivery` in one `transaction.atomic`. The selling price is parked on the trip (`pending_unit_selling_price`) until the quantity is confirmed, so a deferred trip stays visible as "en attente de quantité". A walk-in is a hidden `Customer` row (`is_walk_in=True`) created per sale. Frontend: `AssignCustomerForm.vue` becomes the multi-step popup; Ventes and Trajets get the "Saisir la quantité reçue" action.

**Tech Stack:** Django REST (apps/trips, apps/customers, apps/finance, apps/sales), Vue 3 + TS + vue-i18n (fr/en/ar), pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-11-02-attribution-client-directe-design.md`

## Global Constraints

- All new UI strings in `frontend/src/locales/fr.json`, `en.json`, `ar.json`.
- Whole submit is atomic: no half state (customer linked but price/status lost) on any error.
- Reuse `DeliveryService.record_delivery`, `TripCostService.calculate_trip_cost_basis`, `CustomerPayment` + `PaymentAllocationService`; do not change margin / distributable-result formulas, invoice numbering, client-verification or refusal flows.
- Below-cost sale still requires `confirm_loss` (`SaleBelowCostConfirmationRequired`).
- One selling price per litre for all trips of one submit.
- Walk-in: never in the customers list, customer selects, receivables or customer reports; invoice fully paid at creation.
- Migrations are applied by fuel-deploy; old prod frontend specs must still type-check (additive fields optional in TS types).
- Stage explicit files only (`git add <file>`), never a directory. Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Backend and frontend suites must stay green.

## Builder-check decisions (implementer's calls, from the spec review)

- Pending state is **per trip**; confirming quantity is per trip. A group's single invoice (and the walk-in payment on it) appears only when the last trip is confirmed.
- The popup quantity is an ordinary initial delivery (`record_delivery` semantics); a later client verification stays possible. In the popup the quantity is capped at the loaded quantity (over-quantity needs the existing anomaly confirmation, not offered here).
- Below-cost: the popup shows the loss state live and asks for confirmation before submit; the backend re-checks at Sale creation (quantity time) against the then-current cost, and requires `confirm_loss` there. The stored price is frozen.
- Walk-in invoice follows the normal lifecycle (DRAFT, validated on completion) with the full payment allocated to it. Task 3's test asserts `get_invoice_outstanding == 0`; if allocating to a DRAFT invoice is refused by the existing code, validate the invoice in the same transaction instead.
- Popup source statuses = `CUSTOMS`, `ARRIVED_AT_COMPANY_STOCK`, `STOCKED` (same as the existing Ventes picker); anything else is a 400.
- `assign_customer_for_sale` / `assign_customers_group_for_sale` clear `pending_unit_selling_price`. No undo UI for a pending trip in this scope.
- No `ProductSellingPriceHistory` entry for walk-in sales (skip in `record_delivery` when `customer.is_walk_in`). Task 2 audit list: customer ledger, receivables/aging, dashboard, global search, statements, "no entity picked" reports.

## Review Focus

- Delivery price below cost with no `confirm_loss`: whole submit rolls back (customer not linked, status unchanged).
- Received quantity ≠ loaded in the same submit: invoice bills the received quantity, not the loaded one.
- Two trips (one invoice group) where only one gets its quantity: no invoice and no walk-in payment yet; both exist only after the last trip is confirmed.
- Walk-in name empty/whitespace, or customer id and walk-in name both given / both missing: 400.
- Trip already having a Sale, or not in CUSTOMS/ARRIVED_AT_COMPANY_STOCK/STOCKED: 400, nothing changed.
- Walk-in payment account omitted when the quantity is confirmed: 400, nothing changed; payment amount equals invoice total (after received-qty adjustment).

---

### Task 1: Data model — walk-in flag and parked price

**Files:**
- Modify: `backend/apps/customers/models.py`, `backend/apps/customers/views.py`, `backend/apps/customers/serializers.py`
- Modify: `backend/apps/trips/models.py`, `backend/apps/trips/serializers.py`
- Create: migrations in `backend/apps/customers/migrations/` and `backend/apps/trips/migrations/`
- Test: `backend/apps/customers/tests.py`, `backend/apps/trips/tests.py`

**Interfaces:**
- Produces: `Customer.is_walk_in: BooleanField(default=False)`; `Trip.pending_unit_selling_price: DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)`; `TripSerializer` exposes `pending_unit_selling_price` (str|null), `client_is_walk_in` (bool), `client_name` (existing `client` display if present — reuse what TripSerializer already returns for the client).

- [ ] **Step 1: Write failing tests** — `test_customer_list_excludes_walk_in`: create Customer(name="A") and Customer(name="Passage", is_walk_in=True); `GET /api/customers/` returns only "A"; `GET /api/customers/{walk_in.id}/` still 200 (invoices/ledger links must keep resolving). `test_trip_serializer_exposes_pending_price_and_walk_in_flag`.
- [ ] **Step 2: Run** `cd backend && pytest apps/customers/tests.py apps/trips/tests.py -k "walk_in or pending_price" -v` → FAIL.
- [ ] **Step 3: Implement** the two fields + migrations; in `CustomerViewSet.get_queryset` exclude `is_walk_in=True` for the `list` action only; add `is_walk_in` read-only to `CustomerSerializer`.
- [ ] **Step 4: Run** same command → PASS; `pytest apps/customers apps/trips -q` stays green.
- [ ] **Step 5: Commit** `git add <the touched files and the 2 migrations>`; `feat(sales): walk-in customer flag and parked selling price on trips`.

### Task 2: Walk-in exclusion in reports and receivables

**Files:**
- Modify: whatever builds customer receivable/customer report lists (grep `Customer.objects` and `get_customer_outstanding` callers in `backend/apps/reports/` and `backend/apps/finance/`).
- Test: next to each modified query.

**Interfaces:** Consumes `Customer.is_walk_in` (Task 1). Produces: no walk-in in any customer listing/aggregate of receivables (invoices themselves still appear in sales/invoice reports and profit).

- [ ] **Step 1: Failing test** `test_receivables_report_ignores_walk_in`: a walk-in with a fully paid invoice and a registered customer with an open invoice; report lists only the registered customer. Add the same assertion for the customer picker data endpoints found by the grep.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `.filter(is_walk_in=False)` at each customer-enumeration site (not at invoice-level queries).
- [ ] **Step 4: Run** `pytest apps/reports apps/finance -q` → PASS.
- [ ] **Step 5: Commit** `fix(reports): walk-in customers never listed as customers or receivables`.

### Task 3: `DirectSaleService`

**Files:**
- Create: `backend/apps/trips/direct_sale.py`
- Test: `backend/apps/trips/test_direct_sale.py`

**Interfaces:**
- Consumes: Task 1 fields; `TripCostService.assign_customers_group_for_sale(trip_ids, customer_id, actor)`; `TripWorkflowService.transition_trip(trip_id, Trip.Status.ARRIVED_AT_CLIENT, actor)` (skipping allowed from CUSTOMS/ARRIVED_AT_COMPANY_STOCK/STOCKED); `DeliveryService.record_delivery(...)`; the CustomerPayment creation + `PaymentAllocationService.allocate_payment` path that the customer-payment endpoint uses (reuse the same service/serializer logic so the TreasuryTransaction is posted; do not hand-write treasury rows).
- Produces:
  - `DirectSaleService.assign_and_arrive(trip_ids: list[int], *, customer_id: int | None, walk_in_name: str | None, unit_selling_price: Decimal, received_quantities: dict[int, Decimal] | None, payment_destination: dict | None, confirm_loss: bool, actor) -> list[Trip]`
  - `DirectSaleService.confirm_received_quantity(trip_id: int, received_quantity: Decimal, *, payment_destination: dict | None, confirm_loss: bool, actor) -> Trip`
  - `payment_destination` = `{"destination": "BANK"|"CASH", "bank_account": id|None, "cash_account": id|None}` (same shape `CustomerPaymentSerializer` takes); `method` = BANK_TRANSFER for BANK, CASH for CASH.

- [ ] **Step 1: Failing tests** in `test_direct_sale.py` (fixtures from `apps/trips/tests.py` helpers):
  - `test_registered_customer_deferred_quantity`: trip STOCKED → after `assign_and_arrive(..., received_quantities=None)` trip.client set, status ARRIVED_AT_CLIENT, `pending_unit_selling_price == price`, no Sale, no Invoice.
  - `test_registered_customer_with_quantity_creates_invoice`: with `received_quantities={trip.id: Decimal("44900.00")}` → Sale.delivered_quantity == 44900, invoice total == 44900 × price, status DELIVERED.
  - `test_walk_in_creates_hidden_customer_and_full_cash_payment`: `walk_in_name="Moussa"`, quantity given, `payment_destination={"destination":"CASH","cash_account":ca.id}` → Customer(name="Moussa", is_walk_in=True); one CustomerPayment amount == invoice total allocated fully (`get_invoice_outstanding == 0`); treasury transaction exists on that cash account.
  - `test_walk_in_deferred_then_confirm_pays_on_confirm`: deferred submit makes no payment; `confirm_received_quantity` with destination creates invoice + payment.
  - `test_group_invoice_and_payment_only_after_last_trip`: two trips one group; confirming the first creates no invoice/payment; confirming the second does (walk-in paid for the grouped total).
  - `test_below_cost_without_confirm_loss_rolls_back`: raises `SaleBelowCostConfirmationRequired`; `trip.client` None and status unchanged.
  - `test_validation_errors`: both/neither of `customer_id`/`walk_in_name`; blank walk-in name; trip with a Sale; trip in LOADED; walk-in quantity confirm without `payment_destination` → `ValueError`, nothing changed.
- [ ] **Step 2: Run** `pytest apps/trips/test_direct_sale.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** the two static methods, each `@transaction.atomic`, lock trips with `select_for_update`. Flow of `assign_and_arrive`: validate → get-or-create customer (walk-in: `Customer.objects.create(name=walk_in_name.strip(), is_walk_in=True)`) → assign group (group token only when 2+ trips) → set `pending_unit_selling_price` → transition each trip to ARRIVED_AT_CLIENT → if `received_quantities` given, call `confirm_received_quantity` for each trip. `confirm_received_quantity`: `DeliveryService.record_delivery(trip_id, received_qty=..., control_date=today, method=DeliveryMethod MANUAL_GAUGE, controller=actor, unit_selling_price=trip.pending_unit_selling_price, confirm_loss=...)`; clear `pending_unit_selling_price`; then, if the trip's customer is walk-in and the Sale's invoice now exists (single trip, or group fully billed), create the full-amount CustomerPayment allocated to that invoice. Raise `ValueError` with French messages like the neighbouring services.
- [ ] **Step 4: Run** same → PASS.
- [ ] **Step 5: Commit** `feat(trips): DirectSaleService assigns, arrives, delivers and cashes a walk-in in one transaction`.

### Task 4: API endpoints

**Files:**
- Modify: `backend/apps/trips/views.py`, `backend/apps/trips/serializers.py`
- Test: `backend/apps/trips/test_direct_sale.py` (API section)

**Interfaces:**
- Consumes: Task 3 service.
- Produces:
  - `POST /api/trips/direct-sale/` body `{trips:[ids], customer?:id, walk_in_name?:str, unit_selling_price:str, received_quantities?:{"<tripId>":"<qty>"}, payment_destination?:{...}, confirm_loss?:bool}` → 200 list of `TripSerializer`; `ValueError`/service errors → 400 `{detail}`; `SaleBelowCostConfirmationRequired` → 409-or-the-code the delivery-control endpoint already uses for the same error (copy that mapping).
  - `POST /api/trips/{id}/confirm-received-quantity/` body `{received_quantity, payment_destination?, confirm_loss?}` → 200 `TripSerializer`.
  - Both use the same permission tier as `assign_customer` (operations/edit; check `ACTION_MAP` in `backend/apps/accounts/permissions.py` and add the two action names beside `assign_customer`).

- [ ] **Step 1: Failing tests**: `test_direct_sale_endpoint_registered_and_walk_in` (200 + trip/customer state), `test_direct_sale_endpoint_forbidden_without_operations_edit` (403), `test_confirm_received_quantity_endpoint`, `test_direct_sale_below_cost_returns_confirmation_error`.
- [ ] **Step 2: Run** `pytest apps/trips/test_direct_sale.py -k endpoint -v` → FAIL.
- [ ] **Step 3: Implement** request serializers `DirectSaleRequestSerializer` / `ConfirmReceivedQuantityRequestSerializer` and the two actions; add the permission map entries.
- [ ] **Step 4: Run** `pytest apps/trips apps/accounts -q` → PASS.
- [ ] **Step 5: Commit** `feat(trips): direct-sale and confirm-received-quantity endpoints`.

### Task 5: Frontend API layer and types

**Files:**
- Modify: `frontend/src/modules/trips/api.ts`, `frontend/src/modules/trips/types.ts`
- Test: `frontend/src/modules/trips/__tests__/` (api spec if one exists, else covered in Task 6 spec)

**Interfaces:**
- Produces in `api.ts`: `postDirectSale(payload: DirectSalePayload): Promise<Trip[]>`, `confirmReceivedQuantity(tripId: number, payload: ConfirmQuantityPayload): Promise<Trip>`; types `DirectSalePayload`, `ConfirmQuantityPayload`, `PaymentDestination = { destination: 'BANK' | 'CASH'; bank_account?: number; cash_account?: number }`; `Trip` gains optional `pending_unit_selling_price?: string | null`, `client_is_walk_in?: boolean`.
- [ ] **Step 1: Failing test** that `postDirectSale` POSTs to `/trips/direct-sale/` with the payload (mock `apiClient`, same style as existing api specs).
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/modules/trips` → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(trips): frontend api for direct sale`.

### Task 6: The popup — `AssignCustomerForm.vue`

**Files:**
- Modify: `frontend/src/modules/trips/AssignCustomerForm.vue` (used by `SaleList.vue` and `TripDetail.vue`), `frontend/src/modules/sales/SaleList.vue`, locale files `fr.json`, `en.json`, `ar.json`
- Test: `frontend/src/modules/trips/__tests__/AssignCustomerForm.spec.ts`

**Interfaces:** Consumes `postDirectSale`, `fetchTripCostBasis`, `fetchSuggestedSellingPrice` (needs a customer: only call it for a registered customer), `SearchableSelect`, `formatUnitMoney`, the bank/cash account pickers used by `CustomerPaymentForm`/`PaymentAllocationForm` (reuse, do not rebuild).

- [ ] **Step 1: Failing tests** (names and assertions):
  - `shows walk-in option and name field only`: options include `trips.assignCustomer.walkIn`; choosing it shows one name input and no other customer field.
  - `shows single cost line with eye toggle`: after a customer is chosen a "Prix de revient" total is visible and the component rows (e.g. "Douane") are NOT in the DOM; clicking `[data-test="cost-eye"]` reveals them.
  - `live profit and loss`: price below cost shows the loss state; above shows profit (per litre and total).
  - `submit without quantity calls postDirectSale with no received_quantities`; `submit with quantity sends received_quantities` keyed by trip id.
  - `walk-in with quantity requires an account`: the confirm button is disabled until an account is picked; payload carries `payment_destination`.
  - `below-cost submit sends confirm_loss only after the user confirms`.
- [ ] **Step 2: Run** `npx vitest run src/modules/trips/__tests__/AssignCustomerForm.spec.ts` → FAIL.
- [ ] **Step 3: Implement** the form: customer select + walk-in name; cost line (single trip: that trip's cost basis; several: quantity-weighted average computed client-side from each trip's `fetchTripCostBasis`); price input; profit/loss; per-trip "Quantité reçue" (default loaded, optional toggle "Quantité plus tard"); walk-in account picker shown only when a quantity is entered; on success emit `success` and in `SaleList.onCustomerAssigned` stay on Ventes (reload list) instead of navigating to the trip page.
- [ ] **Step 4: Run** the spec → PASS; `npx vitest run` for `sales` and `trips` modules green.
- [ ] **Step 5: Commit** `feat(sales): attribute-client popup with walk-in, cost price, selling price and received quantity`.

### Task 7: Pending-quantity rows and the "Saisir la quantité reçue" action

**Files:**
- Modify: `frontend/src/modules/sales/SaleList.vue`, `frontend/src/modules/trips/TripDetail.vue`, `frontend/src/modules/trips/TripCard.vue` (board badge), locale files; create `frontend/src/modules/trips/ConfirmQuantityForm.vue`
- Test: `frontend/src/modules/sales/__tests__/SaleList.spec.ts`, `frontend/src/modules/trips/__tests__/ConfirmQuantityForm.spec.ts`

**Interfaces:** Consumes `confirmReceivedQuantity`; produces `ConfirmQuantityForm` props `{ tripId: number; quantityLoaded: string; isWalkIn: boolean }`, emits `success`.

- [ ] **Step 1: Failing tests**: `SaleList lists trips awaiting quantity` (trip with `status ARRIVED_AT_CLIENT`, client set, `pending_unit_selling_price` set, no sale → row labelled `sales.saleList.awaitingQuantity` with a button `[data-test="enter-quantity"]`); `ConfirmQuantityForm posts the quantity (and account only for walk-in)`; `TripDetail shows the same button for such a trip`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; the Ventes pending rows come from the trips list filtered client-side like `openAssignModal` does, shown above/inside the sales table. **Step 4: Run** the specs → PASS.
- [ ] **Step 5: Commit** `feat(sales): deferred received-quantity action on Ventes, Trajets and trip detail`.

### Task 8: Verification and QA

- [ ] **Step 1:** `cd backend && pytest -q` all green; `cd frontend && npx vitest run` all green (note `vue-tsc -b` is a known pre-existing failure — compare, do not fix).
- [ ] **Step 2:** Browser QA (local test DB + Playwright/Chrome recipe from project memory): (a) registered customer + quantity in popup → invoice; (b) registered customer, deferred → row stays on Ventes and Trajets → button → invoice; (c) walk-in with cash account → invoice fully paid, treasury movement, walk-in absent from Clients; (d) below-cost warning; (e) two trucks one invoice.
- [ ] **Step 3:** Fix anything found, re-run suites, commit with explicit file paths.

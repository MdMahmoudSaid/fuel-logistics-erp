# Corrections recette client (2026-09-04) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 6 independent client-validated corrections: 2-decimal per-truck unit-cost display, a simplified delivery workflow with a post-delivery client-verification/loss step, a corrected additive "fond de roulement" formula, a corrected "résultat distribuable" profit figure, print/PDF export on the 3 party ledgers, and removal of mandatory-proof validation across 5 flows.

**Architecture:** Six independently-shippable corrections sharing one plan and one branch history (one commit per task). No new apps, no schema rewrites — additive fields/services on top of existing `TripWorkflowService`/`DeliveryService`/`TripProfitService`/`ControlledDebtPaymentService`/`ShareholderContributionService`.

**Tech Stack:** Django 5 / DRF (`backend/apps/{trips,finance,reports}`), Vue 3 `<script setup>` + Vitest (`frontend/src/modules/{trips,finance,dashboard}`), pytest-django, reportlab (already a dependency).

**Spec:** `docs/superpowers/specs/2026-09-04-recette-corrections-design.md` — read it alongside this plan; it carries the validated business rules, the current-state investigation, and the rulings this plan implements. Also read `docs/superpowers/specs/2026-09-02-business-corrections-6-phases-design.md` for historical context on the code this plan replaces (old `working_capital`/`profit_after_capital` formulas) — do not re-implement anything from that older spec that this plan supersedes.

## Global Constraints

- Never touch `TripCostService`'s cost-computation formulas (`backend/apps/trips/services.py`) — Section 1 is display-only.
- Never make `Sale.delivered_quantity`/`Invoice.total_amount` editable after creation — Section 2's loss correction flows through `TripProfitService`'s margin computation, never through mutating `Sale`.
- `LossToleranceConfig` stays the single configurable tolerance mechanism (already defaults to 100.00) — never hardcode a second 100 L constant anywhere.
- `working_capital.total` (Section 3) and `distributable_result` (Section 4) fully **replace** the old net/signed `working_capital` and `profit_after_capital` — do not keep both old and new figures displayed side by side anywhere.
- Every "attachment optional" change (Section 6) must keep existing file-type/size validation intact when a file **is** provided — only the "must provide one" requirement is removed.
- Section 5 (PDF/print) must not change any business calculation — it only formats/exports data already returned by existing `get_ledger()` services.
- Test suite commands: backend `cd backend && python manage.py test <app>` (or `pytest` if configured — check `backend/pytest.ini`/`setup.cfg` first); frontend `cd frontend && npm run test:unit -- <pattern>` (verify exact script name in `frontend/package.json` before first use).

---

## File Structure

- **Modify** `frontend/src/utils/currency.ts` — `formatUnitMoney` → 2 decimals.
- **Modify** `frontend/src/modules/trips/DeliveryControlForm.vue`, `TripDetail.vue`, `frontend/src/modules/finance/ExpenseForm.vue` — use the corrected formatter.
- **Modify** `backend/apps/trips/services.py` — `TripWorkflowService.FORWARD_TRANSITIONS`, `DeliveryService.record_delivery` (optional `received_qty`), `DeliveryService.sync_transport_shortage_deduction` (tolerance fix), new `DeliveryService.record_client_verification`.
- **Modify** `backend/apps/trips/models.py` — `DeliveryControl`: add `verified_at`, add `company_absorbed_loss_quantity` property.
- **Create** `backend/apps/trips/migrations/00XX_deliverycontrol_verified_at.py`.
- **Modify** `backend/apps/trips/serializers.py` — `DeliveryControlRequestSerializer.received_quantity` optional; new `ClientVerificationRequestSerializer`.
- **Modify** `backend/apps/trips/views.py` — `TripViewSet.delivery_control` passes optional qty; new `TripViewSet.client_verification` action.
- **Modify** `backend/apps/reports/services/profit.py` — `TripProfitService.get_cost_breakdown` subtracts company-absorbed loss.
- **Create** `frontend/src/modules/trips/ClientVerificationForm.vue`; **Modify** `frontend/src/modules/trips/TripDetail.vue`, `frontend/src/modules/trips/api.ts`, `frontend/src/modules/trips/types.ts`.
- **Modify** `backend/apps/finance/services.py` — new `WorkingCapitalService`; `ShareholderProfitPreviewService.get_preview` uses it for `distributable_result`.
- **Modify** `backend/apps/reports/views/dashboard.py` — `working_capital` via `WorkingCapitalService`; `shareholders_summary["distributable_result"]`.
- **Modify** `frontend/src/modules/finance/ProfitView.vue`, `frontend/src/modules/dashboard/DashboardView.vue`, `frontend/src/modules/dashboard/types.ts`, `frontend/src/modules/finance/types.ts`.
- **Create** `backend/apps/reports/services/ledger_pdf.py`. **Modify** `backend/apps/suppliers/views.py` (or wherever `SupplierViewSet.ledger` lives), transporter/customer ledger views, `frontend/src/modules/finance/{SupplierLedgerView,TransporterLedgerView,CustomerLedgerView}.vue` (paths to confirm in Task 12), `frontend/src/modules/finance/api.ts`.
- **Modify** `backend/apps/finance/serializers.py` — remove 4 mandatory-attachment blocks; `backend/apps/finance/services.py` — `ShareholderContributionService.record_contribution` document optional.
- **Modify** `frontend/src/modules/finance/{AdvanceForm,ContributionForm,DebtPaymentForm}.vue` — remove required-file gating.

---

# Section 1 — Frais par camion : affichage 2 décimales

## Task 1: `formatUnitMoney` — 2 décimales

**Files:**
- Modify: `frontend/src/utils/currency.ts`
- Modify: `frontend/src/modules/trips/DeliveryControlForm.vue`, `frontend/src/modules/trips/TripDetail.vue`, `frontend/src/modules/finance/ExpenseForm.vue`
- Test: `frontend/src/utils/__tests__/currency.spec.ts` (create if it doesn't exist — check first)

**Interfaces:**
- Produces: `formatUnitMoney(value: string | number): string` — unchanged signature, now renders 2 decimals with a French comma separator, e.g. `formatUnitMoney(0.2222)` → `"0,22 XOF/L"`, `formatUnitMoney(810)` → `"810,00 XOF/L"`.
- Consumes (unchanged): `formatMoney`, `formatQuantity`, `formatMoneyParts`, `formatQuantityParts` — none of these change; only `formatUnitMoney` changes.

- [ ] **Step 1: Write the failing test**

Check whether `frontend/src/utils/__tests__/currency.spec.ts` already exists (`ls frontend/src/utils/__tests__/`). If it exists, add to it; otherwise create it:

```ts
import { describe, expect, it } from 'vitest'
import { formatUnitMoney, formatMoney, formatQuantity } from '../currency'

describe('formatUnitMoney', () => {
  it('renders 2 decimals with a comma separator, not rounded to 0', () => {
    // 10 000 XOF / 45 000 L = 0.2222... XOF/L
    expect(formatUnitMoney(10000 / 45000)).toContain('0,22')
  })

  it('still renders whole values with 2 decimals', () => {
    expect(formatUnitMoney(810)).toContain('810,00')
  })
})

describe('formatMoney / formatQuantity (unchanged, still integer-rounded)', () => {
  it('formatMoney stays rounded to 0 decimals', () => {
    expect(formatMoney(23576205.6)).not.toContain(',')
  })
  it('formatQuantity stays rounded to 0 decimals', () => {
    expect(formatQuantity(45000.4)).not.toContain(',')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/utils/__tests__/currency.spec.ts`
Expected: FAIL on the `formatUnitMoney` cases (currently rounds to `0 XOF/L` and `810 XOF/L`).

- [ ] **Step 3: Implement**

In `frontend/src/utils/currency.ts`, add a decimal-aware formatter and use it only for `formatUnitMoney`:

```ts
function formatDecimal(value: number, decimals: number): string {
  return value
    .toLocaleString('fr-FR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    .replace(THOUSANDS_SEPARATOR_RE, ' ')
}
```

Replace the body of `formatUnitMoney` (currently `return isolateLtr(\`${formatInteger(toNumber(value))} ${CURRENCY}/L\`)`):

```ts
/** `0,22 XOF/L` — 2 decimals, never rounded to a whole unit (per-litre costs
 * are frequently sub-1-XOF, e.g. a 10 000 XOF "par camion" fee on 45 000 L). */
export function formatUnitMoney(value: string | number): string {
  return isolateLtr(`${formatDecimal(toNumber(value), 2)} ${CURRENCY}/L`)
}
```

Do not touch `formatMoney`, `formatQuantity`, `formatMoneyParts`, `formatQuantityParts` — they keep calling `formatInteger`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/utils/__tests__/currency.spec.ts`
Expected: PASS.

- [ ] **Step 5: Wire the fixed formatter into the 3 remaining call sites**

- `frontend/src/modules/finance/ExpenseForm.vue:267-272` — `perTruckUnitCost` currently does its own `(amount / quantity).toFixed(4)` display, bypassing `formatUnitMoney`. Leave the 4-decimal computed value as-is (it's a live preview during typing, more precision there is fine and already works), but confirm the displayed string still reads correctly (no change required if it already shows decimals — this step is a verification, not necessarily an edit).
- `frontend/src/modules/trips/TripDetail.vue:753,764` (`formatUnitMoney(margin.unit_cost)`, `formatUnitMoney(margin.unit_profit)`) — no code change needed, they already call `formatUnitMoney`; just confirm visually (or via existing component test) that they now render 2 decimals.
- `frontend/src/modules/trips/DeliveryControlForm.vue` `resultText`/`componentRows` — same: already calls `formatUnitMoney`, no code change, just re-run `DeliveryControlForm.spec.ts` (if it exists) to confirm no snapshot breaks.

Run: `cd frontend && npx vitest run src/modules/trips/__tests__/ src/modules/finance/__tests__/ExpenseForm.spec.ts` — fix any snapshot/assertion that hardcoded the old 0-decimal format.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/utils/currency.ts frontend/src/utils/__tests__/currency.spec.ts
git commit -m "fix(frontend): show per-litre costs with 2 decimals instead of rounding to 0"
```

If Step 5 required snapshot fixes in other files, commit those separately:
```bash
git add frontend/src/modules/trips/__tests__/ frontend/src/modules/finance/__tests__/ExpenseForm.spec.ts
git commit -m "test(frontend): update snapshots for 2-decimal unit-cost display"
```

---

# Section 2 — Livraison directe + vérification client / perte

## Task 2: Backend — livraison directe (skip `QUANTITY_CONTROL`), `received_qty` optionnel

**Files:**
- Modify: `backend/apps/trips/services.py` (`TripWorkflowService.FORWARD_TRANSITIONS`, `DeliveryService.record_delivery`)
- Modify: `backend/apps/trips/serializers.py` (`DeliveryControlRequestSerializer.received_quantity`)
- Modify: `backend/apps/trips/views.py` (`TripViewSet.delivery_control`)
- Test: `backend/apps/trips/tests/test_delivery.py` (or wherever existing delivery tests live — `grep -rl "record_delivery" backend/apps/trips/tests/` to confirm the file)

**Interfaces:**
- Produces: `DeliveryService.record_delivery(trip_id, *, received_qty=None, control_date, method, controller, anomaly_confirmed_by=None, document=None, notes="", unit_selling_price=None, confirm_loss=False)` — every parameter after `trip_id` becomes keyword-only (`*` marker) so adding a default to `received_qty` cannot silently shift any other parameter's meaning; the existing call site (`TripViewSet.delivery_control`, `views.py:259-269`) already calls this method entirely by keyword, so it needs no change beyond Step 3 below. **Before implementing, grep `record_delivery(` across the whole `backend/` tree and confirm no other caller uses positional args** — if one does, convert it to keyword args in the same commit.
- Consumes: `Trip.Status.ARRIVED_AT_CLIENT`, `Trip.Status.DELIVERED` (unchanged enum values).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_arrived_at_client_can_go_directly_to_delivered():
    trip = _make_trip_at_status(Trip.Status.ARRIVED_AT_CLIENT)  # use existing trip factory/helper
    allowed = TripWorkflowService.get_allowed_targets(trip)
    assert Trip.Status.DELIVERED in allowed
    assert Trip.Status.QUANTITY_CONTROL not in allowed


@pytest.mark.django_db
def test_record_delivery_defaults_received_qty_to_loaded_quantity():
    trip = _make_trip_at_status(Trip.Status.ARRIVED_AT_CLIENT)  # quantity_loaded=45000, has a client
    _seed_selling_price(trip)  # existing test helper for ProductSellingPriceHistory
    control = DeliveryService.record_delivery(
        trip_id=trip.id,
        control_date=date.today(),
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=_make_user(),
        unit_selling_price=Decimal("850.0000"),
    )
    assert control.received_quantity == trip.quantity_loaded
    assert control.loss_quantity == Decimal("0.00")
    assert control.chargeable_loss_quantity == Decimal("0.00")
```

Read the existing delivery test file first for the actual trip/user factory helpers already in use (`_make_trip_at_status` above is illustrative — use whatever helper the file already defines, e.g. it may be named differently and take different args).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python manage.py test apps.trips.tests.test_delivery -v 2` (adjust module path to the real test file found in Step 1)
Expected: FAIL — `QUANTITY_CONTROL` still in allowed targets; `record_delivery()` still requires `received_qty` positionally/as a required kwarg.

- [ ] **Step 3: Implement**

In `backend/apps/trips/services.py`, `TripWorkflowService.FORWARD_TRANSITIONS` (currently lines 325-340):

```python
FORWARD_TRANSITIONS = {
    Trip.Status.ASSIGNED: Trip.Status.SENT_FOR_LOADING,
    Trip.Status.SENT_FOR_LOADING: Trip.Status.LOADING,
    Trip.Status.LOADING: Trip.Status.LOADED,
    Trip.Status.LOADED: Trip.Status.ROAD_TRANSIT,
    Trip.Status.ROAD_TRANSIT: Trip.Status.IN_TRANSIT,
    Trip.Status.IN_TRANSIT: Trip.Status.BORDER,
    Trip.Status.BORDER: Trip.Status.CUSTOMS,
    Trip.Status.CUSTOMS: Trip.Status.GOING_TO_CLIENT,
    Trip.Status.GOING_TO_CLIENT: Trip.Status.ARRIVED_AT_CLIENT,
    # Client correction (2026-09-04 recette): quantity control is no longer
    # a mandatory gate before delivery - a trip is delivered directly from
    # ARRIVED_AT_CLIENT, defaulting to "full quantity received". The
    # QUANTITY_CONTROL entry below stays mapped for any trip that predates
    # this change and is still sitting at that status - it is otherwise
    # unreachable going forward.
    Trip.Status.ARRIVED_AT_CLIENT: Trip.Status.DELIVERED,
    Trip.Status.QUANTITY_CONTROL: Trip.Status.DELIVERED,
    Trip.Status.DELIVERED: Trip.Status.COMPLETED,
    Trip.Status.GOING_TO_COMPANY_STOCK: Trip.Status.ARRIVED_AT_COMPANY_STOCK,
    Trip.Status.ARRIVED_AT_COMPANY_STOCK: Trip.Status.STOCKED,
}
```

`DeliveryService.record_delivery` signature and body (currently lines 507-520 for the signature, 541-549 for the anomaly check):

```python
@staticmethod
@transaction.atomic
def record_delivery(
    trip_id,
    *,
    received_qty: Decimal | None = None,
    control_date,
    method,
    controller,
    anomaly_confirmed_by=None,
    document=None,
    notes="",
    unit_selling_price: Decimal | None = None,
    confirm_loss: bool = False,
) -> DeliveryControl:
    trip = Trip.objects.select_for_update().get(pk=trip_id)

    if received_qty is None:
        received_qty = trip.quantity_loaded

    if received_qty > trip.quantity_loaded and anomaly_confirmed_by is None:
        raise DeliveryAnomalyConfirmationRequired(
            f"La quantite recue ({received_qty} L) depasse la quantite "
            f"chargee ({trip.quantity_loaded} L) pour le trajet "
            f"{trip.reference} ; une confirmation par un utilisateur "
            "autorise (anomaly_confirmed_by) est requise."
        )
    ...
```

(rest of the method body is unchanged — only the signature and the `received_qty is None` default line are new). **Do not reorder existing keyword arguments used positionally by any caller** — grep `record_delivery(` across `backend/` first and update any positional caller to keyword form if needed.

In `backend/apps/trips/serializers.py`, `DeliveryControlRequestSerializer.received_quantity` (currently lines 326-328):

```python
received_quantity = serializers.DecimalField(
    max_digits=14, decimal_places=2, min_value=Decimal("0"),
    required=False, allow_null=True,
)
```

In `backend/apps/trips/views.py`, `TripViewSet.delivery_control` (currently line 261, `received_qty=data["received_quantity"]`):

```python
received_qty=data.get("received_quantity"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python manage.py test apps.trips.tests.test_delivery -v 2`
Expected: PASS.

- [ ] **Step 5: Run the full trips test suite (this touches a shared workflow map)**

Run: `cd backend && python manage.py test apps.trips -v 2`
Expected: PASS — fix any test that asserted `QUANTITY_CONTROL` was the only allowed target from `ARRIVED_AT_CLIENT`, or that called `record_delivery` relying on `received_qty` being required.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/trips/services.py backend/apps/trips/serializers.py backend/apps/trips/views.py backend/apps/trips/tests/
git commit -m "feat(trips): deliver directly from ARRIVED_AT_CLIENT, defaulting to full quantity received"
```

## Task 3: Backend — fix `sync_transport_shortage_deduction` tolerance bug + `record_client_verification`

**Files:**
- Modify: `backend/apps/trips/models.py` (`DeliveryControl`)
- Create: `backend/apps/trips/migrations/00XX_deliverycontrol_verified_at.py`
- Modify: `backend/apps/trips/services.py` (`DeliveryService.sync_transport_shortage_deduction`, new `record_client_verification`)
- Modify: `backend/apps/trips/serializers.py`, `backend/apps/trips/views.py`
- Test: same test file as Task 2

**Interfaces:**
- Consumes: `DeliveryControl.chargeable_loss_quantity` (existing, recomputed by `save()`), `LossToleranceConfig.get_current_tolerance()` (existing).
- Produces: `DeliveryControl.verified_at` (`DateField`, nullable), `DeliveryControl.company_absorbed_loss_quantity` (property, `Decimal`), `DeliveryService.record_client_verification(trip_id, received_qty, verified_at, actor, notes="") -> DeliveryControl`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_sync_transport_shortage_deduction_respects_tolerance():
    # loss of 80L (<= 100L tolerance): must NOT create/charge a TransportDeduction
    trip = _make_delivered_trip(quantity_loaded=Decimal("45000.00"))
    DeliveryService.sync_transport_shortage_deduction(
        trip=trip, received_qty=Decimal("44920.00"), unit_selling_price=Decimal("850.0000")
    )
    assert not TransportDeduction.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_sync_transport_shortage_deduction_charges_only_above_tolerance():
    # loss of 150L: only 50L (150 - 100 tolerance) must be charged
    trip = _make_delivered_trip(quantity_loaded=Decimal("45000.00"))
    DeliveryService.sync_transport_shortage_deduction(
        trip=trip, received_qty=Decimal("44850.00"), unit_selling_price=Decimal("850.0000")
    )
    deduction = TransportDeduction.objects.get(trip=trip)
    assert deduction.chargeable_quantity == Decimal("50.00")


@pytest.mark.django_db
def test_record_client_verification_80L_loss_company_absorbs():
    trip = _make_delivered_trip(quantity_loaded=Decimal("45000.00"))  # delivered with full qty by default
    control = DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44920.00"),
        verified_at=date.today(), actor=_make_user(), notes="Ecart signale par le client",
    )
    assert control.loss_quantity == Decimal("80.00")
    assert control.chargeable_loss_quantity == Decimal("0.00")
    assert control.company_absorbed_loss_quantity == Decimal("80.00")
    assert not TransportDeduction.objects.filter(trip=trip).exists()


@pytest.mark.django_db
def test_record_client_verification_150L_loss_splits_company_and_transporter():
    trip = _make_delivered_trip(quantity_loaded=Decimal("45000.00"))
    control = DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44850.00"),
        verified_at=date.today(), actor=_make_user(),
    )
    assert control.company_absorbed_loss_quantity == Decimal("100.00")
    assert control.chargeable_loss_quantity == Decimal("50.00")
    deduction = TransportDeduction.objects.get(trip=trip)
    assert deduction.chargeable_quantity == Decimal("50.00")


@pytest.mark.django_db
def test_record_client_verification_rejected_on_cancelled_trip():
    trip = _make_trip_at_status(Trip.Status.CANCELLED)
    with pytest.raises(ValueError):
        DeliveryService.record_client_verification(
            trip_id=trip.id, received_qty=Decimal("44000.00"),
            verified_at=date.today(), actor=_make_user(),
        )
```

Use whichever trip-factory helpers the existing test file already defines for "delivered trip with a Sale" (`_make_delivered_trip` above is illustrative) — read the file first.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python manage.py test apps.trips.tests.test_delivery -v 2`
Expected: FAIL — `sync_transport_shortage_deduction` currently charges the full missing quantity; `record_client_verification` doesn't exist yet.

- [ ] **Step 3: Implement**

`backend/apps/trips/models.py`, `DeliveryControl` (add after `anomaly_confirmed_at`, currently line 260):

```python
    verified_at = models.DateField(
        null=True, blank=True,
        help_text="Date a laquelle la quantite recue a ete verifiee/corrigee "
        "par le client, distincte de control_date (date de livraison initiale).",
    )
```

And add a property near `save()` (after line 290):

```python
    @property
    def company_absorbed_loss_quantity(self) -> Decimal:
        """Portion de la perte non facturable au transporteur (<= tolerance),
        supportee par l'entreprise (client modifications 2026-09-04)."""
        return max(self.loss_quantity, Decimal("0.00")) - self.chargeable_loss_quantity
```

Generate the migration: `cd backend && python manage.py makemigrations trips -n deliverycontrol_verified_at`.

`backend/apps/trips/services.py`, fix `sync_transport_shortage_deduction` (currently line 657, `missing_quantity = (trip.quantity_loaded - received_qty).quantize(Decimal("0.01"))`):

```python
        tolerance = LossToleranceConfig.get_current_tolerance()
        missing_quantity = max(
            (trip.quantity_loaded - received_qty) - tolerance, Decimal("0.00")
        ).quantize(Decimal("0.01"))
```

(Everything below that line in the method is unchanged — it already branches on `missing_quantity <= _ZERO`.) Import `LossToleranceConfig` from `apps.core.models` at the top of `services.py` if not already imported.

Add `record_client_verification` right after `record_delivery` in `DeliveryService`:

```python
    @staticmethod
    @transaction.atomic
    def record_client_verification(
        trip_id, received_qty: Decimal, verified_at, actor, notes: str = ""
    ) -> DeliveryControl:
        """Post-delivery client quantity check (client modifications
        2026-09-04): updates the DeliveryControl created at delivery time
        (defaulted to full quantity_loaded) with what the client actually
        reports having received. Never touches Sale/Invoice ("Delivered
        Quantity is Commercial Truth" stays frozen) - the loss below
        tolerance is instead subtracted from margin by TripProfitService,
        and the loss above tolerance re-syncs the existing
        TransportDeduction mechanism.
        """
        trip = Trip.objects.select_for_update().get(pk=trip_id)
        if trip.status not in (Trip.Status.DELIVERED, Trip.Status.COMPLETED):
            raise ValueError(
                f"Le trajet {trip.reference} doit etre livre ou termine pour "
                "enregistrer une verification client."
            )
        try:
            control = DeliveryControl.objects.select_for_update().get(trip=trip)
        except DeliveryControl.DoesNotExist:
            raise ValueError(
                f"Le trajet {trip.reference} n'a pas de controle de livraison "
                "a corriger."
            )

        control.received_quantity = received_qty
        control.verified_at = verified_at
        control.notes = notes
        control.save(
            update_fields=[
                "received_quantity", "verified_at", "notes",
                "loss_quantity", "chargeable_loss_quantity", "updated_at",
            ]
        )

        sale = getattr(trip, "sale", None)
        DeliveryService.sync_transport_shortage_deduction(
            trip=trip,
            received_qty=received_qty,
            unit_selling_price=sale.unit_selling_price if sale else Decimal("0.0000"),
        )
        return control
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python manage.py test apps.trips.tests.test_delivery -v 2`
Expected: PASS.

- [ ] **Step 5: Run the full trips + finance suites (TransportDeduction/TransportPayment are cross-app)**

Run: `cd backend && python manage.py test apps.trips apps.finance -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/trips/models.py backend/apps/trips/migrations/ backend/apps/trips/services.py backend/apps/trips/tests/
git commit -m "fix(trips): apply loss tolerance to transporter deduction, add post-delivery client verification"
```

## Task 4: Backend — margin subtracts company-absorbed loss

**Files:**
- Modify: `backend/apps/reports/services/profit.py`
- Test: `backend/apps/reports/tests/test_profit.py` (confirm exact path with `grep -rl "get_cost_breakdown" backend/apps/reports/tests/`)

**Interfaces:**
- Consumes: `trip.delivery_control.company_absorbed_loss_quantity` (Task 3), `sale.unit_selling_price` (existing).
- Produces: `TripProfitService.get_cost_breakdown(trip)["margin"]` now reflects the entreprise-absorbed loss; new key `"company_absorbed_loss_amount"` in the returned dict.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_margin_subtracts_company_absorbed_loss():
    trip = _make_delivered_trip_with_sale(quantity_loaded=Decimal("45000.00"), unit_selling_price=Decimal("850.0000"))
    margin_before = TripProfitService.get_cost_breakdown(trip)["margin"]

    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44920.00"),  # 80L loss, all company-absorbed
        verified_at=date.today(), actor=_make_user(),
    )
    breakdown_after = TripProfitService.get_cost_breakdown(trip)
    expected_drop = Decimal("80.00") * Decimal("850.0000")
    assert breakdown_after["margin"] == (margin_before - expected_drop).quantize(Decimal("0.01"))
    assert breakdown_after["company_absorbed_loss_amount"] == expected_drop.quantize(Decimal("0.01"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python manage.py test apps.reports.tests.test_profit -v 2`
Expected: FAIL — margin currently ignores the tolerated loss.

- [ ] **Step 3: Implement**

In `backend/apps/reports/services/profit.py`, `get_cost_breakdown` (currently lines 142-172):

```python
        sale = getattr(trip, "sale", None)
        if sale is None:
            raise ValueError(...)
        cost_basis = TripCostService.calculate_trip_cost_basis(trip)
        revenue = sale.delivered_quantity * sale.unit_selling_price
        transporter_loss_quantity = cls._transporter_loss_quantity(trip)
        transporter_loss_indemnity = cls._transporter_loss_indemnity(trip)

        # Client modifications (2026-09-04): the tolerated portion of a
        # post-delivery loss (<=100L by default, LossToleranceConfig) is
        # never compensated by a TransportDeduction and Sale.delivered_quantity
        # stays frozen at its original (usually full-load) value - so it must
        # be subtracted from margin explicitly here, the only place a
        # DeliveryControl's real received quantity feeds profitability.
        delivery_control = getattr(trip, "delivery_control", None)
        company_absorbed_loss_amount = (
            (delivery_control.company_absorbed_loss_quantity * sale.unit_selling_price).quantize(Decimal("0.01"))
            if delivery_control is not None
            else Decimal("0.00")
        )

        real_total_cost = cost_basis["total_cost"]
        margin = (
            revenue + transporter_loss_indemnity - company_absorbed_loss_amount - real_total_cost
        ).quantize(Decimal("0.01"))
        unit_cost = cost_basis["unit_cost"]
        unit_profit = sale.unit_selling_price - unit_cost
        return {
            "quantity_loaded": trip.quantity_loaded,
            "quantity_invoiced": sale.delivered_quantity,
            "transporter_loss_quantity": transporter_loss_quantity,
            "transporter_loss_indemnity": transporter_loss_indemnity,
            "company_absorbed_loss_amount": company_absorbed_loss_amount,
            "revenue": revenue,
            "fuel_purchase_cost": cost_basis["fuel_purchase_cost"],
            "transport_cost": cost_basis["transport_cost"],
            "expenses_by_category": cost_basis["expenses_by_category"],
            "total_expenses": cost_basis["total_expenses"],
            "real_total_cost": real_total_cost,
            "margin": margin,
            "unit_cost": unit_cost,
            "unit_profit": unit_profit,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python manage.py test apps.reports.tests.test_profit -v 2`
Expected: PASS.

- [ ] **Step 5: Run the full reports suite**

Run: `cd backend && python manage.py test apps.reports -v 2`
Expected: PASS — fix any test asserting the old margin formula on a trip with a `delivery_control` whose `received_quantity` differs from `quantity_loaded`.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/reports/services/profit.py backend/apps/reports/tests/
git commit -m "fix(reports): trip margin subtracts company-absorbed post-delivery loss"
```

## Task 5: Frontend — simplified delivery form + "Vérification client" action

**Files:**
- Modify: `frontend/src/modules/trips/DeliveryControlForm.vue`, `frontend/src/modules/trips/TripDetail.vue`, `frontend/src/modules/trips/api.ts`, `frontend/src/modules/trips/types.ts`
- Create: `frontend/src/modules/trips/ClientVerificationForm.vue`, `frontend/src/modules/trips/__tests__/ClientVerificationForm.spec.ts`
- Modify: `frontend/src/locales/fr.json`, `en.json`, `ar.json`

**Interfaces:**
- Consumes: `POST /api/trips/{id}/delivery-control/` (existing, `received_quantity` now optional — omit it from the payload for the simplified confirm-delivery flow), new `POST /api/trips/{id}/client-verification/` (Task 6 wires the backend route — coordinate or stub the API call against the documented shape: `{received_quantity, verified_at, notes}` → returns the updated `DeliveryControl` JSON, same shape as `DeliveryControlSerializer`).
- Produces: `ClientVerificationForm.vue` emits `verified: [control: DeliveryControl]`.

- [ ] **Step 1: Read current `DeliveryControlForm.vue` in full** (already partially quoted in the spec, lines 1-140) to see the rest of the template (the submit button, the received-quantity input markup) before editing.

- [ ] **Step 2: Simplify `DeliveryControlForm.vue`**

Remove the `received_quantity` input, `hasReceivedInput`, `receivedQty`, `lossQty`, `chargeableLossQty`, `isAnomaly`, `anomalyConfirmed`, `canConfirmAnomaly` computeds/refs (the anomaly path is now unreachable — `received_qty` is never sent, so the backend always defaults to full load, never `> quantity_loaded`). Keep `unit_selling_price`, `control_date`, `method`, `document` (now optional per Section 6), `notes`, the cost-basis/benefit preview. `canSubmit` becomes:

```ts
const canSubmit = computed(() => {
  if (!form.value.control_date || !form.value.unit_selling_price) return false
  if (isLoss.value && !lossConfirmed.value) return false
  return true
})
```

The POST payload in `submit()` no longer includes `received_quantity`/`anomaly_confirmed_by`.

- [ ] **Step 3: Create `ClientVerificationForm.vue`**

Mirror `DeliveryControlForm.vue`'s structure (props: `tripId`, `quantityLoaded`; script setup; `Button` component) but with fields: quantité chargée (read-only, from `quantityLoaded` prop), quantité reçue (input), date de vérification (input, default today), notes (textarea). Live-computed (client-side preview only, same "estimate, server freezes the real value" pattern as `DeliveryControlForm.vue`):

```ts
const toleranceLitres = ref(100) // same fetchLossTolerance() pattern as DeliveryControlForm.vue
const lossQty = computed(() => loadedQty.value - receivedQty.value)
const companyAbsorbedQty = computed(() => Math.max(Math.min(lossQty.value, toleranceLitres.value), 0))
const transporterChargeableQty = computed(() => Math.max(lossQty.value - toleranceLitres.value, 0))
```

Display both `companyAbsorbedQty`/`transporterChargeableQty` via `formatQuantity`. Add `postClientVerification(tripId, payload)` to `frontend/src/modules/trips/api.ts` posting to `/api/trips/{id}/client-verification/`.

- [ ] **Step 4: Wire into `TripDetail.vue`**

Where `DeliveryControlForm` is currently gated (`v-if="trip.status === 'QUANTITY_CONTROL' && canChangeStatus"`, line 539) — this now only ever matches legacy trips, leave it as-is for backward compat, but the delivery-confirmation form must ALSO render when `trip.status === 'ARRIVED_AT_CLIENT'` (it didn't need to before, since the old flow required going through `QUANTITY_CONTROL` first — confirm exactly how the "confirm delivery" action is currently triggered from `ARRIVED_AT_CLIENT` in the status-transition UI before assuming this; it may already open `DeliveryControlForm` generically for any pre-`DELIVERED` status - read the surrounding template first).

Add the new button + form:

```vue
<Button
  v-if="['DELIVERED', 'COMPLETED'].includes(trip.status) && canChangeStatus"
  @click="showVerificationForm = true"
>
  {{ t('trips.detail.clientVerificationAction') }}
</Button>
<ClientVerificationForm
  v-if="showVerificationForm"
  :trip-id="trip.id"
  :quantity-loaded="trip.quantity_loaded"
  @verified="onVerified"
/>
```

`trip.status !== 'CANCELLED'` is already implied by the explicit `['DELIVERED', 'COMPLETED']` allow-list.

- [ ] **Step 5: Write and run the component test**

```ts
// frontend/src/modules/trips/__tests__/ClientVerificationForm.spec.ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ClientVerificationForm from '../ClientVerificationForm.vue'
// follow the exact mounting/i18n-plugin/mock-api pattern already used in
// DeliveryControlForm.spec.ts (read it first) - api calls must be mocked.

describe('ClientVerificationForm', () => {
  it('computes company-absorbed vs transporter-chargeable loss client-side', async () => {
    const wrapper = mount(ClientVerificationForm, {
      props: { tripId: 1, quantityLoaded: '45000.00' },
      global: { /* i18n + mocks, mirror DeliveryControlForm.spec.ts setup */ },
    })
    await wrapper.find('[data-test="received-quantity"]').setValue('44850')
    expect(wrapper.text()).toContain('100') // company-absorbed capped at tolerance
    expect(wrapper.text()).toContain('50')  // transporter-chargeable = 150 - 100
  })
})
```

Add `data-test="received-quantity"` to the input in Step 3 so this selector resolves.

Run: `cd frontend && npx vitest run src/modules/trips/__tests__/ClientVerificationForm.spec.ts src/modules/trips/__tests__/DeliveryControlForm.spec.ts src/modules/trips/__tests__/TripDetail.spec.ts`
Expected: PASS (fix any `TripDetail.spec.ts` assertion that hardcoded the old `QUANTITY_CONTROL`-only gating).

- [ ] **Step 6: Add i18n keys**

Add `trips.detail.clientVerificationAction`, `trips.clientVerification.*` (title, fields, submit) to `fr.json`/`en.json`/`ar.json`, mirroring the existing `trips.delivery.*` key structure.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/trips/ frontend/src/locales/
git commit -m "feat(trips): simplify delivery confirmation, add post-delivery client verification UI"
```

## Task 6: Backend — `client-verification` API route

**Files:**
- Modify: `backend/apps/trips/serializers.py`, `backend/apps/trips/views.py`
- Test: same trips test file as Tasks 2-3, API-level via `APIClient`

**Interfaces:**
- Produces: `POST /api/trips/{id}/client-verification/` → 200 with `DeliveryControlSerializer(control).data` on success; 400/422 with a clear `detail` message when the trip isn't `DELIVERED`/`COMPLETED` or has no `delivery_control`.

- [ ] **Step 1: Write the failing API test**

```python
@pytest.mark.django_db
def test_client_verification_endpoint_updates_delivery_control():
    trip = _make_delivered_trip(quantity_loaded=Decimal("45000.00"))
    admin = _make_admin("CLIENTVERIF1")
    client = APIClient()
    client.force_authenticate(admin)
    response = client.post(
        f"/api/trips/{trip.id}/client-verification/",
        {"received_quantity": "44920.00", "verified_at": str(date.today()), "notes": "Ecart client"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["received_quantity"] == "44920.00"


@pytest.mark.django_db
def test_client_verification_rejected_on_non_delivered_trip():
    trip = _make_trip_at_status(Trip.Status.ARRIVED_AT_CLIENT)
    admin = _make_admin("CLIENTVERIF2")
    client = APIClient()
    client.force_authenticate(admin)
    response = client.post(
        f"/api/trips/{trip.id}/client-verification/",
        {"received_quantity": "44000.00", "verified_at": str(date.today())},
        format="json",
    )
    assert response.status_code in (400, 422)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python manage.py test apps.trips.tests.test_delivery -v 2`
Expected: FAIL — 404, route doesn't exist.

- [ ] **Step 3: Implement**

`backend/apps/trips/serializers.py`, add near `DeliveryControlRequestSerializer`:

```python
class ClientVerificationRequestSerializer(serializers.Serializer):
    received_quantity = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"))
    verified_at = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")
```

`backend/apps/trips/views.py`, add action near `delivery_control` (after its closing, currently ending around line 277+):

```python
    @action(detail=True, methods=["post"], url_path="client-verification")
    def client_verification(self, request, pk=None):
        """Post-delivery client quantity check (client modifications
        2026-09-04) - see DeliveryService.record_client_verification().

        POST /api/trips/{id}/client-verification/
        """
        trip = self.get_object()
        input_serializer = ClientVerificationRequestSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        try:
            control = DeliveryService.record_client_verification(
                trip_id=trip.id,
                received_qty=data["received_quantity"],
                verified_at=data["verified_at"],
                actor=request.user,
                notes=data.get("notes", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(DeliveryControlSerializer(control).data)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python manage.py test apps.trips.tests.test_delivery -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/trips/serializers.py backend/apps/trips/views.py backend/apps/trips/tests/
git commit -m "feat(trips): add POST /api/trips/{id}/client-verification/ endpoint"
```

---

# Section 3+4 — Fond de roulement (formule additive) + Résultat distribuable

## Task 7: Backend — `WorkingCapitalService`

**Files:**
- Modify: `backend/apps/finance/services.py`
- Test: `backend/apps/finance/tests/test_working_capital.py` (create — check `backend/apps/finance/tests/` layout first for naming convention)

**Interfaces:**
- Produces: `WorkingCapitalService.get_working_capital() -> dict` with keys `capital`, `treasury_available`, `customer_receivables`, `supplier_debt_total`, `transporter_debt_total`, `other_debts`, `total` (all `Decimal`), where `total = treasury_available + customer_receivables + supplier_debt_total + transporter_debt_total + other_debts`.
- Consumes: `BankAccount`, `CashAccount` (`apps.finance.models`, already imported in this file), `CustomerOutstandingReportQuery` (`apps.reports.queries.customer_outstanding_report` — new import, same pattern as the existing `MarginReportQuery` import at line 40), `ControlledDebtPaymentService.describe_supplier_balance`/`describe_transporter_balance`/`describe_expense_group` (existing, same class), `ShareholderContributionService.get_total_capital` (existing, same file), `Supplier`/`Transporter` (already imported).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_working_capital_adds_debts_as_positive_no_netting():
    bank = BankAccount.objects.create(name="Banque", is_active=True)
    # ... seed via existing test factories: treasury_available=2_000_000,
    # customer_receivables=1_000_000, an open supplier debt of 1_000_000
    # (no advance), an open transporter debt of 1_000_000 (no advance),
    # a customs/transit expense debt totalling 1_000_000.
    result = WorkingCapitalService.get_working_capital()
    assert result["total"] == Decimal("6000000.00")


@pytest.mark.django_db
def test_working_capital_debt_total_is_gross_not_net_of_advances():
    # A supplier with an open advance of 500_000 AND an open debt of
    # 1_000_000: net_balance would be -500_000, but supplier_debt_total
    # must be the gross 1_000_000 (client rule: debts added as positive,
    # advances not netted in this indicator).
    ...
    result = WorkingCapitalService.get_working_capital()
    assert result["supplier_debt_total"] == Decimal("1000000.00")
```

Read `backend/apps/finance/tests/` (or wherever the existing `describe_supplier_balance` tests live — `grep -rl "describe_supplier_balance" backend/apps/finance/tests/`) for the exact fixture helpers to seed a supplier debt/advance, and reuse them rather than hand-rolling new ones.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python manage.py test apps.finance.tests.test_working_capital -v 2`
Expected: FAIL — `WorkingCapitalService` doesn't exist.

- [ ] **Step 3: Implement**

In `backend/apps/finance/services.py`, add the import (near line 40, alongside `MarginReportQuery`):

```python
from apps.reports.queries.customer_outstanding_report import CustomerOutstandingReportQuery
```

Add the new class near `ShareholderContributionService`:

```python
ZERO = Decimal("0.00")  # confirm this module-level constant doesn't already exist under a different name before adding a duplicate


class WorkingCapitalService:
    """Fond de roulement client (docs/superpowers/specs/2026-09-04-recette-
    corrections-design.md, Section 3) - a management indicator matching the
    client's own "ETAT DE LA TRESORERIE" spreadsheet, NOT the accounting
    fonds de roulement and NOT the old net/signed working_capital this
    replaces. Open debts are added here as positive figures (mass of funds
    engaged in operations) - everywhere else (party balances, ledgers,
    payment screens) a debt stays displayed as an amount owed. Never a
    source of payment - payments always draw from real BankAccount/
    CashAccount.
    """

    @staticmethod
    def get_working_capital() -> dict:
        treasury_available = sum(
            (a.current_balance for a in BankAccount.objects.filter(is_active=True)), ZERO
        ) + sum(
            (a.current_balance for a in CashAccount.objects.filter(is_active=True)), ZERO
        )
        customer_receivables = sum(
            (row["outstanding"] for row in CustomerOutstandingReportQuery.run()), ZERO
        )
        supplier_debt_total = sum(
            (
                ControlledDebtPaymentService.describe_supplier_balance(s)["total_due"]
                for s in Supplier.objects.filter(is_active=True)
            ),
            ZERO,
        )
        transporter_debt_total = sum(
            (
                ControlledDebtPaymentService.describe_transporter_balance(t)["total_due"]
                for t in Transporter.objects.filter(is_active=True)
            ),
            ZERO,
        )
        other_debts = sum(
            (
                ControlledDebtPaymentService.describe_expense_group(group)["remaining_amount"]
                for group in (
                    ControlledDebtPaymentService.CUSTOMS,
                    ControlledDebtPaymentService.TRANSIT,
                    ControlledDebtPaymentService.ROAD_TRANSIT,
                    ControlledDebtPaymentService.BORDER,
                    ControlledDebtPaymentService.LOADING,
                    ControlledDebtPaymentService.TRIP_OTHER,
                )
            ),
            ZERO,
        )
        capital = ShareholderContributionService.get_total_capital()
        total = (
            treasury_available + customer_receivables
            + supplier_debt_total + transporter_debt_total + other_debts
        )
        return {
            "capital": capital,
            "treasury_available": treasury_available,
            "customer_receivables": customer_receivables,
            "supplier_debt_total": supplier_debt_total,
            "transporter_debt_total": transporter_debt_total,
            "other_debts": other_debts,
            "total": total,
        }
```

Before adding `ZERO = Decimal("0.00")`, check whether this exact constant already exists at module scope in `backend/apps/finance/services.py` (likely, given the pattern used throughout this file) — reuse it, don't shadow/duplicate.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python manage.py test apps.finance.tests.test_working_capital -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/finance/tests/test_working_capital.py
git commit -m "feat(finance): add WorkingCapitalService with the client's additive fond-de-roulement formula"
```

## Task 8: Backend — wire `working_capital` (Dashboard) + `distributable_result` (ProfitPreview), replacing old formulas

**Files:**
- Modify: `backend/apps/reports/views/dashboard.py`, `backend/apps/finance/services.py` (`ShareholderProfitPreviewService.get_preview`)
- Test: `backend/apps/reports/test_views.py`, `backend/apps/reports/test_queries.py` (both already reference `profit_after_capital` per prior investigation — update, don't just add)

**Interfaces:**
- Produces: `DashboardViewSet.summary()` response `working_capital` key = `WorkingCapitalService.get_working_capital()` output (replaces the old net/signed dict entirely — same key name, different shape: `supplier_net_balance`/`transporter_net_balance` keys are gone, replaced by `supplier_debt_total`/`transporter_debt_total`). `shareholders_summary["distributable_result"]` replaces `shareholders_summary["profit_after_capital"]`. `ShareholderProfitPreviewService.get_preview()` return dict: `total_capital_contributed` key is removed (redundant with `working_capital["capital"]`, which is now included as a nested `working_capital` key in the returned dict), `profit_after_capital` key is removed, replaced by `working_capital: dict` and `distributable_result: Decimal`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/apps/finance tests, or wherever ShareholderProfitPreviewService is tested:
@pytest.mark.django_db
def test_distributable_result_formula():
    # capital=2_000_000, dettes totales (fournisseurs+transporteurs+autres)=3_000_000,
    # treasury_available+customer_receivables such that working_capital.total=6_000_000
    ...
    preview = ShareholderProfitPreviewService.get_preview()
    assert preview["distributable_result"] == Decimal("1000000.00")
    assert "profit_after_capital" not in preview
    assert "total_capital_contributed" not in preview
    assert preview["working_capital"]["total"] == Decimal("6000000.00")
```

```python
# backend/apps/reports/test_views.py:
@pytest.mark.django_db
def test_dashboard_summary_working_capital_uses_additive_formula():
    ...
    response = client.get("/api/dashboard/summary/")
    wc = response.data["working_capital"]
    assert "supplier_net_balance" not in wc  # old key removed
    assert "supplier_debt_total" in wc       # new key present
    assert Decimal(response.data["shareholders_summary"]["distributable_result"]) is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python manage.py test apps.finance apps.reports -v 2`
Expected: FAIL on the new assertions; also expect PRE-EXISTING failures in any test still asserting the old `profit_after_capital`/`supplier_net_balance` keys — note those, they get fixed in Step 5.

- [ ] **Step 3: Implement**

`backend/apps/finance/services.py`, `ShareholderProfitPreviewService.get_preview` — replace lines 2028-2037 (the `total_capital_contributed`/`profit_after_capital` block):

```python
        # Client modifications (2026-09-04): "resultat distribuable apres
        # dettes et capital" replaces the old profit_after_capital
        # (net_profit - capital) formula entirely per client clarification -
        # see docs/superpowers/specs/2026-09-04-recette-corrections-design.md
        # Section 4. Never feeds indicative_share (still net_profit-based
        # below) or ShareholderProfitDistribution.
        working_capital = WorkingCapitalService.get_working_capital()
        distributable_result = (
            working_capital["total"]
            - working_capital["supplier_debt_total"]
            - working_capital["transporter_debt_total"]
            - working_capital["other_debts"]
            - working_capital["capital"]
        )
```

And the return dict (currently lines 2056-2066) — remove `total_capital_contributed`/`profit_after_capital`, add `working_capital`/`distributable_result`:

```python
        return {
            "period_start": date_from,
            "period_end": date_to,
            "current_profit": current_profit,
            "operational_profit": operational_profit,
            "general_expenses_paid": general_expenses_paid,
            "net_profit": net_profit,
            "working_capital": working_capital,
            "distributable_result": distributable_result,
            "shareholders": shareholders,
        }
```

`backend/apps/reports/views/dashboard.py`: replace the inline `working_capital = {...}` block (currently lines 343-368) with:

```python
        # Fond de roulement client (docs/superpowers/specs/2026-09-04-
        # recette-corrections-design.md, Section 3) - single source of
        # truth also used by ShareholderProfitPreviewService's
        # distributable_result, never a second formula.
        working_capital = WorkingCapitalService.get_working_capital()
```

Add `WorkingCapitalService` to the `from apps.finance.services import (...)` block (currently lines 24-28).

And `shareholders_summary` (currently lines 200-221) — replace `"profit_after_capital": profit_preview["profit_after_capital"]` and `"total_capital_contributed": profit_preview["total_capital_contributed"]` with:

```python
            "distributable_result": profit_preview["distributable_result"],
```

(keep `"current_profit": profit_preview["current_profit"]` and the other existing keys unchanged).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python manage.py test apps.finance apps.reports -v 2`
Expected: PASS.

- [ ] **Step 5: Fix every other test still asserting the old keys**

Run: `cd backend && grep -rln "profit_after_capital\|total_capital_contributed\|supplier_net_balance\|transporter_net_balance" apps/` and update each hit (production code should have none left outside this task's edits; test code gets updated to the new keys/formula). Re-run: `cd backend && python manage.py test apps.finance apps.reports -v 2` until clean.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/reports/views/dashboard.py backend/apps/finance/tests/ backend/apps/reports/test_views.py backend/apps/reports/test_queries.py
git commit -m "feat(finance): replace working_capital/profit_after_capital with the client's fond-de-roulement and resultat-distribuable formulas"
```

## Task 9: Frontend — labels + wiring for the 3 profit blocks + FDR

**Files:**
- Modify: `frontend/src/modules/finance/ProfitView.vue`, `frontend/src/modules/finance/types.ts`, `frontend/src/modules/dashboard/DashboardView.vue`, `frontend/src/modules/dashboard/types.ts`
- Modify: `frontend/src/locales/fr.json`, `en.json`, `ar.json`
- Test: `frontend/src/modules/finance/__tests__/ProfitView.spec.ts`, `frontend/src/modules/dashboard/__tests__/DashboardView.spec.ts`

**Interfaces:**
- Consumes: new backend shape from Task 8 — `working_capital: {capital, treasury_available, customer_receivables, supplier_debt_total, transporter_debt_total, other_debts, total}`, `distributable_result` (replaces `profit_after_capital`/`total_capital_contributed` at every cited call site).

- [ ] **Step 1: Update failing tests first**

Read `frontend/src/modules/finance/__tests__/ProfitView.spec.ts` and `frontend/src/modules/dashboard/__tests__/DashboardView.spec.ts` in full (both already reference the old keys per the investigation citations — lines 151/259/280/300/312 and 959/993/1004 respectively). Update every fixture/mock response in these test files from `profit_after_capital`/`total_capital_contributed` to `distributable_result`/`working_capital`, and update assertions to check for the new labels below. This intentionally breaks the tests against the still-old component code — that's the expected red state.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ProfitView.spec.ts src/modules/dashboard/__tests__/DashboardView.spec.ts`
Expected: FAIL — components still read the old keys/labels.

- [ ] **Step 3: Implement**

`frontend/src/modules/finance/types.ts` / `frontend/src/modules/dashboard/types.ts`: update the relevant interface(s) — remove `profit_after_capital`/`total_capital_contributed`, add:

```ts
export interface WorkingCapital {
  capital: string
  treasury_available: string
  customer_receivables: string
  supplier_debt_total: string
  transporter_debt_total: string
  other_debts: string
  total: string
}
// ... and on the profit-preview / dashboard-summary interfaces:
// working_capital: WorkingCapital
// distributable_result: string
```

`ProfitView.vue` (cited lines 151, 259, 280, 300, 312): replace every `profit_after_capital`/`total_capital_contributed` reference with `distributable_result`/`working_capital.capital`, and render the three required blocks with these exact labels (add i18n keys `finance.profit.operationalProfit`, `finance.profit.netProfit`, `finance.profit.workingCapital`, `finance.profit.distributableResult`):
  - "Bénéfice opérationnel des trajets" → `operational_profit`
  - "Bénéfice net après dépenses générales" → `net_profit`
  - "Fond de roulement client" → `working_capital.total`
  - "Résultat distribuable après dettes et capital" → `distributable_result`

`DashboardView.vue` (cited lines 959, 993, 1004): same replacement — at minimum show `working_capital.total` ("Fond de roulement client") and `distributable_result` ("Résultat distribuable après dettes et capital") cards.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ProfitView.spec.ts src/modules/dashboard/__tests__/DashboardView.spec.ts`
Expected: PASS.

- [ ] **Step 5: Add/update i18n keys in `fr.json`/`en.json`/`ar.json`**

Add the 4 label keys above (French labels exactly as specified by the client: "Bénéfice opérationnel des trajets", "Bénéfice net après dépenses générales", "Fond de roulement client", "Résultat distribuable après dettes et capital"), with reasonable EN/AR translations.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/finance/ frontend/src/modules/dashboard/ frontend/src/locales/
git commit -m "feat(frontend): show the 3 distinct profit blocks and fond-de-roulement client on Benefices/Dashboard"
```

---

# Section 5 — Impression / export PDF des Grands Livres

## Task 10: Backend — `render_ledger_pdf` + wire onto the 3 ledger endpoints

**Files:**
- Create: `backend/apps/reports/services/ledger_pdf.py`
- Modify: whichever views currently serve `GET /api/suppliers/{id}/ledger/`, `GET /api/transporters/{id}/ledger/`, `GET /api/customers/{id}/ledger/` (`backend/apps/finance/views.py` around line 443 for the `SupplierViewSet`/`TransporterViewSet` pattern if both live there; `backend/apps/customers/views.py:24` for the customer one — confirm exact classes/files with `grep -rn "def ledger" backend/apps/*/views.py` before editing)
- Test: `backend/apps/reports/tests/test_ledger_pdf.py` (create)

**Interfaces:**
- Produces: `render_ledger_pdf(*, company_name: str, account_type: str, party_name: str, export_date: date, summary: dict, rows: list[dict], lang: str = "fr") -> bytes` (a PDF). `?format=pdf&lang=fr|en|ar` on each of the 3 existing `ledger` actions returns `Content-Type: application/pdf` instead of JSON when `format=pdf` is present (same convention as `reports/views/reports.py:128`); `lang` defaults to `fr` if omitted or unrecognized.
- Consumes: the exact dict already returned by `SupplierLedgerService.get_ledger(supplier)` / `TransporterLedgerService.get_ledger(transporter)` / the customer-ledger service found in Step 1 below — **read one real response from each of these three before writing `render_ledger_pdf`**, this task's Step 1 is that reconnaissance, not optional.

- [ ] **Step 1: Read the exact current ledger response shapes**

Run: `cd backend && grep -n "def get_ledger" -A 60 apps/finance/services.py | sed -n '1,70p'` (Supplier + Transporter) and find + read the customer-ledger equivalent (`grep -rn "def.*ledger\|CustomerStatementQuery" apps/customers/ apps/reports/queries/customer_statement.py`). Note down, for each of the 3: the summary/balance fields, the row/operation fields, any status field — this is what `render_ledger_pdf` must accept and print. Do not guess field names; use exactly what these functions return.

- [ ] **Step 2: Write the failing test**

```python
def test_render_ledger_pdf_produces_valid_pdf_bytes():
    pdf_bytes = render_ledger_pdf(
        company_name="Sahel Commerce et Transport",
        account_type="fournisseur",
        party_name="Fournisseur Test",
        export_date=date.today(),
        summary={"total_due": Decimal("500000.00"), "open_advances": Decimal("100000.00")},  # use real keys from Step 1
        rows=[{"date": date.today(), "type": "PAYMENT", "amount": Decimal("200000.00"), "status": "PAID"}],  # use real keys from Step 1
        lang="fr",
    )
    assert pdf_bytes.startswith(b"%PDF")
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && python manage.py test apps.reports.tests.test_ledger_pdf -v 2`
Expected: FAIL — module doesn't exist.

- [ ] **Step 4: Implement `render_ledger_pdf`**

```python
# backend/apps/reports/services/ledger_pdf.py
#
# PDF export for the 3 party ledgers (Grand livre fournisseur/transporteur/
# client) - docs/superpowers/specs/2026-09-04-recette-corrections-design.md
# Section 5. No business calculation here: prints the dict already returned
# by {Supplier,Transporter,Customer}LedgerService.get_ledger(), same
# reportlab dependency already used by apps/reports/export.py.
#
# KNOWN LIMITATION (documented per client's explicit pre-approval of a
# minimal correction over a blocking one): reportlab's default Helvetica
# font has no Arabic glyphs and no bidi/reshaping support. For lang="ar" we
# right-align the table (minimal RTL correction) but keep French field
# labels rather than rendering unreadable tofu glyphs - full Arabic PDF
# support needs an embedded Unicode font (e.g. Noto Naskh Arabic) plus
# arabic-reshaper/python-bidi, deliberately out of scope for this small,
# safe correction. Follow-up ticket if the client needs true Arabic PDFs.

import io
from decimal import Decimal
import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

LEDGER_PDF_LABELS = {
    "fr": {"title": "Grand livre", "account_type": "Type de compte", "party": "Compte",
           "export_date": "Date d'export", "summary": "Resume des soldes", "history": "Historique des operations"},
    "en": {"title": "Ledger", "account_type": "Account type", "party": "Account",
           "export_date": "Export date", "summary": "Balance summary", "history": "Operation history"},
    # AR: labels kept in French pending an embedded Arabic-capable font (see module docstring).
    "ar": {"title": "Grand livre", "account_type": "Type de compte", "party": "Compte",
           "export_date": "Date d'export", "summary": "Resume des soldes", "history": "Historique des operations"},
}


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


def render_ledger_pdf(
    *, company_name: str, account_type: str, party_name: str, export_date,
    summary: dict, rows: list[dict], lang: str = "fr",
) -> bytes:
    labels = LEDGER_PDF_LABELS.get(lang, LEDGER_PDF_LABELS["fr"])
    is_rtl = lang == "ar"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"{labels['title']} - {party_name}",
    )
    styles = getSampleStyleSheet()
    align_style = ParagraphStyle("aligned", parent=styles["Normal"], alignment=TA_RIGHT if is_rtl else 0)

    elements = [
        Paragraph(company_name, styles["Title"]),
        Paragraph(f"{labels['account_type']}: {account_type} — {labels['party']}: {party_name}", align_style),
        Paragraph(f"{labels['export_date']}: {export_date.isoformat()}", align_style),
        Spacer(1, 8 * mm),
        Paragraph(labels["summary"], styles["Heading2"]),
    ]
    summary_data = [[key.replace("_", " ").title(), _stringify(value)] for key, value in summary.items()]
    elements.append(Table(summary_data, style=TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d5cc"))])))
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph(labels["history"], styles["Heading2"]))

    if rows:
        fields = list(rows[0].keys())
        header = [field.replace("_", " ").title() for field in fields]
        if is_rtl:
            fields = list(reversed(fields))
            header = list(reversed(header))
        data = [header] + [[_stringify(row.get(f)) for f in fields] for row in rows]
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12171c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d5cc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f4ef")]),
        ]))
        elements.append(table)

    doc.build(elements)
    return buffer.getvalue()
```

Adjust field names in the `summary`/`rows` handling to whatever Step 1 actually found — the code above is generic over dict shape by design (no hardcoded field names), so it should need no changes once the ledger services' real dicts are passed in.

- [ ] **Step 5: Wire `?format=pdf` onto the 3 ledger views**

For each of `SupplierViewSet.ledger`, `TransporterViewSet.ledger`, and the customer-ledger view found in Step 1: read `request.query_params.get("format")` and `request.query_params.get("lang", "fr")`; when `format == "pdf"`, call `render_ledger_pdf(...)` with the already-computed `get_ledger()` dict and return `HttpResponse(pdf_bytes, content_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="grand-livre-{party.name}.pdf"'})` instead of the normal `Response(decimals_to_str(summary))`. Mirror the exact `format=pdf` branch already in `backend/apps/reports/views/reports.py:128` for the response-construction pattern (headers, content-type).

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python manage.py test apps.reports.tests.test_ledger_pdf apps.finance apps.customers -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/reports/services/ledger_pdf.py backend/apps/reports/tests/test_ledger_pdf.py backend/apps/finance/views.py backend/apps/customers/views.py
git commit -m "feat(reports): add PDF export to the 3 party ledger endpoints"
```

## Task 11: Backend — trip settlement PDF ("Règlement par trajet")

**Files:**
- Modify: `backend/apps/reports/services/ledger_pdf.py` (new function) or `backend/apps/finance/views.py` (wherever `TransportPayment`/`SupplierPayment` are exposed — confirm the exact ViewSet with `grep -rn "class.*Payment.*ViewSet" backend/apps/finance/views.py`)
- Test: extend `backend/apps/reports/tests/test_ledger_pdf.py`

**Interfaces:**
- Produces: `render_trip_settlement_pdf(payment, lang="fr") -> bytes` and `GET /api/transport-payments/{id}/pdf/?lang=...` (adjust URL to the real ViewSet's `basename` found above).

- [ ] **Step 1: Read `TransportPayment` (`backend/apps/finance/models.py:487-527+`, already partially quoted in the spec) and `Trip` fields needed** — `reference`, `truck.internal_id`/plate field (check `Truck` model's exact plate field name), `transporter.name`, `client`/`customer_order.customer.name`, `product.name`, `quantity_loaded`, `status`, plus `TransportPayment.base_amount`, `deduction_amount`, `net_amount`, `date`/`payment_date` (confirm exact field name), `notes`.

- [ ] **Step 2: Write the failing test**

```python
def test_render_trip_settlement_pdf():
    payment = _make_transport_payment()  # existing test factory
    pdf_bytes = render_trip_settlement_pdf(payment, lang="fr")
    assert pdf_bytes.startswith(b"%PDF")
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && python manage.py test apps.reports.tests.test_ledger_pdf -v 2`
Expected: FAIL.

- [ ] **Step 4: Implement `render_trip_settlement_pdf`** in `ledger_pdt.py`, single-record layout (not a table of many rows — a label/value grid) covering exactly the fields listed in the spec: référence trajet, camion, plaque, transporteur, client, produit, quantité, statut du trajet, montant brut (`base_amount`), déductions (`deduction_amount`), net (`net_amount`), date, notes. Reuse the same `LEDGER_PDF_LABELS` pattern, extended with these field labels.

- [ ] **Step 5: Add the endpoint** on the `TransportPayment` ViewSet found in Step 1 of this task, same `format=pdf`-or-dedicated-action pattern as Task 10 Step 5.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python manage.py test apps.reports.tests.test_ledger_pdf apps.finance -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/reports/services/ledger_pdf.py backend/apps/reports/tests/test_ledger_pdf.py backend/apps/finance/views.py
git commit -m "feat(reports): add per-trip settlement PDF export"
```

## Task 12: Frontend — Imprimer/Exporter PDF buttons on the 3 ledger pages + settlement rows

**Files:**
- Modify: `frontend/src/modules/finance/CustomerLedgerView.vue`, `frontend/src/modules/finance/TransporterLedgerView.vue`, `frontend/src/modules/suppliers/SupplierLedgerView.vue`, `frontend/src/modules/finance/api.ts`
- Test: `frontend/src/modules/finance/__tests__/CustomerLedgerView.spec.ts`, `TransporterLedgerView.spec.ts`, `frontend/src/modules/suppliers/__tests__/SupplierLedgerView.spec.ts`

**Interfaces:**
- Consumes: Task 10/11's `?format=pdf&lang=...` endpoints.

- [ ] **Step 1: Read `ReportsView.vue:118-135`** (existing `printReport()`/PDF-export precedent) to copy its exact pattern: `window.print()` for Imprimer, blob-download for `format=pdf`.

- [ ] **Step 2: Write failing tests** — add to each of the 3 ledger spec files an assertion that an "Imprimer" and an "Exporter PDF" button exist and that clicking "Exporter PDF" calls the export API with the current i18n locale as `lang`.

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/CustomerLedgerView.spec.ts src/modules/finance/__tests__/TransporterLedgerView.spec.ts src/modules/suppliers/__tests__/SupplierLedgerView.spec.ts`

- [ ] **Step 4: Implement**

Add `exportLedgerPdf(kind: 'supplier'|'transporter'|'customer', id: number, lang: string)` to `frontend/src/modules/finance/api.ts` (blob response, `responseType: 'blob'`), and two buttons at the top of each of the 3 views: "Imprimer" (`@click="window.print()"`) and "Exporter PDF" (`@click="exportLedgerPdf(...)"`, passing `useI18n().locale.value` as `lang`). Also add an "Imprimer"/"PDF" action on each "Règlement par trajet" row (wherever `TransportPayment` rows are rendered inside these ledger views — locate via `grep -n "TransportPayment\|transport_payment\|reglement" <each file>`), calling Task 11's per-payment PDF endpoint.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/CustomerLedgerView.spec.ts src/modules/finance/__tests__/TransporterLedgerView.spec.ts src/modules/suppliers/__tests__/SupplierLedgerView.spec.ts`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/finance/ frontend/src/modules/suppliers/
git commit -m "feat(frontend): add print/PDF export to the 3 party ledger pages and settlement rows"
```

---

# Section 6 — Justificatif non obligatoire

## Task 13: Backend — remove the 4 mandatory-attachment blocks

**Files:**
- Modify: `backend/apps/finance/serializers.py` (`ControlledDebtPaymentRequestSerializer`, `SupplierAdvanceSerializer`, `TransporterAdvanceSerializer`, `ShareholderContributionSerializer`)
- Modify: `backend/apps/finance/services.py` (`ShareholderContributionService.record_contribution`)
- Test: `backend/apps/finance/tests/` — extend existing tests for each of the 4 flows (`test_contributions.py` for contributions, `grep -rl "justificatif image est obligatoire" backend/apps/finance/tests/` for the other 3)

**Interfaces:**
- Produces: all 4 flows now accept `attachment`/`document` omitted or `None` and succeed; file-type/size validation (`validate_image_upload`) still runs when a file **is** provided.

- [ ] **Step 1: Write the failing tests**

For each of the 4 flows, add a test that submitting without an attachment now succeeds (currently these should already exist as the inverse — "rejected without proof" tests; find them with `grep -rln "obligatoire" backend/apps/finance/tests/` and flip/replace their assertions):

```python
@pytest.mark.django_db
def test_debt_payment_succeeds_without_attachment():
    ...
    response = client.post("/api/treasury-transactions/record-debt-payment/", {..., "attachment": None}, format="multipart")
    assert response.status_code == 201  # or 200, match existing success-path test

@pytest.mark.django_db
def test_supplier_advance_succeeds_without_attachment():
    ...

@pytest.mark.django_db
def test_transporter_advance_succeeds_without_attachment():
    ...

@pytest.mark.django_db
def test_shareholder_contribution_succeeds_without_attachment():
    contribution = ShareholderContributionService.record_contribution(
        shareholder_id=shareholder.id, amount=Decimal("500000.00"), date=date.today(),
        actor=user, attachment=None, bank_account_id=bank.id,
    )
    assert contribution.document_id is None
```

Also **update** (not just add to) any existing test asserting the old "rejected without justificatif" behavior for these 4 flows — those assertions are now wrong and must be inverted or removed, per the spec's residual-risk note about `test_contributions.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python manage.py test apps.finance -v 2`
Expected: FAIL on the new "succeeds without attachment" tests; the old "rejected without" tests for these 4 flows should still currently PASS (they'll need updating once the behavior flips — track which ones in Step 5).

- [ ] **Step 3: Implement**

`backend/apps/finance/serializers.py`:

1. `ControlledDebtPaymentRequestSerializer.validate()` (currently lines 912-919) — delete the `if not data.get("attachment"): raise ...` block entirely, keep `return data`. `validate_attachment` (currently lines 922-927) — change to match the advance serializers' pattern:
   ```python
   def validate_attachment(self, value):
       if value is None:
           return value
       return validate_image_upload(value)
   ```
2. `SupplierAdvanceSerializer.validate()` — delete the `if self.instance is None and not data.get("attachment"): raise ...` block (currently 2 lines within the method).
3. `TransporterAdvanceSerializer.validate()` — same deletion.
4. `ShareholderContributionSerializer.validate()` — delete the `if not data.get("attachment"): raise ...` block.

`backend/apps/finance/services.py`, `ShareholderContributionService.record_contribution` — remove the `if not attachment: raise ShareholderContributionError(...)` guard, and make document creation conditional:

```python
        document = None
        if attachment:
            document = Document.objects.create(
                file=attachment, document_type="shareholder_contribution_proof", reference=reference,
                uploaded_by=actor, content_type=ContentType.objects.get_for_model(ShareholderContribution),
                object_id=contribution.id,
            )
            contribution.document = document
            contribution.save(update_fields=["document", "updated_at"])
```

(move this block to after `contribution` is created, same position as today — only the `if attachment:` guard and the `document = None` default are new.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python manage.py test apps.finance -v 2`
Expected: PASS.

- [ ] **Step 5: Update every pre-existing "rejected without justificatif" test for these 4 flows**

Run: `cd backend && grep -rln "obligatoire pour" apps/finance/tests/` and, for each hit that covers debt-payment/supplier-advance/transporter-advance/shareholder-contribution (not the flows that stay mandatory — none do, per the spec's table, but double-check none of the found tests are for an unrelated still-required field), invert the assertion or delete the now-invalid test case. Re-run `cd backend && python manage.py test apps.finance -v 2` until clean.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/serializers.py backend/apps/finance/services.py backend/apps/finance/tests/
git commit -m "feat(finance): make proof/justificatif optional on debt payments, advances, and shareholder contributions"
```

## Task 14: Frontend — remove required-file gating on the 3 forms

**Files:**
- Modify: `frontend/src/modules/finance/AdvanceForm.vue`, `frontend/src/modules/finance/ContributionForm.vue`, `frontend/src/modules/finance/DebtPaymentForm.vue`
- Test: existing spec files for each (`AdvanceForm.spec.ts`, `ContributionForm.spec.ts`, `DebtPaymentForm.spec.ts` — confirm exact names with `ls frontend/src/modules/finance/__tests__/ | grep -i "advance\|contribution\|debtpayment"`)

**Interfaces:** none new — same emitted events, same submit payload shape (still includes `attachment: attachment.value`, now potentially `null`).

This is one same-shape edit repeated 3 times — batch it into a single dispatch/task per subagent-driven-development's "batch small same-shape work" guidance, not 3 separate tasks.

- [ ] **Step 1: Write the failing tests**

For each of the 3 spec files, add a test that submitting with no file selected succeeds (calls the create API) instead of being blocked client-side:

```ts
it('allows submitting without an attachment', async () => {
  const wrapper = mount(AdvanceForm, { props: {...}, global: {...} })
  // fill every other required field, leave the file input untouched
  await wrapper.find('form').trigger('submit')
  expect(mockCreateSupplierAdvance).toHaveBeenCalled() // no client-side block
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/AdvanceForm.spec.ts src/modules/finance/__tests__/ContributionForm.spec.ts src/modules/finance/__tests__/DebtPaymentForm.spec.ts`
Expected: FAIL — current `validate()`/submit-gate blocks it.

- [ ] **Step 3: Implement (identical edit in each of the 3 files)**

`AdvanceForm.vue`:
- Delete lines 172-175 (`if (!attachment.value) { error.value = ...proofRequired; return false }`) from `validate()`.
- Line 180: change `if (!validate() || !selectedParty.value || !selectedAccount.value || !attachment.value) return` → `if (!validate() || !selectedParty.value || !selectedAccount.value) return`.
- Line 343: delete the `required` attribute on the `<input type="file" ...>`.
- Line 339 label: append `\` (${t('common.optional')})\`` or equivalent existing "(optionnel)" i18n convention used elsewhere in the codebase (`grep -rn "common.optional\|optionnel" frontend/src/locales/fr.json` to find the existing key).

`ContributionForm.vue`: same pattern — delete lines 120-123 from `validate()`, line 128 drop `|| !attachment.value`, line 233 drop `required`, line 230 label append "(optionnel)".

`DebtPaymentForm.vue`: same pattern — delete lines 168-171 from `validate()`, line 176's gate (`if (!validate() || !selectedDebt.value || !selectedBank.value) return`) already doesn't reference `attachment.value`, so no change needed there; drop `required` at line ~354, append "(optionnel)" to the label at line ~350.

Do not touch `onAttachmentChange`/the file-type-validation logic (`attachmentError`) in any of the 3 — that stays exactly as-is, still runs when a file is provided.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/AdvanceForm.spec.ts src/modules/finance/__tests__/ContributionForm.spec.ts src/modules/finance/__tests__/DebtPaymentForm.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/finance/AdvanceForm.vue frontend/src/modules/finance/ContributionForm.vue frontend/src/modules/finance/DebtPaymentForm.vue frontend/src/modules/finance/__tests__/
git commit -m "feat(frontend): make proof upload optional on advance, contribution, and debt-payment forms"
```

---

## Final full-suite pass (run once, after all 14 tasks)

- [ ] `cd backend && python manage.py test` — full backend suite, zero failures.
- [ ] `cd frontend && npx vitest run` — full frontend suite, zero failures.
- [ ] `cd frontend && npm run type-check` (or equivalent — confirm script name in `package.json`) — zero errors.
- [ ] `cd backend && python manage.py makemigrations --check --dry-run` — confirms no missing migration was left uncommitted (Task 3's migration should already be committed).

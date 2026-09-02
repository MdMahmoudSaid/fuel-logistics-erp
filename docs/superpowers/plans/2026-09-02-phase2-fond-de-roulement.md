# Phase 2 — Fond de roulement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Fond de roulement" (working capital) figure and breakdown to the Dashboard, computed from data already assembled by `DashboardViewSet.summary()` — no new queries, no double-counting of capital already sitting in bank/caisse.

**Architecture:** One new dict key `working_capital` added to the existing `DashboardViewSet.summary()` payload (`backend/apps/reports/views/dashboard.py`), built entirely from local variables that function already computes (`bank_amounts`, `cash_amounts`, `customer_amounts`, `supplier_net_total`, `transporter_net_total`, `customs_total`, `transit_total`, `road_transit_total`, `other_total`) plus one new call to `ShareholderContributionService.get_total_capital()` (Phase 1, already merged). Frontend: one new computed + one new template section in `DashboardView.vue`, mirroring the existing `treasuryCard`/party-balances sections.

**Tech Stack:** Django 5 / DRF (backend/apps/reports), Vue 3 `<script setup>` + Vitest (frontend/src/modules/dashboard), pytest-django.

**Spec:** `docs/superpowers/specs/2026-09-02-business-corrections-6-phases-design.md` (Phase 2 section — read the corrected formula there, it fixes the original spec draft's double-counting and advance-as-liability mistakes).

## Global Constraints

- Formula: `working_capital.total = treasury_available + customer_receivables + supplier_net_balance + transporter_net_balance - other_debts`, where `supplier_net_balance`/`transporter_net_balance` are the SIGNED `supplier_net_total`/`transporter_net_total` values already computed in `summary()` (positive = net advance position, negative = net debt) — **add them, never subtract them as if they were pure debts.**
- `capital` (from `get_total_capital()`) appears in the payload as an informational figure only — it must NOT be added into `working_capital.total` (it's already reflected in `treasury_available` once a contribution has posted to a bank/cash account).
- Do not modify `party_balances`, `debts`, `financial_summary`, or any other existing key in the payload — purely additive.
- Do not add a new query/service call beyond `ShareholderContributionService.get_total_capital()` — every other figure must be reused from variables already in scope in `summary()`.

---

## File Structure

- **Modify** `backend/apps/reports/views/dashboard.py` — add `working_capital` key to `summary()`'s response, import `ShareholderContributionService`.
- **Modify** `backend/apps/reports/test_views.py` — new tests.
- **Modify** `frontend/src/modules/dashboard/types.ts` — add `working_capital` to `DashboardSummary`.
- **Modify** `frontend/src/modules/dashboard/DashboardView.vue` — new `workingCapitalCard` computed + template section.
- **Modify** `frontend/src/locales/fr.json`, `en.json`, `ar.json` — add `dashboard.workingCapital.*` keys.

---

## Task 1: Backend — `working_capital` in DashboardViewSet.summary()

**Files:**
- Modify: `backend/apps/reports/views/dashboard.py`
- Test: `backend/apps/reports/test_views.py`

**Interfaces:**
- Consumes: `ShareholderContributionService.get_total_capital()` (Phase 1, `apps.finance.services`), and the following variables already in scope inside `summary()` at the point `party_balances` is built (`backend/apps/reports/views/dashboard.py`, right after the `party_balances = {...}` block, i.e. after line ~296 in the current file — re-check the exact line before editing since the file may have shifted): `bank_amounts["total"]`, `cash_amounts["total"]`, `customer_amounts["total"]`, `supplier_net_total`, `transporter_net_total`, `customs_total`, `transit_total`, `road_transit_total`, `other_total`, `ZERO`.
- Produces: `working_capital` key in the `summary()` response: `{"capital": Decimal, "treasury_available": Decimal, "customer_receivables": Decimal, "supplier_net_balance": Decimal, "transporter_net_balance": Decimal, "other_debts": Decimal, "total": Decimal}` (all pass through `decimals_to_str` like the rest of the payload — no special handling needed, it's applied once at the end to the whole dict).

- [ ] **Step 1: Write the failing tests**

Read `backend/apps/reports/test_views.py` first to find `_make_admin`, `_make_full_trip`, and any existing helper for creating a supplier/transporter/customer/bank/shareholder-contribution fixture (mirror whatever helpers the file already has rather than reinventing them — e.g. `_make_admin(suffix)` already exists, confirmed at line ~274's test). Then append:

```python
@pytest.mark.django_db
def test_dashboard_summary_includes_working_capital_section():
    admin_user = _make_admin("DASHWC1")
    client = APIClient()
    client.force_authenticate(admin_user)

    response = client.get("/api/dashboard/summary/")

    assert response.status_code == 200, response.data
    assert set(response.data["working_capital"]) >= {
        "capital", "treasury_available", "customer_receivables",
        "supplier_net_balance", "transporter_net_balance", "other_debts", "total",
    }


@pytest.mark.django_db
def test_dashboard_working_capital_formula_matches_manual_calculation():
    from decimal import Decimal
    from apps.finance.models import BankAccount, CashAccount, Shareholder
    from apps.finance.services import ShareholderContributionService
    from django.core.files.uploadedfile import SimpleUploadedFile

    admin_user = _make_admin("DASHWC2")
    bank = BankAccount.objects.create(name="WC Bank", opening_balance=Decimal("10000000.00"))
    CashAccount.objects.create(name="WC Cash", opening_balance=Decimal("2000000.00"))
    shareholder = Shareholder.objects.create(
        name="WC Shareholder", participation_percent=Decimal("100.00"), contribution=Decimal("0.00"),
    )
    ShareholderContributionService.record_contribution(
        shareholder_id=shareholder.id, amount=Decimal("5000000.00"), date="2026-09-02",
        actor=admin_user, attachment=SimpleUploadedFile("p.jpg", b"x", content_type="image/jpeg"),
        bank_account_id=bank.id,
    )

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/dashboard/summary/")
    wc = response.data["working_capital"]

    # Bank now holds 10,000,000 (opening) + 5,000,000 (contribution) = 15,000,000.
    # Cash = 2,000,000. No suppliers/transporters/customers/debts exist in this
    # test, so treasury_available is the only nonzero component.
    assert wc["treasury_available"] == "17000000.00"
    assert wc["capital"] == "5000000.00"
    assert wc["total"] == "17000000.00"
    # Capital must NOT be double-counted: total == treasury_available exactly,
    # not treasury_available + capital.
    assert Decimal(wc["total"]) == Decimal(wc["treasury_available"])


@pytest.mark.django_db
def test_dashboard_working_capital_treats_open_advance_as_asset_not_liability():
    from decimal import Decimal
    from apps.finance.models import CashAccount
    from apps.finance.services import AdvanceService
    from apps.suppliers.models import Supplier
    from django.core.files.uploadedfile import SimpleUploadedFile

    admin_user = _make_admin("DASHWC3")
    cash = CashAccount.objects.create(name="WC Cash 2", opening_balance=Decimal("10000000.00"))
    supplier = Supplier.objects.create(name="WC Supplier", country="Senegal")

    client = APIClient()
    client.force_authenticate(admin_user)
    before = client.get("/api/dashboard/summary/").data["working_capital"]["total"]

    AdvanceService.create_supplier_advance(
        supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash.id,
        amount=Decimal("2000000.00"), date="2026-09-02", reference="", notes="",
        attachment=SimpleUploadedFile("p.jpg", b"x", content_type="image/jpeg"), actor=admin_user,
    )

    after = client.get("/api/dashboard/summary/").data["working_capital"]["total"]
    # Cash dropped by 2,000,000 but the advance is now an open asset
    # (supplier_net_balance +2,000,000) - total working capital is unchanged.
    assert after == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python -m pytest apps/reports/test_views.py -k working_capital -v`
Expected: FAIL — `KeyError: 'working_capital'`.

- [ ] **Step 3: Implement**

In `backend/apps/reports/views/dashboard.py`, add `ShareholderContributionService` to the existing `from apps.finance.services import ControlledDebtPaymentService, ShareholderProfitPreviewService` line (making it `from apps.finance.services import (ControlledDebtPaymentService, ShareholderContributionService, ShareholderProfitPreviewService)`).

Immediately after the `party_balances = {...}` dict is fully built (i.e. right after its closing `}`, before the "Only trips that have physically arrived..." comment that follows it), add:

```python
        # Fond de roulement (Phase 2, docs/superpowers/specs/2026-09-02-
        # business-corrections-6-phases-design.md): reuses the exact same
        # variables party_balances above already computed - never a second
        # query path that could disagree. Capital is shown for information
        # only and is NOT summed into total: a posted ShareholderContribution
        # already increased bank/cash, so adding it again here would double
        # count the same money. supplier_net_total/transporter_net_total are
        # signed (advances minus debts) and are ADDED, not subtracted - an
        # open advance is the company's asset, not a liability.
        treasury_available = bank_amounts["total"] + cash_amounts["total"]
        other_debts = customs_total + transit_total + road_transit_total + other_total
        working_capital = {
            "capital": ShareholderContributionService.get_total_capital(),
            "treasury_available": treasury_available,
            "customer_receivables": customer_amounts["total"],
            "supplier_net_balance": supplier_net_total,
            "transporter_net_balance": transporter_net_total,
            "other_debts": other_debts,
            "total": (
                treasury_available
                + customer_amounts["total"]
                + supplier_net_total
                + transporter_net_total
                - other_debts
            ),
        }
```

Then add `"working_capital": working_capital,` to the returned dict, immediately after the `"party_balances": party_balances,` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python -m pytest apps/reports/test_views.py -k working_capital -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full reports test suite for regressions**

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python -m pytest apps/reports -q`
Expected: PASS, same count as baseline plus 3.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/reports/views/dashboard.py backend/apps/reports/test_views.py
git commit -m "feat(reports): add working_capital (fond de roulement) to dashboard summary"
```

---

## Task 2: Frontend — display "Fond de roulement" on the Dashboard

**Files:**
- Modify: `frontend/src/modules/dashboard/types.ts`
- Modify: `frontend/src/modules/dashboard/DashboardView.vue`
- Modify: `frontend/src/modules/dashboard/__tests__/DashboardView.spec.ts` (if it exists — check first; if not, note that in your report and add the assertions to whichever existing dashboard spec file covers `treasuryCard`/`partyCards`)
- Modify: `frontend/src/locales/fr.json`, `en.json`, `ar.json`

**Interfaces:**
- Consumes: `DashboardSummary.working_capital` (produced by Task 1, already committed).
- Produces: a new `workingCapitalCard` computed property and a rendered "Fond de roulement" section, structurally parallel to the existing `treasuryCard`/"Trésorerie disponible" section.

- [ ] **Step 1: Add the type**

In `frontend/src/modules/dashboard/types.ts`, immediately after the `party_balances` block closes (find its matching closing `}` — read the file to confirm exact placement), add:

```typescript
  working_capital: {
    capital: string
    treasury_available: string
    customer_receivables: string
    supplier_net_balance: string
    transporter_net_balance: string
    other_debts: string
    total: string
  }
```

- [ ] **Step 2: Add locale keys**

In `frontend/src/locales/fr.json`, inside the existing `"final": { ... }` object (under the `dashboard` key — find it, confirmed to exist at the path `dashboard.final.*` from keys like `dashboard.final.availableTreasury`), add:

```json
      "workingCapital": "Fond de roulement",
      "workingCapitalHelp": "Vue financière large : trésorerie + créances clients + soldes nets fournisseurs/transporteurs - dettes douane/transit/frais. Différent de la trésorerie disponible (banques + caisses uniquement).",
      "capitalContributed": "Capital apporté (information)",
      "customerReceivables": "Créances clients",
      "supplierNetBalance": "Solde net fournisseurs",
      "transporterNetBalance": "Solde net transporteurs",
      "otherDebts": "Dettes douane/transit/frais",
```

Add the equivalent English keys inside `en.json`'s `dashboard.final` object (natural English, matching the sibling keys' style — e.g. `"workingCapital": "Working capital"`, `"workingCapitalHelp"` explaining the same distinction from available treasury in English) and the equivalent Arabic keys inside `ar.json`'s `dashboard.final` object, matching that file's existing terminology for "trésorerie"/"créances"/"dettes" already used by sibling keys in the same object.

- [ ] **Step 3: Write the failing test**

First check whether `frontend/src/modules/dashboard/__tests__/DashboardView.spec.ts` exists and what it currently covers (read it). Add a test following its existing mocking pattern for `summary`, extending the mocked summary fixture with a `working_capital` object, e.g.:

```typescript
it('renders the fond de roulement section', async () => {
  // extend this spec file's existing mocked summary object with:
  // working_capital: {
  //   capital: '5000000.00', treasury_available: '17000000.00',
  //   customer_receivables: '1000000.00', supplier_net_balance: '2000000.00',
  //   transporter_net_balance: '-500000.00', other_debts: '300000.00',
  //   total: '19200000.00',
  // }
  // then mount DashboardView, flushPromises, and assert the rendered
  // "Fond de roulement" heading and total amount appear in the DOM.
})
```

Write this test using whatever mount/mock helpers the existing spec file already uses (do not invent a new mocking approach) — the exact assertions should check that `t('dashboard.final.workingCapital')`'s rendered text and the formatted `total` value both appear in the wrapper's text.

- [ ] **Step 4: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/modules/dashboard/__tests__/DashboardView.spec.ts`
Expected: FAIL — section doesn't exist yet.

- [ ] **Step 5: Implement**

In `frontend/src/modules/dashboard/DashboardView.vue`, immediately after the `treasuryCard` computed (ends at the line `})` following `negative: Number(balance) < 0,`), add:

```typescript
const workingCapitalCard = computed(() => {
  if (!summary.value) return null
  const wc = summary.value.working_capital
  return {
    totalParts: formatMoneyParts(wc.total),
    negative: Number(wc.total) < 0,
    capitalParts: formatMoneyParts(wc.capital),
    treasuryParts: formatMoneyParts(wc.treasury_available),
    receivablesParts: formatMoneyParts(wc.customer_receivables),
    supplierParts: formatMoneyParts(wc.supplier_net_balance),
    transporterParts: formatMoneyParts(wc.transporter_net_balance),
    otherDebtsParts: formatMoneyParts(wc.other_debts),
  }
})
```

In the template, immediately after the closing `</section>` of the existing `treasury-card` section (the one containing `dashboard.final.availableTreasury`) and before the `</section>` that closes their shared parent grid (read the surrounding markup to confirm exactly where the parent section ends — do not nest incorrectly), add a new sibling section:

```html
<section class="working-capital-card border-ligne rounded-lg border bg-white p-4">
  <div class="flex items-center gap-2">
    <span
      class="bg-transit-tint text-transit-texte inline-flex size-8 shrink-0 items-center justify-center rounded-lg"
    >
      <Icon name="scale" :size="16" />
    </span>
    <h2 class="text-texte-2 text-sm font-semibold uppercase">
      {{ t('dashboard.final.workingCapital') }}
    </h2>
  </div>
  <p class="text-texte-3 mt-1 text-xs">{{ t('dashboard.final.workingCapitalHelp') }}</p>
  <p
    v-if="workingCapitalCard"
    class="mt-3 text-2xl font-semibold"
    :class="workingCapitalCard.negative ? 'text-critique' : 'text-texte'"
  >
    <MonoValue v-bind="workingCapitalCard.totalParts" align="left" />
  </p>
  <dl v-if="workingCapitalCard" class="mt-4 grid gap-2 text-sm">
    <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
      <dt class="text-texte-2">{{ t('dashboard.final.capitalContributed') }}</dt>
      <dd class="text-texte font-medium"><MonoValue v-bind="workingCapitalCard.capitalParts" /></dd>
    </div>
    <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
      <dt class="text-texte-2">{{ t('dashboard.final.availableTreasury') }}</dt>
      <dd class="text-texte font-medium"><MonoValue v-bind="workingCapitalCard.treasuryParts" /></dd>
    </div>
    <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
      <dt class="text-texte-2">{{ t('dashboard.final.customerReceivables') }}</dt>
      <dd class="text-texte font-medium"><MonoValue v-bind="workingCapitalCard.receivablesParts" /></dd>
    </div>
    <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
      <dt class="text-texte-2">{{ t('dashboard.final.supplierNetBalance') }}</dt>
      <dd class="text-texte font-medium"><MonoValue v-bind="workingCapitalCard.supplierParts" /></dd>
    </div>
    <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
      <dt class="text-texte-2">{{ t('dashboard.final.transporterNetBalance') }}</dt>
      <dd class="text-texte font-medium"><MonoValue v-bind="workingCapitalCard.transporterParts" /></dd>
    </div>
    <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
      <dt class="text-texte-2">{{ t('dashboard.final.otherDebts') }}</dt>
      <dd class="text-texte font-medium"><MonoValue v-bind="workingCapitalCard.otherDebtsParts" /></dd>
    </div>
  </dl>
</section>
```

If `Icon` doesn't have a `"scale"` icon available (check `frontend/src/components/ui/Icon.vue`'s icon set), substitute any existing finance-appropriate icon name already used elsewhere in this file (e.g. `"landmark"` again, or `"wallet"` if present) rather than adding a new icon — icon set changes are out of scope for this task.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/modules/dashboard/__tests__/DashboardView.spec.ts`
Expected: PASS.

- [ ] **Step 7: Run full frontend suite for regressions**

Run: `cd frontend && npx vitest run`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/modules/dashboard/types.ts frontend/src/modules/dashboard/DashboardView.vue frontend/src/modules/dashboard/__tests__/DashboardView.spec.ts frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json
git commit -m "feat(dashboard): display fond de roulement section"
```

---

## Self-Review Notes

- **Spec coverage:** formula matches the client-corrected spec exactly (signed net balances added, capital informational-only, no double counting). Breakdown sub-cards match the spec's requested list (Banques+Caisses as "Trésorerie disponible", Capital info, Créances clients, Solde net fournisseurs, Solde net transporteurs, Dettes douane/transit/frais, total). "Trésorerie disponible" stays visually distinct from "Fond de roulement" (two separate cards, not merged).
- **Type consistency:** `working_capital` key names in the backend dict (Task 1) match the TS interface field names (Task 2) exactly: `capital, treasury_available, customer_receivables, supplier_net_balance, transporter_net_balance, other_debts, total`.
- **Known risk for the implementer:** re-verify the exact current line numbers/surrounding markup in both `dashboard.py` and `DashboardView.vue` before editing — this plan's line-number references are investigation-time estimates on the post-Phase-1 `main` tip, not guaranteed current fact.

# Phase 3 — Dépenses générales + catégories configurables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user record general company expenses (loyer, salaires, internet...) with user-creatable categories, on a dedicated "Dépenses générales" page, while trip-linked expense categories (douane, transit, transit routière, frontière, chargement, transport) stay protected and untouched.

**Architecture:** A **parallel lookup table**, not a schema migration of `Expense.category`. New `ExpenseCategory` model (name, code, is_system, is_active, display_order) is seeded with the 14 existing category codes (6 marked `is_system=True`). `Expense.category` **stays a plain `CharField`** — its `choices=` kwarg is dropped and its DRF field is loosened to validate against `ExpenseCategory.objects.filter(code=value, is_active=True)` instead of a fixed enum. This means every one of the ~97 existing `Expense.Category.X` call sites across the codebase (TripCostService, ControlledDebtPaymentService, margin_report, labels.py, ~90 test fixtures) **keeps working unchanged** — `Expense.Category.CUSTOMS` is still just the string `"customs"`, which still matches an `ExpenseCategory` row. No FK conversion, no re-keying, no migration risk to the trip-cost/debt-bucket logic. The existing `ExpenseForm.vue` component (already supports creating an `Expense` with zero allocations) is reused for the general-expense create flow instead of building a new form from scratch; its category dropdown becomes dynamic (API-backed) instead of the static `EXPENSE_CATEGORIES` array. A new "Dépenses générales" page adds a list (filtered server-side to unallocated expenses) plus a read-only monitoring section that reuses the **already-existing** `/api/treasury-transactions/payable-debts/` endpoint — no new backend work needed for monitoring.

**Tech Stack:** Django 5 / DRF (backend/apps/finance), Vue 3 `<script setup>` + Vitest (frontend/src/modules/finance), pytest-django.

**Spec:** `docs/superpowers/specs/2026-09-02-business-corrections-6-phases-design.md` (Phase 3 section). Note: this plan's architecture is a deliberate, lower-risk simplification of the spec's original "convert `Expense.category` to a ForeignKey" idea — see Global Constraints for the ruling and why it satisfies every requirement without the migration blast radius.

## Global Constraints

- **Ruling (controller decision, not open for re-litigation mid-implementation):** `Expense.category` remains a `CharField`, never becomes a `ForeignKey`. The business requirements ("catégories système protégées", "catégories générales créables par l'utilisateur") are fully satisfied by a parallel `ExpenseCategory` lookup table plus validation-time checks. This avoids touching ~97 existing call sites and eliminates the data-migration risk the original spec draft flagged as the phase's biggest danger.
- The 6 system category codes (`customs`, `transit`, `road_transit`, `road`, `loading`, `transport`) must be seeded with `is_system=True` and must never be deletable, renamable, or deactivatable via the API.
- The other 8 existing codes (`import_intention`, `unloading`, `administration`, `rent`, `salary`, `repairs`, `bank_charges`, `other`) are seeded with `is_system=False` — freely editable, same as any user-created category.
- Do not touch `TripCostService`, `ControlledDebtPaymentService`, `margin_report.py`, or `labels.py` — their `Expense.Category.X` comparisons continue to work unchanged because the underlying string values never change.
- Do not touch `IndirectSettlementRequestSerializer.category` (stays restricted to `Expense.Category.choices` — indirect settlement is a trip-fee-paid-by-customer flow, not a place a "Loyer"/"Internet" category makes sense).
- A general expense = an `Expense` with zero `ExpenseAllocation` rows. Trip-linked expenses (with allocations) are unaffected by this phase and must keep working exactly as before.
- No new "kind" field distinguishing general vs. trip categories — `is_system` already captures the only distinction that needs enforcement (protection). Any active category (system or custom) may be selected for either a general or trip-linked expense; the general/trip distinction comes from allocation presence, not category choice.

---

## File Structure

- **Modify** `backend/apps/finance/models.py` — add `ExpenseCategory` model; drop `choices=Category.choices` from `Expense.category` field (keep the `Category` TextChoices class itself, other code still references `Expense.Category.CUSTOMS` etc. as plain string constants).
- **Create** `backend/apps/finance/migrations/0014_expensecategory.py` — new table + seed data migration.
- **Modify** `backend/apps/finance/serializers.py` — add `ExpenseCategorySerializer`; override `ExpenseSerializer.category` to validate against the new table instead of the dropped `choices=`.
- **Modify** `backend/apps/finance/views.py` — add `ExpenseCategoryViewSet` (blocks edit/delete on `is_system=True` rows); add `?unallocated=true` filter to `ExpenseViewSet.get_queryset()`.
- **Modify** `backend/apps/finance/urls.py` — register `expense-categories`.
- **Modify** `backend/apps/finance/tests.py` — new tests.
- **Modify** `frontend/src/modules/finance/types.ts` — add `ExpenseCategoryOption` interface (do not rename or remove the existing `ExpenseCategory` union type/`EXPENSE_CATEGORIES` array — other components still reference them); widen `Expense.category`'s field type to `string`.
- **Modify** `frontend/src/modules/finance/api.ts` — add `expenseCategoryResource`, `createExpenseCategory()`.
- **Modify** `frontend/src/modules/finance/ExpenseForm.vue` — category dropdown becomes API-backed with an inline "create new category" option.
- **Create** `frontend/src/modules/finance/ExpensesView.vue` — new "Dépenses générales" page.
- **Create** `frontend/src/modules/finance/__tests__/ExpensesView.spec.ts`.
- **Modify** `frontend/src/modules/finance/__tests__/ExpenseForm.spec.ts` (or wherever it lives — check first).
- **Modify** `frontend/src/router/index.ts` — new route.
- **Modify** `frontend/src/modules/shell/AppShell.vue` — new nav entry in the `treasury` group.
- **Modify** `frontend/src/locales/fr.json`, `en.json`, `ar.json` — new keys.

---

## Task 1: `ExpenseCategory` model + migration + serializer + viewset

**Files:**
- Modify: `backend/apps/finance/models.py`
- Create: `backend/apps/finance/migrations/0014_expensecategory.py`
- Modify: `backend/apps/finance/serializers.py`
- Modify: `backend/apps/finance/views.py`, `backend/apps/finance/urls.py`
- Test: `backend/apps/finance/tests.py`

**Interfaces:**
- Produces: `ExpenseCategory` model (`name`, `code` unique slug, `is_system` bool default False, `is_active` bool default True, `display_order` int default 0); `ExpenseCategorySerializer`; `ExpenseCategoryViewSet` at `/api/expense-categories/`.

- [ ] **Step 1: Write the failing tests**

Read `backend/apps/finance/tests.py`'s top imports and the `finance_client` fixture (line ~101) first, then append:

```python
@pytest.mark.django_db
def test_expense_category_migration_seeds_system_and_custom_categories():
    from apps.finance.models import ExpenseCategory

    system_codes = {"customs", "transit", "road_transit", "road", "loading", "transport"}
    seeded = {c.code: c.is_system for c in ExpenseCategory.objects.all()}
    assert system_codes <= set(seeded)
    for code in system_codes:
        assert seeded[code] is True
    assert seeded["rent"] is False
    assert seeded["other"] is False


@pytest.mark.django_db
def test_expense_category_crud_via_api(finance_client):
    response = finance_client.post(
        "/api/expense-categories/", {"name": "Internet", "code": "internet"}
    )
    assert response.status_code == 201, response.data
    assert response.data["is_system"] is False
    assert response.data["is_active"] is True

    list_response = finance_client.get("/api/expense-categories/")
    assert list_response.status_code == 200
    codes = {row["code"] for row in list_response.data["results"]}
    assert "internet" in codes
    assert "customs" in codes


@pytest.mark.django_db
def test_expense_category_system_rows_cannot_be_deactivated_or_renamed():
    from apps.finance.models import ExpenseCategory

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+22200000ADM", pin="1234", role=admin_role)
    client = APIClient()
    client.force_authenticate(admin_user)
    customs = ExpenseCategory.objects.get(code="customs")

    response = client.patch(
        f"/api/expense-categories/{customs.id}/", {"is_active": False}, format="json"
    )
    assert response.status_code == 400
    customs.refresh_from_db()
    assert customs.is_active is True

    rename_response = client.patch(
        f"/api/expense-categories/{customs.id}/", {"name": "Renamed"}, format="json"
    )
    assert rename_response.status_code == 400


@pytest.mark.django_db
def test_expense_category_system_rows_cannot_be_hard_deleted():
    from apps.finance.models import ExpenseCategory

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+22200000ADM2", pin="1234", role=admin_role)
    client = APIClient()
    client.force_authenticate(admin_user)
    customs = ExpenseCategory.objects.get(code="customs")

    response = client.delete(f"/api/expense-categories/{customs.id}/")
    assert response.status_code in (400, 405)
    assert ExpenseCategory.objects.filter(code="customs").exists()


@pytest.mark.django_db
def test_expense_category_non_system_rows_can_be_edited_and_deleted(finance_client):
    from apps.finance.models import ExpenseCategory

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+22200000ADM3", pin="1234", role=admin_role)
    client = APIClient()
    client.force_authenticate(admin_user)

    custom = ExpenseCategory.objects.create(name="Fournitures", code="fournitures")
    response = client.patch(
        f"/api/expense-categories/{custom.id}/", {"name": "Fournitures bureau"}, format="json"
    )
    assert response.status_code == 200
    delete_response = client.delete(f"/api/expense-categories/{custom.id}/")
    assert delete_response.status_code == 204
```

Add `Role, User` and `APIClient` to the top imports of `tests.py` if not already present (check first — `finance_client` already uses both, so they should already be imported).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python -m pytest apps/finance/tests.py -k expense_category -v`
Expected: FAIL — `ExpenseCategory` doesn't exist.

- [ ] **Step 3: Add the model**

In `backend/apps/finance/models.py`, immediately before the `Expense` class definition (around line 567), add:

```python
class ExpenseCategory(TimeStampedModel):
    """A lookup row for Expense.category (Phase 3, docs/superpowers/specs/
    2026-09-02-business-corrections-6-phases-design.md). Deliberately a
    PARALLEL table, not a ForeignKey target for Expense.category (which
    stays a plain CharField) - this lets every existing Expense.Category.X
    string comparison across the codebase (TripCostService,
    ControlledDebtPaymentService, margin_report.py, labels.py, and ~90 test
    fixtures) keep working unchanged, since the underlying string values
    never move. is_system=True rows are the 6 categories the trip-cost and
    debt-bucket calculations key off of by exact string match - they must
    never be renamed, deactivated, or deleted (enforced in
    ExpenseCategoryViewSet/Serializer), unlike a user-created category
    like "Internet" or "Loyer".
    """

    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=30, unique=True)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return self.name
```

Then, on the `Expense.category` field definition (currently `category = models.CharField(max_length=30, choices=Category.choices)`), remove the `choices=Category.choices` kwarg so it reads:

```python
    category = models.CharField(max_length=30)
```

Do NOT remove or modify the `class Category(models.TextChoices): ...` block above it — every other file's `Expense.Category.CUSTOMS`-style reference still needs that class to exist and keep returning the same string values.

- [ ] **Step 4: Generate and apply the migration**

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python manage.py makemigrations finance`
Expected: creates `apps/finance/migrations/0014_expensecategory.py` with two operations — `CreateModel` for `ExpenseCategory`, and `AlterField` on `Expense.category` (dropping `choices`). Open it and confirm both are there and nothing else changed.

Add a `migrations.RunPython` seed step to the generated migration (append to its `operations` list), following the exact pattern of `backend/apps/accounts/migrations/0002_seed_roles.py` or `0005_seed_shareholder_permissions.py` (read one of those first for the forward/reverse structure):

```python
SYSTEM_CODES = {"customs", "transit", "road_transit", "road", "loading", "transport"}

ALL_CATEGORIES = [
    ("customs", "Customs"), ("import_intention", "Import intention"), ("transit", "Transit"),
    ("road_transit", "Road transit"), ("transport", "Transport"), ("loading", "Loading"),
    ("unloading", "Unloading"), ("road", "Road"), ("administration", "Administration"),
    ("rent", "Rent"), ("salary", "Salary"), ("repairs", "Repairs"),
    ("bank_charges", "Bank charges"), ("other", "Other"),
]


def seed_expense_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model("finance", "ExpenseCategory")
    for order, (code, name) in enumerate(ALL_CATEGORIES):
        ExpenseCategory.objects.get_or_create(
            code=code, defaults={"name": name, "is_system": code in SYSTEM_CODES, "display_order": order},
        )


def unseed_expense_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model("finance", "ExpenseCategory")
    ExpenseCategory.objects.filter(code__in=[c for c, _ in ALL_CATEGORIES]).delete()
```

Add `migrations.RunPython(seed_expense_categories, unseed_expense_categories)` as the last item in the migration's `operations` list.

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python manage.py migrate finance`
Expected: applies cleanly, 14 `ExpenseCategory` rows created.

- [ ] **Step 5: Implement the serializer and viewset**

In `backend/apps/finance/serializers.py`, add (anywhere near `ExpenseSerializer`, e.g. immediately before it):

```python
class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "name", "code", "is_system", "is_active", "display_order"]
        read_only_fields = ["id", "is_system"]

    def validate(self, data):
        if self.instance is not None and self.instance.is_system:
            changed_fields = {
                key for key, value in data.items()
                if key != "is_system" and getattr(self.instance, key) != value
            }
            if changed_fields:
                raise serializers.ValidationError(
                    "Une categorie systeme ne peut pas etre modifiee."
                )
        return data
```

Add `ExpenseCategory` to the model import block at the top of `serializers.py` (the block importing `Expense`).

In `backend/apps/finance/views.py`, add (near `ExpenseViewSet`):

```python
class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    filterset_fields = ["is_system", "is_active"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_system:
            return Response(
                {"detail": "Une categorie systeme ne peut pas etre supprimee."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)
```

Add `ExpenseCategory` to the model import block and `ExpenseCategorySerializer` to the serializer import block at the top of `views.py`.

In `backend/apps/finance/urls.py`, add the import and register: `router.register("expense-categories", ExpenseCategoryViewSet, basename="expensecategory")`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python -m pytest apps/finance/tests.py -k expense_category -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Run the full finance suite for regressions**

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python -m pytest apps/finance apps/trips apps/reports -q`
Expected: PASS, no existing test broken — this specifically checks that dropping `choices=` from `Expense.category` and adding the new model didn't disturb `TripCostService`/`ControlledDebtPaymentService`/`margin_report.py`'s existing behavior (it shouldn't have touched them at all).

- [ ] **Step 8: Commit**

```bash
git add backend/apps/finance/models.py backend/apps/finance/migrations/0014_expensecategory.py backend/apps/finance/serializers.py backend/apps/finance/views.py backend/apps/finance/urls.py backend/apps/finance/tests.py
git commit -m "feat(finance): add configurable ExpenseCategory lookup with protected system categories"
```

---

## Task 2: Loosen `Expense.category` validation + add unallocated filter

**Files:**
- Modify: `backend/apps/finance/serializers.py` (`ExpenseSerializer`)
- Modify: `backend/apps/finance/views.py` (`ExpenseViewSet`)
- Test: `backend/apps/finance/tests.py`

**Interfaces:**
- Consumes: `ExpenseCategory` (Task 1).
- Produces: `ExpenseSerializer.category` accepts any code matching an active `ExpenseCategory` row (not just the original 14 enum values); `GET /api/expenses/?unallocated=true` returns only `Expense` rows with zero `ExpenseAllocation`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/finance/tests.py`:

```python
@pytest.mark.django_db
def test_expense_accepts_custom_category(finance_client):
    from apps.finance.models import ExpenseCategory

    ExpenseCategory.objects.create(name="Internet", code="internet")
    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "internet", "amount": "50000.00",
            "calculation_method": "MANUAL", "date": "2026-09-02",
        },
    )
    assert response.status_code == 201, response.data
    assert response.data["category"] == "internet"


@pytest.mark.django_db
def test_expense_rejects_unknown_category(finance_client):
    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "not_a_real_category", "amount": "50000.00",
            "calculation_method": "MANUAL", "date": "2026-09-02",
        },
    )
    assert response.status_code == 400
    assert "category" in response.data


@pytest.mark.django_db
def test_expense_still_accepts_system_categories(finance_client):
    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "customs", "amount": "100000.00",
            "calculation_method": "FIXED", "date": "2026-09-02",
        },
    )
    assert response.status_code == 201, response.data


@pytest.mark.django_db
def test_expense_rejects_inactive_category(finance_client):
    from apps.finance.models import ExpenseCategory

    ExpenseCategory.objects.create(name="Old", code="old_cat", is_active=False)
    response = finance_client.post(
        "/api/expenses/",
        {
            "category": "old_cat", "amount": "10000.00",
            "calculation_method": "MANUAL", "date": "2026-09-02",
        },
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_expense_list_unallocated_filter(finance_client):
    unallocated = Expense.objects.create(
        category=Expense.Category.RENT, amount=Decimal("300000.00"),
        calculation_method=Expense.CalculationMethod.MANUAL, date="2026-09-02",
    )
    trip, _ = _make_trip_for_deduction("UNALLOC")
    allocated = Expense.objects.create(
        category=Expense.Category.CUSTOMS, amount=Decimal("100000.00"),
        calculation_method=Expense.CalculationMethod.FIXED, date="2026-09-02",
    )
    ExpenseAllocation.objects.create(
        expense=allocated, content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id, allocated_amount=Decimal("100000.00"),
    )

    response = finance_client.get("/api/expenses/?unallocated=true")

    assert response.status_code == 200
    returned_ids = {row["id"] for row in response.data["results"]}
    assert unallocated.id in returned_ids
    assert allocated.id not in returned_ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python -m pytest apps/finance/tests.py -k "custom_category or unknown_category or system_categories or inactive_category or unallocated_filter" -v`
Expected: FAIL — `test_expense_accepts_custom_category`/`inactive_category`/`unallocated_filter` fail (category still restricted to old choices / no filter yet); `test_expense_still_accepts_system_categories` and `test_expense_rejects_unknown_category` may already pass by coincidence (DRF's default ChoiceField already rejects unknown values) — that's fine, just confirm the others fail for the right reason.

- [ ] **Step 3: Implement**

In `backend/apps/finance/serializers.py`, in `ExpenseSerializer` (around line 572), add an explicit `category` field to override DRF's auto-derived one (since `choices=` was dropped from the model, DRF would otherwise fall back to a plain unconstrained `CharField` with no validation at all — we need the explicit `ExpenseCategory` check):

```python
class ExpenseSerializer(serializers.ModelSerializer):
    allocations_detail = ExpenseAllocationSerializer(source="allocations", many=True, read_only=True)
    allocations = ExpenseAllocationInputSerializer(many=True, write_only=True, required=False)
    category = serializers.CharField()

    class Meta:
        model = Expense
        fields = [
            "id", "category", "amount", "calculation_method", "date", "status",
            "paid_by_customer_directly", "notes",
            "allocations", "allocations_detail", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "paid_by_customer_directly", "created_at", "updated_at"]

    def validate_category(self, value):
        if not ExpenseCategory.objects.filter(code=value, is_active=True).exists():
            raise serializers.ValidationError("Categorie de depense invalide ou inactive.")
        return value

    def create(self, validated_data):
        ...  # unchanged, do not modify
```

(Only add the `category = serializers.CharField()` field declaration and the `validate_category` method — leave `create()`/`update()` exactly as they are.)

In `backend/apps/finance/views.py`, in `ExpenseViewSet.get_queryset()` (around line 180), add the unallocated filter alongside the existing `trip` filter:

```python
    def get_queryset(self):
        queryset = super().get_queryset()
        trip_id = self.request.query_params.get("trip")
        if trip_id:
            trip_content_type = ContentType.objects.get_for_model(Trip)
            queryset = queryset.filter(
                allocations__content_type=trip_content_type, allocations__object_id=trip_id
            ).distinct()
        if self.request.query_params.get("unallocated") == "true":
            queryset = queryset.filter(allocations__isnull=True)
        return queryset
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python -m pytest apps/finance/tests.py -k "custom_category or unknown_category or system_categories or inactive_category or unallocated_filter" -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full finance/trips/reports suites for regressions**

Run: `cd backend && /Users/mohamed/Downloads/fuel-logistics-erp/backend/.venv/bin/python -m pytest apps/finance apps/trips apps/reports -q`
Expected: PASS, no regressions — this is the critical check that `IndirectSettlementRequestSerializer` (untouched) and every existing `Expense`-creating test (still using `Expense.Category.X` string constants, all still valid `ExpenseCategory` codes from Task 1's seed) still work.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/serializers.py backend/apps/finance/views.py backend/apps/finance/tests.py
git commit -m "feat(finance): validate Expense.category against ExpenseCategory, add unallocated filter"
```

---

## Task 3: Frontend — dynamic category dropdown in `ExpenseForm.vue`

**Files:**
- Modify: `frontend/src/modules/finance/types.ts`
- Modify: `frontend/src/modules/finance/api.ts`
- Modify: `frontend/src/modules/finance/ExpenseForm.vue`
- Modify: whichever spec file currently covers `ExpenseForm.vue` (check `frontend/src/modules/finance/__tests__/` first)
- Modify: `frontend/src/locales/fr.json`, `en.json`, `ar.json`

**Interfaces:**
- Produces: `ExpenseCategoryOption` interface (`id, name, code, is_system, is_active, display_order`), `expenseCategoryResource`, `createExpenseCategory(payload: {name: string; code: string}): Promise<ExpenseCategoryOption>`.
- Does NOT remove or rename the existing `ExpenseCategory` TS union type or `EXPENSE_CATEGORIES` array in `types.ts` — other components (e.g. `TripDetail.vue`'s `automaticExpenseByStatus`) still reference them for their fixed literal values; this task adds a new, separate lookup type alongside them.

- [ ] **Step 1: Add types and API client**

In `frontend/src/modules/finance/types.ts`, immediately after the existing `EXPENSE_CATEGORIES` array (do not modify that array or the `ExpenseCategory` union type above it), add:

```typescript
export interface ExpenseCategoryOption {
  id: number
  name: string
  code: string
  is_system: boolean
  is_active: boolean
  display_order: number
}
```

Find the `Expense` interface's `category: ExpenseCategory` field and widen it to `category: string` (a custom category code is no longer guaranteed to be one of the 14 fixed literals).

In `frontend/src/modules/finance/api.ts`, add:

```typescript
export const expenseCategoryResource = createResourceApi<ExpenseCategoryOption>(
  '/expense-categories/',
)

export function createExpenseCategory(payload: {
  name: string
  code: string
}): Promise<ExpenseCategoryOption> {
  return apiClient.post<ExpenseCategoryOption>('/expense-categories/', payload).then((r) => r.data)
}
```

Add `ExpenseCategoryOption` to the existing `import type { ... } from './types'` block.

- [ ] **Step 2: Add locale keys**

In `frontend/src/locales/fr.json`, find the `expenseCategory` object (it holds i18n keys for each of the 14 fixed category values, referenced by `ExpenseForm.vue`'s dropdown per-option label — confirm its exact location by reading the file) and, in the same general area, add a new small object for the "create category" inline UI:

```json
    "expenseCategoryForm": {
      "createNew": "+ Créer une nouvelle catégorie",
      "newCategoryName": "Nom de la nouvelle catégorie",
      "createButton": "Créer",
      "cancelButton": "Annuler",
      "createError": "Impossible de créer cette catégorie."
    },
```

Add the equivalent English (`en.json`) and Arabic (`ar.json`) blocks at the same nesting location in each file, matching the surrounding style.

- [ ] **Step 3: Write the failing test**

First read the existing spec file covering `ExpenseForm.vue` (check `frontend/src/modules/finance/__tests__/` for one — if none exists, say so in your report and add a new minimal spec file mirroring `ContributionForm.spec.ts`'s mocking conventions). Add:

```typescript
it('loads categories from the API and can create a new one inline', async () => {
  // Mock expenseCategoryResource.list() to return a fixed set of categories
  // (e.g. { id: 1, name: 'Douane', code: 'customs', is_system: true, is_active: true, display_order: 0 }
  // and one custom one), mount ExpenseForm, flushPromises, assert the
  // category <select> lists both by name. Then click the "+ Créer une
  // nouvelle catégorie" control, type a name, submit, and assert
  // createExpenseCategory was called with the typed name and a
  // slugified code, and that the new category becomes selected afterward.
})
```

Write the actual assertions using whatever mount/mock pattern the existing spec file for this component already uses.

- [ ] **Step 4: Run test to verify it fails**

Run: `cd frontend && npx vitest run` (target the specific spec file once you've confirmed its path)
Expected: FAIL — category dropdown is still the static `EXPENSE_CATEGORIES` array, no create-new control exists.

- [ ] **Step 5: Implement**

In `frontend/src/modules/finance/ExpenseForm.vue`:
1. Replace the static `import { EXPENSE_CATEGORIES } from './types'` usage in the template's category `<select>` with a reactive `categories = ref<ExpenseCategoryOption[]>([])` populated via `expenseCategoryResource.list()` in the component's existing load/onMounted flow (read the current file to find where other reference data — e.g. banks/cash accounts, if this form loads any — is fetched, and follow that same pattern).
2. Add a "+ Créer une nouvelle catégorie" option/button below the dropdown. On click, show a small inline name input; on submit, call `createExpenseCategory({ name, code: slugify(name) })` (implement a minimal local slugify — lowercase, replace non-alphanumeric runs with `_`, trim — do not add a new dependency for this), append the result to `categories.value`, and select it.
3. Keep the default category value logic working: if the form has no `initialCategory` prop, default to whatever the first loaded category is (or keep `'other'` as the fallback default if it's still present in the loaded list — check the current default logic before changing it).

Do not touch `calculation_method`, `allocations`, or any other part of this form — this task is scoped to the category field only.

- [ ] **Step 6: Run test to verify it passes**

Run the same command as Step 4.
Expected: PASS.

- [ ] **Step 7: Run full frontend suite for regressions**

Run: `cd frontend && npx vitest run`
Expected: PASS — this specifically checks that `TripDetail.vue`'s existing "Frais du trajet" flow (which also renders `ExpenseForm.vue` with a `presetAllocation`) still works with the new dynamic category source.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/modules/finance/types.ts frontend/src/modules/finance/api.ts frontend/src/modules/finance/ExpenseForm.vue frontend/src/modules/finance/__tests__/*.spec.ts frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json
git commit -m "feat(finance): make ExpenseForm category dropdown dynamic with inline category creation"
```

---

## Task 4: "Dépenses générales" page + monitoring section + navigation

**Files:**
- Create: `frontend/src/modules/finance/ExpensesView.vue`
- Create: `frontend/src/modules/finance/__tests__/ExpensesView.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/modules/shell/AppShell.vue`
- Modify: `frontend/src/locales/fr.json`, `en.json`, `ar.json`

**Interfaces:**
- Consumes: `expenseResource` (already exists in `./api`), `?unallocated=true` filter (Task 2), `ExpenseForm.vue` (Task 3, used with no `presetAllocation` prop — already supported), `fetchPayableDebts`/`DebtPaymentType`/`PayableDebt` (already exist in `./api`/`./types`).

- [ ] **Step 1: Add the route**

In `frontend/src/router/index.ts`, in the same route array as the other finance children (near `treasury/transactions`, `bank-accounts`, etc.), add:

```typescript
{
  path: 'expenses',
  name: 'expenses',
  component: () => import('@/modules/finance/ExpensesView.vue'),
},
```

- [ ] **Step 2: Add the nav entry**

In `frontend/src/modules/shell/AppShell.vue`, in the `treasury` nav group's `items` array (alongside `treasury-transactions`, `bank-accounts`, `cash-accounts`), add:

```typescript
{ to: 'expenses', labelKey: 'navigation.expenses', module: 'finance' },
```

Add an icon mapping entry for `expenses` in the icon map near the top of the file (find where `profit`/`shareholders` map to icon names, e.g. `expenses: 'receipt'` — check `frontend/src/components/ui/Icon.vue` for an available icon name close to "receipt"/"file-text"/"wallet"; use whichever already exists rather than adding a new one).

- [ ] **Step 3: Add locale keys**

In `frontend/src/locales/fr.json`, add `"navigation": { ..., "expenses": "Dépenses" }` (add the key to the existing `navigation` object — do not create a new one), and a new top-level-ish section (matching how sibling pages like `finance.shareholder` are namespaced) e.g.:

```json
    "expensesView": {
      "title": "Dépenses générales",
      "newExpense": "Nouvelle dépense",
      "periodFilter": "Période",
      "listEmpty": "Aucune dépense enregistrée sur cette période.",
      "monitoringTitle": "Suivi des dettes de frais trajet",
      "monitoringHelp": "Lecture seule : ces montants proviennent des frais trajet existants, aucune nouvelle dette n'est créée ici.",
      "monitoring": {
        "customs": "Douane",
        "transit": "Transit",
        "roadTransit": "Transit routière",
        "border": "Frontière",
        "loading": "Chargement",
        "tripOther": "Autres frais trajet"
      }
    },
```

Add the equivalent English/Arabic translations to `en.json`/`ar.json` at the same nesting location, matching each file's existing style for sibling finance pages.

- [ ] **Step 4: Write the failing test**

Create `frontend/src/modules/finance/__tests__/ExpensesView.spec.ts`, mirroring the mocking conventions of an existing simple list-page spec in this directory (check `ProfitView.spec.ts` or similar for the pattern — mock `expenseResource.list()`, `fetchPayableDebts`, mount, flushPromises). Write tests for:
1. Renders the page title and an empty-state message when the expense list is empty.
2. Renders a list row for each returned unallocated expense (mock `expenseResource.list` to have been called with `{ unallocated: 'true' }` or equivalent params, per whatever the resource API's `list()` signature supports for query params — check `createResourceApi`'s implementation first).
3. Clicking "Nouvelle dépense" opens the `ExpenseForm` modal.
4. The monitoring section renders the 6 debt buckets (mock `fetchPayableDebts` to return distinct amounts per `debt_type` and assert each rendered label + amount).

- [ ] **Step 5: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ExpensesView.spec.ts`
Expected: FAIL — component doesn't exist.

- [ ] **Step 6: Implement `ExpensesView.vue`**

Structure (mirror `ProfitView.vue` or `TreasuryLedgerView.vue`'s overall page shape — header + filter + list + modal, check one of those files for the exact styling conventions before writing this):

- A page header with title and a "Nouvelle dépense" button that opens `ExpenseForm` in a `Modal` (no `presetAllocation` prop — creates a standalone, unallocated expense).
- A period filter (reuse the existing `DateRangeFilter` component if this codebase has one already wired into a similar list page — check `ReportsView.vue`'s usage of it as a template) filtering the list's `date` client-side or via query params, whichever this codebase's list pages already do elsewhere.
- A table/list of `Expense` rows fetched via `expenseResource.list({ unallocated: 'true' })` — confirmed correct: `createResourceApi`'s `list(params?: Record<string, unknown>)` (`frontend/src/api/resource.ts:11,23`) passes `params` straight through to axios as query params. Showing category name (resolve `category` code to a human label via the categories fetched in Task 3's `expenseCategoryResource`, or via `t('expenseCategory.' + code)` for the fixed ones — check how existing category labels are displayed elsewhere in this codebase, e.g. `TripDetail.vue`'s `tripExpenseLabel`, and follow the same resolution approach), amount, date, reference/notes.
- A read-only "Suivi des dettes de frais trajet" section below the list, with 6 sub-cards (Douane/Transit/Transit routière/Frontière/Chargement/Autres), each populated by `fetchPayableDebts('customs')`, `fetchPayableDebts('transit')`, `fetchPayableDebts('road_transit')`, `fetchPayableDebts('border')`, `fetchPayableDebts('loading')`, `fetchPayableDebts('trip_other')` respectively, displaying each result's `remaining_amount`. This section creates no new expense/debt — it is purely a read of the existing `payable-debts` endpoint, exactly as the spec requires ("aucune nouvelle dette n'est créée").

- [ ] **Step 7: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ExpensesView.spec.ts`
Expected: PASS.

- [ ] **Step 8: Run full frontend suite for regressions**

Run: `cd frontend && npx vitest run`
Expected: PASS, no regressions.

- [ ] **Step 9: Manual smoke check note**

No dev server available in the sandboxed execution context — note this explicitly in the report rather than attempting it.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/modules/finance/ExpensesView.vue frontend/src/modules/finance/__tests__/ExpensesView.spec.ts frontend/src/router/index.ts frontend/src/modules/shell/AppShell.vue frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json
git commit -m "feat(finance): add Depenses generales page with trip-fee debt monitoring"
```

---

## Self-Review Notes

- **Spec coverage:** system categories protected (Task 1), general categories user-creatable (Tasks 1+3), general expense = unallocated Expense (Task 2 filter, Task 4 page), monitoring section reads existing debts without creating new ones (Task 4, reuses `payable-debts` endpoint verbatim). The spec's original "convert category to FK" idea is deliberately NOT implemented — see the Global Constraints ruling; the parallel-table approach satisfies every stated requirement with far less risk, since none of the ~97 existing `Expense.Category.X` call sites needed to change.
- **Type consistency:** `ExpenseCategoryOption` field names (Task 1's backend serializer) match Task 3's TS interface exactly. `createExpenseCategory`'s payload (`name`, `code`) matches what Task 3's inline-create UI sends.
- **Risk retired vs. original spec draft:** no data migration converts existing `Expense.category` string values — they were never touched, since the field's underlying type never changes. The only schema change is dropping `choices=` (a validation-time-only Django feature, not a DB constraint) and adding one new table.
- **Verified during planning:** `createResourceApi`'s `list(params?: Record<string, unknown>)` (`frontend/src/api/resource.ts:11,23`) passes params straight to axios — `expenseResource.list({ unallocated: 'true' })` in Task 4 is confirmed correct syntax, no ambiguity for the implementer.

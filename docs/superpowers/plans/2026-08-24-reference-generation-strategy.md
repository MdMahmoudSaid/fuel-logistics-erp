# Stratégie globale de génération des références — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Server-authoritative, race-safe reference generation (`ACH-YYYYMM-XXXX` / `CES-YYYYMM-XXXX` / `FAC-YYYYMM-XXXX`) for SupplierOrder, CessionLetter and Invoice, plus consistent per-field 400 error handling across the supply-chain creation forms.

**Architecture:** A single shared backend generator (`apps.core.reference.generate_monthly_reference`) computes `PREFIX-YYYYMM-NNNN` from the current max reference for that model/month, reused by three call sites with the same retry-on-`IntegrityError` savepoint pattern `TripViewSet` already uses for its own (unrelated, unmodified) `TRIP-000001` sequence. `reference`/`invoice_number` become read-only at the API boundary; a small non-reserving "preview" `GET` action lets the two affected forms display a value before submit. A shared frontend `extractFieldErrors` helper replaces three different ad hoc/buggy 400-parsing implementations.

**Tech Stack:** Django REST Framework (backend/apps/*), Vue 3 `<script setup>` + vue-i18n (frontend/src/modules/*), pytest (backend/apps/*/tests.py), Vitest + @vue/test-utils (frontend/src/modules/*/__tests__/*.spec.ts).

**Spec:** `docs/superpowers/specs/2026-08-24-reference-generation-strategy-design.md`

## Global Constraints

- Reference format: `PREFIX-YYYYMM-NNNN`, `NNNN` a 4-digit, zero-padded, **monthly** sequential counter per prefix (not global, not random). `ACH` for SupplierOrder, `CES` for CessionLetter, `FAC` for Invoice.
- Trip's own `reference` (`TRIP-000001`, sequential, no date) is explicitly **out of scope** — do not touch `apps/trips/views.py`'s existing `_generate_next_reference`/`_REFERENCE_PREFIX`/`_REFERENCE_WIDTH`.
- No model changes, no migrations — `unique=True` already exists on every affected field; only serializer `read_only_fields` and view/service generation logic change.
- Error-handling audit scope is exactly four forms: `SupplierOrderForm.vue`, `CessionLetterForm.vue`, `TripForm.vue`, `CustomerOrderForm.vue`. Do not touch any other form.
- All new/changed reference inputs get `autocomplete="off"` and are rendered `disabled` (server-authoritative, never user-editable, in both create and edit mode).
- Backend tests: pytest, `@pytest.mark.django_db`, run from `backend/` with `pytest apps/<app>/tests.py -v`. Frontend tests: `npm run test:unit` (or `npx vitest run <path>`) from `frontend/`.

---

### Task 1: Shared monthly reference generator

**Files:**
- Create: `backend/apps/core/reference.py`
- Test: `backend/apps/core/tests.py` (append)

**Interfaces:**
- Produces: `generate_monthly_reference(model, field_name: str, prefix: str, width: int = 4, now: datetime | None = None) -> str` — importable as `from apps.core.reference import generate_monthly_reference`. Returns `f"{prefix}-{YYYYMM}-{NNNN}"`; ignores any existing value for `field_name` that doesn't match that exact format (so hand-typed/legacy values never perturb the count); `now` param exists purely for deterministic testing (defaults to `django.utils.timezone.now()`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/core/tests.py`:

```python
from datetime import datetime

from django.utils import timezone

from apps.core.reference import generate_monthly_reference
from apps.purchasing.models import SupplierOrder
from apps.suppliers.models import Supplier


@pytest.mark.django_db
def test_generate_monthly_reference_starts_at_0001():
    reference = generate_monthly_reference(SupplierOrder, "reference", "ACH")
    yyyymm = timezone.now().strftime("%Y%m")
    assert reference == f"ACH-{yyyymm}-0001"


@pytest.mark.django_db
def test_generate_monthly_reference_increments_within_month():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000030", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    now = timezone.now()
    yyyymm = now.strftime("%Y%m")

    SupplierOrder.objects.create(
        reference=f"ACH-{yyyymm}-0001",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100.00"),
        unit_price=Decimal("600.00"),
        created_by=admin_user,
    )
    SupplierOrder.objects.create(
        reference=f"ACH-{yyyymm}-0002",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100.00"),
        unit_price=Decimal("600.00"),
        created_by=admin_user,
    )

    reference = generate_monthly_reference(SupplierOrder, "reference", "ACH")
    assert reference == f"ACH-{yyyymm}-0003"


@pytest.mark.django_db
def test_generate_monthly_reference_ignores_legacy_format():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000031", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")

    # Hand-typed/legacy reference that doesn't match PREFIX-YYYYMM-NNNN.
    SupplierOrder.objects.create(
        reference="SO-LEGACY-9999",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100.00"),
        unit_price=Decimal("600.00"),
        created_by=admin_user,
    )

    reference = generate_monthly_reference(SupplierOrder, "reference", "ACH")
    yyyymm = timezone.now().strftime("%Y%m")
    assert reference == f"ACH-{yyyymm}-0001"


@pytest.mark.django_db
def test_generate_monthly_reference_scoped_to_current_month():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000032", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")

    # A reference from a different (earlier) month must not affect this
    # month's count.
    SupplierOrder.objects.create(
        reference="ACH-202001-0099",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100.00"),
        unit_price=Decimal("600.00"),
        created_by=admin_user,
    )

    reference = generate_monthly_reference(SupplierOrder, "reference", "ACH")
    yyyymm = timezone.now().strftime("%Y%m")
    assert reference == f"ACH-{yyyymm}-0001"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest apps/core/tests.py -k generate_monthly_reference -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.core.reference'`

- [ ] **Step 3: Write the implementation**

Create `backend/apps/core/reference.py`:

```python
import re

from django.utils import timezone


def generate_monthly_reference(model, field_name, prefix, width=4, now=None) -> str:
    """Next PREFIX-YYYYMM-NNNN for `model.field_name`, scoped to the current
    calendar month.

    Reads the current highest matching value and increments it - there's no
    dedicated sequence table (same trade-off as
    apps.trips.views._generate_next_reference). Callers are responsible for
    retrying on IntegrityError to cover the race between two concurrent
    creates picking the same number.

    The regex restricts the lookup to values matching our own generated
    format (exact prefix, exact month, fixed-width digits) - hand-typed or
    legacy references in a different format are ignored rather than
    corrupting the count or being mistaken for the highest value.
    """
    now = now or timezone.now()
    yyyymm = now.strftime("%Y%m")
    full_prefix = f"{prefix}-{yyyymm}-"
    pattern = rf"^{re.escape(full_prefix)}\d{{{width}}}$"

    last = (
        model.objects.filter(**{f"{field_name}__regex": pattern})
        .order_by(f"-{field_name}")
        .first()
    )
    last_number = 0
    if last:
        try:
            last_number = int(getattr(last, field_name)[len(full_prefix) :])
        except ValueError:
            last_number = 0

    return f"{full_prefix}{last_number + 1:0{width}d}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest apps/core/tests.py -k generate_monthly_reference -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/apps/core/reference.py backend/apps/core/tests.py
git commit -m "feat(backend): add shared monthly reference generator"
```

---

### Task 2: SupplierOrder — server-generated `ACH-YYYYMM-NNNN` reference

**Files:**
- Modify: `backend/apps/purchasing/serializers.py:104-110` (SupplierOrderSerializer.Meta.read_only_fields)
- Modify: `backend/apps/purchasing/views.py:1-36` (imports, SupplierOrderViewSet)
- Test: `backend/apps/purchasing/tests.py` (append)

**Interfaces:**
- Consumes: `generate_monthly_reference(model, field_name, prefix, width=4, now=None) -> str` from Task 1.
- Produces: `GET /api/supplier-orders/next-reference/` → `{"reference": "ACH-202608-0001"}`. `POST /api/supplier-orders/` ignores any client-supplied `reference` and always returns the server-generated one.

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/purchasing/tests.py`:

```python
@pytest.mark.django_db
def test_supplier_order_reference_is_server_generated():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000040", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.post(
        "/api/supplier-orders/",
        {
            "reference": "CLIENT-SUPPLIED-IGNORED",
            "supplier": supplier.id,
            "product": product.id,
            "purchase_date": "2026-08-18",
            "quantity_litres": "50000.00",
            "unit_price": "600.0000",
        },
    )
    assert response.status_code == 201
    assert response.data["reference"] != "CLIENT-SUPPLIED-IGNORED"
    assert response.data["reference"].startswith("ACH-")


@pytest.mark.django_db
def test_supplier_order_next_reference_endpoint():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000041", pin="1234", role=admin_role
    )
    client = APIClient()
    client.force_authenticate(admin_user)

    response = client.get("/api/supplier-orders/next-reference/")
    assert response.status_code == 200
    assert response.data["reference"].startswith("ACH-")

    # Non-reserving: calling it again without creating anything returns the
    # same preview value.
    response_again = client.get("/api/supplier-orders/next-reference/")
    assert response_again.data["reference"] == response.data["reference"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest apps/purchasing/tests.py -k "reference_is_server_generated or next_reference_endpoint" -v`
Expected: FAIL — `test_supplier_order_reference_is_server_generated` fails because `response.data["reference"] == "CLIENT-SUPPLIED-IGNORED"`; `test_supplier_order_next_reference_endpoint` fails with 404 (no such route).

- [ ] **Step 3: Write the implementation**

In `backend/apps/purchasing/serializers.py`, update `SupplierOrderSerializer.Meta.read_only_fields` (currently lines 104-110):

```python
        read_only_fields = [
            "id",
            "reference",
            "total_amount",
            "created_by",
            "created_at",
            "updated_at",
        ]
```

In `backend/apps/purchasing/views.py`, update the imports and `SupplierOrderViewSet`:

```python
from django.db import IntegrityError, transaction
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.core.reference import generate_monthly_reference
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.purchasing.serializers import CessionLetterSerializer, SupplierOrderSerializer
from apps.purchasing.services import SupplierStockService
```

Replace the `SupplierOrderViewSet` class body (currently lines 25-54):

```python
_SUPPLIER_ORDER_REFERENCE_PREFIX = "ACH"
_MAX_REFERENCE_ATTEMPTS = 5


class SupplierOrderViewSet(viewsets.ModelViewSet):
    queryset = SupplierOrder.objects.all()
    serializer_class = SupplierOrderSerializer
    filterset_fields = ["supplier", "product", "status"]
    permission_classes = [HasModulePermission]
    module = "purchasing"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        for _ in range(_MAX_REFERENCE_ATTEMPTS):
            reference = generate_monthly_reference(
                SupplierOrder, "reference", _SUPPLIER_ORDER_REFERENCE_PREFIX
            )
            try:
                with transaction.atomic():
                    serializer.save(reference=reference, created_by=self.request.user)
                return
            except IntegrityError:
                continue
        raise IntegrityError(
            "Impossible de generer une reference de commande fournisseur "
            f"unique apres {_MAX_REFERENCE_ATTEMPTS} tentatives."
        )

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)

    @action(detail=True, methods=["get"])
    def reliquat(self, request, pk=None):
        """Endpoint to get the remaining unallocated quantity for a supplier order.

        GET /api/supplier-orders/{id}/reliquat/
        """
        order = self.get_object()
        reliquat = SupplierStockService.get_purchase_reliquat(order)
        return Response(
            {
                "supplier_order_id": order.id,
                "reference": order.reference,
                "quantity_litres": str(order.quantity_litres),
                "reliquat": f"{reliquat:.2f}",
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="next-reference")
    def next_reference(self, request):
        """Non-reserving preview of the reference the next created
        SupplierOrder will receive - for form display only, not a
        reservation. GET /api/supplier-orders/next-reference/
        """
        reference = generate_monthly_reference(
            SupplierOrder, "reference", _SUPPLIER_ORDER_REFERENCE_PREFIX
        )
        return Response({"reference": reference})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest apps/purchasing/tests.py -v`
Expected: PASS (all tests, including the two new ones and every pre-existing test in the file)

- [ ] **Step 5: Commit**

```bash
git add backend/apps/purchasing/serializers.py backend/apps/purchasing/views.py backend/apps/purchasing/tests.py
git commit -m "feat(backend): generate SupplierOrder reference server-side (ACH-YYYYMM-NNNN)"
```

---

### Task 3: CessionLetter — server-generated `CES-YYYYMM-NNNN` reference

**Files:**
- Modify: `backend/apps/purchasing/serializers.py:18-36` (CessionLetterSerializer.Meta.read_only_fields)
- Modify: `backend/apps/purchasing/views.py:57-77` (CessionLetterViewSet, uses `_MAX_REFERENCE_ATTEMPTS` from Task 2)
- Test: `backend/apps/purchasing/tests.py` (append)

**Interfaces:**
- Consumes: `generate_monthly_reference` (Task 1), `_MAX_REFERENCE_ATTEMPTS` constant (Task 2, same file).
- Produces: `GET /api/cession-letters/next-reference/` → `{"reference": "CES-202608-0001"}`. `POST /api/cession-letters/` ignores any client-supplied `reference`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/purchasing/tests.py`:

```python
@pytest.mark.django_db
def test_cession_letter_reference_is_server_generated():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000042", pin="1234", role=admin_role
    )
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name="Total", country="Senegal")
    order = SupplierOrder.objects.create(
        reference="SO-CES-GEN-001",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("100000.00"),
        unit_price=Decimal("600.00"),
        created_by=admin_user,
    )

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.post(
        "/api/cession-letters/",
        {
            "reference": "CLIENT-SUPPLIED-IGNORED",
            "supplier_order": order.id,
            "authorized_quantity": "1000.00",
            "issue_date": "2026-08-18",
        },
    )
    assert response.status_code == 201
    assert response.data["reference"] != "CLIENT-SUPPLIED-IGNORED"
    assert response.data["reference"].startswith("CES-")


@pytest.mark.django_db
def test_cession_letter_next_reference_endpoint():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(
        phone="+2220000043", pin="1234", role=admin_role
    )
    client = APIClient()
    client.force_authenticate(admin_user)

    response = client.get("/api/cession-letters/next-reference/")
    assert response.status_code == 200
    assert response.data["reference"].startswith("CES-")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest apps/purchasing/tests.py -k "cession_letter_reference_is_server_generated or cession_letter_next_reference_endpoint" -v`
Expected: FAIL (same shape as Task 2 — client value not ignored, 404 on the new route)

- [ ] **Step 3: Write the implementation**

In `backend/apps/purchasing/serializers.py`, update `CessionLetterSerializer.Meta.read_only_fields` (currently line 36):

```python
        read_only_fields = ["id", "reference", "created_by", "created_at", "updated_at"]
```

In `backend/apps/purchasing/views.py`, replace the `CessionLetterViewSet` class body (currently lines 57-77):

```python
_CESSION_LETTER_REFERENCE_PREFIX = "CES"


class CessionLetterViewSet(viewsets.ModelViewSet):
    queryset = CessionLetter.objects.all()
    serializer_class = CessionLetterSerializer
    filterset_fields = ["supplier_order", "status"]
    permission_classes = [HasModulePermission]
    module = "purchasing"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        for _ in range(_MAX_REFERENCE_ATTEMPTS):
            reference = generate_monthly_reference(
                CessionLetter, "reference", _CESSION_LETTER_REFERENCE_PREFIX
            )
            try:
                with transaction.atomic():
                    serializer.save(reference=reference, created_by=self.request.user)
                return
            except IntegrityError:
                continue
        raise IntegrityError(
            "Impossible de generer une reference de lettre de cession "
            f"unique apres {_MAX_REFERENCE_ATTEMPTS} tentatives."
        )

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)

    @action(detail=False, methods=["get"], url_path="next-reference")
    def next_reference(self, request):
        """Non-reserving preview of the reference the next created
        CessionLetter will receive. GET /api/cession-letters/next-reference/
        """
        reference = generate_monthly_reference(
            CessionLetter, "reference", _CESSION_LETTER_REFERENCE_PREFIX
        )
        return Response({"reference": reference})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest apps/purchasing/tests.py -v`
Expected: PASS (all tests in the file, including `test_concurrency_select_for_update`, which posts a client-supplied `reference` that is now simply ignored — the 201/400 split it asserts is driven by the reliquat lock, not by the reference)

- [ ] **Step 5: Commit**

```bash
git add backend/apps/purchasing/serializers.py backend/apps/purchasing/views.py backend/apps/purchasing/tests.py
git commit -m "feat(backend): generate CessionLetter reference server-side (CES-YYYYMM-NNNN)"
```

---

### Task 4: Invoice — rename to server-generated `FAC-YYYYMM-NNNN`

**Files:**
- Modify: `backend/apps/trips/services.py:14` (import), `backend/apps/trips/services.py:292-305` (invoice creation in `DeliveryService.record_delivery`)
- Test: `backend/apps/sales/tests.py` (append)

**Interfaces:**
- Consumes: `generate_monthly_reference` (Task 1).
- Produces: every `Invoice` created by `DeliveryService.record_delivery()` now gets `invoice_number` in `FAC-YYYYMM-NNNN` format instead of `INV-{trip.reference}`.

- [ ] **Step 1: Write the failing test**

`backend/apps/trips/tests.py` already has everything needed: `_fixtures_with_customer(suffix)` (builds admin/product/supplier/transporter/supplier_order/customer), `_deliverable_trip(fx, reference, quantity=...)` (creates a truck + trip and advances it all the way to `QUANTITY_CONTROL` status via `_advance_to_quantity_control`, ready for `record_delivery`) — see the pattern used by `test_delivery_service_happy_path_creates_deduction_sale_and_invoice` at line 857. Append a new test right after that one (after line 906):

```python
@pytest.mark.django_db
def test_delivery_confirmation_generates_fac_invoice_number():
    fx = _fixtures_with_customer("FAC-FORMAT")
    trip = _deliverable_trip(fx, "TRIP-FAC-FORMAT-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("650.0000"), changed_by=fx["admin_user"],
    )

    DeliveryService.record_delivery(
        trip_id=trip.id,
        received_qty=Decimal("44850.00"),
        control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=fx["admin_user"],
    )

    invoice = trip.sale.invoice
    yyyymm = timezone.now().strftime("%Y%m")
    assert invoice.invoice_number.startswith(f"FAC-{yyyymm}-")
    assert not invoice.invoice_number.startswith("INV-")
```

This test file doesn't import `timezone` yet — add it to the existing `django.db` import line at the top of `backend/apps/trips/tests.py` (currently line 5, `from django.db import IntegrityError, transaction`) by adding a new line right after it:

```python
from django.utils import timezone
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest apps/trips/tests.py -k test_delivery_confirmation_generates_fac_invoice_number -v`
Expected: FAIL — `invoice.invoice_number` starts with `INV-`, not `FAC-`

- [ ] **Step 3: Write the implementation**

In `backend/apps/trips/services.py`, update the import block (currently lines 14-22):

```python
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import LossToleranceConfig
from apps.core.reference import generate_monthly_reference
from apps.finance.models import TransportDeduction
from apps.sales.models import Invoice, ProductSellingPriceHistory, Sale
from apps.sales.services import CustomerOrderService
from apps.transport.models import Truck
from apps.trips.models import DeliveryControl, Trip, TripStatusHistory
```

Add the prefix/attempts constants near the other module-level constants at the top of the class (right before `class DeliveryService:` or alongside its other `@staticmethod`s — place them as module-level constants right after the imports):

```python
_INVOICE_REFERENCE_PREFIX = "FAC"
_MAX_INVOICE_REFERENCE_ATTEMPTS = 5
```

Replace the invoice-creation block (currently lines 300-305):

```python
        invoice = None
        for _ in range(_MAX_INVOICE_REFERENCE_ATTEMPTS):
            invoice_number = generate_monthly_reference(
                Invoice, "invoice_number", _INVOICE_REFERENCE_PREFIX
            )
            try:
                with transaction.atomic():
                    invoice = Invoice.objects.create(
                        invoice_number=invoice_number,
                        sale=sale,
                        total_amount=sale.subtotal,
                        issued_date=control_date,
                    )
                break
            except IntegrityError:
                continue
        else:
            raise IntegrityError(
                "Impossible de generer un numero de facture unique apres "
                f"{_MAX_INVOICE_REFERENCE_ATTEMPTS} tentatives."
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest apps/trips/tests.py apps/sales/tests.py -v`
Expected: PASS (all tests — the pre-existing sales/tests.py invoice tests call `Invoice.objects.create()` directly and are unaffected; only DeliveryService-driven creation changes format)

- [ ] **Step 5: Commit**

```bash
git add backend/apps/trips/services.py backend/apps/trips/tests.py
git commit -m "feat(backend): generate Invoice number server-side (FAC-YYYYMM-NNNN)"
```

---

### Task 5: Frontend — shared `extractFieldErrors` helper

**Files:**
- Modify: `frontend/src/i18n/apiErrors.ts`
- Test: Create `frontend/src/i18n/__tests__/apiErrors.spec.ts`

**Interfaces:**
- Produces: `extractFieldErrors(data: Record<string, unknown> | undefined | null): Record<string, string>` — exported alongside the existing `translateApiError`. Drops `detail`/`non_field_errors` keys; for each remaining key, takes the first array element (or the raw string) if it's a string.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/i18n/__tests__/apiErrors.spec.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { extractFieldErrors } from '../apiErrors'

describe('extractFieldErrors', () => {
  it('returns an empty object for undefined input', () => {
    expect(extractFieldErrors(undefined)).toEqual({})
  })

  it('maps each field to its first error message', () => {
    const result = extractFieldErrors({
      reference: ['Cette référence existe déjà.'],
      quantity: ['Doit être positif.'],
    })
    expect(result).toEqual({
      reference: 'Cette référence existe déjà.',
      quantity: 'Doit être positif.',
    })
  })

  it('ignores detail and non_field_errors keys', () => {
    const result = extractFieldErrors({
      detail: 'Erreur générique',
      non_field_errors: ['Erreur globale'],
      status: ['Valeur invalide.'],
    })
    expect(result).toEqual({ status: 'Valeur invalide.' })
  })

  it('accepts a plain string value for a field', () => {
    const result = extractFieldErrors({ notes: 'Trop long.' })
    expect(result).toEqual({ notes: 'Trop long.' })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/i18n/__tests__/apiErrors.spec.ts`
Expected: FAIL — `extractFieldErrors` is not exported from `../apiErrors`

- [ ] **Step 3: Write the implementation**

Append to `frontend/src/i18n/apiErrors.ts`:

```typescript
export function extractFieldErrors(
  data: Record<string, unknown> | undefined | null,
): Record<string, string> {
  const fieldErrors: Record<string, string> = {}
  if (!data) return fieldErrors
  for (const [field, value] of Object.entries(data)) {
    if (field === 'detail' || field === 'non_field_errors') continue
    const message = Array.isArray(value) ? value[0] : value
    if (typeof message === 'string') fieldErrors[field] = message
  }
  return fieldErrors
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/i18n/__tests__/apiErrors.spec.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/apiErrors.ts frontend/src/i18n/__tests__/apiErrors.spec.ts
git commit -m "feat(frontend): add shared extractFieldErrors helper for 400 responses"
```

---

### Task 6: SupplierOrderForm.vue — read-only generated reference + shared error handling

**Files:**
- Modify: `frontend/src/modules/purchasing/api.ts`
- Modify: `frontend/src/modules/purchasing/SupplierOrderForm.vue`
- Modify: `frontend/src/locales/fr.json` (add `purchasing.orderForm.referenceGenerated`)
- Modify: `frontend/src/modules/purchasing/__tests__/SupplierOrderForm.spec.ts`

**Interfaces:**
- Consumes: `extractFieldErrors` (Task 5), `GET /api/supplier-orders/next-reference/` (Task 2).
- Produces: `fetchNextSupplierOrderReference(): Promise<string>` exported from `frontend/src/modules/purchasing/api.ts`, also consumed by Task 7's tests as a sibling pattern (not imported cross-file — CessionLetterForm gets its own `fetchNextCessionLetterReference`).

- [ ] **Step 1: Update the failing tests**

Replace the first test in `frontend/src/modules/purchasing/__tests__/SupplierOrderForm.spec.ts` (currently lines 49-58) and the `vi.mock('../api', ...)` block (currently lines 21-28):

```typescript
const create = vi.fn()
const fetchNextSupplierOrderReference = vi.fn(async () => 'ACH-202608-0007')
vi.mock('../api', () => ({
  supplierOrderResource: {
    get: vi.fn(),
    create: (payload: Record<string, unknown>) => create(payload),
    update: vi.fn(),
  },
  uploadDocument: vi.fn(),
  fetchNextSupplierOrderReference: () => fetchNextSupplierOrderReference(),
}))
```

```typescript
  it('pre-fills the reference as a read-only, server-generated value', async () => {
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(SupplierOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    const input = wrapper.find<HTMLInputElement>('#reference')
    expect(input.attributes('autocomplete')).toBe('off')
    expect(input.attributes('disabled')).toBeDefined()
    expect(input.element.value).toBe('ACH-202608-0007')
    expect(fetchNextSupplierOrderReference).toHaveBeenCalled()
  })
```

Leave the second test (`'surfaces a backend uniqueness error...'`, currently lines 60-78) as-is — it exercises the generic `fieldErrors` display mechanism, which is unaffected by the reference field becoming read-only.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/modules/purchasing/__tests__/SupplierOrderForm.spec.ts`
Expected: FAIL — `fetchNextSupplierOrderReference` doesn't exist in `../api`, `#reference` has no `disabled` attribute, value doesn't match `'ACH-202608-0007'`

- [ ] **Step 3: Write the implementation**

In `frontend/src/modules/purchasing/api.ts`, add:

```typescript
export function fetchNextSupplierOrderReference(): Promise<string> {
  return apiClient
    .get<{ reference: string }>('/supplier-orders/next-reference/')
    .then((r) => r.data.reference)
}
```

In `frontend/src/modules/purchasing/SupplierOrderForm.vue`:

Replace the import line (currently line 7):

```typescript
import { supplierOrderResource, uploadDocument, fetchNextSupplierOrderReference } from './api'
```

Delete the `generateReferenceSuggestion` function and its comment (currently lines 22-31), and change the `form` ref's `reference` default (currently line 34):

```typescript
const form = ref({
  reference: '',
  supplier: '',
```

In `onMounted` (currently lines 70-78), fetch the preview reference for new orders:

```typescript
onMounted(async () => {
  const [supplierData, productData] = await Promise.all([
    supplierResource.list(),
    productResource.list(),
  ])
  suppliers.value = supplierData.results
  products.value = productData.results
  if (isNew.value) {
    form.value.reference = await fetchNextSupplierOrderReference()
  }
  await loadOrder()
})
```

In `onSubmit`, remove `reference` from the payload (currently line 85):

```typescript
  const payload = {
    supplier: Number(form.value.supplier),
    product: Number(form.value.product),
```

In the template, replace the reference input block (currently lines 180-194):

```html
      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="reference">{{
          t('purchasing.orderForm.reference')
        }}</label>
        <input
          id="reference"
          v-model="form.reference"
          disabled
          autocomplete="off"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-sable px-3.5 text-texte-2"
        />
        <p class="text-texte-3 text-xs">{{ t('purchasing.orderForm.referenceGenerated') }}</p>
        <p v-if="fieldErrors.reference" class="text-critique text-xs">
          {{ fieldErrors.reference }}
        </p>
      </div>
```

In `frontend/src/locales/fr.json`, add `"referenceGenerated"` to the `orderForm` block (currently starting at line 518, right after `"reference": "Référence",` at line 521):

```json
      "reference": "Référence",
      "referenceGenerated": "Généré automatiquement",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/purchasing/__tests__/SupplierOrderForm.spec.ts`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/purchasing/api.ts frontend/src/modules/purchasing/SupplierOrderForm.vue frontend/src/locales/fr.json frontend/src/modules/purchasing/__tests__/SupplierOrderForm.spec.ts
git commit -m "feat(frontend): read-only server-generated reference in SupplierOrderForm"
```

---

### Task 7: CessionLetterForm.vue — read-only generated reference + fix narrow error handling

**Files:**
- Modify: `frontend/src/modules/purchasing/api.ts`
- Modify: `frontend/src/modules/purchasing/CessionLetterForm.vue`
- Modify: `frontend/src/locales/fr.json` (add `purchasing.cessionForm.referenceGenerated`)
- Create: `frontend/src/modules/purchasing/__tests__/CessionLetterForm.spec.ts`

**Interfaces:**
- Consumes: `extractFieldErrors` (Task 5), `GET /api/cession-letters/next-reference/` (Task 3).
- Produces: `fetchNextCessionLetterReference(): Promise<string>` exported from `frontend/src/modules/purchasing/api.ts`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/modules/purchasing/__tests__/CessionLetterForm.spec.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import CessionLetterForm from '../CessionLetterForm.vue'

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

const create = vi.fn()
const fetchNextCessionLetterReference = vi.fn(async () => 'CES-202608-0003')
vi.mock('../api', () => ({
  cessionLetterResource: {
    get: vi.fn(),
    create: (payload: Record<string, unknown>) => create(payload),
    update: vi.fn(),
  },
  supplierOrderResource: {
    get: vi.fn(async () => ({
      id: 1,
      reference: 'ACH-202608-0001',
      reliquat: '40000.00',
      quantity_litres: '100000.00',
      supplier_detail: { name: 'Total' },
    })),
    list: vi.fn(async () => paginated([])),
  },
  uploadDocument: vi.fn(),
  fetchNextCessionLetterReference: () => fetchNextCessionLetterReference(),
}))

function makeRouter(query: Record<string, string> = {}) {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/cession-letters/new', name: 'cession-letter-new', component: CessionLetterForm },
      { path: '/cession-letters/:id', name: 'cession-letter-detail', component: stub },
    ],
  })
  router.push({ name: 'cession-letter-new', query })
  return router
}

describe('CessionLetterForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('pre-fills the reference as a read-only, server-generated value', async () => {
    const router = makeRouter({ supplier_order: '1' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    const input = wrapper.find<HTMLInputElement>('#reference')
    expect(input.attributes('disabled')).toBeDefined()
    expect(input.element.value).toBe('CES-202608-0003')
    expect(fetchNextCessionLetterReference).toHaveBeenCalled()
  })

  it('surfaces any field error, not just authorized_quantity', async () => {
    create.mockRejectedValueOnce({
      response: { status: 400, data: { issue_date: ["Ce champ est requis."] } },
    })
    const router = makeRouter({ supplier_order: '1' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#authorized_quantity').setValue('1000')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Ce champ est requis.')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/modules/purchasing/__tests__/CessionLetterForm.spec.ts`
Expected: FAIL — `fetchNextCessionLetterReference` doesn't exist in `../api`; the second test fails because the current catch block only ever reads `authorized_quantity`

- [ ] **Step 3: Write the implementation**

In `frontend/src/modules/purchasing/api.ts`, add:

```typescript
export function fetchNextCessionLetterReference(): Promise<string> {
  return apiClient
    .get<{ reference: string }>('/cession-letters/next-reference/')
    .then((r) => r.data.reference)
}
```

In `frontend/src/modules/purchasing/CessionLetterForm.vue`:

Replace the imports (currently lines 1-7):

```typescript
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  cessionLetterResource,
  supplierOrderResource,
  uploadDocument,
  fetchNextCessionLetterReference,
} from './api'
import { translateApiError, extractFieldErrors } from '@/i18n/apiErrors'
import Button from '@/components/ui/Button.vue'
import type { CessionLetter, CessionLetterStatus, SupplierOrder } from './types'
```

Add a `fieldErrors` ref next to `error` (currently line 30):

```typescript
const saving = ref(false)
const error = ref('')
const fieldErrors = ref<Record<string, string>>({})
```

In `onMounted` (currently lines 36-61), fetch the preview reference for new cessions, right before the `preselected` branch:

```typescript
onMounted(async () => {
  if (!isNew.value) {
    cession.value = await cessionLetterResource.get!(cessionId.value!)
    form.value = {
      reference: cession.value.reference,
      supplier_order: String(cession.value.supplier_order),
      authorized_quantity: cession.value.authorized_quantity,
      issue_date: cession.value.issue_date,
      status: cession.value.status,
      notes: cession.value.notes,
    }
    await loadOrder(cession.value.supplier_order)
    return
  }

  form.value.reference = await fetchNextCessionLetterReference()

  const preselected = route.query.supplier_order ? Number(route.query.supplier_order) : null
  if (preselected) {
    form.value.supplier_order = String(preselected)
    await loadOrder(preselected)
  } else {
    // No order pre-selected (arrived from top-level nav rather than a
    // supplier order's page) — let the user pick one.
    const data = await supplierOrderResource.list({ status: 'CONFIRMED' })
    availableOrders.value = data.results
  }
})
```

Replace `onSubmit` (currently lines 93-121):

```typescript
async function onSubmit() {
  saving.value = true
  error.value = ''
  fieldErrors.value = {}
  const payload = {
    supplier_order: Number(form.value.supplier_order),
    authorized_quantity: form.value.authorized_quantity,
    issue_date: form.value.issue_date,
    status: form.value.status,
    notes: form.value.notes,
  }
  try {
    if (isNew.value) {
      const created = await cessionLetterResource.create(payload)
      router.replace({ name: 'cession-letter-detail', params: { id: created.id } })
    } else {
      cession.value = await cessionLetterResource.update(cessionId.value!, payload)
      await loadOrder(Number(form.value.supplier_order))
    }
  } catch (e) {
    // The server enforces the same limit under a row lock (concurrency-safe)
    // even though the bar above already warns the user client-side.
    const response = (e as { response?: { status?: number; data?: Record<string, unknown> } })
      ?.response
    const body = response?.status === 400 ? response.data : undefined
    fieldErrors.value = extractFieldErrors(body)
    const generic = body?.detail ?? body?.non_field_errors
    const genericMessage = Array.isArray(generic) ? generic[0] : generic
    error.value =
      translateApiError(typeof genericMessage === 'string' ? genericMessage : undefined) ??
      (Object.keys(fieldErrors.value).length ? '' : t('purchasing.cessionForm.saveError'))
  } finally {
    saving.value = false
  }
}
```

In the template, replace the reference input block (currently lines 167-177):

```html
      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="reference">{{
          t('purchasing.cessionForm.reference')
        }}</label>
        <input
          id="reference"
          v-model="form.reference"
          disabled
          autocomplete="off"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-sable px-3.5 text-texte-2"
        />
        <p class="text-texte-3 text-xs">{{ t('purchasing.cessionForm.referenceGenerated') }}</p>
        <p v-if="fieldErrors.reference" class="text-critique text-xs">
          {{ fieldErrors.reference }}
        </p>
      </div>
```

Add error slots for the remaining fields: after the `supplier_order` `<select>`'s closing `</select>` (currently line 204, just before the closing `</div>` at line 205):

```html
        </select>
        <p v-if="fieldErrors.supplier_order" class="text-critique text-xs">
          {{ fieldErrors.supplier_order }}
        </p>
      </div>
```

After the `authorized_quantity` input (currently lines 249-258, right before that field's closing `</div>`):

```html
          />
          <p v-if="fieldErrors.authorized_quantity" class="text-critique text-xs">
            {{ fieldErrors.authorized_quantity }}
          </p>
        </div>
```

After the `issue_date` input (currently lines 265-272, right before that field's closing `</div>`):

```html
          />
          <p v-if="fieldErrors.issue_date" class="text-critique text-xs">
            {{ fieldErrors.issue_date }}
          </p>
        </div>
```

After the `status` select (currently lines 278-286, right before that field's closing `</div>`):

```html
          </select>
          <p v-if="fieldErrors.status" class="text-critique text-xs">{{ fieldErrors.status }}</p>
        </div>
```

After the `notes` textarea (currently lines 294-299, right before that field's closing `</div>`):

```html
        />
        <p v-if="fieldErrors.notes" class="text-critique text-xs">{{ fieldErrors.notes }}</p>
      </div>
```

In `frontend/src/locales/fr.json`, add `"referenceGenerated"` to the `cessionForm` block (currently starting at line 477, right after `"reference": "Référence",` at line 480):

```json
      "reference": "Référence",
      "referenceGenerated": "Généré automatiquement",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/purchasing/__tests__/CessionLetterForm.spec.ts`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/purchasing/api.ts frontend/src/modules/purchasing/CessionLetterForm.vue frontend/src/locales/fr.json frontend/src/modules/purchasing/__tests__/CessionLetterForm.spec.ts
git commit -m "feat(frontend): read-only server-generated reference and fix field-error handling in CessionLetterForm"
```

---

### Task 8: TripForm.vue — adopt shared field-error handling

**Files:**
- Modify: `frontend/src/modules/trips/TripForm.vue`
- Create: `frontend/src/modules/trips/__tests__/TripForm.spec.ts`

**Interfaces:**
- Consumes: `extractFieldErrors` (Task 5).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/modules/trips/__tests__/TripForm.spec.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import TripForm from '../TripForm.vue'

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

vi.mock('@/api/resource', () => ({
  createResourceApi: vi.fn(() => ({
    list: vi.fn(async () => paginated([])),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  })),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { role_detail: { name: 'Admin' } } }),
}))

const create = vi.fn()
vi.mock('../api', () => ({
  tripResource: { create: (payload: Record<string, unknown>) => create(payload) },
}))

vi.mock('@/modules/purchasing/api', () => ({
  cessionLetterResource: { list: vi.fn(async () => paginated([])) },
  supplierOrderResource: { get: vi.fn() },
}))

vi.mock('@/modules/sales/api', () => ({
  customerOrderResource: { list: vi.fn(async () => paginated([])) },
  fetchCustomerOrderTrips: vi.fn(async () => []),
}))

function makeRouter() {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/trips/new', name: 'trip-new', component: TripForm },
      { path: '/trips/:id', name: 'trip-detail', component: stub },
    ],
  })
  router.push({ name: 'trip-new' })
  return router
}

describe('TripForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('surfaces a per-field 400 error under the matching field instead of a generic message', async () => {
    create.mockRejectedValueOnce({
      response: { status: 400, data: { bl_reference: ['Cette référence existe déjà.'] } },
    })
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(TripForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#bl_reference').setValue('BL-DUP')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Cette référence existe déjà.')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/modules/trips/__tests__/TripForm.spec.ts`
Expected: FAIL — current `onSubmit` catch reads `Object.values(data)[0]` regardless of field, but since `bl_reference` is the only 400 key here it may coincidentally show the right text without the per-field slot; the test additionally needs `#bl_reference`'s own error slot to exist. Confirm failure by checking `fieldErrors` isn't wired — if this specific scenario passes coincidentally, add a second 400 key (e.g. `truck: ['Autre erreur.']`) to `data` in the mock so the "first value found" logic picks the wrong one, proving the bug before the fix. Use:

```typescript
    create.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { truck: ['Autre erreur.'], bl_reference: ['Cette référence existe déjà.'] },
      },
    })
```

Re-run; expected FAIL: `wrapper.text()` contains `'Autre erreur.'` instead of `'Cette référence existe déjà.'` under `#bl_reference`, or the generic `error` paragraph shows the wrong message.

- [ ] **Step 3: Write the implementation**

In `frontend/src/modules/trips/TripForm.vue`, update the import (currently line 13):

```typescript
import { translateApiError, extractFieldErrors } from '@/i18n/apiErrors'
```

Add a `fieldErrors` ref next to `error` (currently line 66):

```typescript
const saving = ref(false)
const error = ref('')
const fieldErrors = ref<Record<string, string>>({})
```

Replace `onSubmit`'s error handling (currently lines 140-174):

```typescript
async function onSubmit() {
  if (!selectedCession.value || !selectedSupplierOrder.value) {
    error.value = t('trips.newForm.selectCessionFirst')
    return
  }
  saving.value = true
  error.value = ''
  fieldErrors.value = {}
  const payload: Partial<Trip> = {
    truck: Number(form.value.truck),
    transporter: Number(form.value.transporter),
    driver: form.value.driver ? Number(form.value.driver) : null,
    supplier: selectedSupplierOrder.value.supplier,
    supplier_order: selectedSupplierOrder.value.id,
    cession_letter: selectedCession.value.id,
    product: selectedSupplierOrder.value.product,
    quantity_loaded: form.value.quantity_loaded,
    client: form.value.client ? Number(form.value.client) : null,
    customer_order: form.value.customer_order ? Number(form.value.customer_order) : null,
    loading_date: form.value.loading_date,
    bl_reference: form.value.bl_reference,
    notes: form.value.notes,
    force: showBusyTrucks.value,
  }
  try {
    const created = await tripResource.create(payload)
    router.push({ name: 'trip-detail', params: { id: created.id } })
  } catch (e) {
    const response = (e as { response?: { status?: number; data?: Record<string, unknown> } })
      ?.response
    const body = response?.status === 400 ? response.data : undefined
    fieldErrors.value = extractFieldErrors(body)
    const generic = body?.detail ?? body?.non_field_errors
    const genericMessage = Array.isArray(generic) ? generic[0] : generic
    error.value =
      translateApiError(typeof genericMessage === 'string' ? genericMessage : undefined) ??
      (Object.keys(fieldErrors.value).length ? '' : t('trips.newForm.saveError'))
  } finally {
    saving.value = false
  }
}
```

In the template, add error slots after each relevant field's closing tag. After the `cession_letter` `<select>` (currently lines 193-205, before that field's closing `</div>`):

```html
        </select>
        <p v-if="fieldErrors.cession_letter" class="text-critique text-xs">
          {{ fieldErrors.cession_letter }}
        </p>
      </div>
```

After the `truck` `<select>` (currently lines 243-257, before that field's closing `</div>`):

```html
          </select>
          <p v-if="fieldErrors.truck" class="text-critique text-xs">{{ fieldErrors.truck }}</p>
        </div>
```

After the `transporter` `<select>` (currently lines 264-272, before that field's closing `</div>`):

```html
          </select>
          <p v-if="fieldErrors.transporter" class="text-critique text-xs">
            {{ fieldErrors.transporter }}
          </p>
        </div>
```

After the `driver` `<select>` (currently lines 279-286, before that field's closing `</div>`):

```html
          </select>
          <p v-if="fieldErrors.driver" class="text-critique text-xs">{{ fieldErrors.driver }}</p>
        </div>
```

After the `quantity_loaded` input (currently lines 293-302, before that field's closing `</div>`):

```html
          />
          <p v-if="fieldErrors.quantity_loaded" class="text-critique text-xs">
            {{ fieldErrors.quantity_loaded }}
          </p>
        </div>
```

After the `loading_date` input (currently lines 309-315, before that field's closing `</div>`):

```html
          />
          <p v-if="fieldErrors.loading_date" class="text-critique text-xs">
            {{ fieldErrors.loading_date }}
          </p>
        </div>
```

After the `bl_reference` input (currently lines 322-327, before that field's closing `</div>`):

```html
          />
          <p v-if="fieldErrors.bl_reference" class="text-critique text-xs">
            {{ fieldErrors.bl_reference }}
          </p>
        </div>
```

After the `customer_order` `<select>` (currently lines 339-351, before that field's closing `</div>`):

```html
        </select>
        <p v-if="fieldErrors.customer_order" class="text-critique text-xs">
          {{ fieldErrors.customer_order }}
        </p>
      </div>
```

After the `client` `<select>` (currently lines 358-365, before that field's closing `</div>`):

```html
        </select>
        <p v-if="fieldErrors.client" class="text-critique text-xs">{{ fieldErrors.client }}</p>
      </div>
```

After the `notes` textarea (currently lines 372-377, before that field's closing `</div>`):

```html
        />
        <p v-if="fieldErrors.notes" class="text-critique text-xs">{{ fieldErrors.notes }}</p>
      </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/modules/trips/__tests__/TripForm.spec.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/trips/TripForm.vue frontend/src/modules/trips/__tests__/TripForm.spec.ts
git commit -m "feat(frontend): per-field 400 error handling in TripForm"
```

---

### Task 9: CustomerOrderForm.vue — adopt shared field-error handling

**Files:**
- Modify: `frontend/src/modules/sales/CustomerOrderForm.vue`
- Create: `frontend/src/modules/sales/__tests__/CustomerOrderForm.spec.ts`

**Interfaces:**
- Consumes: `extractFieldErrors` (Task 5).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/modules/sales/__tests__/CustomerOrderForm.spec.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import CustomerOrderForm from '../CustomerOrderForm.vue'

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

vi.mock('@/api/resource', () => ({
  createResourceApi: vi.fn(() => ({
    list: vi.fn(async () => paginated([])),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  })),
}))

const create = vi.fn()
vi.mock('../api', () => ({
  customerOrderResource: {
    get: vi.fn(),
    create: (payload: Record<string, unknown>) => create(payload),
    update: vi.fn(),
  },
  fetchCustomerOrderTrips: vi.fn(async () => []),
}))

function makeRouter() {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/customer-orders/new', name: 'customer-order-new', component: CustomerOrderForm },
      { path: '/customer-orders/:id', name: 'customer-order-detail', component: stub },
      { path: '/customer-orders', name: 'customer-orders', component: stub },
    ],
  })
  router.push({ name: 'customer-order-new' })
  return router
}

describe('CustomerOrderForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('surfaces a per-field 400 error instead of swallowing the response body', async () => {
    create.mockRejectedValueOnce({
      response: { status: 400, data: { quantity_ordered: ['Doit être positif.'] } },
    })
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(CustomerOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#customer').setValue('')
    await wrapper.find('#product').setValue('')
    await wrapper.find('#quantity_ordered').setValue('-1')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Doit être positif.')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/modules/sales/__tests__/CustomerOrderForm.spec.ts`
Expected: FAIL — current `catch { error.value = t('sales.orderForm.saveError') }` never reads the response body, so `'Doit être positif.'` never appears and there's no `fieldErrors.quantity_ordered` slot in the template

- [ ] **Step 3: Write the implementation**

In `frontend/src/modules/sales/CustomerOrderForm.vue`, add the import (currently after line 4):

```typescript
import { translateApiError, extractFieldErrors } from '@/i18n/apiErrors'
```

Add a `fieldErrors` ref next to `error` (currently line 37):

```typescript
const saving = ref(false)
const error = ref('')
const fieldErrors = ref<Record<string, string>>({})
```

Replace `onSubmit`'s catch block (currently lines 73-98):

```typescript
async function onSubmit() {
  saving.value = true
  error.value = ''
  fieldErrors.value = {}
  const payload: Partial<CustomerOrder> = {
    customer: Number(form.value.customer),
    product: Number(form.value.product),
    quantity_ordered: form.value.quantity_ordered,
    expected_price: form.value.expected_price || null,
    notes: form.value.notes,
  }
  if (statusIsManuallyEditable.value) payload.status = form.value.status

  try {
    if (isNew.value) {
      const created = await customerOrderResource.create(payload)
      router.replace({ name: 'customer-order-detail', params: { id: created.id } })
    } else {
      order.value = await customerOrderResource.update(orderId.value!, payload)
      form.value.status = order.value.status
    }
  } catch (e) {
    const response = (e as { response?: { status?: number; data?: Record<string, unknown> } })
      ?.response
    const body = response?.status === 400 ? response.data : undefined
    fieldErrors.value = extractFieldErrors(body)
    const generic = body?.detail ?? body?.non_field_errors
    const genericMessage = Array.isArray(generic) ? generic[0] : generic
    error.value =
      translateApiError(typeof genericMessage === 'string' ? genericMessage : undefined) ??
      (Object.keys(fieldErrors.value).length ? '' : t('sales.orderForm.saveError'))
  } finally {
    saving.value = false
  }
}
```

In the template, add error slots. After the `customer` `<select>` (currently lines 182-190, before that field's closing `</div>`):

```html
        </select>
        <p v-if="fieldErrors.customer" class="text-critique text-xs">{{ fieldErrors.customer }}</p>
      </div>
```

After the `product` `<select>` (currently lines 197-205, before that field's closing `</div>`):

```html
        </select>
        <p v-if="fieldErrors.product" class="text-critique text-xs">{{ fieldErrors.product }}</p>
      </div>
```

After the `quantity_ordered` input (currently lines 212-220, before that field's closing `</div>`):

```html
        />
        <p v-if="fieldErrors.quantity_ordered" class="text-critique text-xs">
          {{ fieldErrors.quantity_ordered }}
        </p>
      </div>
```

After the `expected_price` input (currently lines 227-234, before that field's closing `</div>`):

```html
        />
        <p v-if="fieldErrors.expected_price" class="text-critique text-xs">
          {{ fieldErrors.expected_price }}
        </p>
      </div>
```

After the `notes` textarea (currently lines 261-266, before that field's closing `</div>`):

```html
        />
        <p v-if="fieldErrors.notes" class="text-critique text-xs">{{ fieldErrors.notes }}</p>
      </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/modules/sales/__tests__/CustomerOrderForm.spec.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/sales/CustomerOrderForm.vue frontend/src/modules/sales/__tests__/CustomerOrderForm.spec.ts
git commit -m "feat(frontend): per-field 400 error handling in CustomerOrderForm"
```

---

### Task 10: Full-suite verification + end-to-end validation

**Files:** None modified — verification only.

**Interfaces:** None — this task consumes everything built in Tasks 1-9 as a black box, through the running app and full test suites.

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && pytest -v`
Expected: PASS, zero failures — every test added in Tasks 1-4 plus every pre-existing test in `apps/core`, `apps/purchasing`, `apps/trips`, `apps/sales`.

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd frontend && npm run test:unit -- --run` (or `npx vitest run` if `test:unit` isn't watch-friendly in CI mode — check `frontend/package.json` `scripts` for the exact non-watch invocation before running)
Expected: PASS, zero failures — every test added in Tasks 5-9 plus every pre-existing spec (including `MasterDataView.spec.ts` and the other already-modified specs from git status).

- [ ] **Step 3: Run the frontend build**

Run: `cd frontend && npm run build`
Expected: PASS — no TypeScript errors (particularly: no leftover references to the removed `generateReferenceSuggestion`, no unused-import errors from the `apiErrors.ts` changes).

- [ ] **Step 4: Manual end-to-end pass via browser automation**

Start the dev servers per `LANCER_LOCALEMENT.md` (backend `python manage.py runserver`, frontend `npm run dev`, served at `http://localhost:5173`). Using Claude in Chrome (load `mcp__claude-in-chrome__tabs_context_mcp`, `navigate`, `computer`, `read_page`, `tabs_create_mcp`, `form_input` first via ToolSearch), log in and walk the full chain:

1. Open "Nouvelle commande fournisseur" — confirm the Référence field shows a non-empty `ACH-YYYYMM-0001`-shaped value, disabled, before you touch anything else. Fill the rest, save. Confirm the detail page's reference matches what was previewed (or is at least a valid `ACH-` value if a race shifted it).
2. From that order's detail page, click "Nouvelle cession" — confirm the Référence field shows a non-empty `CES-YYYYMM-0001`-shaped value, disabled, and that the "Commande fournisseur" text still shows the linked order's own `ACH-...` reference unchanged. Fill authorized quantity/date, save.
3. Create a new Trip against that cession letter — confirm it saves without any reference-related error (Trip's own reference is untouched/hidden, as decided).
4. Confirm delivery on that trip (delivery-control flow) — open the resulting Invoice (via Sale/Invoice list) and confirm `invoice_number` is `FAC-YYYYMM-NNNN`, not `INV-...`.
5. Trigger at least one deliberate 400 on `CessionLetterForm` (e.g. exceed the reliquat) and on `TripForm` (e.g. exceed cession remaining) and confirm the error renders under the correct field, not just as a generic banner.

Record the outcome in your final report to the user — if any step fails, treat it as a real bug (per project history, browser QA has caught real defects unit tests missed) and fix it before declaring the task done, re-running the affected backend/frontend test suite afterward.

- [ ] **Step 5: Final commit (only if Step 4 required fixes)**

If step 4 required no code changes, there is nothing to commit for this task. If it did, commit those fixes with a message describing the specific bug found, e.g.:

```bash
git add <fixed files>
git commit -m "fix: <specific bug found during end-to-end reference validation>"
```

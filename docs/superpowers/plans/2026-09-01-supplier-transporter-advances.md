# Avances fournisseur / transporteur — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add prudent advance-payment management for suppliers and transporters — advances hit treasury immediately, become an open credit, and are consumed FIFO by future confirmed debt — without breaking `Nouveau paiement`, double-counting anything, or touching the profit formula.

**Architecture:** Two mirrored models (`SupplierAdvance`, new; `TransporterAdvance`, extended) plus one shared junction model (`AdvanceConsumption`) recording FIFO allocations against real debts (`SupplierOrder`/`TransportPayment`). A new `AdvanceConsumptionService` performs the FIFO matching automatically via model `save()` hooks. `ControlledDebtPaymentService` gains `describe_supplier_balance`/`describe_transporter_balance` as the single source of truth for net balance, reused by a new `party-balances` endpoint, the Dashboard, and two new `*LedgerService` classes that back the Grand livre pages. Frontend gets a new `AdvanceForm.vue` mirroring `DebtPaymentForm.vue`'s lock/prefill pattern.

**Tech Stack:** Django 5 / DRF (backend, pytest), Vue 3 `<script setup>` + TypeScript (frontend, Vitest).

**Spec:** `docs/superpowers/specs/2026-08-31-supplier-transporter-advances-design.md`

## Global Constraints

- Never create a `TreasuryTransaction` when an advance is *consumed* — only when it is *created*.
- Never let `SupplierAdvance`/`TransporterAdvance`/`AdvanceConsumption` be referenced by `TripProfitService`/`MarginReportQuery`.
- Never count a `DRAFT`/`CANCELLED` `SupplierOrder` as debt or as something an advance can consume.
- Never delete an `AdvanceConsumption` row — reverse via `reversed_at`, never a hard delete.
- Every new avance-related money movement requires exactly one of `bank_account`/`cash_account`, and (for new rows) a required image-only (`JPG`/`JPEG`/`PNG`/`WEBP`) justificatif.
- `ControlledDebtPaymentService.describe_supplier_balance`/`describe_transporter_balance` is the *only* place `net_balance` is computed — Dashboard, `party-balances`, and both Grand livre pages all call it, never recompute it locally.
- Keep `SupplierViewSet.ledger`/`TransporterViewSet.ledger`'s existing response keys unchanged (only add `summary`/`entries`).

---

## Task 1: Models — `SupplierAdvance`, `AdvanceConsumption`, extend `TransporterAdvance`

**Files:**
- Modify: `backend/apps/finance/models.py`
- Modify: `backend/apps/finance/views.py:129` (drop `"settled"` from `filterset_fields`)
- Modify: `backend/apps/finance/tests.py` (one assertion removed, new tests added)
- Create: a new migration (via `makemigrations`)

**Interfaces:**
- Produces: `SupplierAdvance` (fields: `supplier`, `bank_account`, `cash_account`, `amount`, `date`, `reference`, `notes`, `document`, `recorded_by`, property `remaining_amount`), `AdvanceConsumption` (fields: `supplier_advance`, `transporter_advance`, `debt_content_type`, `debt_object_id`, `amount`, `reversed_at`), `TransporterAdvance` extended with `bank_account`, `cash_account`, `document`, `recorded_by` (all nullable), `settled` removed as a stored field and replaced by a derived property, new property `remaining_amount`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/tests.py`, in a new section after the existing `TransporterAdvance`/`TransportPayment` section (after line ~929, before the "Client modification Task 2" section):

```python
# ---------------------------------------------------------------------------
# Advance management (docs/superpowers/specs/2026-08-31-supplier-
# transporter-advances-design.md): SupplierAdvance, AdvanceConsumption,
# TransporterAdvance extended with treasury accounts + document.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_supplier_advance_requires_positive_amount():
    admin_user, supplier, _order = _make_supplier_order("SADV-NEG")
    cash_account = CashAccount.objects.create(name="Main Cash")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SupplierAdvance.objects.create(
                supplier=supplier, amount=Decimal("0.00"), date="2026-08-18",
                cash_account=cash_account, recorded_by=admin_user,
            )


@pytest.mark.django_db
def test_supplier_advance_requires_exactly_one_account():
    admin_user, supplier, _order = _make_supplier_order("SADV-ACC")
    bank_account = BankAccount.objects.create(name="Main BOA Account")
    cash_account = CashAccount.objects.create(name="Main Cash")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SupplierAdvance.objects.create(
                supplier=supplier, amount=Decimal("1000000.00"), date="2026-08-18",
                bank_account=bank_account, cash_account=cash_account, recorded_by=admin_user,
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SupplierAdvance.objects.create(
                supplier=supplier, amount=Decimal("1000000.00"), date="2026-08-18",
                recorded_by=admin_user,
            )


@pytest.mark.django_db
def test_supplier_advance_remaining_amount_defaults_to_full_amount():
    admin_user, supplier, _order = _make_supplier_order("SADV-REM")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("2000000.00"), date="2026-08-18",
        cash_account=cash_account, recorded_by=admin_user,
    )
    assert advance.remaining_amount == Decimal("2000000.00")


@pytest.mark.django_db
def test_advance_consumption_reduces_remaining_amount_but_reversed_rows_do_not():
    admin_user, supplier, order = _make_supplier_order("SADV-CONS")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("2000000.00"), date="2026-08-18",
        cash_account=cash_account, recorded_by=admin_user,
    )
    order_ct = ContentType.objects.get_for_model(SupplierOrder)
    AdvanceConsumption.objects.create(
        supplier_advance=advance, debt_content_type=order_ct, debt_object_id=order.id,
        amount=Decimal("500000.00"),
    )
    assert advance.remaining_amount == Decimal("1500000.00")

    reversed_consumption = AdvanceConsumption.objects.create(
        supplier_advance=advance, debt_content_type=order_ct, debt_object_id=order.id,
        amount=Decimal("300000.00"), reversed_at=timezone.now(),
    )
    assert advance.remaining_amount == Decimal("1500000.00")
    assert reversed_consumption.reversed_at is not None


@pytest.mark.django_db
def test_advance_consumption_requires_exactly_one_advance_type():
    admin_user, supplier, order = _make_supplier_order("CONS-BOTH")
    cash_account = CashAccount.objects.create(name="Main Cash")
    supplier_advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-18",
        cash_account=cash_account, recorded_by=admin_user,
    )
    trip, transporter = _make_trip_for_deduction("CONS-BOTH2")
    transporter_advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-18",
        cash_account=cash_account,
    )
    order_ct = ContentType.objects.get_for_model(SupplierOrder)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AdvanceConsumption.objects.create(
                supplier_advance=supplier_advance, transporter_advance=transporter_advance,
                debt_content_type=order_ct, debt_object_id=order.id, amount=Decimal("100.00"),
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AdvanceConsumption.objects.create(
                debt_content_type=order_ct, debt_object_id=order.id, amount=Decimal("100.00"),
            )


@pytest.mark.django_db
def test_transporter_advance_now_supports_treasury_account_and_document():
    trip, transporter = _make_trip_for_deduction("TADV-ACC")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-18",
        cash_account=cash_account,
    )
    assert advance.remaining_amount == Decimal("100000.00")
    assert advance.settled is False
    assert advance.document_id is None


@pytest.mark.django_db
def test_transporter_advance_settled_property_reflects_consumption():
    trip, transporter = _make_trip_for_deduction("TADV-SETTLE")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-18",
        cash_account=cash_account,
    )
    payment_ct = ContentType.objects.get_for_model(TransportPayment)
    dummy_payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    AdvanceConsumption.objects.create(
        transporter_advance=advance, debt_content_type=payment_ct,
        debt_object_id=dummy_payment.id, amount=Decimal("100000.00"),
    )
    assert advance.settled is True
```

Add these imports at the top of `backend/apps/finance/tests.py` (extend the existing `from apps.finance.models import (...)` block and add a `django.utils` import):

```python
from django.utils import timezone
```

and extend the existing model import block to include `AdvanceConsumption`, `SupplierAdvance`.

Also **remove** this one assertion from the existing `test_acceptance_transporter_net_settlement_via_api` test (it currently sits right after `assert response.data["net_amount"] == "557500.00"`):

```python
    advance.refresh_from_db()
    assert advance.settled is True
```

Replace with a comment explaining why, so Task 4 knows to restore it:

```python
    # `settled` becomes a property derived from AdvanceConsumption once
    # automatic FIFO consumption lands (Task 4 of the advances plan) - no
    # assertion here yet since nothing consumes this advance until then.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/tests.py -k "supplier_advance or advance_consumption or transporter_advance_now or transporter_advance_settled" -v`
Expected: FAIL with `ImportError`/`AttributeError` (`SupplierAdvance`/`AdvanceConsumption` don't exist yet).

- [ ] **Step 3: Add the models**

In `backend/apps/finance/models.py`, insert immediately after the `SupplierPayment` class (after line 300, before `class TransporterAdvance`):

```python
class SupplierAdvance(AuditableModel, TimeStampedModel):
    """A cash advance handed to a supplier ahead of any confirmed debt
    (docs/superpowers/specs/2026-08-31-supplier-transporter-advances-design.md).

    Becomes a credit consumed later, oldest-first, by AdvanceConsumption
    rows created automatically when a SupplierOrder is confirmed.
    `remaining_amount` is always derived from those rows, never stored, so
    it can never drift (same "computed, never stored" convention as
    BankAccount.current_balance).
    """

    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.PROTECT, related_name="advances"
    )
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="supplier_advances",
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="supplier_advances",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="supplier_advances",
    )
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="supplier_advances_recorded"
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_supplieradvance_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=True) | models.Q(cash_account__isnull=True),
                name="finance_supplieradvance_single_account",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=False) | models.Q(cash_account__isnull=False),
                name="finance_supplieradvance_requires_account",
            ),
        ]

    def __str__(self) -> str:
        return f"Advance to {self.supplier}: {self.amount} ({self.date})"

    @property
    def remaining_amount(self) -> Decimal:
        consumed = (
            self.consumptions.filter(reversed_at__isnull=True).aggregate(
                total=models.Sum("amount")
            )["total"]
            or Decimal("0.00")
        )
        return self.amount - consumed
```

Replace the existing `TransporterAdvance` class (lines 303-330) with:

```python
class TransporterAdvance(AuditableModel, TimeStampedModel):
    """A road-expense advance handed to a transporter ahead of settlement
    (docs/PHASE_5_PLAN.md Etape 3; guide Section 8.6), now a real treasury
    outflow like SupplierAdvance (docs/superpowers/specs/
    2026-08-31-supplier-transporter-advances-design.md) - it previously had
    no bank_account/cash_account and never posted a TreasuryTransaction.

    `settled` is a derived property (remaining_amount <= 0), never a stored
    field - AdvanceConsumptionService is the only writer of the
    AdvanceConsumption rows it's computed from. bank_account/cash_account/
    document/recorded_by are nullable at the DB level only to keep rows
    created before this change valid; every new advance requires them.
    """

    transporter = models.ForeignKey(
        "transport.Transporter", on_delete=models.PROTECT, related_name="advances"
    )
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="transporter_advances",
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="transporter_advances",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transporter_advances",
    )
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True,
        related_name="transporter_advances_recorded",
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_transporteradvance_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Advance to {self.transporter}: {self.amount} ({self.date})"

    @property
    def remaining_amount(self) -> Decimal:
        consumed = (
            self.consumptions.filter(reversed_at__isnull=True).aggregate(
                total=models.Sum("amount")
            )["total"]
            or Decimal("0.00")
        )
        return self.amount - consumed

    @property
    def settled(self) -> bool:
        return self.remaining_amount <= Decimal("0.00")


class AdvanceConsumption(TimeStampedModel):
    """One FIFO allocation of an open SupplierAdvance/TransporterAdvance
    against a real debt (a confirmed SupplierOrder or a TransportPayment) -
    never a mutation of either row, so the ledger stays auditable
    (docs/superpowers/specs/2026-08-31-supplier-transporter-advances-design.md).

    reversed_at marks a consumption undone because the underlying
    SupplierOrder was cancelled after consuming an advance - the row is
    kept (never deleted) so the ledger shows both the consumption and its
    reversal; remaining_amount on the advance always excludes rows with
    reversed_at set.
    """

    supplier_advance = models.ForeignKey(
        SupplierAdvance, on_delete=models.PROTECT, null=True, blank=True,
        related_name="consumptions",
    )
    transporter_advance = models.ForeignKey(
        TransporterAdvance, on_delete=models.PROTECT, null=True, blank=True,
        related_name="consumptions",
    )
    debt_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    debt_object_id = models.PositiveIntegerField()
    debt_object = GenericForeignKey("debt_content_type", "debt_object_id")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_advanceconsumption_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(supplier_advance__isnull=True, transporter_advance__isnull=False)
                    | models.Q(supplier_advance__isnull=False, transporter_advance__isnull=True)
                ),
                name="finance_advanceconsumption_single_advance",
            ),
        ]

    def __str__(self) -> str:
        advance = self.supplier_advance or self.transporter_advance
        return f"{advance}: {self.amount} -> {self.debt_object}"
```

In the (unchanged-until-now) `TransportPayment.save()` method (originally lines 396-403), remove the trailing block that writes the now-retired stored field:

```python
    def save(self, *args, **kwargs):
        advance_amount = self.advance_applied.amount if self.advance_applied_id else Decimal("0.00")
        self.net_amount = (
            self.base_amount - self.deduction_amount - advance_amount
        ).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
```

(i.e. delete the two lines `if self.advance_applied_id and not self.advance_applied.settled:` / `TransporterAdvance.objects.filter(pk=self.advance_applied_id).update(settled=True)` — `settled` is no longer a column, so writing to it would raise `FieldError`. The net_amount formula itself is untouched until Task 4.)

In `backend/apps/finance/views.py:129`, change:

```python
    filterset_fields = ["transporter", "settled"]
```

to:

```python
    filterset_fields = ["transporter"]
```

(`settled` is now a Python property, not a filterable model field.)

- [ ] **Step 4: Generate and apply the migration**

Run: `cd backend && python manage.py makemigrations finance`
Run: `cd backend && python manage.py migrate`

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/tests.py -v`
Expected: PASS (full file, to confirm the `settled`-removal didn't break anything beyond the one assertion already handled).

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/models.py backend/apps/finance/views.py backend/apps/finance/tests.py backend/apps/finance/migrations/
git commit -m "feat(finance): add SupplierAdvance/AdvanceConsumption models, extend TransporterAdvance with treasury accounts"
```

---

## Task 2: `AdvanceConsumptionService` — pure FIFO engine

**Files:**
- Modify: `backend/apps/finance/services.py`
- Modify: `backend/apps/finance/tests.py`

**Interfaces:**
- Consumes: `SupplierAdvance`, `TransporterAdvance`, `AdvanceConsumption` (Task 1).
- Produces: `AdvanceConsumptionService` with public methods `consume_for_supplier_order(order)`, `reverse_for_supplier_order(order)`, `consume_for_transport_payment(payment) -> Decimal`, `get_consumed_amount(debt) -> Decimal`, `open_supplier_advances(supplier, for_update=False) -> list[SupplierAdvance]`, `open_transporter_advances(transporter, for_update=False) -> list[TransporterAdvance]`. Task 3/4 call these from model `save()` hooks; Task 5 calls `open_*_advances`/`get_consumed_amount` from `describe_*_balance`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/tests.py`, right after Task 1's new tests:

```python
@pytest.mark.django_db
def test_consume_for_supplier_order_is_fifo_across_two_advances():
    admin_user, supplier, order = _make_supplier_order("FIFO-TWO")
    # _make_supplier_order's order is already CONFIRMED with total 300000000
    # (500000 L x 600) - too large for this scenario; build a smaller order
    # by hand instead.
    order.delete()
    product = Product.objects.get(code="gasoil")
    order = SupplierOrder.objects.create(
        reference="SO-FIFO-TWO", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.DRAFT,
        created_by=admin_user,
    )  # total 600000, still DRAFT - not yet a debt
    cash_account = CashAccount.objects.create(name="Main Cash")
    older_advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("200000.00"), date="2026-08-10",
        cash_account=cash_account, recorded_by=admin_user,
    )
    newer_advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-15",
        cash_account=cash_account, recorded_by=admin_user,
    )

    AdvanceConsumptionService.consume_for_supplier_order(order)  # DRAFT: no-op
    older_advance.refresh_from_db()
    newer_advance.refresh_from_db()
    assert older_advance.remaining_amount == Decimal("200000.00")
    assert newer_advance.remaining_amount == Decimal("500000.00")

    order.status = SupplierOrder.Status.CONFIRMED
    order.save()
    AdvanceConsumptionService.consume_for_supplier_order(order)

    older_advance.refresh_from_db()
    newer_advance.refresh_from_db()
    assert older_advance.remaining_amount == Decimal("0.00")  # oldest consumed first, in full
    assert newer_advance.remaining_amount == Decimal("400000.00")  # remaining 400000 covers the rest


@pytest.mark.django_db
def test_consume_for_supplier_order_is_idempotent_when_called_twice():
    admin_user, supplier, order = _make_supplier_order("FIFO-IDEMPOTENT")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("50000000.00"), date="2026-08-10",
        cash_account=cash_account, recorded_by=admin_user,
    )

    AdvanceConsumptionService.consume_for_supplier_order(order)
    AdvanceConsumptionService.consume_for_supplier_order(order)

    assert AdvanceConsumption.objects.filter(supplier_advance=advance).count() == 1


@pytest.mark.django_db
def test_consume_for_supplier_order_only_matches_advances_of_the_same_supplier():
    admin_user, supplier, order = _make_supplier_order("FIFO-SAMETENANT")
    other_supplier = Supplier.objects.create(name="Other Supplier FIFO", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash")
    SupplierAdvance.objects.create(
        supplier=other_supplier, amount=Decimal("50000000.00"), date="2026-08-10",
        cash_account=cash_account, recorded_by=admin_user,
    )

    AdvanceConsumptionService.consume_for_supplier_order(order)

    assert AdvanceConsumption.objects.count() == 0


@pytest.mark.django_db
def test_reverse_for_supplier_order_restores_the_advance():
    admin_user, supplier, order = _make_supplier_order("FIFO-REVERSE")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("50000000.00"), date="2026-08-10",
        cash_account=cash_account, recorded_by=admin_user,
    )
    AdvanceConsumptionService.consume_for_supplier_order(order)
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("0.00")

    AdvanceConsumptionService.reverse_for_supplier_order(order)
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("50000000.00")
    consumption = AdvanceConsumption.objects.get(supplier_advance=advance)
    assert consumption.reversed_at is not None


@pytest.mark.django_db
def test_consume_for_transport_payment_caps_at_the_payment_amount():
    trip, transporter = _make_trip_for_deduction("FIFO-TRANS-CAP")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("900000.00"), date="2026-08-10",
        cash_account=cash_account,
    )
    payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    payment.advance_applied = None  # this task's service isn't wired to save() yet

    consumed = AdvanceConsumptionService.consume_for_transport_payment(payment)

    assert consumed == Decimal("700000.00")
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("200000.00")
```

Add `AdvanceConsumptionService` to the `from apps.finance.services import (...)` block in `tests.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/tests.py -k "consume_for or reverse_for" -v`
Expected: FAIL with `ImportError` (`AdvanceConsumptionService` doesn't exist).

- [ ] **Step 3: Implement the service**

In `backend/apps/finance/services.py`, extend the model import block (around line 19-33) to add `AdvanceConsumption`, `SupplierAdvance`, `TransporterAdvance`, and add `from django.utils import timezone` is already imported (line 16) — reuse it. Insert the new class right before `class ControlledDebtPaymentError(ValueError):` (before line 412):

```python
class AdvanceConsumptionService:
    """Consumes open SupplierAdvance/TransporterAdvance rows, oldest-first,
    against a real debt (a confirmed SupplierOrder or a TransportPayment) -
    the automatic counterpart to ControlledDebtPaymentService's FIFO payment
    allocation, but for advances instead of bank payments (docs/superpowers/
    specs/2026-08-31-supplier-transporter-advances-design.md).

    Never creates a TreasuryTransaction: consuming an advance is a pure
    accounting compensation, the cash already left the company when the
    advance itself was created.
    """

    @classmethod
    def open_supplier_advances(cls, supplier, *, for_update=False) -> list:
        queryset = SupplierAdvance.objects.filter(supplier=supplier).order_by("date", "id")
        if for_update:
            queryset = queryset.select_for_update()
        return [advance for advance in queryset if advance.remaining_amount > ZERO]

    @classmethod
    def open_transporter_advances(cls, transporter, *, for_update=False) -> list:
        queryset = TransporterAdvance.objects.filter(transporter=transporter).order_by("date", "id")
        if for_update:
            queryset = queryset.select_for_update()
        return [advance for advance in queryset if advance.remaining_amount > ZERO]

    @staticmethod
    def get_consumed_amount(debt) -> Decimal:
        content_type = ContentType.objects.get_for_model(debt.__class__)
        return (
            AdvanceConsumption.objects.filter(
                debt_content_type=content_type, debt_object_id=debt.id, reversed_at__isnull=True
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )

    @classmethod
    @transaction.atomic
    def consume_for_supplier_order(cls, order) -> None:
        """Idempotent: safe to call more than once for the same order - it
        always recomputes what's still uncovered before consuming further,
        so a redundant call (or a resave of an already-CONFIRMED order)
        never double-consumes an advance."""
        if order.status != order.Status.CONFIRMED:
            return
        content_type = ContentType.objects.get_for_model(order.__class__)
        remaining_to_cover = order.total_amount - cls.get_consumed_amount(order)
        if remaining_to_cover <= ZERO:
            return
        for advance in cls.open_supplier_advances(order.supplier, for_update=True):
            if remaining_to_cover <= ZERO:
                break
            amount = min(advance.remaining_amount, remaining_to_cover)
            if amount <= ZERO:
                continue
            AdvanceConsumption.objects.create(
                supplier_advance=advance,
                debt_content_type=content_type,
                debt_object_id=order.id,
                amount=amount,
            )
            remaining_to_cover -= amount

    @classmethod
    @transaction.atomic
    def reverse_for_supplier_order(cls, order) -> None:
        """Undo every non-reversed consumption this order made, restoring
        the advance(s) it used to open (design doc: reversed_at rather than
        a deletion, for a full audit trail)."""
        content_type = ContentType.objects.get_for_model(order.__class__)
        AdvanceConsumption.objects.filter(
            debt_content_type=content_type, debt_object_id=order.id, reversed_at__isnull=True
        ).update(reversed_at=timezone.now())

    @classmethod
    @transaction.atomic
    def consume_for_transport_payment(cls, payment) -> Decimal:
        """Returns the total now consumed (non-reversed) for this payment,
        for TransportPayment.save() to fold into net_amount directly."""
        content_type = ContentType.objects.get_for_model(payment.__class__)
        target = payment.base_amount - payment.deduction_amount
        remaining_to_cover = target - cls.get_consumed_amount(payment)
        if remaining_to_cover > ZERO:
            for advance in cls.open_transporter_advances(payment.transporter, for_update=True):
                if remaining_to_cover <= ZERO:
                    break
                amount = min(advance.remaining_amount, remaining_to_cover)
                if amount <= ZERO:
                    continue
                AdvanceConsumption.objects.create(
                    transporter_advance=advance,
                    debt_content_type=content_type,
                    debt_object_id=payment.id,
                    amount=amount,
                )
                remaining_to_cover -= amount
        return cls.get_consumed_amount(payment)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/tests.py -k "consume_for or reverse_for" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/finance/tests.py
git commit -m "feat(finance): add AdvanceConsumptionService FIFO engine"
```

---

## Task 3: Wire `SupplierOrder` confirmation/cancellation to `AdvanceConsumptionService`

**Files:**
- Modify: `backend/apps/purchasing/models.py`
- Modify: `backend/apps/finance/services.py` (`_supplier_order_paid`)
- Create: `backend/apps/finance/test_advances.py`

**Interfaces:**
- Consumes: `AdvanceConsumptionService.consume_for_supplier_order`/`reverse_for_supplier_order` (Task 2).
- Produces: `SupplierOrder.save()` now triggers consumption/reversal automatically on status transitions; `ControlledDebtPaymentService._supplier_order_paid` now also subtracts non-reversed `AdvanceConsumption` amounts, so `describe_supplier_order`/`describe_supplier`/`get_payable_debts("supplier")` become advance-aware.

- [ ] **Step 1: Write the failing tests**

Create `backend/apps/finance/test_advances.py` (new file — kept separate from the already-2700-line `tests.py`, following this app's `test_*.py` split convention, discovered automatically by `python_files = tests.py test_*.py *_tests.py` in `pytest.ini`):

```python
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.finance.models import (
    AdvanceConsumption,
    BankAccount,
    CashAccount,
    SupplierAdvance,
    SupplierPayment,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import ControlledDebtPaymentService
from apps.purchasing.models import SupplierOrder
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip


def _proof_file(name="proof.jpg"):
    return SimpleUploadedFile(name, b"fake-proof-bytes", content_type="image/jpeg")


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(phone=(f"+222{suffix}")[:20], pin="1234", role=admin_role)


def _make_supplier_order_with_status(suffix, status, *, quantity=Decimal("1000.00"), unit_price=Decimal("600.0000")):
    admin_user = _make_admin(suffix)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    order = SupplierOrder.objects.create(
        reference=f"SO-ADV-{suffix}", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=quantity, unit_price=unit_price,
        status=status, created_by=admin_user,
    )
    return admin_user, supplier, order


def _make_trip_for_deduction(suffix):
    admin_user = _make_admin(suffix)
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Trans Supplier {suffix}", country="Senegal")
    transporter = Transporter.objects.create(name=f"Trans {suffix}")
    from apps.purchasing.models import CessionLetter

    supplier_order = SupplierOrder.objects.create(
        reference=f"SO-ADVTRIP-{suffix}", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )
    cession = CessionLetter.objects.create(
        reference=f"CL-ADVTRIP-{suffix}", supplier_order=supplier_order,
        authorized_quantity=Decimal("500000.00"), issue_date="2026-08-18", created_by=admin_user,
    )
    truck = Truck.objects.create(
        internal_id=f"TRK-ADVTRIP-{suffix}", tractor_registration=f"{suffix}-TRACTOR",
        tanker_registration=f"{suffix}-TANKER", capacity_litres=Decimal("45000.00"),
    )
    trip = Trip.objects.create(
        reference=f"TRIP-ADVTRIP-{suffix}", truck=truck, transporter=transporter, supplier=supplier,
        supplier_order=supplier_order, cession_letter=cession, product=product,
        quantity_loaded=Decimal("45000.00"), loading_date="2026-08-18",
        bl_reference=f"BL-ADVTRIP-{suffix}", created_by=admin_user,
    )
    return trip, transporter


# ---------------------------------------------------------------------------
# Task 3: SupplierOrder confirmation/cancellation wiring
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_confirming_supplier_order_directly_consumes_open_advance_fifo():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "CONFIRM-DIRECT", SupplierOrder.Status.CONFIRMED,
    )  # total_amount = 600000.00
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("400000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )

    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("0.00")
    remaining_debt = ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"]
    assert remaining_debt == Decimal("200000.00")


@pytest.mark.django_db
def test_draft_to_confirmed_transition_consumes_advance_but_draft_creation_does_not():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "DRAFT-THEN-CONFIRM", SupplierOrder.Status.DRAFT,
    )
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("600000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    assert advance.remaining_amount == Decimal("600000.00")

    order.status = SupplierOrder.Status.CONFIRMED
    order.save()
    advance.refresh_from_db()

    assert advance.remaining_amount == Decimal("0.00")
    assert ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"] == Decimal("0.00")


@pytest.mark.django_db
def test_supplier_advance_partially_covers_larger_order_leaves_remaining_payable():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "PARTIAL", SupplierOrder.Status.CONFIRMED,
    )  # total 600000
    cash_account = CashAccount.objects.create(name="Main Cash")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("250000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )

    remaining = ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"]
    assert remaining == Decimal("350000.00")


@pytest.mark.django_db
def test_advance_exceeding_order_leaves_surplus_open_for_next_order():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "SURPLUS", SupplierOrder.Status.CONFIRMED, quantity=Decimal("500.00"),
    )  # total 300000
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )

    assert ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"] == Decimal("0.00")
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("200000.00")


@pytest.mark.django_db
def test_resaving_already_confirmed_order_does_not_double_consume():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "IDEMPOTENT", SupplierOrder.Status.CONFIRMED, quantity=Decimal("500.00"),
    )
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("200000.00")

    order.notes = "unrelated edit"
    order.save()
    advance.refresh_from_db()

    assert advance.remaining_amount == Decimal("200000.00")


@pytest.mark.django_db
def test_cancelling_confirmed_order_reverses_its_advance_consumption():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "CANCEL-REVERSE", SupplierOrder.Status.CONFIRMED, quantity=Decimal("500.00"),
    )  # total 300000
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("300000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("0.00")

    order.status = SupplierOrder.Status.CANCELLED
    order.save()
    advance.refresh_from_db()

    assert advance.remaining_amount == Decimal("300000.00")
    consumption = AdvanceConsumption.objects.get(supplier_advance=advance)
    assert consumption.reversed_at is not None


@pytest.mark.django_db
def test_supplier_advance_alone_without_debt_does_not_create_payable_debt():
    admin_user = _make_admin("NO-DEBT")
    supplier = Supplier.objects.create(name="No Order Supplier", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("1000000.00"), date="2026-08-18",
        cash_account=cash_account, recorded_by=admin_user,
    )
    payable = [
        row for row in ControlledDebtPaymentService.get_payable_debts("supplier")
        if row["id"] == supplier.id
    ]
    assert payable == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -v`
Expected: FAIL — orders confirm but advances stay untouched (hook not wired yet).

- [ ] **Step 3: Wire the hook and update `_supplier_order_paid`**

In `backend/apps/purchasing/models.py`, replace `SupplierOrder.save()` (lines 66-71):

```python
    def save(self, *args, **kwargs):
        total = (self.quantity_litres * self.unit_price) + (
            self.optional_costs or Decimal("0.00")
        )
        self.total_amount = total.quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
```

with:

```python
    def save(self, *args, **kwargs):
        total = (self.quantity_litres * self.unit_price) + (
            self.optional_costs or Decimal("0.00")
        )
        self.total_amount = total.quantize(Decimal("0.01"))

        previous_status = None
        if self.pk:
            previous_status = (
                SupplierOrder.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )

        super().save(*args, **kwargs)

        # Imported lazily: apps.purchasing sits below apps.finance in the
        # app dependency graph (apps.finance.services imports
        # apps.purchasing.models.SupplierOrder at module level already), so
        # a module-level import here would run the dependency backwards.
        from apps.finance.services import AdvanceConsumptionService

        if previous_status != self.Status.CONFIRMED and self.status == self.Status.CONFIRMED:
            AdvanceConsumptionService.consume_for_supplier_order(self)
        elif previous_status == self.Status.CONFIRMED and self.status == self.Status.CANCELLED:
            AdvanceConsumptionService.reverse_for_supplier_order(self)
```

In `backend/apps/finance/services.py`, update `_supplier_order_paid` (lines 735-745) to also subtract non-reversed `AdvanceConsumption`:

```python
    @staticmethod
    def _supplier_order_paid(order, *, override=None) -> Decimal:
        if override is not None:
            return override
        payments = (
            SupplierPayment.objects.filter(
                supplier_order=order,
                is_advance=False,
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )
        consumed = AdvanceConsumptionService.get_consumed_amount(order)
        return payments + consumed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/test_advances.py apps/purchasing/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/purchasing/models.py backend/apps/finance/services.py backend/apps/finance/test_advances.py
git commit -m "feat(purchasing): auto-consume open supplier advances on order confirmation"
```

---

## Task 4: Wire `TransportPayment` to `AdvanceConsumptionService`, retire manual `advance_applied` selection

**Files:**
- Modify: `backend/apps/finance/models.py` (`TransportPayment.save()`)
- Modify: `backend/apps/finance/serializers.py` (`TransportPaymentSerializer`)
- Modify: `backend/apps/finance/tests.py` (restore one assertion)
- Modify: `backend/apps/finance/test_advances.py`

**Interfaces:**
- Consumes: `AdvanceConsumptionService.consume_for_transport_payment`/`get_consumed_amount` (Task 2).
- Produces: `TransportPayment.net_amount` now always reflects automatic FIFO advance consumption; `advance_applied` becomes read-only/legacy on the serializer (still present on the model for historical rows, never written by new code).

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/test_advances.py`:

```python
# ---------------------------------------------------------------------------
# Task 4: TransportPayment automatic consumption
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_transport_payment_consumes_advance_automatically_without_manual_selection():
    trip, transporter = _make_trip_for_deduction("AUTO-CONSUME")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-17",
        cash_account=cash_account,
    )

    payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"), deduction_amount=Decimal("42500.00"),
    )

    assert payment.net_amount == Decimal("557500.00")
    assert payment.advance_applied_id is None


@pytest.mark.django_db
def test_transport_payment_partial_advance_leaves_remaining_payable():
    trip, transporter = _make_trip_for_deduction("PARTIAL-TRANS")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("200000.00"), date="2026-08-17",
        cash_account=cash_account,
    )

    payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )

    assert payment.net_amount == Decimal("500000.00")
    remaining = ControlledDebtPaymentService.describe_transport_payment(payment)["remaining_amount"]
    assert remaining == Decimal("500000.00")


@pytest.mark.django_db
def test_transport_payment_advance_surplus_stays_open_for_next_trip():
    trip, transporter = _make_trip_for_deduction("SURPLUS-TRANS")
    cash_account = CashAccount.objects.create(name="Main Cash")
    advance = TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("900000.00"), date="2026-08-17",
        cash_account=cash_account,
    )

    payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )

    assert payment.net_amount == Decimal("0.00")
    advance.refresh_from_db()
    assert advance.remaining_amount == Decimal("200000.00")


@pytest.mark.django_db
def test_transporter_advance_alone_without_trip_does_not_create_payable_debt():
    trip, transporter = _make_trip_for_deduction("NO-DEBT-TRANS")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("500000.00"), date="2026-08-18",
        cash_account=cash_account,
    )
    payable = [
        row for row in ControlledDebtPaymentService.get_payable_debts("transporter")
        if row["id"] == transporter.id
    ]
    assert payable == []
```

In `backend/apps/finance/tests.py`, restore the assertion removed in Task 1 — `test_acceptance_transporter_net_settlement_via_api` should end with:

```python
    assert response.status_code == 201
    assert response.data["net_amount"] == "557500.00"

    advance.refresh_from_db()
    assert advance.settled is True
```

(replacing the placeholder comment Task 1 left in its place).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -k transport_payment -v && python -m pytest apps/finance/tests.py -k test_acceptance_transporter_net_settlement_via_api -v`
Expected: FAIL — `net_amount` still computed from `advance_applied` (which stays `None` since nothing sets it), so it equals `base_amount - deduction_amount` with no advance subtracted.

- [ ] **Step 3: Implement**

In `backend/apps/finance/models.py`, replace `TransportPayment.save()` with:

```python
    def save(self, *args, **kwargs):
        # Imported lazily to avoid a circular import at module load time:
        # apps.finance.services imports apps.finance.models at module level.
        from apps.finance.services import AdvanceConsumptionService

        is_new = self._state.adding
        if is_new:
            self.net_amount = (self.base_amount - self.deduction_amount).quantize(Decimal("0.01"))
            super().save(*args, **kwargs)
            consumed = AdvanceConsumptionService.consume_for_transport_payment(self)
            if consumed > Decimal("0.00"):
                self.net_amount = (
                    self.base_amount - self.deduction_amount - consumed
                ).quantize(Decimal("0.01"))
                super().save(update_fields=["net_amount", "updated_at"])
        else:
            consumed = AdvanceConsumptionService.get_consumed_amount(self)
            self.net_amount = (
                self.base_amount - self.deduction_amount - consumed
            ).quantize(Decimal("0.01"))
            super().save(*args, **kwargs)
```

In `backend/apps/finance/serializers.py`, in `TransportPaymentSerializer`:
- Change `read_only_fields` (line 370) to: `["id", "net_amount", "advance_applied", "created_at", "updated_at"]`
- Remove the now-dead cross-validation block at the top of `validate()`:

```python
        advance = data.get("advance_applied", getattr(self.instance, "advance_applied", None))
```
and
```python
        if advance and transporter and advance.transporter_id != transporter.id:
            raise serializers.ValidationError(
                "L'avance selectionnee n'appartient pas a ce transporteur."
            )
```

(both deleted — `advance_applied` is now read-only, so `data` never carries a client-supplied value for it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/ -v`
Expected: PASS (full finance app, including the restored assertion and the three pre-existing `advance_applied=`-passing tests, which still pass because a single open `TransporterAdvance` gets consumed automatically to the same effect).

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/models.py backend/apps/finance/serializers.py backend/apps/finance/tests.py backend/apps/finance/test_advances.py
git commit -m "feat(finance): auto-consume open transporter advances on settlement creation"
```

---

## Task 5: `describe_supplier_balance` / `describe_transporter_balance`

**Files:**
- Modify: `backend/apps/finance/services.py` (`ControlledDebtPaymentService`)
- Modify: `backend/apps/finance/test_advances.py`

**Interfaces:**
- Consumes: `describe_supplier`/`describe_transporter` (existing), `AdvanceConsumptionService.open_supplier_advances`/`open_transporter_advances` (Task 2), `SupplierAdvance`/`TransporterAdvance` (Task 1).
- Produces: `ControlledDebtPaymentService.describe_supplier_balance(supplier) -> dict` and `describe_transporter_balance(transporter) -> dict`, each `{id, label, total_due, open_advances, net_balance, last_advance, last_payment}` — the single source of truth Task 6 (creation guard), Task 8 (`party-balances`), Task 9 (report alignment already uses `describe_supplier`), Task 10 (ledger services), and Task 11 (dashboard) all consume.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/test_advances.py`:

```python
# ---------------------------------------------------------------------------
# Task 5: describe_supplier_balance / describe_transporter_balance
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_describe_supplier_balance_debt_only():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "BAL-DEBT", SupplierOrder.Status.CONFIRMED,
    )
    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["total_due"] == Decimal("600000.00")
    assert balance["open_advances"] == Decimal("0.00")
    assert balance["net_balance"] == Decimal("-600000.00")


@pytest.mark.django_db
def test_describe_supplier_balance_advance_only():
    admin_user = _make_admin("BAL-ADV-ONLY")
    cash_account = CashAccount.objects.create(name="Main Cash")
    supplier = Supplier.objects.create(name="No Debt Supplier", country="Senegal")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("300000.00"), date="2026-08-18",
        cash_account=cash_account, recorded_by=admin_user,
    )
    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["total_due"] == Decimal("0.00")
    assert balance["open_advances"] == Decimal("300000.00")
    assert balance["net_balance"] == Decimal("300000.00")


@pytest.mark.django_db
def test_describe_supplier_balance_partial_consumption():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "BAL-PARTIAL", SupplierOrder.Status.CONFIRMED,
    )  # total 600000
    cash_account = CashAccount.objects.create(name="Main Cash")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("250000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["total_due"] == Decimal("350000.00")
    assert balance["open_advances"] == Decimal("0.00")
    assert balance["net_balance"] == Decimal("-350000.00")


@pytest.mark.django_db
def test_describe_supplier_balance_full_consumption_with_surplus():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "BAL-FULL", SupplierOrder.Status.CONFIRMED, quantity=Decimal("500.00"),
    )  # total 300000
    cash_account = CashAccount.objects.create(name="Main Cash")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("500000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["total_due"] == Decimal("0.00")
    assert balance["open_advances"] == Decimal("200000.00")
    assert balance["net_balance"] == Decimal("200000.00")


@pytest.mark.django_db
def test_describe_transporter_balance_debt_only():
    trip, transporter = _make_trip_for_deduction("TBAL-DEBT")
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    balance = ControlledDebtPaymentService.describe_transporter_balance(transporter)
    assert balance["total_due"] == Decimal("700000.00")
    assert balance["net_balance"] == Decimal("-700000.00")


@pytest.mark.django_db
def test_describe_transporter_balance_advance_only():
    trip, transporter = _make_trip_for_deduction("TBAL-ADV")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("150000.00"), date="2026-08-18",
        cash_account=cash_account,
    )
    balance = ControlledDebtPaymentService.describe_transporter_balance(transporter)
    assert balance["total_due"] == Decimal("0.00")
    assert balance["open_advances"] == Decimal("150000.00")
    assert balance["net_balance"] == Decimal("150000.00")


@pytest.mark.django_db
def test_describe_transporter_balance_partial_consumption():
    trip, transporter = _make_trip_for_deduction("TBAL-PARTIAL")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("200000.00"), date="2026-08-17",
        cash_account=cash_account,
    )
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    balance = ControlledDebtPaymentService.describe_transporter_balance(transporter)
    assert balance["total_due"] == Decimal("500000.00")
    assert balance["open_advances"] == Decimal("0.00")
    assert balance["net_balance"] == Decimal("-500000.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -k describe_supplier_balance or describe_transporter_balance -v`
Expected: FAIL with `AttributeError` (methods don't exist yet).

- [ ] **Step 3: Implement**

In `backend/apps/finance/services.py`, add to `ControlledDebtPaymentService` (e.g. right after `describe_supplier`/before `describe_supplier_order`, or at the end of the class — placement inside the class doesn't matter for correctness):

```python
    @classmethod
    def describe_supplier_balance(cls, supplier) -> dict:
        total_due = cls.describe_supplier(supplier)["remaining_amount"]
        open_advances = sum(
            (advance.remaining_amount for advance in AdvanceConsumptionService.open_supplier_advances(supplier)),
            ZERO,
        )
        last_advance = (
            SupplierAdvance.objects.filter(supplier=supplier)
            .order_by("-date", "-id").values("date", "amount").first()
        )
        last_payment = (
            SupplierPayment.objects.filter(supplier=supplier, is_advance=False)
            .order_by("-payment_date", "-id").values("payment_date", "amount").first()
        )
        return {
            "id": supplier.id,
            "label": supplier.name,
            "total_due": total_due,
            "open_advances": open_advances,
            "net_balance": open_advances - total_due,
            "last_advance": (
                {"date": last_advance["date"], "amount": last_advance["amount"]}
                if last_advance else None
            ),
            "last_payment": (
                {"date": last_payment["payment_date"], "amount": last_payment["amount"]}
                if last_payment else None
            ),
        }

    @classmethod
    def describe_transporter_balance(cls, transporter) -> dict:
        total_due = cls.describe_transporter(transporter)["remaining_amount"]
        open_advances = sum(
            (
                advance.remaining_amount
                for advance in AdvanceConsumptionService.open_transporter_advances(transporter)
            ),
            ZERO,
        )
        last_advance = (
            TransporterAdvance.objects.filter(transporter=transporter)
            .order_by("-date", "-id").values("date", "amount").first()
        )
        last_payment_txn = (
            TreasuryTransaction.objects.filter(
                source_content_type=ContentType.objects.get_for_model(TransportPayment),
                source_object_id__in=TransportPayment.objects.filter(
                    transporter=transporter
                ).values_list("id", flat=True),
                type=TreasuryTransaction.Type.MONEY_OUT,
            ).order_by("-date", "-id").values("date", "amount").first()
        )
        return {
            "id": transporter.id,
            "label": transporter.name,
            "total_due": total_due,
            "open_advances": open_advances,
            "net_balance": open_advances - total_due,
            "last_advance": (
                {"date": last_advance["date"], "amount": last_advance["amount"]}
                if last_advance else None
            ),
            "last_payment": (
                {"date": last_payment_txn["date"], "amount": last_payment_txn["amount"]}
                if last_payment_txn else None
            ),
        }
```

Add `TransporterAdvance` to the existing model import block in `services.py` (it's already imported for other uses per Task 1/2, but double check it's present alongside `SupplierAdvance`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/finance/test_advances.py
git commit -m "feat(finance): add describe_supplier_balance/describe_transporter_balance"
```

---

## Task 6: `AdvanceService` — creation with treasury posting and the open-debt guard

**Files:**
- Modify: `backend/apps/finance/services.py`
- Modify: `backend/apps/finance/test_advances.py`

**Interfaces:**
- Consumes: `describe_supplier_balance`/`describe_transporter_balance` (Task 5).
- Produces: `AdvanceError(ValueError)`, `AdvanceService.create_supplier_advance(*, supplier_id, bank_account_id, cash_account_id, amount, date, reference, notes, attachment, actor) -> SupplierAdvance` and `create_transporter_advance(...) -> TransporterAdvance` — Task 7's serializers call these from `create()`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/test_advances.py`:

```python
# ---------------------------------------------------------------------------
# Task 6: AdvanceService (creation, treasury posting, open-debt guard)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_supplier_advance_posts_one_treasury_transaction_and_document():
    admin_user = _make_admin("CREATE-SADV")
    supplier = Supplier.objects.create(name="Create Advance Supplier", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    advance = AdvanceService.create_supplier_advance(
        supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
        amount=Decimal("1000000.00"), date="2026-08-18", reference="SADV-1", notes="",
        attachment=_proof_file(), actor=admin_user,
    )

    assert advance.remaining_amount == Decimal("1000000.00")
    assert advance.document_id is not None
    cash_account.refresh_from_db()
    assert cash_account.current_balance == Decimal("4000000.00")
    txn = TreasuryTransaction.objects.get(
        source_content_type=ContentType.objects.get_for_model(SupplierAdvance), source_object_id=advance.id,
    )
    assert txn.type == TreasuryTransaction.Type.MONEY_OUT
    assert txn.amount == Decimal("1000000.00")
    assert txn.document_id == advance.document_id


@pytest.mark.django_db
def test_create_supplier_advance_rejected_when_open_debt_exists():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "REJECT-SADV", SupplierOrder.Status.CONFIRMED,
    )  # total 600000, no advance yet -> net_balance = -600000
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    with pytest.raises(AdvanceError):
        AdvanceService.create_supplier_advance(
            supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
            amount=Decimal("100000.00"), date="2026-08-18", reference="", notes="",
            attachment=_proof_file(), actor=admin_user,
        )
    assert SupplierAdvance.objects.filter(supplier=supplier).count() == 0


@pytest.mark.django_db
def test_create_supplier_advance_allowed_when_net_balance_is_already_positive():
    admin_user = _make_admin("STACK-SADV")
    supplier = Supplier.objects.create(name="Stack Advance Supplier", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))
    AdvanceService.create_supplier_advance(
        supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
        amount=Decimal("300000.00"), date="2026-08-17", reference="SADV-A", notes="",
        attachment=_proof_file(), actor=admin_user,
    )

    second = AdvanceService.create_supplier_advance(
        supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
        amount=Decimal("200000.00"), date="2026-08-18", reference="SADV-B", notes="",
        attachment=_proof_file(), actor=admin_user,
    )

    assert second.remaining_amount == Decimal("200000.00")
    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["open_advances"] == Decimal("500000.00")


@pytest.mark.django_db
def test_create_transporter_advance_posts_treasury_transaction():
    trip, transporter = _make_trip_for_deduction("CREATE-TADV")
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance=Decimal("2000000.00"))

    advance = AdvanceService.create_transporter_advance(
        transporter_id=transporter.id, bank_account_id=bank_account.id, cash_account_id=None,
        amount=Decimal("500000.00"), date="2026-08-18", reference="TADV-1", notes="",
        attachment=_proof_file(), actor=_make_admin("CREATE-TADV-ACTOR"),
    )

    assert advance.remaining_amount == Decimal("500000.00")
    bank_account.refresh_from_db()
    assert bank_account.current_balance == Decimal("1500000.00")
    assert TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(TransporterAdvance),
        source_object_id=advance.id,
    ).exists()


@pytest.mark.django_db
def test_create_transporter_advance_rejected_when_open_debt_exists():
    trip, transporter = _make_trip_for_deduction("REJECT-TADV")
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance=Decimal("2000000.00"))

    with pytest.raises(AdvanceError):
        AdvanceService.create_transporter_advance(
            transporter_id=transporter.id, bank_account_id=bank_account.id, cash_account_id=None,
            amount=Decimal("100000.00"), date="2026-08-18", reference="", notes="",
            attachment=_proof_file(), actor=_make_admin("REJECT-TADV-ACTOR"),
        )


@pytest.mark.django_db
def test_create_supplier_advance_rejects_amount_exceeding_account_balance():
    admin_user = _make_admin("INSUF-SADV")
    supplier = Supplier.objects.create(name="Insufficient Balance Supplier", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("100000.00"))

    with pytest.raises(AdvanceError):
        AdvanceService.create_supplier_advance(
            supplier_id=supplier.id, bank_account_id=None, cash_account_id=cash_account.id,
            amount=Decimal("1000000.00"), date="2026-08-18", reference="", notes="",
            attachment=_proof_file(), actor=admin_user,
        )
```

Add `AdvanceError`, `AdvanceService` to the `from apps.finance.services import (...)` block in `test_advances.py`; add `Document`, `ContentType` imports (`from django.contrib.contenttypes.models import ContentType`, `from apps.documents.models import Document` — only needed if referenced directly; the tests above reference `ContentType` already).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -k "create_supplier_advance or create_transporter_advance" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

In `backend/apps/finance/services.py`, add near the top (after `ControlledDebtPaymentError`/before `ControlledDebtPaymentService`, or anywhere after `AdvanceConsumptionService` is defined since it's only referenced inside method bodies):

```python
class AdvanceError(ValueError):
    """Raised when an advance request breaks a financial rule (open debt
    already exists, insufficient treasury balance, invalid amount)."""


class AdvanceService:
    """Creates a SupplierAdvance/TransporterAdvance and posts its immediate
    treasury outflow, atomically (docs/superpowers/specs/2026-08-31-
    supplier-transporter-advances-design.md). Consuming an advance never
    goes through here - only AdvanceConsumptionService does that, and it
    never touches treasury."""

    @staticmethod
    def _lock_account(*, bank_account_id, cash_account_id):
        if bank_account_id:
            return BankAccount.objects.select_for_update().get(pk=bank_account_id), None
        return None, CashAccount.objects.select_for_update().get(pk=cash_account_id)

    @staticmethod
    def _check_balance(bank_account, cash_account, amount):
        account = bank_account or cash_account
        if amount > account.current_balance:
            raise AdvanceError("Solde insuffisant pour verser cette avance.")

    @classmethod
    @transaction.atomic
    def create_supplier_advance(
        cls, *, supplier_id, bank_account_id, cash_account_id, amount, date,
        reference, notes, attachment, actor,
    ) -> SupplierAdvance:
        supplier = Supplier.objects.select_for_update().get(pk=supplier_id)
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= ZERO:
            raise AdvanceError("Le montant de l'avance doit etre superieur a zero.")

        net_balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)["net_balance"]
        if net_balance < ZERO:
            raise AdvanceError(
                "Impossible de creer une avance : ce fournisseur a une dette ouverte reelle."
            )

        bank_account, cash_account = cls._lock_account(
            bank_account_id=bank_account_id, cash_account_id=cash_account_id
        )
        cls._check_balance(bank_account, cash_account, amount)

        advance = SupplierAdvance.objects.create(
            supplier=supplier, bank_account=bank_account, cash_account=cash_account,
            amount=amount, date=date, reference=reference, notes=notes, recorded_by=actor,
        )
        document = Document.objects.create(
            file=attachment, document_type="supplier_advance_proof", reference=reference,
            uploaded_by=actor, content_type=ContentType.objects.get_for_model(SupplierAdvance),
            object_id=advance.id,
        )
        advance.document = document
        advance.save(update_fields=["document", "updated_at"])
        TreasuryTransaction.objects.create(
            bank_account=bank_account, cash_account=cash_account,
            type=TreasuryTransaction.Type.MONEY_OUT, amount=amount, date=date,
            reference=reference, note=notes,
            source_content_type=ContentType.objects.get_for_model(SupplierAdvance),
            source_object_id=advance.id, document=document, recorded_by=actor,
        )
        return advance

    @classmethod
    @transaction.atomic
    def create_transporter_advance(
        cls, *, transporter_id, bank_account_id, cash_account_id, amount, date,
        reference, notes, attachment, actor,
    ) -> TransporterAdvance:
        transporter = Transporter.objects.select_for_update().get(pk=transporter_id)
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= ZERO:
            raise AdvanceError("Le montant de l'avance doit etre superieur a zero.")

        net_balance = ControlledDebtPaymentService.describe_transporter_balance(transporter)["net_balance"]
        if net_balance < ZERO:
            raise AdvanceError(
                "Impossible de creer une avance : ce transporteur a une dette ouverte reelle."
            )

        bank_account, cash_account = cls._lock_account(
            bank_account_id=bank_account_id, cash_account_id=cash_account_id
        )
        cls._check_balance(bank_account, cash_account, amount)

        advance = TransporterAdvance.objects.create(
            transporter=transporter, bank_account=bank_account, cash_account=cash_account,
            amount=amount, date=date, reference=reference, notes=notes, recorded_by=actor,
        )
        document = Document.objects.create(
            file=attachment, document_type="transporter_advance_proof", reference=reference,
            uploaded_by=actor, content_type=ContentType.objects.get_for_model(TransporterAdvance),
            object_id=advance.id,
        )
        advance.document = document
        advance.save(update_fields=["document", "updated_at"])
        TreasuryTransaction.objects.create(
            bank_account=bank_account, cash_account=cash_account,
            type=TreasuryTransaction.Type.MONEY_OUT, amount=amount, date=date,
            reference=reference, note=notes,
            source_content_type=ContentType.objects.get_for_model(TransporterAdvance),
            source_object_id=advance.id, document=document, recorded_by=actor,
        )
        return advance
```

`Document` is already imported at the top of `services.py` (line 18: `from apps.documents.models import Document`) — no new import needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/finance/test_advances.py
git commit -m "feat(finance): add AdvanceService with treasury posting and open-debt guard"
```

---

## Task 7: `SupplierAdvanceSerializer`/`ViewSet` (new), extend `TransporterAdvanceSerializer`/`ViewSet`

**Files:**
- Modify: `backend/apps/finance/serializers.py`
- Modify: `backend/apps/finance/views.py`
- Modify: `backend/apps/finance/urls.py`
- Modify: `backend/apps/finance/test_advances.py`

**Interfaces:**
- Consumes: `AdvanceService.create_supplier_advance`/`create_transporter_advance` (Task 6), `validate_image_upload` (existing, `apps/documents/validators.py`).
- Produces: `POST /api/supplier-advances/` (new), `POST /api/transporter-advances/` (now requires account + attachment).

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/test_advances.py`:

```python
# ---------------------------------------------------------------------------
# Task 7: API endpoints
# ---------------------------------------------------------------------------

import pytest as _pytest  # noqa: E402 - keep fixture below near its usage


@pytest.fixture
def advances_finance_client():
    from apps.accounts.models import Role, User
    from rest_framework.test import APIClient

    role = Role.objects.get(name=Role.NAME_FINANCE)
    user = User.objects.create_user(phone="+2220000077", pin="1234", role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_supplier_advance_endpoint_requires_image_attachment(advances_finance_client):
    supplier = Supplier.objects.create(name="API Advance Supplier", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    response = advances_finance_client.post(
        "/api/supplier-advances/",
        {
            "supplier": supplier.id, "cash_account": cash_account.id,
            "amount": "500000.00", "date": "2026-08-18", "reference": "SADV-API",
        },
    )
    assert response.status_code == 400
    assert "attachment" in response.data


@pytest.mark.django_db
def test_supplier_advance_endpoint_rejects_non_image_attachment(advances_finance_client):
    supplier = Supplier.objects.create(name="API Advance Supplier PDF", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))
    pdf_file = SimpleUploadedFile("proof.pdf", b"%PDF-1.4 fake", content_type="application/pdf")

    response = advances_finance_client.post(
        "/api/supplier-advances/",
        {
            "supplier": supplier.id, "cash_account": cash_account.id,
            "amount": "500000.00", "date": "2026-08-18", "attachment": pdf_file,
        },
        format="multipart",
    )
    assert response.status_code == 400
    assert "attachment" in response.data


@pytest.mark.django_db
def test_supplier_advance_endpoint_creates_advance_with_valid_image(advances_finance_client):
    supplier = Supplier.objects.create(name="API Advance Supplier OK", country="Senegal")
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    response = advances_finance_client.post(
        "/api/supplier-advances/",
        {
            "supplier": supplier.id, "cash_account": cash_account.id,
            "amount": "500000.00", "date": "2026-08-18", "reference": "SADV-API-OK",
            "attachment": _proof_file(),
        },
        format="multipart",
    )
    assert response.status_code == 201, response.data
    assert response.data["remaining_amount"] == "500000.00"
    assert response.data["proof_url"] is not None


@pytest.mark.django_db
def test_supplier_advance_endpoint_rejects_creation_with_open_debt(advances_finance_client):
    admin_user, supplier, order = _make_supplier_order_with_status(
        "API-REJECT", SupplierOrder.Status.CONFIRMED,
    )
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))

    response = advances_finance_client.post(
        "/api/supplier-advances/",
        {
            "supplier": supplier.id, "cash_account": cash_account.id,
            "amount": "100000.00", "date": "2026-08-18", "attachment": _proof_file(),
        },
        format="multipart",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_transporter_advance_endpoint_now_requires_account_and_attachment(advances_finance_client):
    trip, transporter = _make_trip_for_deduction("API-TADV")

    response = advances_finance_client.post(
        "/api/transporter-advances/",
        {"transporter": transporter.id, "amount": "100000.00", "date": "2026-08-18"},
    )
    assert response.status_code == 400
    assert "attachment" in response.data


@pytest.mark.django_db
def test_transporter_advance_endpoint_creates_advance_and_posts_treasury(advances_finance_client):
    trip, transporter = _make_trip_for_deduction("API-TADV-OK")
    bank_account = BankAccount.objects.create(name="Main BOA Account", opening_balance=Decimal("2000000.00"))

    response = advances_finance_client.post(
        "/api/transporter-advances/",
        {
            "transporter": transporter.id, "bank_account": bank_account.id,
            "amount": "300000.00", "date": "2026-08-18", "attachment": _proof_file(),
        },
        format="multipart",
    )
    assert response.status_code == 201, response.data
    bank_account.refresh_from_db()
    assert bank_account.current_balance == Decimal("1700000.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -k "endpoint" -v`
Expected: FAIL — `/api/supplier-advances/` doesn't exist (404); transporter-advances endpoint accepts the old shape without attachment (so the "requires attachment" test fails).

- [ ] **Step 3: Implement**

In `backend/apps/finance/serializers.py`, add `SupplierAdvance`, `AdvanceService`, `AdvanceError` to the existing imports, then add (near `TransporterAdvanceSerializer`, replacing it):

```python
class SupplierAdvanceSerializer(serializers.ModelSerializer):
    supplier_detail = SupplierSerializer(source="supplier", read_only=True)
    attachment = serializers.FileField(write_only=True, required=False, allow_null=True, default=None)
    proof_url = serializers.SerializerMethodField()
    remaining_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = SupplierAdvance
        fields = [
            "id", "supplier", "supplier_detail", "bank_account", "cash_account",
            "amount", "date", "reference", "notes", "attachment", "proof_url",
            "remaining_amount", "recorded_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "remaining_amount", "recorded_by", "created_at", "updated_at"]

    def get_proof_url(self, obj) -> str | None:
        if not obj.document_id or not obj.document.file:
            return None
        return obj.document.file.url

    def validate(self, data):
        bank_account = data.get("bank_account")
        cash_account = data.get("cash_account")
        if bank_account and cash_account:
            raise serializers.ValidationError("Un seul compte (banque OU caisse) peut etre renseigne.")
        if not bank_account and not cash_account:
            raise serializers.ValidationError("Un compte de tresorerie (banque ou caisse) est requis.")
        if self.instance is None and not data.get("attachment"):
            raise serializers.ValidationError(
                {"attachment": "Un justificatif image est obligatoire pour creer une avance."}
            )
        return data

    def validate_attachment(self, value):
        if value is None:
            return value
        return validate_image_upload(value)

    def create(self, validated_data):
        actor = self.context["request"].user
        bank_account = validated_data.get("bank_account")
        cash_account = validated_data.get("cash_account")
        try:
            return AdvanceService.create_supplier_advance(
                supplier_id=validated_data["supplier"].id,
                bank_account_id=bank_account.id if bank_account else None,
                cash_account_id=cash_account.id if cash_account else None,
                amount=validated_data["amount"],
                date=validated_data["date"],
                reference=validated_data.get("reference", ""),
                notes=validated_data.get("notes", ""),
                attachment=validated_data["attachment"],
                actor=actor,
            )
        except AdvanceError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError("Une avance enregistree ne peut pas etre modifiee.")


class TransporterAdvanceSerializer(serializers.ModelSerializer):
    transporter_detail = TransporterSerializer(source="transporter", read_only=True)
    attachment = serializers.FileField(write_only=True, required=False, allow_null=True, default=None)
    proof_url = serializers.SerializerMethodField()
    remaining_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = TransporterAdvance
        fields = [
            "id", "transporter", "transporter_detail", "bank_account", "cash_account",
            "amount", "date", "reference", "notes", "attachment", "proof_url",
            "remaining_amount", "settled", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "remaining_amount", "settled", "created_at", "updated_at"]

    def get_proof_url(self, obj) -> str | None:
        if not obj.document_id or not obj.document.file:
            return None
        return obj.document.file.url

    def validate(self, data):
        bank_account = data.get("bank_account")
        cash_account = data.get("cash_account")
        if bank_account and cash_account:
            raise serializers.ValidationError("Un seul compte (banque OU caisse) peut etre renseigne.")
        if not bank_account and not cash_account:
            raise serializers.ValidationError("Un compte de tresorerie (banque ou caisse) est requis.")
        if self.instance is None and not data.get("attachment"):
            raise serializers.ValidationError(
                {"attachment": "Un justificatif image est obligatoire pour creer une avance."}
            )
        return data

    def validate_attachment(self, value):
        if value is None:
            return value
        return validate_image_upload(value)

    def create(self, validated_data):
        actor = self.context["request"].user
        bank_account = validated_data.get("bank_account")
        cash_account = validated_data.get("cash_account")
        try:
            return AdvanceService.create_transporter_advance(
                transporter_id=validated_data["transporter"].id,
                bank_account_id=bank_account.id if bank_account else None,
                cash_account_id=cash_account.id if cash_account else None,
                amount=validated_data["amount"],
                date=validated_data["date"],
                reference=validated_data.get("reference", ""),
                notes=validated_data.get("notes", ""),
                attachment=validated_data["attachment"],
                actor=actor,
            )
        except AdvanceError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError("Une avance enregistree ne peut pas etre modifiee.")
```

In `backend/apps/finance/views.py`:
- Add `SupplierAdvance` to the model imports, `SupplierAdvanceSerializer` to the serializer imports.
- Add, right before `class TransporterAdvanceViewSet`:

```python
class SupplierAdvanceViewSet(viewsets.ModelViewSet):
    queryset = SupplierAdvance.objects.select_related("supplier", "bank_account", "cash_account").all()
    serializer_class = SupplierAdvanceSerializer
    filterset_fields = ["supplier"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def perform_create(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)
```

(`perform_create` doesn't need `recorded_by=self.request.user` here since `SupplierAdvanceSerializer.create()` already reads the actor from `self.context["request"].user` itself and passes it into `AdvanceService`.)

In `backend/apps/finance/urls.py`, add `SupplierAdvanceViewSet` to the imports and register it:

```python
router.register("supplier-advances", SupplierAdvanceViewSet, basename="supplieradvance")
```

(placed next to `"transporter-advances"` for readability.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/ -v`
Expected: PASS (full app, confirming nothing else broke).

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/serializers.py backend/apps/finance/views.py backend/apps/finance/urls.py backend/apps/finance/test_advances.py
git commit -m "feat(finance): add supplier-advances endpoint, require account+proof on transporter-advances"
```

---

## Task 8: `party-balances` endpoint

**Files:**
- Modify: `backend/apps/finance/views.py`
- Modify: `backend/apps/finance/test_advances.py`

**Interfaces:**
- Consumes: `describe_supplier_balance`/`describe_transporter_balance` (Task 5).
- Produces: `GET /api/treasury-transactions/party-balances/?debt_type=supplier|transporter` — the single source Task 15/17/18/19 frontend wiring calls for button visibility and the free-mode party picker.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/test_advances.py`:

```python
# ---------------------------------------------------------------------------
# Task 8: party-balances endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_party_balances_endpoint_matches_describe_supplier_balance(advances_finance_client):
    admin_user, supplier, order = _make_supplier_order_with_status(
        "PB-SUP", SupplierOrder.Status.CONFIRMED,
    )
    cash_account = CashAccount.objects.create(name="Main Cash")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("250000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )

    response = advances_finance_client.get(
        "/api/treasury-transactions/party-balances/", {"debt_type": "supplier"}
    )
    assert response.status_code == 200
    row = next(r for r in response.data if r["id"] == supplier.id)
    expected = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert row["total_due"] == f"{expected['total_due']:.2f}"
    assert row["net_balance"] == f"{expected['net_balance']:.2f}"


@pytest.mark.django_db
def test_party_balances_endpoint_lists_transporters(advances_finance_client):
    trip, transporter = _make_trip_for_deduction("PB-TRANS")
    response = advances_finance_client.get(
        "/api/treasury-transactions/party-balances/", {"debt_type": "transporter"}
    )
    assert response.status_code == 200
    assert any(r["id"] == transporter.id for r in response.data)


@pytest.mark.django_db
def test_party_balances_endpoint_rejects_unknown_debt_type(advances_finance_client):
    response = advances_finance_client.get(
        "/api/treasury-transactions/party-balances/", {"debt_type": "bogus"}
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -k party_balances -v`
Expected: FAIL with 404 (action doesn't exist).

- [ ] **Step 3: Implement**

In `backend/apps/finance/views.py`, add `from apps.suppliers.models import Supplier` and `from apps.transport.models import Transporter` to the imports (same module-level import direction `services.py` already uses safely), and add this action to `TreasuryTransactionViewSet` (e.g. right after `payable_debts`):

```python
    @action(detail=False, methods=["get"], url_path="party-balances")
    def party_balances(self, request):
        """Single source of truth for net_balance per supplier/transporter -
        consumed by the Nouvelle avance / Nouveau paiement button logic
        everywhere (Journal, Grands livres) and must never disagree with
        the Dashboard or Grand livre summary cards.

        GET /api/treasury-transactions/party-balances/?debt_type=supplier|transporter
        """
        debt_type = request.query_params.get("debt_type")
        if debt_type == ControlledDebtPaymentService.SUPPLIER:
            rows = [
                ControlledDebtPaymentService.describe_supplier_balance(supplier)
                for supplier in Supplier.objects.filter(is_active=True).order_by("name", "id")
            ]
        elif debt_type == ControlledDebtPaymentService.TRANSPORTER:
            rows = [
                ControlledDebtPaymentService.describe_transporter_balance(transporter)
                for transporter in Transporter.objects.filter(is_active=True).order_by("name", "id")
            ]
        else:
            return Response({"detail": "Type de tiers inconnu."}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(decimals_to_str(rows))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/views.py backend/apps/finance/test_advances.py
git commit -m "feat(finance): add party-balances endpoint"
```

---

## Task 9: Fix `SupplierOutstandingReportQuery` to be advance-aware

**Files:**
- Modify: `backend/apps/reports/queries/supplier_outstanding_report.py`
- Modify: `backend/apps/reports/test_queries_v2.py`

**Interfaces:**
- Consumes: `ControlledDebtPaymentService.describe_supplier` (existing, now advance-aware via Task 3).
- Produces: `SupplierOutstandingReportQuery.run()` now matches `describe_supplier`/`describe_supplier_balance` exactly (mirrors the alignment `TransporterOutstandingReportQuery` already has) — Task 11's dashboard wiring depends on this.

- [ ] **Step 1: Write the failing test**

Add to `backend/apps/reports/test_queries_v2.py` (add `from apps.finance.models import SupplierAdvance` to the imports):

```python
@pytest.mark.django_db
def test_supplier_outstanding_report_nets_out_advance_consumption():
    admin_user = _make_admin("SUPOUTADV")
    supplier = Supplier.objects.create(name="Supplier SUPOUTADV", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Cash SUPOUTADV")
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("2000000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    order = SupplierOrder.objects.create(
        reference="SO-QUERY2-SUPOUTADV", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 300000000, advance created BEFORE confirmation so it's consumed at confirm time

    rows = SupplierOutstandingReportQuery.run()
    row = next(r for r in rows if r["supplier"] == supplier.name)
    assert row["outstanding"] == order.total_amount - Decimal("2000000.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest apps/reports/test_queries_v2.py -k nets_out_advance -v`
Expected: FAIL — today's query sums *all* `SupplierPayment.amount` (there are none here) and ignores `SupplierAdvance`/`AdvanceConsumption` entirely, so it reports the full `300000000.00` instead of `298000000.00`.

- [ ] **Step 3: Implement**

Replace the full content of `backend/apps/reports/queries/supplier_outstanding_report.py`:

```python
# SupplierOutstandingReportQuery - "supplier outstanding report"
# (ERP_Specification.md Section 37; docs/PHASE_6_PLAN.md Etape 4/6).
#
# "Outstanding" per supplier is the same reste-a-payer figure as the
# "Nouveau paiement" screen (ControlledDebtPaymentService.describe_supplier,
# already advance-aware since docs/superpowers/specs/2026-08-31-supplier-
# transporter-advances-design.md), so this report, the payment screen, and
# the Dashboard never disagree - mirrors TransporterOutstandingReportQuery's
# alignment.

from decimal import Decimal

from apps.finance.services import ControlledDebtPaymentService
from apps.purchasing.models import SupplierOrder
from apps.suppliers.models import Supplier

FIELDS = ["supplier", "outstanding"]
ZERO = Decimal("0.00")


class SupplierOutstandingReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls) -> list[dict]:
        supplier_ids = (
            SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED)
            .values_list("supplier_id", flat=True)
            .distinct()
        )
        rows = []
        for supplier in Supplier.objects.filter(id__in=supplier_ids):
            outstanding = ControlledDebtPaymentService.describe_supplier(supplier)["remaining_amount"]
            if outstanding > ZERO:
                rows.append({"supplier": supplier.name, "outstanding": outstanding})
        return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/reports/test_queries_v2.py apps/reports/test_views.py -v`
Expected: PASS — including the two pre-existing `SupplierOutstandingReportQuery` tests (`test_supplier_outstanding_report_matches_purchases_minus_payments`, `test_supplier_outstanding_report_only_counts_confirmed_orders`), which are unaffected since neither scenario involves an advance.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/reports/queries/supplier_outstanding_report.py backend/apps/reports/test_queries_v2.py
git commit -m "fix(reports): align SupplierOutstandingReportQuery with describe_supplier (advance-aware)"
```

---

## Task 10: `SupplierLedgerService` / `TransporterLedgerService` — Grand livre summary + chronological entries

**Files:**
- Modify: `backend/apps/finance/services.py`
- Modify: `backend/apps/suppliers/views.py`
- Modify: `backend/apps/transport/views.py`
- Modify: `backend/apps/finance/test_advances.py`

**Interfaces:**
- Consumes: `describe_supplier_balance`/`describe_transporter_balance` (Task 5), `SupplierAdvance`/`TransporterAdvance`/`AdvanceConsumption` (Task 1).
- Produces: `SupplierLedgerService.get_ledger(supplier) -> {"summary": {...}, "entries": [...]}`, `TransporterLedgerService.get_ledger(transporter) -> {"summary": {...}, "entries": [...]}`. `entries` items: `{type, date, amount, reference, note, proof_url}` with `type` in `{advance_given, debt_created, advance_consumed, payment}`. `SupplierViewSet.ledger`/`TransporterViewSet.ledger` responses gain `summary`/`entries` keys; all existing keys stay.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/test_advances.py`:

```python
# ---------------------------------------------------------------------------
# Task 10: SupplierLedgerService / TransporterLedgerService
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_supplier_ledger_service_orders_entries_chronologically_with_all_four_types():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "LEDGER-SVC", SupplierOrder.Status.DRAFT,
    )
    cash_account = CashAccount.objects.create(name="Main Cash", opening_balance=Decimal("5000000.00"))
    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("300000.00"), date="2026-08-10",
        cash_account=cash_account, recorded_by=admin_user,
    )
    order.purchase_date = "2026-08-15"
    order.status = SupplierOrder.Status.CONFIRMED
    order.save()  # 600000 debt, consumes the 300000 advance, leaves 300000 payable

    ControlledDebtPaymentService.record_payment(
        debt_type="supplier", debt_id=supplier.id,
        bank_account_id=BankAccount.objects.create(
            name="Ledger Bank", opening_balance=Decimal("5000000.00")
        ).id,
        amount=Decimal("300000.00"), date="2026-08-20", reference="PAY-LEDGER-SVC", actor=admin_user,
    )

    ledger = SupplierLedgerService.get_ledger(supplier)

    assert ledger["summary"]["net_balance"] == Decimal("0.00")
    types_in_order = [entry["type"] for entry in ledger["entries"]]
    assert types_in_order == ["advance_given", "debt_created", "advance_consumed", "payment"]
    assert ledger["entries"][0]["amount"] == Decimal("300000.00")
    assert ledger["entries"][1]["amount"] == Decimal("600000.00")
    assert ledger["entries"][3]["amount"] == Decimal("300000.00")


@pytest.mark.django_db
def test_transporter_ledger_service_reports_summary_and_entries():
    trip, transporter = _make_trip_for_deduction("LEDGER-SVC-T")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("200000.00"), date="2026-08-10",
        cash_account=cash_account,
    )
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )

    ledger = TransporterLedgerService.get_ledger(transporter)

    assert ledger["summary"]["total_due"] == Decimal("500000.00")
    types_present = {entry["type"] for entry in ledger["entries"]}
    assert types_present == {"advance_given", "debt_created", "advance_consumed"}


@pytest.mark.django_db
def test_supplier_ledger_endpoint_keeps_existing_keys_and_adds_summary_entries(advances_finance_client):
    admin_user, supplier, order = _make_supplier_order_with_status(
        "LEDGER-API", SupplierOrder.Status.CONFIRMED,
    )
    response = advances_finance_client.get(f"/api/suppliers/{supplier.id}/ledger/")
    assert response.status_code == 200
    for key in ("orders", "reliquat_summary", "payments", "total_purchased", "total_paid", "outstanding_balance"):
        assert key in response.data
    assert "summary" in response.data
    assert "entries" in response.data


@pytest.mark.django_db
def test_transporter_ledger_endpoint_advances_applied_reflects_automatic_consumption(advances_finance_client):
    trip, transporter = _make_trip_for_deduction("LEDGER-API-T")
    cash_account = CashAccount.objects.create(name="Main Cash")
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("100000.00"), date="2026-08-17",
        cash_account=cash_account,
    )
    TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )

    response = advances_finance_client.get(f"/api/transporters/{transporter.id}/ledger/")
    assert response.status_code == 200
    assert response.data["advances_applied"] == "100000.00"
    assert "summary" in response.data
    assert "entries" in response.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -k ledger -v`
Expected: FAIL — `SupplierLedgerService`/`TransporterLedgerService` don't exist; `advances_applied` still reads the retired `advance_applied` FK (always `None` now) so it reports `"0.00"` instead of `"100000.00"`.

- [ ] **Step 3: Implement the services**

In `backend/apps/finance/services.py`, add near the end of the file (after `ShareholderLedgerService` or anywhere past `AdvanceConsumption`'s definition):

```python
class SupplierLedgerService:
    """Chronological Grand livre for one supplier: advances given, debts
    created, advances consumed, and complementary payments, all in one
    ordered timeline (docs/superpowers/specs/2026-08-31-supplier-
    transporter-advances-design.md) - built on describe_supplier_balance so
    the summary cards never disagree with Nouveau paiement/Dashboard."""

    @staticmethod
    def get_ledger(supplier) -> dict:
        entries = []

        for advance in SupplierAdvance.objects.filter(supplier=supplier):
            entries.append({
                "type": "advance_given",
                "date": advance.date,
                "amount": advance.amount,
                "reference": advance.reference,
                "note": advance.notes,
                "proof_url": (
                    advance.document.file.url
                    if advance.document_id and advance.document.file else None
                ),
            })

        orders = SupplierOrder.objects.filter(supplier=supplier, status=SupplierOrder.Status.CONFIRMED)
        for order in orders:
            entries.append({
                "type": "debt_created",
                "date": order.purchase_date,
                "amount": order.total_amount,
                "reference": order.reference,
                "note": "",
                "proof_url": None,
            })

        order_ct = ContentType.objects.get_for_model(SupplierOrder)
        consumptions = AdvanceConsumption.objects.filter(
            supplier_advance__supplier=supplier, debt_content_type=order_ct, reversed_at__isnull=True,
        ).select_related("supplier_advance")
        for consumption in consumptions:
            entries.append({
                "type": "advance_consumed",
                "date": consumption.created_at.date(),
                "amount": consumption.amount,
                "reference": consumption.supplier_advance.reference,
                "note": "",
                "proof_url": None,
            })

        payments = SupplierPayment.objects.filter(supplier=supplier, is_advance=False)
        payment_ct = ContentType.objects.get_for_model(SupplierPayment)
        for payment in payments:
            txn = (
                TreasuryTransaction.objects.filter(
                    source_content_type=payment_ct, source_object_id=payment.id, document__isnull=False,
                ).select_related("document").order_by("-date", "-id").first()
            )
            entries.append({
                "type": "payment",
                "date": payment.payment_date,
                "amount": payment.amount,
                "reference": payment.reference,
                "note": "",
                "proof_url": txn.document.file.url if txn and txn.document.file else None,
            })

        entries.sort(key=lambda entry: entry["date"])

        return {
            "summary": ControlledDebtPaymentService.describe_supplier_balance(supplier),
            "entries": entries,
        }


class TransporterLedgerService:
    """Same chronological Grand livre as SupplierLedgerService, for
    transporters - 'debt_created' entries come from TransportPayment
    (base_amount - deduction_amount, before any advance consumption),
    'payment' entries from the TreasuryTransaction rows
    ControlledDebtPaymentService posts against each TransportPayment."""

    @staticmethod
    def get_ledger(transporter) -> dict:
        entries = []

        for advance in TransporterAdvance.objects.filter(transporter=transporter):
            entries.append({
                "type": "advance_given",
                "date": advance.date,
                "amount": advance.amount,
                "reference": advance.reference,
                "note": advance.notes,
                "proof_url": (
                    advance.document.file.url
                    if advance.document_id and advance.document.file else None
                ),
            })

        payments = list(TransportPayment.objects.filter(transporter=transporter).select_related("trip"))
        for payment in payments:
            entries.append({
                "type": "debt_created",
                "date": payment.created_at.date(),
                "amount": payment.base_amount - payment.deduction_amount,
                "reference": payment.trip.reference,
                "note": "",
                "proof_url": None,
            })

        payment_ct = ContentType.objects.get_for_model(TransportPayment)
        consumptions = AdvanceConsumption.objects.filter(
            transporter_advance__transporter=transporter, debt_content_type=payment_ct,
            reversed_at__isnull=True,
        ).select_related("transporter_advance")
        for consumption in consumptions:
            entries.append({
                "type": "advance_consumed",
                "date": consumption.created_at.date(),
                "amount": consumption.amount,
                "reference": consumption.transporter_advance.reference,
                "note": "",
                "proof_url": None,
            })

        payment_ids = [payment.id for payment in payments]
        treasury_rows = TreasuryTransaction.objects.filter(
            source_content_type=payment_ct, source_object_id__in=payment_ids,
            type=TreasuryTransaction.Type.MONEY_OUT,
        ).select_related("document")
        for txn in treasury_rows:
            entries.append({
                "type": "payment",
                "date": txn.date,
                "amount": txn.amount,
                "reference": txn.reference,
                "note": txn.note,
                "proof_url": txn.document.file.url if txn.document_id and txn.document.file else None,
            })

        entries.sort(key=lambda entry: entry["date"])

        return {
            "summary": ControlledDebtPaymentService.describe_transporter_balance(transporter),
            "entries": entries,
        }
```

- [ ] **Step 4: Wire the two ledger viewsets**

In `backend/apps/suppliers/views.py`, add `from apps.reports.serialization import decimals_to_str` to the top-level imports, and inside `SupplierViewSet.ledger`, after the lazy `from apps.finance.serializers import SupplierPaymentSerializer` line, add:

```python
        from apps.finance.services import SupplierLedgerService

        ledger_data = SupplierLedgerService.get_ledger(supplier)
```

then extend the returned `Response({...})` dict (keep every existing key) by adding, right before the closing `}`:

```python
                "summary": decimals_to_str(ledger_data["summary"]),
                "entries": decimals_to_str(ledger_data["entries"]),
```

In `backend/apps/transport/views.py`:
- Add `from apps.reports.serialization import decimals_to_str` to the top-level imports.
- Inside `TransporterViewSet.ledger`, replace the `advances_applied` computation:

```python
        advances_applied = sum(
            (p.advance_applied.amount for p in payments if p.advance_applied_id),
            Decimal("0.00"),
        )
```

with:

```python
        from apps.finance.models import AdvanceConsumption
        from apps.finance.services import TransporterLedgerService

        advances_applied = AdvanceConsumption.objects.filter(
            transporter_advance__transporter=transporter,
            debt_content_type=transport_payment_type,
            reversed_at__isnull=True,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        ledger_data = TransporterLedgerService.get_ledger(transporter)
```

(`transport_payment_type` is already computed a few lines below as `ContentType.objects.get_for_model(TransportPayment)` — move that line above the new `advances_applied` block so it's defined before use.)

Extend the returned `Response({...})` dict by adding, right before the closing `}`:

```python
                "summary": decimals_to_str(ledger_data["summary"]),
                "entries": decimals_to_str(ledger_data["entries"]),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/finance/test_advances.py apps/finance/tests.py apps/suppliers/ apps/transport/ -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/suppliers/views.py backend/apps/transport/views.py backend/apps/finance/test_advances.py
git commit -m "feat(finance): add SupplierLedgerService/TransporterLedgerService, wire into ledger endpoints"
```

---

## Task 11: Dashboard `party_balances` — `net_balance` for suppliers/transporters

**Files:**
- Modify: `backend/apps/reports/views/dashboard.py`
- Modify: `backend/apps/reports/test_views.py`

**Interfaces:**
- Consumes: `describe_supplier_balance`/`describe_transporter_balance` (Task 5).
- Produces: `party_balances.suppliers.balance`/`party_balances.transporters.balance` now equal `net_balance` (can be positive), matching the sign convention the frontend (Task 19) will read.

- [ ] **Step 1: Write the failing test**

Add to `backend/apps/reports/test_views.py` (check the existing imports at the top of that file and add `SupplierAdvance`, `ControlledDebtPaymentService` if not already imported):

```python
@pytest.mark.django_db
def test_dashboard_party_balances_suppliers_reflects_advance_then_debt_then_payment(finance_client):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(phone="+222770000088", pin="1234", role=admin_role)
    supplier = Supplier.objects.create(name="Dashboard Sync Supplier", country="Senegal")
    product = Product.objects.get(code="gasoil")
    cash_account = CashAccount.objects.create(name="Cash Dash Sync")
    bank_account = BankAccount.objects.create(name="Bank Dash Sync", opening_balance=Decimal("10000000.00"))

    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("2000000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    response = finance_client.get("/api/dashboard/summary/")
    balance_after_advance = Decimal(response.data["party_balances"]["suppliers"]["balance"])
    assert balance_after_advance >= Decimal("2000000.00")

    SupplierOrder.objects.create(
        reference="SO-DASH-SYNC", supplier=supplier, product=product,
        purchase_date="2026-08-18", quantity_litres=Decimal("1000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 600000, fully covered by the 2M advance
    response = finance_client.get("/api/dashboard/summary/")
    balance_after_debt = Decimal(response.data["party_balances"]["suppliers"]["balance"])
    assert balance_after_debt == balance_after_advance - Decimal("600000.00")
    assert balance_after_debt > Decimal("0.00")

    SupplierOrder.objects.create(
        reference="SO-DASH-SYNC-2", supplier=supplier, product=product,
        purchase_date="2026-08-19", quantity_litres=Decimal("5000.00"),
        unit_price=Decimal("600.0000"), status=SupplierOrder.Status.CONFIRMED,
        created_by=admin_user,
    )  # total 3000000, consumes remaining 1400000 advance, leaves 1600000 real debt
    response = finance_client.get("/api/dashboard/summary/")
    assert Decimal(response.data["party_balances"]["suppliers"]["balance"]) == Decimal("-1600000.00")

    ControlledDebtPaymentService.record_payment(
        debt_type="supplier", debt_id=supplier.id, bank_account_id=bank_account.id,
        amount=Decimal("600000.00"), date="2026-08-20", reference="PAY-DASH-SYNC", actor=admin_user,
    )
    response = finance_client.get("/api/dashboard/summary/")
    assert Decimal(response.data["party_balances"]["suppliers"]["balance"]) == Decimal("-1000000.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest apps/reports/test_views.py -k dashboard_party_balances_suppliers_reflects -v`
Expected: FAIL — today's `balance = -supplier_total` never goes positive (an advance-only supplier doesn't even appear in `SupplierOutstandingReportQuery` rows), so `balance_after_advance` would be `0`, not `>= 2000000`.

- [ ] **Step 3: Implement**

In `backend/apps/reports/views/dashboard.py`:
- Add imports: `from apps.suppliers.models import Supplier`, `from apps.transport.models import Transporter` (Transporter may already be imported transitively via `Trip` — add explicitly to be safe).
- Replace the `party_balances` construction. First, before building `party_balances`, add:

```python
        supplier_balances = [
            ControlledDebtPaymentService.describe_supplier_balance(supplier)
            for supplier in Supplier.objects.filter(is_active=True)
        ]
        supplier_net_total = sum((row["net_balance"] for row in supplier_balances), ZERO)

        transporter_balances = [
            ControlledDebtPaymentService.describe_transporter_balance(transporter)
            for transporter in Transporter.objects.filter(is_active=True)
        ]
        transporter_net_total = sum((row["net_balance"] for row in transporter_balances), ZERO)

        def _largest_negative(rows):
            negative_rows = [row for row in rows if row["net_balance"] < ZERO]
            if not negative_rows:
                return None
            row = min(negative_rows, key=lambda item: item["net_balance"])
            return {"name": row["label"], "amount": -row["net_balance"]}
```

Then, inside `party_balances = {...}`, replace the `"suppliers"` and `"transporters"` entries:

```python
            "suppliers": {
                "balance": supplier_net_total,
                "open_count": len([row for row in supplier_balances if row["net_balance"] != ZERO]),
                "largest_open": _largest_negative(supplier_balances),
            },
            "transporters": {
                "balance": transporter_net_total,
                "open_count": len([row for row in transporter_balances if row["net_balance"] != ZERO]),
                "largest_open": _largest_negative(transporter_balances),
            },
```

(The `debts.suppliers`/`debts.transporters` block above — driven by `SupplierOutstandingReportQuery`/`TransporterOutstandingReportQuery` — is untouched: it continues to represent gross remaining debt for the "Total des dettes" widget, and is already advance-aware via Task 9's fix.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest apps/reports/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/reports/views/dashboard.py backend/apps/reports/test_views.py
git commit -m "feat(reports): dashboard party_balances.suppliers/transporters now report net_balance"
```

---

## Task 12: Retire `SupplierPayment.is_advance` for new writes, migrate legacy rows

**Files:**
- Modify: `backend/apps/finance/serializers.py` (`SupplierPaymentSerializer`)
- Modify: `backend/apps/finance/services.py` (`AdvanceMigrationService`)
- Create: a data migration in `backend/apps/finance/migrations/`
- Modify: `backend/apps/finance/test_advances.py`

**Interfaces:**
- Consumes: `SupplierAdvance` (Task 1).
- Produces: `AdvanceMigrationService.migrate_legacy_supplier_advances()` (real-model, directly testable — the migration's `RunPython` forward function just calls it); `SupplierPaymentSerializer` rejects `is_advance=True` on create.

- [ ] **Step 1: Write the failing tests**

Add to `backend/apps/finance/test_advances.py`:

```python
# ---------------------------------------------------------------------------
# Task 12: retire SupplierPayment.is_advance, migrate legacy rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_supplier_payment_serializer_rejects_new_advance_creation(advances_finance_client):
    admin_user, supplier, order = _make_supplier_order("BLOCK-ADV")
    cash_account = CashAccount.objects.create(name="Main Cash")
    response = advances_finance_client.post(
        "/api/supplier-payments/",
        {
            "supplier": supplier.id, "amount": "500000.00", "payment_date": "2026-08-18",
            "method": "CASH", "cash_account": cash_account.id, "is_advance": True,
        },
    )
    assert response.status_code == 400
    assert "is_advance" in response.data


@pytest.mark.django_db
def test_migrate_legacy_supplier_advances_creates_open_supplier_advance():
    admin_user, supplier, order = _make_supplier_order("MIGRATE-LEGACY")
    cash_account = CashAccount.objects.create(name="Main Cash")
    legacy_payment = SupplierPayment.objects.create(
        supplier=supplier, amount=Decimal("1500000.00"), payment_date="2026-08-10",
        method=SupplierPayment.Method.CASH, cash_account=cash_account,
        is_advance=True, reference="LEGACY-ADV-1", recorded_by=admin_user,
    )

    AdvanceMigrationService.migrate_legacy_supplier_advances()

    migrated = SupplierAdvance.objects.get(supplier=supplier)
    assert migrated.amount == Decimal("1500000.00")
    assert migrated.cash_account_id == cash_account.id
    assert migrated.date == legacy_payment.payment_date
    assert migrated.remaining_amount == Decimal("1500000.00")
    assert TreasuryTransaction.objects.filter(
        source_content_type=ContentType.objects.get_for_model(SupplierAdvance)
    ).count() == 0


@pytest.mark.django_db
def test_migrated_legacy_advance_does_not_double_count_in_supplier_balance():
    admin_user, supplier, order = _make_supplier_order_with_status(
        "MIGRATE-BALANCE", SupplierOrder.Status.CONFIRMED,
    )  # total 600000, no advance existed at confirm time -> fully payable
    cash_account = CashAccount.objects.create(name="Main Cash")
    SupplierPayment.objects.create(
        supplier=supplier, amount=Decimal("200000.00"), payment_date="2026-08-10",
        method=SupplierPayment.Method.CASH, cash_account=cash_account,
        is_advance=True, reference="LEGACY-ADV-3", recorded_by=admin_user,
    )

    AdvanceMigrationService.migrate_legacy_supplier_advances()

    balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)
    assert balance["total_due"] == Decimal("600000.00")  # unaffected: never applied to this order
    assert balance["open_advances"] == Decimal("200000.00")  # counted once, via SupplierAdvance only
    assert balance["net_balance"] == Decimal("-400000.00")
```

Add `AdvanceMigrationService` to the `from apps.finance.services import (...)` block.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -k "block_adv or migrate_legacy or migrated_legacy" -v`
Expected: FAIL — `is_advance=True` still accepted; `AdvanceMigrationService` doesn't exist.

- [ ] **Step 3: Implement**

In `backend/apps/finance/serializers.py`, in `SupplierPaymentSerializer.validate()`, add at the very top of the method body (before the `bank_account`/`cash_account` checks):

```python
        is_advance = data.get("is_advance", getattr(self.instance, "is_advance", False))
        if self.instance is None and is_advance:
            raise serializers.ValidationError(
                {
                    "is_advance": (
                        "Utilisez POST /api/supplier-advances/ pour creer une nouvelle "
                        "avance fournisseur."
                    )
                }
            )
```

(the method already computes `is_advance` again a few lines later for the bank/cash rule — leave that duplicate read in place, it's harmless and keeps this diff minimal.)

In `backend/apps/finance/services.py`, add:

```python
class AdvanceMigrationService:
    """One-time backfill: every legacy SupplierPayment(is_advance=True) row
    becomes a SupplierAdvance, so it's consumable going forward and counted
    exactly once in describe_supplier_balance (docs/superpowers/specs/
    2026-08-31-supplier-transporter-advances-design.md). No new
    TreasuryTransaction is created - the cash already left the company via
    the original SupplierPayment, which stays untouched. Uses the current
    (not historical) models directly since this migration is written and
    applied in the same change as the schema it depends on."""

    @staticmethod
    def migrate_legacy_supplier_advances() -> int:
        migrated = 0
        for payment in SupplierPayment.objects.filter(is_advance=True):
            SupplierAdvance.objects.create(
                supplier_id=payment.supplier_id,
                bank_account_id=payment.bank_account_id,
                cash_account_id=payment.cash_account_id,
                amount=payment.amount,
                date=payment.payment_date,
                reference=payment.reference,
                notes=f"Migre depuis SupplierPayment #{payment.id}",
                document=None,
                recorded_by_id=payment.recorded_by_id,
            )
            migrated += 1
        return migrated
```

Create the migration (run `cd backend && python manage.py makemigrations finance --empty --name migrate_legacy_supplier_advances` to get the correctly-numbered stub, then fill it in):

```python
from django.db import migrations


def migrate_legacy_advances(apps, schema_editor):
    from apps.finance.services import AdvanceMigrationService

    AdvanceMigrationService.migrate_legacy_supplier_advances()


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "PREVIOUS_MIGRATION_NAME_HERE"),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_advances, migrations.RunPython.noop),
    ]
```

(Replace `PREVIOUS_MIGRATION_NAME_HERE` with whatever `makemigrations --empty` actually filled in — it auto-detects the latest applied migration in the app.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python manage.py migrate && python -m pytest apps/finance/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/finance/serializers.py backend/apps/finance/services.py backend/apps/finance/migrations/ backend/apps/finance/test_advances.py
git commit -m "feat(finance): retire SupplierPayment.is_advance for new writes, migrate legacy rows"
```

---

## Task 13: Dedicated profit non-impact test

**Files:**
- Modify: `backend/apps/finance/test_advances.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6. No production code changes in this task — it's a pinning test confirming the invariant already holds by construction.

- [ ] **Step 1: Write the test**

Add to `backend/apps/finance/test_advances.py`:

```python
# ---------------------------------------------------------------------------
# Task 13: profit non-impact (pinning test - no production code change)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_advance_creation_and_consumption_never_touch_the_fields_profit_reads_from():
    """TripProfitService/TripCostService read SupplierOrder.unit_price and
    TransportPayment.base_amount for cost purposes - never total_amount or
    net_amount, which are the only fields advance consumption can affect.
    Pinning this at the source is more decisive than wiring up a full
    Sale/margin computation: if either input field below ever moved, the
    margin formula would silently change too."""
    admin_user, supplier, order = _make_supplier_order_with_status(
        "PROFIT-ADV", SupplierOrder.Status.DRAFT, quantity=Decimal("45000.00"),
    )
    cash_account = CashAccount.objects.create(name="Main Cash")
    trip, transporter = _make_trip_for_deduction("PROFIT-ADV")

    SupplierAdvance.objects.create(
        supplier=supplier, amount=Decimal("2000000.00"), date="2026-08-17",
        cash_account=cash_account, recorded_by=admin_user,
    )
    order.status = SupplierOrder.Status.CONFIRMED
    order.save()
    order.refresh_from_db()

    assert order.unit_price == Decimal("600.0000")
    assert order.total_amount == Decimal("27000000.00")

    payment = TransportPayment.objects.create(
        trip=trip, transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.FIXED,
        base_amount=Decimal("700000.00"),
    )
    TransporterAdvance.objects.create(
        transporter=transporter, amount=Decimal("300000.00"), date="2026-08-17",
        cash_account=cash_account,
    )
    payment.refresh_from_db()
    assert payment.base_amount == Decimal("700000.00")
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `cd backend && python -m pytest apps/finance/test_advances.py -k profit_non_impact_or_never_touch -v`
Expected: PASS already (this pins existing, correct behavior from Tasks 1-6 — if it failed, that would mean an earlier task introduced a regression, and you'd stop and fix that task first rather than adjust this test).

- [ ] **Step 3: Commit**

```bash
git add backend/apps/finance/test_advances.py
git commit -m "test(finance): pin that advance creation/consumption never touch profit-formula inputs"
```

---

## Task 14: Frontend types + API client functions

**Files:**
- Modify: `frontend/src/modules/finance/types.ts`
- Modify: `frontend/src/modules/purchasing/types.ts`
- Modify: `frontend/src/modules/finance/api.ts`

**Interfaces:**
- Produces: `SupplierAdvance`, extended `TransporterAdvance`, `PartyType`, `PartyBalance`, `LedgerEntryType`, `LedgerEntry` (in `finance/types.ts`); `SupplierLedger`/`TransporterLedger` gain `summary`/`entries`; `supplierAdvanceResource`, `createSupplierAdvance`, `createTransporterAdvance`, `fetchPartyBalances` (in `finance/api.ts`). No dedicated test file — exercised through the component tests in Tasks 15/17/18/19, consistent with this codebase's existing convention (no `api.ts` has its own spec file).

- [ ] **Step 1: Extend `frontend/src/modules/finance/types.ts`**

Replace the existing `TransporterAdvance` interface with:

```typescript
export interface SupplierAdvance {
  id: number
  supplier: number
  supplier_detail: SupplierBrief | null
  bank_account: number | null
  cash_account: number | null
  amount: string
  date: string
  reference: string
  notes: string
  proof_url: string | null
  remaining_amount: string
  recorded_by: number | null
  created_at: string
  updated_at: string
}

export interface TransporterAdvance {
  id: number
  transporter: number
  transporter_detail: TransporterBrief | null
  bank_account: number | null
  cash_account: number | null
  amount: string
  date: string
  reference: string
  notes: string
  proof_url: string | null
  remaining_amount: string
  settled: boolean
  created_at: string
  updated_at: string
}
```

Add, after `TransporterLedger`:

```typescript
export type PartyType = 'supplier' | 'transporter'

export interface PartyBalance {
  id: number
  label: string
  total_due: string
  open_advances: string
  net_balance: string
  last_advance: { date: string; amount: string } | null
  last_payment: { date: string; amount: string } | null
}

export type LedgerEntryType = 'advance_given' | 'debt_created' | 'advance_consumed' | 'payment'

export interface LedgerEntry {
  type: LedgerEntryType
  date: string
  amount: string
  reference: string
  note: string
  proof_url: string | null
}
```

Extend `TransporterLedger` (add two fields):

```typescript
export interface TransporterLedger {
  transporter: { id: number; name: string; company_name: string }
  gross_amount: string
  deductions: string
  advances_applied: string
  settled: string
  net_outstanding: string
  unsettled_advances: string
  payments: TransportPayment[]
  advances: TransporterAdvance[]
  summary: PartyBalance
  entries: LedgerEntry[]
}
```

- [ ] **Step 2: Extend `frontend/src/modules/purchasing/types.ts`**

Add the import and extend `SupplierLedger`:

```typescript
import type { LedgerEntry, PartyBalance } from '@/modules/finance/types'
```

```typescript
export interface SupplierLedger {
  supplier: { id: number; name: string }
  orders: SupplierOrder[]
  reliquat_summary: SupplierLedgerProductReliquat[]
  payments: SupplierLedgerPayment[]
  total_purchased: string
  total_paid: string
  outstanding_balance: string
  summary: PartyBalance
  entries: LedgerEntry[]
}
```

- [ ] **Step 3: Add API functions to `frontend/src/modules/finance/api.ts`**

Add `SupplierAdvance`, `PartyBalance`, `PartyType` to the existing type-only import block, and add:

```typescript
export const supplierAdvanceResource = createResourceApi<SupplierAdvance>('/supplier-advances/')

function buildAdvanceForm(fields: Record<string, unknown>, attachment: File): FormData {
  const form = new FormData()
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined && value !== null) form.append(key, String(value))
  }
  form.append('attachment', attachment)
  return form
}

export function createSupplierAdvance(payload: {
  supplier: number
  bank_account?: number | null
  cash_account?: number | null
  amount: string
  date: string
  reference?: string
  notes?: string
  attachment: File
}): Promise<SupplierAdvance> {
  const { attachment, ...fields } = payload
  return apiClient
    .post<SupplierAdvance>('/supplier-advances/', buildAdvanceForm(fields, attachment), {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}

export function createTransporterAdvance(payload: {
  transporter: number
  bank_account?: number | null
  cash_account?: number | null
  amount: string
  date: string
  reference?: string
  notes?: string
  attachment: File
}): Promise<TransporterAdvance> {
  const { attachment, ...fields } = payload
  return apiClient
    .post<TransporterAdvance>('/transporter-advances/', buildAdvanceForm(fields, attachment), {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}

export function fetchPartyBalances(partyType: PartyType): Promise<PartyBalance[]> {
  return apiClient
    .get<PartyBalance[]>('/treasury-transactions/party-balances/', {
      params: { debt_type: partyType },
    })
    .then((r) => r.data)
}
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run type-check` (or the project's equivalent `vue-tsc` script — check `package.json` if the exact name differs)
Expected: PASS with no new type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/finance/types.ts frontend/src/modules/purchasing/types.ts frontend/src/modules/finance/api.ts
git commit -m "feat(frontend): add SupplierAdvance/PartyBalance types and advance API client functions"
```

---

## Task 15: `AdvanceForm.vue` component

**Files:**
- Create: `frontend/src/modules/finance/AdvanceForm.vue`
- Create: `frontend/src/modules/finance/__tests__/AdvanceForm.spec.ts`

**Interfaces:**
- Consumes: `fetchPartyBalances`, `createSupplierAdvance`, `createTransporterAdvance` (Task 14), `IMAGE_UPLOAD_ACCEPT`/`isAllowedImageFile` (existing, `@/utils/imageUpload`).
- Produces: `<AdvanceForm :initial-party-type :initial-party-id :lock-party-type :lock-party @success @cancel />` — Tasks 16/17/18 mount this.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/modules/finance/__tests__/AdvanceForm.spec.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdvanceForm from '../AdvanceForm.vue'

const fetchPartyBalances = vi.fn()
const createSupplierAdvance = vi.fn()
const createTransporterAdvance = vi.fn()

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    fetchPartyBalances: (...args: unknown[]) => fetchPartyBalances(...args),
    createSupplierAdvance: (...args: unknown[]) => createSupplierAdvance(...args),
    createTransporterAdvance: (...args: unknown[]) => createTransporterAdvance(...args),
  }
})

vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({
    list: vi.fn(async () => ({
      count: 1, next: null, previous: null,
      results: [{ id: 1, name: 'BIM', current_balance: '500000.00' }],
    })),
  }),
}))

describe('AdvanceForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchPartyBalances.mockResolvedValue([
      { id: 10, label: 'Supplier 1', total_due: '0.00', open_advances: '0.00', net_balance: '0.00', last_advance: null, last_payment: null },
    ])
    createSupplierAdvance.mockResolvedValue({ id: 1 })
    createTransporterAdvance.mockResolvedValue({ id: 1 })
  })

  it('free mode from the journal only lists parties with a non-negative net balance', async () => {
    fetchPartyBalances.mockResolvedValueOnce([
      { id: 10, label: 'Debtor Supplier', total_due: '500000.00', open_advances: '0.00', net_balance: '-500000.00', last_advance: null, last_payment: null },
      { id: 11, label: 'Eligible Supplier', total_due: '0.00', open_advances: '0.00', net_balance: '0.00', last_advance: null, last_payment: null },
    ])
    const wrapper = mount(AdvanceForm)
    await flushPromises()

    const partySelect = wrapper.find('select#party')
    expect(partySelect.text()).toContain('Eligible Supplier')
    expect(partySelect.text()).not.toContain('Debtor Supplier')
  })

  it('locks the party and party type when opened from a ledger page', async () => {
    fetchPartyBalances.mockResolvedValueOnce([
      { id: 11, label: 'Trans A', total_due: '0.00', open_advances: '0.00', net_balance: '0.00', last_advance: null, last_payment: null },
    ])
    const wrapper = mount(AdvanceForm, {
      props: { initialPartyType: 'transporter', initialPartyId: 11, lockPartyType: true, lockParty: true },
    })
    await flushPromises()

    const selects = wrapper.findAll('select')
    expect((selects[0].element as HTMLSelectElement).disabled).toBe(true)
    const partySelect = wrapper.find('select#party')
    expect((partySelect.element as HTMLSelectElement).disabled).toBe(true)
    expect((partySelect.element as HTMLSelectElement).value).toBe('11')
  })

  it('requires an image proof before submitting', async () => {
    const wrapper = mount(AdvanceForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('form').trigger('submit')

    expect(createSupplierAdvance).not.toHaveBeenCalled()
  })

  it('rejects a non-image attachment client-side', async () => {
    const wrapper = mount(AdvanceForm)
    await flushPromises()

    const file = new File(['doc'], 'proof.pdf', { type: 'application/pdf' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('form').trigger('submit')

    expect(createSupplierAdvance).not.toHaveBeenCalled()
  })

  it('submits a supplier advance with the chosen account and attachment', async () => {
    const wrapper = mount(AdvanceForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('300000')
    const file = new File(['receipt'], 'recu.jpg', { type: 'image/jpeg' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createSupplierAdvance).toHaveBeenCalledWith(
      expect.objectContaining({ supplier: 10, amount: '300000', attachment: file }),
    )
    expect(createTransporterAdvance).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/AdvanceForm.spec.ts`
Expected: FAIL — `AdvanceForm.vue` doesn't exist.

- [ ] **Step 3: Implement the component**

Create `frontend/src/modules/finance/AdvanceForm.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { createSupplierAdvance, createTransporterAdvance, fetchPartyBalances } from './api'
import type { PartyBalance, PartyType } from './types'
import { formatMoney } from '@/utils/currency'
import { IMAGE_UPLOAD_ACCEPT, isAllowedImageFile } from '@/utils/imageUpload'

const emit = defineEmits<{
  success: []
  cancel: []
}>()

const props = withDefaults(
  defineProps<{
    initialPartyType?: PartyType
    initialPartyId?: number | null
    lockPartyType?: boolean
    lockParty?: boolean
  }>(),
  {
    initialPartyType: 'supplier',
    initialPartyId: null,
    lockPartyType: false,
    lockParty: false,
  },
)

const { t } = useI18n()

interface AccountOption {
  id: number
  name: string
  current_balance: string
}

const PARTY_TYPES: { value: PartyType; labelKey: string }[] = [
  { value: 'supplier', labelKey: 'finance.debtPayment.types.supplier' },
  { value: 'transporter', labelKey: 'finance.debtPayment.types.transporter' },
]

const bankAccountResource = createResourceApi<AccountOption>('/bank-accounts/')
const cashAccountResource = createResourceApi<AccountOption>('/cash-accounts/')

const partyType = ref<PartyType>(props.initialPartyType)
const partyId = ref('')
const accountKind = ref<'bank' | 'cash'>('bank')
const bankAccountId = ref('')
const cashAccountId = ref('')
const amount = ref('')
const reference = ref('')
const note = ref('')
const attachment = ref<File | null>(null)
const attachmentError = ref('')
const date = ref(new Date().toISOString().slice(0, 10))

function onAttachmentChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (file && !isAllowedImageFile(file)) {
    attachment.value = null
    input.value = ''
    attachmentError.value = t('finance.advanceForm.imageOnlyError')
    return
  }
  attachment.value = file
  attachmentError.value = ''
}

const parties = ref<PartyBalance[]>([])
const banks = ref<AccountOption[]>([])
const cashAccounts = ref<AccountOption[]>([])
const loading = ref(true)
const partyLoading = ref(false)
const saving = ref(false)
const error = ref('')
const emptyPartyMessage = ref('')

const selectedParty = computed(
  () => parties.value.find((party) => party.id === Number(partyId.value)) ?? null,
)
const selectedAccount = computed(() =>
  accountKind.value === 'bank'
    ? (banks.value.find((bank) => bank.id === Number(bankAccountId.value)) ?? null)
    : (cashAccounts.value.find((account) => account.id === Number(cashAccountId.value)) ?? null),
)
const amountNumber = computed(() => Number(amount.value || 0))

async function loadParties() {
  partyLoading.value = true
  error.value = ''
  emptyPartyMessage.value = ''
  partyId.value = ''
  try {
    const fetched = await fetchPartyBalances(partyType.value)
    if (props.lockParty) {
      const lockedParty = fetched.find((party) => party.id === props.initialPartyId)
      parties.value = lockedParty ? [lockedParty] : []
      partyId.value = lockedParty ? String(lockedParty.id) : ''
      if (!lockedParty) {
        error.value = t('finance.advanceForm.errors.partyNotFound')
      }
    } else {
      const eligible = fetched.filter((party) => Number(party.net_balance) >= 0)
      parties.value = eligible
      const initialParty = eligible.find((party) => party.id === props.initialPartyId)
      partyId.value = initialParty
        ? String(initialParty.id)
        : eligible[0]
          ? String(eligible[0].id)
          : ''
      if (!eligible.length) {
        emptyPartyMessage.value = t('finance.advanceForm.errors.noEligibleParty')
      }
    }
  } catch {
    parties.value = []
    partyId.value = ''
    error.value = t('finance.advanceForm.loadError')
  } finally {
    partyLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [bankData, cashData] = await Promise.all([
      bankAccountResource.list(),
      cashAccountResource.list(),
      loadParties(),
    ])
    banks.value = bankData.results
    cashAccounts.value = cashData.results
    bankAccountId.value = banks.value[0]?.id ? String(banks.value[0].id) : ''
    cashAccountId.value = cashAccounts.value[0]?.id ? String(cashAccounts.value[0].id) : ''
  } catch {
    error.value = t('finance.advanceForm.loadError')
  } finally {
    loading.value = false
  }
}

function validate(): boolean {
  error.value = ''
  if (!selectedParty.value) {
    error.value = t('finance.advanceForm.errors.partyRequired')
    return false
  }
  if (!selectedAccount.value) {
    error.value = t('finance.advanceForm.errors.accountRequired')
    return false
  }
  if (amountNumber.value <= 0) {
    error.value = t('finance.advanceForm.errors.positiveAmount')
    return false
  }
  if (amountNumber.value > Number(selectedAccount.value.current_balance)) {
    error.value = t('finance.advanceForm.errors.insufficientBalance')
    return false
  }
  if (!attachment.value) {
    error.value = t('finance.advanceForm.errors.proofRequired')
    return false
  }
  return true
}

async function submit() {
  if (!validate() || !selectedParty.value || !selectedAccount.value || !attachment.value) return
  saving.value = true
  try {
    const payload = {
      bank_account: accountKind.value === 'bank' ? Number(bankAccountId.value) : null,
      cash_account: accountKind.value === 'cash' ? Number(cashAccountId.value) : null,
      amount: amount.value,
      date: date.value,
      reference: reference.value,
      notes: note.value,
      attachment: attachment.value,
    }
    if (partyType.value === 'supplier') {
      await createSupplierAdvance({ supplier: selectedParty.value.id, ...payload })
    } else {
      await createTransporterAdvance({ transporter: selectedParty.value.id, ...payload })
    }
    emit('success')
  } catch (err: unknown) {
    const data = (err as { response?: { data?: Record<string, unknown> } }).response?.data
    const detail =
      (data?.detail as string | undefined) ??
      (Array.isArray(data?.non_field_errors) ? (data!.non_field_errors as string[])[0] : undefined)
    error.value = detail ?? t('finance.advanceForm.saveError')
  } finally {
    saving.value = false
  }
}

watch(partyType, loadParties)
onMounted(load)
</script>

<template>
  <form class="space-y-5" @submit.prevent="submit">
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else>
      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.type') }}</span>
          <select
            v-model="partyType"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
            :disabled="lockPartyType"
          >
            <option v-for="type in PARTY_TYPES" :key="type.value" :value="type.value">
              {{ t(type.labelKey) }}
            </option>
          </select>
        </label>

        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.party') }}</span>
          <select
            id="party"
            v-model="partyId"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
            :disabled="partyLoading || parties.length === 0 || lockParty"
          >
            <option v-for="party in parties" :key="party.id" :value="String(party.id)">
              {{ party.label }}
            </option>
          </select>
          <span v-if="emptyPartyMessage" class="text-texte-3 block text-xs">
            {{ emptyPartyMessage }}
          </span>
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-3">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.accountKind') }}</span>
          <select v-model="accountKind" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm">
            <option value="bank">{{ t('finance.advanceForm.bank') }}</option>
            <option value="cash">{{ t('finance.advanceForm.cash') }}</option>
          </select>
        </label>
        <label v-if="accountKind === 'bank'" class="space-y-1.5 sm:col-span-2">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.bank') }}</span>
          <select v-model="bankAccountId" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm">
            <option v-for="bank in banks" :key="bank.id" :value="String(bank.id)">{{ bank.name }}</option>
          </select>
        </label>
        <label v-else class="space-y-1.5 sm:col-span-2">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.cash') }}</span>
          <select v-model="cashAccountId" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm">
            <option v-for="account in cashAccounts" :key="account.id" :value="String(account.id)">
              {{ account.name }}
            </option>
          </select>
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.amount') }}</span>
          <input
            id="amount"
            v-model="amount"
            min="0.01"
            step="0.01"
            type="number"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          />
        </label>
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.date') }}</span>
          <input v-model="date" type="date" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm" />
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.reference') }}</span>
          <input v-model="reference" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm" />
        </label>
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.note') }}</span>
          <textarea v-model="note" rows="2" class="border-ligne w-full rounded-lg border px-3 py-2 text-sm" />
        </label>
      </div>

      <label class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.attachment') }}</span>
        <input
          type="file"
          required
          :accept="IMAGE_UPLOAD_ACCEPT"
          class="border-ligne w-full rounded-lg border px-3 py-2 text-sm"
          @change="onAttachmentChange"
        />
        <span v-if="attachment" class="text-texte-2 block text-xs">{{ attachment.name }}</span>
        <span v-if="attachmentError" class="text-critique block text-xs">{{ attachmentError }}</span>
      </label>

      <div v-if="selectedAccount" class="border-ligne rounded-lg border bg-sable p-3 text-sm">
        <p class="text-texte-3 text-xs font-medium uppercase">
          {{ t('finance.advanceForm.availableBalance') }}
        </p>
        <MonoValue :value="formatMoney(selectedAccount.current_balance)" align="left" />
      </div>

      <div class="flex justify-end gap-2">
        <Button variant="ghost" type="button" @click="emit('cancel')">{{ t('common.cancel') }}</Button>
        <Button variant="primary" type="submit" :loading="saving">
          {{ t('finance.advanceForm.submit') }}
        </Button>
      </div>
    </template>
  </form>
</template>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/AdvanceForm.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/finance/AdvanceForm.vue frontend/src/modules/finance/__tests__/AdvanceForm.spec.ts
git commit -m "feat(frontend): add AdvanceForm component"
```

---

## Task 16: Wire `TreasuryLedgerView.vue` — `Nouvelle avance` button + deep link

**Files:**
- Modify: `frontend/src/modules/finance/TreasuryLedgerView.vue`
- Create: `frontend/src/modules/finance/__tests__/TreasuryLedgerView.spec.ts`

**Interfaces:**
- Consumes: `AdvanceForm.vue` (Task 15).
- Produces: `Nouvelle avance` button next to `Nouveau paiement`; `?action=advance` opens the same modal `?action=payment` already does.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/modules/finance/__tests__/TreasuryLedgerView.spec.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import TreasuryLedgerView from '../TreasuryLedgerView.vue'

const routeQuery: Record<string, string> = {}
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: routeQuery }),
}))

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    treasuryTransactionResource: {
      list: vi.fn(async () => ({ count: 0, next: null, previous: null, results: [] })),
    },
  }
})

vi.mock('@/modules/dashboard/api', () => ({
  fetchDashboardSummary: vi.fn(async () => ({
    finance: { treasury_balance: '0' },
    bank_amounts: { total: '0' },
    cash_amounts: { total: '0' },
    financial_summary: { period_collections: '0', period_paid_expenses: '0' },
  })),
}))

describe('TreasuryLedgerView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    delete routeQuery.action
  })

  it('shows a Nouvelle avance button next to Nouveau paiement', async () => {
    const wrapper = mount(TreasuryLedgerView)
    await flushPromises()

    const buttons = wrapper.findAll('button').map((button) => button.text())
    expect(buttons).toContain('+ Nouveau paiement')
    expect(buttons).toContain('+ Nouvelle avance')
  })

  it('opens the advance modal when navigated with ?action=advance', async () => {
    routeQuery.action = 'advance'
    const wrapper = mount(TreasuryLedgerView)
    await flushPromises()

    expect(wrapper.findComponent({ name: 'UiModal' }).exists()).toBe(true)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/TreasuryLedgerView.spec.ts`
Expected: FAIL — no `Nouvelle avance` button, `?action=advance` does nothing.

- [ ] **Step 3: Implement**

In `frontend/src/modules/finance/TreasuryLedgerView.vue`:
- Add `import AdvanceForm from './AdvanceForm.vue'`.
- Add `const showAdvanceModal = ref(false)`.
- Add a handler:

```typescript
function onAdvanceSuccess() {
  showAdvanceModal.value = false
  load()
}
```

- In the `onMounted` callback, add a third line:

```typescript
  if (route.query.action === 'advance') showAdvanceModal.value = true
```

- In the template, next to the existing `Nouveau paiement` button:

```html
<Button variant="secondary" @click="showAdvanceModal = true">
  {{ t('finance.treasuryLedger.newAdvance') }}
</Button>
```

- After the existing `showDebtPaymentModal` `<Modal>` block, add:

```html
<Modal
  v-if="showAdvanceModal"
  :title="t('finance.advanceForm.title')"
  max-width="max-w-2xl"
  @close="showAdvanceModal = false"
>
  <AdvanceForm @success="onAdvanceSuccess" @cancel="showAdvanceModal = false" />
</Modal>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/TreasuryLedgerView.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/finance/TreasuryLedgerView.vue frontend/src/modules/finance/__tests__/TreasuryLedgerView.spec.ts
git commit -m "feat(frontend): add Nouvelle avance button to Journal de tresorerie"
```

---

## Task 17: Wire `SupplierLedgerView.vue` — button, cards, entries table

**Files:**
- Modify: `frontend/src/modules/suppliers/SupplierLedgerView.vue`
- Modify: `frontend/src/modules/suppliers/__tests__/SupplierLedgerView.spec.ts`

**Interfaces:**
- Consumes: `AdvanceForm.vue` (Task 15), `ledger.summary`/`ledger.entries` (Task 14 types, Task 10 backend).
- Produces: `Nouvelle avance` button (visible only when `net_balance >= 0`, replacing `Nouveau paiement` which shows only when `net_balance < 0`), 4 summary cards, chronological entries table with internal-modal proof preview.

- [ ] **Step 1: Extend the failing test fixture and add assertions**

In `frontend/src/modules/suppliers/__tests__/SupplierLedgerView.spec.ts`, extend the `ledger` fixture object with:

```typescript
  summary: {
    id: 1, label: 'Total',
    total_due: '0.00', open_advances: '150000.00', net_balance: '150000.00',
    last_advance: { date: '2026-08-20', amount: '150000.00' },
    last_payment: { date: '2026-08-20', amount: '100000.00' },
  },
  entries: [
    { type: 'advance_given', date: '2026-08-15', amount: '150000.00', reference: 'ADV-1', note: '', proof_url: '/media/documents/advance.png' },
    { type: 'debt_created', date: '2026-08-18', amount: '60000000.00', reference: 'ACH-010', note: '', proof_url: null },
    { type: 'payment', date: '2026-08-20', amount: '100000.00', reference: 'PAY-WITH-PROOF', note: '', proof_url: null },
  ],
```

Add two new tests:

```typescript
it('shows the 4 balance cards from summary and a Nouvelle avance button when net_balance >= 0', async () => {
  const wrapper = mount(SupplierLedgerView)
  await flushPromises()

  expect(wrapper.text()).toContain('Total dû')
  expect(wrapper.text()).toContain('Avances ouvertes')
  expect(wrapper.text()).toContain('Solde net')
  const buttons = wrapper.findAll('button').map((button) => button.text())
  expect(buttons).toContain('Nouvelle avance')
  expect(buttons).not.toContain('Enregistrer un paiement')
})

it('renders the chronological entries table and opens a proof in the internal modal', async () => {
  const wrapper = mount(SupplierLedgerView)
  await flushPromises()

  expect(wrapper.text()).toContain('Avance versée')
  expect(wrapper.text()).toContain('Dette créée')
  expect(wrapper.text()).toContain('Paiement complémentaire')

  const proofButtons = wrapper.findAll('button').filter((button) => button.text() === 'Voir justificatif')
  await proofButtons[proofButtons.length - 1].trigger('click')
  await flushPromises()

  expect(wrapper.find('img[src="/media/documents/advance.png"]').exists()).toBe(true)
})
```

(Existing tests keep passing unchanged — `is_advance`/proof-url assertions on `orders`/`payments` are untouched.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/modules/suppliers/__tests__/SupplierLedgerView.spec.ts`
Expected: FAIL — no cards, no button, no entries table yet.

- [ ] **Step 3: Implement**

In `frontend/src/modules/suppliers/SupplierLedgerView.vue`:
- Add `import AdvanceForm from '@/modules/finance/AdvanceForm.vue'`.
- Add `const showAdvanceForm = ref(false)`.
- Add:

```typescript
async function onAdvanceSaved() {
  showAdvanceForm.value = false
  await load()
}
```

- Replace the button row:

```html
<div class="flex gap-2">
  <Button
    v-if="ledger && Number(ledger.summary.net_balance) < 0"
    variant="primary"
    @click="showPaymentForm = true"
  >
    {{ t('finance.supplierPayment.recordPayment') }}
  </Button>
  <Button
    v-if="ledger && Number(ledger.summary.net_balance) >= 0"
    variant="secondary"
    @click="showAdvanceForm = true"
  >
    {{ t('finance.advanceForm.title') }}
  </Button>
  <Button variant="ghost" @click="router.push({ name: 'suppliers' })">
    {{ t('purchasing.supplierLedger.back') }}
  </Button>
</div>
```

- Add a new cards section right after the existing 5-card `<section>` (keep that section untouched):

```html
<section class="grid gap-3 md:grid-cols-4">
  <div class="border-ligne rounded-lg border bg-white p-4">
    <p class="text-texte-2 text-xs font-semibold uppercase">{{ t('finance.partyLedger.totalDue') }}</p>
    <MonoValue class="font-semibold" align="left" :value="formatMoney(ledger.summary.total_due)" />
  </div>
  <div class="border-ligne rounded-lg border bg-white p-4">
    <p class="text-texte-2 text-xs font-semibold uppercase">{{ t('finance.partyLedger.openAdvances') }}</p>
    <MonoValue class="font-semibold" align="left" :value="formatMoney(ledger.summary.open_advances)" />
  </div>
  <div class="border-ligne rounded-lg border bg-white p-4">
    <p class="text-texte-2 text-xs font-semibold uppercase">{{ t('finance.partyLedger.netBalance') }}</p>
    <MonoValue
      class="font-semibold" align="left"
      :class="Number(ledger.summary.net_balance) < 0 ? 'text-critique' : 'text-livre'"
      :value="formatMoney(ledger.summary.net_balance)"
    />
  </div>
  <div class="border-ligne rounded-lg border bg-white p-4">
    <p class="text-texte-2 text-xs font-semibold uppercase">{{ t('finance.partyLedger.lastMovement') }}</p>
    <p class="text-texte text-sm">
      <template v-if="ledger.summary.last_advance">
        {{ t('finance.partyLedger.advance') }}: {{ formatMoney(ledger.summary.last_advance.amount) }}
      </template>
      <template v-else>—</template>
    </p>
    <p class="text-texte text-sm">
      <template v-if="ledger.summary.last_payment">
        {{ t('finance.partyLedger.payment') }}: {{ formatMoney(ledger.summary.last_payment.amount) }}
      </template>
      <template v-else>—</template>
    </p>
  </div>
</section>
```

- Add a new `<Card>` for the entries table, after the existing "Paiements & avances" card:

```html
<Card :title="t('finance.partyLedger.entriesTitle')">
  <table class="w-full text-start text-sm">
    <thead>
      <tr class="border-ligne text-texte-2 border-b">
        <th class="px-3 py-2.5 font-medium">{{ t('finance.partyLedger.table.date') }}</th>
        <th class="px-3 py-2.5 font-medium">{{ t('finance.partyLedger.table.type') }}</th>
        <th class="px-3 py-2.5 font-medium">{{ t('finance.partyLedger.table.reference') }}</th>
        <th class="px-3 py-2.5 text-end font-medium">{{ t('finance.partyLedger.table.amount') }}</th>
        <th class="px-3 py-2.5 font-medium">{{ t('finance.partyLedger.table.proof') }}</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="(entry, index) in ledger.entries" :key="index" class="border-ligne border-b last:border-0">
        <td class="px-3 py-2.5">{{ entry.date }}</td>
        <td class="px-3 py-2.5">{{ t(`finance.partyLedger.entryTypes.${entry.type}`) }}</td>
        <td class="px-3 py-2.5">{{ entry.reference || '—' }}</td>
        <td class="px-3 py-2.5 text-end"><MonoValue :value="formatMoney(entry.amount)" /></td>
        <td class="px-3 py-2.5">
          <button
            v-if="entry.proof_url"
            type="button"
            class="text-bitume underline"
            @click="previewUrl = entry.proof_url"
          >
            {{ t('purchasing.supplierLedger.viewProof') }}
          </button>
          <span v-else class="text-texte-3">—</span>
        </td>
      </tr>
      <tr v-if="ledger.entries.length === 0">
        <td colspan="5" class="text-texte-3 px-3 py-8 text-center">{{ t('finance.partyLedger.noEntries') }}</td>
      </tr>
    </tbody>
  </table>
</Card>
```

- Add the `AdvanceForm` modal, next to the existing `showPaymentForm` modal:

```html
<Modal
  v-if="showAdvanceForm && ledger"
  :title="t('finance.advanceForm.title')"
  max-width="max-w-2xl"
  @close="showAdvanceForm = false"
>
  <AdvanceForm
    initial-party-type="supplier"
    :initial-party-id="ledger.supplier.id"
    lock-party-type
    lock-party
    @success="onAdvanceSaved"
    @cancel="showAdvanceForm = false"
  />
</Modal>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/suppliers/__tests__/SupplierLedgerView.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/suppliers/SupplierLedgerView.vue frontend/src/modules/suppliers/__tests__/SupplierLedgerView.spec.ts
git commit -m "feat(frontend): add advance button, balance cards, entries table to SupplierLedgerView"
```

---

## Task 18: Wire `TransporterLedgerView.vue` — button, cards, entries table

**Files:**
- Modify: `frontend/src/modules/finance/TransporterLedgerView.vue`
- Create: `frontend/src/modules/finance/__tests__/TransporterLedgerView.spec.ts`

**Interfaces:**
- Consumes: `AdvanceForm.vue` (Task 15), `ledger.summary`/`ledger.entries` (Task 14/10).
- Produces: same button/cards/entries pattern as Task 17, mirrored for transporters.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/modules/finance/__tests__/TransporterLedgerView.spec.ts`, mirroring `SupplierLedgerView.spec.ts`'s fixture style:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import TransporterLedgerView from '../TransporterLedgerView.vue'
import type { TransporterLedger } from '../types'

const push = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '1' } }),
  useRouter: () => ({ push }),
}))

const ledger: TransporterLedger = {
  transporter: { id: 1, name: 'Trans SA', company_name: '' },
  gross_amount: '700000.00',
  deductions: '0.00',
  advances_applied: '100000.00',
  settled: '0.00',
  net_outstanding: '600000.00',
  unsettled_advances: '0.00',
  payments: [
    {
      id: 1, trip: 1, trip_reference: 'TRIP-001', transporter: 1, transporter_detail: null,
      calculation_method: 'FIXED', base_amount: '700000.00', unit_price_per_litre: null,
      deduction_amount: '0.00', advance_applied: null, net_amount: '600000.00', status: 'PAYABLE',
      created_at: '', updated_at: '',
    },
  ],
  advances: [
    {
      id: 1, transporter: 1, transporter_detail: null, bank_account: null, cash_account: 1,
      amount: '100000.00', date: '2026-08-17', reference: 'TADV-1', notes: '',
      proof_url: null, remaining_amount: '0.00', settled: true, created_at: '', updated_at: '',
    },
  ],
  summary: {
    id: 1, label: 'Trans SA',
    total_due: '600000.00', open_advances: '0.00', net_balance: '-600000.00',
    last_advance: { date: '2026-08-17', amount: '100000.00' },
    last_payment: null,
  },
  entries: [
    { type: 'advance_given', date: '2026-08-17', amount: '100000.00', reference: 'TADV-1', note: '', proof_url: null },
    { type: 'debt_created', date: '2026-08-18', amount: '700000.00', reference: 'TRIP-001', note: '', proof_url: null },
    { type: 'advance_consumed', date: '2026-08-18', amount: '100000.00', reference: 'TADV-1', note: '', proof_url: null },
  ],
}

const fetchTransporterLedger = vi.fn(async () => ledger)

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return { ...actual, fetchTransporterLedger: (...args: unknown[]) => fetchTransporterLedger(...(args as [])) }
})

describe('TransporterLedgerView', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows a Nouvelle avance button (not Nouveau paiement) when net_balance is negative and there IS an open debt', async () => {
    // net_balance < 0 means a real debt is owed -> Nouveau paiement, not Nouvelle avance
    const wrapper = mount(TransporterLedgerView)
    await flushPromises()

    const buttons = wrapper.findAll('button').map((button) => button.text())
    expect(buttons).toContain('Enregistrer un paiement')
    expect(buttons).not.toContain('Nouvelle avance')
  })

  it('shows the 4 balance cards and the chronological entries table', async () => {
    const wrapper = mount(TransporterLedgerView)
    await flushPromises()

    expect(wrapper.text()).toContain('Total dû')
    expect(wrapper.text()).toContain('Avances ouvertes')
    expect(wrapper.text()).toContain('Solde net')
    expect(wrapper.text()).toContain('Avance versée')
    expect(wrapper.text()).toContain('Dette créée')
    expect(wrapper.text()).toContain('Avance imputée')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/TransporterLedgerView.spec.ts`
Expected: FAIL — no cards, no entries table, button always says "Enregistrer un paiement" already so the first assertion may pass but the second test fails.

- [ ] **Step 3: Implement**

Mirror Task 17's edits in `frontend/src/modules/finance/TransporterLedgerView.vue`:
- Add `import AdvanceForm from './AdvanceForm.vue'`, `const showAdvanceForm = ref(false)`, and `onAdvanceSaved`.
- Replace the button row (currently always showing `Nouveau paiement`) with the same `net_balance`-conditioned pair as Task 17, using `t('finance.transporterLedger.newPayment')` for the payment button (existing key) and `t('finance.advanceForm.title')` for the advance button.
- Add the same 4-card section (`finance.partyLedger.*` keys — shared with Task 17, no new keys needed here).
- Add the same entries table (`finance.partyLedger.entriesTitle`/`table.*`/`entryTypes.*`).
- Add the `AdvanceForm` modal, locked with `initial-party-type="transporter"` and `:initial-party-id="ledger.transporter.id"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/TransporterLedgerView.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/finance/TransporterLedgerView.vue frontend/src/modules/finance/__tests__/TransporterLedgerView.spec.ts
git commit -m "feat(frontend): add advance button, balance cards, entries table to TransporterLedgerView"
```

---

## Task 19: Dashboard — `net_balance` labels for Fournisseurs/Transporteurs cards

**Files:**
- Modify: `frontend/src/modules/dashboard/DashboardView.vue`
- Modify: `frontend/src/modules/dashboard/__tests__/DashboardView.spec.ts`

**Interfaces:**
- Consumes: `party_balances.suppliers.balance`/`transporters.balance` now carrying `net_balance` (Task 11).
- Produces: sub-label reads "Dette à payer" (negative) / "Avance disponible" (positive) / "Aucun solde ouvert" (zero); card amount styling (`negative` class) now sign-correct for these two cards instead of hardcoded false.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/modules/dashboard/__tests__/DashboardView.spec.ts` (reusing the existing `summary` fixture and `makeRouter()` helper already defined in that file):

```typescript
it('labels supplier/transporter balances by sign: dette a payer, avance disponible, aucun solde ouvert', async () => {
  const router = makeRouter()
  fetchDashboardSummary.mockResolvedValueOnce({
    ...summary,
    party_balances: {
      ...summary.party_balances,
      suppliers: { balance: '-500000.00', open_count: 1, largest_open: null },
      transporters: { balance: '300000.00', open_count: 0, largest_open: null },
    },
  })
  const wrapper = mount(DashboardView, { global: { plugins: [router] } })
  await flushPromises()

  const cards = wrapper.findAll('[data-test="party-balance-card"]')
  const supplierCard = cards.find((card) => card.text().includes('Fournisseurs'))!
  const transporterCard = cards.find((card) => card.text().includes('Transporteurs'))!
  expect(supplierCard.text()).toContain('Dette à payer')
  expect(transporterCard.text()).toContain('Avance disponible')
  expect(supplierCard.find('[data-test="party-balance-amount"]').classes()).toContain('text-critique')
})

it('shows "aucun solde ouvert" when a party has net_balance exactly zero', async () => {
  const router = makeRouter()
  fetchDashboardSummary.mockResolvedValueOnce({
    ...summary,
    party_balances: {
      ...summary.party_balances,
      suppliers: { balance: '0.00', open_count: 0, largest_open: null },
    },
  })
  const wrapper = mount(DashboardView, { global: { plugins: [router] } })
  await flushPromises()

  const cards = wrapper.findAll('[data-test="party-balance-card"]')
  const supplierCard = cards.find((card) => card.text().includes('Fournisseurs'))!
  expect(supplierCard.text()).toContain('Aucun solde ouvert')
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/modules/dashboard/__tests__/DashboardView.spec.ts -t "dette a payer|aucun solde"`
Expected: FAIL — today's `sub` text for suppliers/transporters is "Plus gros impayé"/"Rien à régler", and `negative` is hardcoded `false` for every party card.

- [ ] **Step 3: Implement**

In `frontend/src/modules/dashboard/DashboardView.vue`, replace the `partyCards` computed (lines ~200-259):

```typescript
const partyCards = computed(() => {
  if (!summary.value) return []
  const p = summary.value.party_balances

  function partySub(balance: string) {
    const value = Number(balance)
    if (value < 0) return t('dashboard.final.debtToPay')
    if (value > 0) return t('dashboard.final.advanceAvailable')
    return t('dashboard.final.noOpenBalance')
  }

  return [
    {
      label: t('dashboard.final.customers'),
      to: { name: 'customers' },
      balance: p.customers.balance,
      detail: t('dashboard.final.openCustomers', { count: p.customers.open_count }),
      sub: p.customers.largest_open
        ? t('dashboard.final.largestCustomerDebt', { name: p.customers.largest_open.name })
        : t('dashboard.final.nothingToSettle'),
      icon: 'users' as IconName,
      negative: false,
    },
    {
      label: t('dashboard.final.suppliers'),
      to: { name: 'suppliers' },
      balance: p.suppliers.balance,
      detail: t('dashboard.final.openSuppliers', { count: p.suppliers.open_count }),
      sub: partySub(p.suppliers.balance),
      icon: 'package' as IconName,
      negative: Number(p.suppliers.balance) < 0,
    },
    {
      label: t('dashboard.final.transporters'),
      to: { name: 'transporters' },
      balance: p.transporters.balance,
      detail: t('dashboard.final.openTransporters', { count: p.transporters.open_count }),
      sub: partySub(p.transporters.balance),
      icon: 'truck' as IconName,
      negative: Number(p.transporters.balance) < 0,
    },
    {
      label: t('dashboard.final.shareholders'),
      to: { name: 'shareholders' },
      balance: p.shareholders.balance,
      detail: t('dashboard.final.withdrawn', { amount: formatMoney(p.shareholders.total_withdrawn) }),
      sub: t('dashboard.final.openLoans', { amount: formatMoney(p.shareholders.open_loans_total) }),
      icon: 'pie-chart' as IconName,
      negative: false,
    },
    {
      label: t('dashboard.final.customsAndOther'),
      to: { name: 'treasury-transactions' },
      balance: p.customs_and_other.balance,
      detail: t('dashboard.final.customs', { amount: formatMoney(p.customs_and_other.customs) }),
      sub: t('dashboard.final.roadTransit', { amount: formatMoney(p.customs_and_other.road_transit) }),
      icon: 'shield' as IconName,
      negative: false,
    },
  ].map((card) => ({
    ...card,
    balanceParts: formatMoneyParts(card.balance),
  }))
})
```

(The key change from today's version: the final `.map()` no longer forces `negative: false` on every card — each card object now sets its own `negative`, computed correctly for suppliers/transporters and preserved as `false` for the three untouched cards.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/modules/dashboard/__tests__/DashboardView.spec.ts`
Expected: PASS (full file, confirming the pre-existing tests — which use the base fixture's negative supplier/transporter balances — still render correctly).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/dashboard/DashboardView.vue frontend/src/modules/dashboard/__tests__/DashboardView.spec.ts
git commit -m "feat(frontend): label Fournisseurs/Transporteurs dashboard cards by net_balance sign"
```

---

## Task 20: i18n keys (fr / en / ar)

**Files:**
- Modify: `frontend/src/locales/fr.json`
- Modify: `frontend/src/locales/en.json`
- Modify: `frontend/src/locales/ar.json`

**Interfaces:**
- Consumes: nothing (pure content addition).
- Produces: every `t('finance.advanceForm.*')`, `t('finance.partyLedger.*')`, `t('finance.treasuryLedger.newAdvance')`, `t('dashboard.final.debtToPay'|'advanceAvailable'|'noOpenBalance')` key referenced by Tasks 15-19. Since the three locale files are structurally parallel (verified: identical line numbers for `dashboard.final`, `finance.debtPayment`, `finance.transporterLedger`, `purchasing.supplierLedger` blocks), each insertion below goes at the same relative position in all three files.

- [ ] **Step 1: This task has no separate test — it satisfies assertions already written in Tasks 15-19's specs**

Run: `cd frontend && npx vitest run` (full suite) once Step 2 is done, to confirm every French-text assertion from earlier tasks now passes for real (some may have coincidentally passed already if you ran individual files with stubbed `t()` — running the full i18n-aware suite is the real check here).

- [ ] **Step 2: Add keys to `frontend/src/locales/fr.json`**

Inside the `finance` object, immediately after the `debtPayment` block closes (after line ~732, i.e. right after `}` that closes `debtPayment` and before `"shareholder": {`), insert:

```json
    "advanceForm": {
      "title": "Nouvelle avance",
      "type": "Type de tiers",
      "party": "Tiers",
      "accountKind": "Type de compte",
      "bank": "Banque",
      "cash": "Caisse",
      "amount": "Montant de l'avance",
      "date": "Date",
      "reference": "Référence",
      "note": "Note",
      "attachment": "Justificatif (image)",
      "availableBalance": "Solde disponible",
      "submit": "Enregistrer l'avance",
      "imageOnlyError": "Seules les images JPG, JPEG, PNG ou WEBP sont autorisées.",
      "loadError": "Impossible de charger les tiers éligibles.",
      "saveError": "Impossible d'enregistrer cette avance.",
      "errors": {
        "partyRequired": "Choisissez un tiers.",
        "accountRequired": "Choisissez un compte.",
        "positiveAmount": "Le montant doit être supérieur à zéro.",
        "insufficientBalance": "Solde insuffisant pour cette avance.",
        "proofRequired": "Un justificatif image est obligatoire pour enregistrer cette avance.",
        "partyNotFound": "Aucun tiers éligible trouvé.",
        "noEligibleParty": "Aucun tiers éligible pour une nouvelle avance."
      }
    },
    "partyLedger": {
      "totalDue": "Total dû",
      "openAdvances": "Avances ouvertes",
      "netBalance": "Solde net",
      "lastMovement": "Dernière avance / dernier paiement",
      "advance": "Avance",
      "payment": "Paiement",
      "entriesTitle": "Historique",
      "noEntries": "Aucun mouvement.",
      "table": {
        "date": "Date",
        "type": "Type",
        "reference": "Référence",
        "amount": "Montant",
        "proof": "Justificatif"
      },
      "entryTypes": {
        "advance_given": "Avance versée",
        "debt_created": "Dette créée",
        "advance_consumed": "Avance imputée",
        "payment": "Paiement complémentaire"
      }
    },
```

Inside `finance.treasuryLedger` (around line 672-689), add one key alongside `newPayment`:

```json
      "newAdvance": "+ Nouvelle avance",
```

Inside `dashboard.final` (around line 112-142), add three keys alongside `nothingToSettle`:

```json
      "debtToPay": "Dette à payer",
      "advanceAvailable": "Avance disponible",
      "noOpenBalance": "Aucun solde ouvert",
```

- [ ] **Step 3: Mirror the same insertions in `frontend/src/locales/en.json`**

Same structure, same nesting, at the same relative position (line numbers are parallel across the three files):

```json
    "advanceForm": {
      "title": "New advance",
      "type": "Party type",
      "party": "Party",
      "accountKind": "Account type",
      "bank": "Bank",
      "cash": "Cash",
      "amount": "Advance amount",
      "date": "Date",
      "reference": "Reference",
      "note": "Note",
      "attachment": "Proof (image)",
      "availableBalance": "Available balance",
      "submit": "Save advance",
      "imageOnlyError": "Only JPG, JPEG, PNG or WEBP images are allowed.",
      "loadError": "Unable to load eligible parties.",
      "saveError": "Unable to save this advance.",
      "errors": {
        "partyRequired": "Choose a party.",
        "accountRequired": "Choose an account.",
        "positiveAmount": "The amount must be greater than zero.",
        "insufficientBalance": "Insufficient balance for this advance.",
        "proofRequired": "An image proof is required to save this advance.",
        "partyNotFound": "No eligible party found.",
        "noEligibleParty": "No party eligible for a new advance."
      }
    },
    "partyLedger": {
      "totalDue": "Total due",
      "openAdvances": "Open advances",
      "netBalance": "Net balance",
      "lastMovement": "Last advance / last payment",
      "advance": "Advance",
      "payment": "Payment",
      "entriesTitle": "History",
      "noEntries": "No movement.",
      "table": {
        "date": "Date",
        "type": "Type",
        "reference": "Reference",
        "amount": "Amount",
        "proof": "Proof"
      },
      "entryTypes": {
        "advance_given": "Advance given",
        "debt_created": "Debt created",
        "advance_consumed": "Advance applied",
        "payment": "Additional payment"
      }
    },
```

`treasuryLedger.newAdvance`: `"+ New advance"`. `dashboard.final`: `"debtToPay": "Debt to pay"`, `"advanceAvailable": "Advance available"`, `"noOpenBalance": "No open balance"`.

- [ ] **Step 4: Mirror the same insertions in `frontend/src/locales/ar.json`**

```json
    "advanceForm": {
      "title": "سلفة جديدة",
      "type": "نوع الطرف",
      "party": "الطرف",
      "accountKind": "نوع الحساب",
      "bank": "بنك",
      "cash": "نقدية",
      "amount": "مبلغ السلفة",
      "date": "التاريخ",
      "reference": "المرجع",
      "note": "ملاحظة",
      "attachment": "المستند المرفق (صورة)",
      "availableBalance": "الرصيد المتاح",
      "submit": "حفظ السلفة",
      "imageOnlyError": "يُسمح فقط بصور JPG أو JPEG أو PNG أو WEBP.",
      "loadError": "تعذر تحميل الأطراف المؤهلة.",
      "saveError": "تعذر حفظ هذه السلفة.",
      "errors": {
        "partyRequired": "اختر طرفًا.",
        "accountRequired": "اختر حسابًا.",
        "positiveAmount": "يجب أن يكون المبلغ أكبر من الصفر.",
        "insufficientBalance": "الرصيد غير كافٍ لهذه السلفة.",
        "proofRequired": "المستند المرفق (صورة) إلزامي لحفظ هذه السلفة.",
        "partyNotFound": "لم يتم العثور على طرف مؤهل.",
        "noEligibleParty": "لا يوجد طرف مؤهل لسلفة جديدة."
      }
    },
    "partyLedger": {
      "totalDue": "إجمالي المستحق",
      "openAdvances": "السلف المفتوحة",
      "netBalance": "الرصيد الصافي",
      "lastMovement": "آخر سلفة / آخر دفعة",
      "advance": "سلفة",
      "payment": "دفعة",
      "entriesTitle": "السجل",
      "noEntries": "لا توجد حركة.",
      "table": {
        "date": "التاريخ",
        "type": "النوع",
        "reference": "المرجع",
        "amount": "المبلغ",
        "proof": "المستند"
      },
      "entryTypes": {
        "advance_given": "سلفة مدفوعة",
        "debt_created": "دين مستحق",
        "advance_consumed": "سلفة مخصومة",
        "payment": "دفعة تكميلية"
      }
    },
```

`treasuryLedger.newAdvance`: `"+ سلفة جديدة"`. `dashboard.final`: `"debtToPay": "دين مستحق الدفع"`, `"advanceAvailable": "سلفة متاحة"`, `"noOpenBalance": "لا يوجد رصيد مفتوح"`.

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: PASS — every test from Tasks 15-19 that asserted on French UI text now passes for real; `npm run type-check` (or project equivalent) still clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json
git commit -m "feat(i18n): add advanceForm/partyLedger/dashboard translation keys (fr/en/ar)"
```

---

## Self-Review

**Spec coverage:**
- Modèle avance (mirroir + service commun) → Tasks 1-2.
- Consommation FIFO auto pour les deux tiers, réversion `CONFIRMED→CANCELLED` → Tasks 3-4.
- Migration `is_advance` legacy, blocage nouvelles créations → Task 12.
- Trésorerie (1 transaction création, 0 consommation) → Task 6.
- Non-impact bénéfice → Task 13 (pinning test) + design invariant baked into Tasks 1-6 (no model ever referenced by `TripProfitService`).
- `describe_supplier_balance`/`describe_transporter_balance` source unique → Task 5, consumed by Tasks 6/8/9/10/11.
- Endpoints `/api/supplier-advances/`, extended `/api/transporter-advances/`, `party-balances` → Tasks 7-8.
- Correction `SupplierOutstandingReportQuery` → Task 9.
- Grand livre (`summary`+`entries`, 4 types de lignes) → Task 10.
- Dashboard `net_balance` + libellés tri-état → Tasks 11 (backend) + 19 (frontend).
- `AdvanceForm.vue` (libre/verrouillé), boutons Journal/Grands livres, justificatif obligatoire image → Tasks 15-18.
- i18n fr/en/ar → Task 20.

**Placeholder scan:** none remaining — every step has real code/real test bodies; the one stray placeholder line introduced mid-draft in Task 2 was corrected in place.

**Type consistency:** `AdvanceConsumptionService` method names (`consume_for_supplier_order`, `reverse_for_supplier_order`, `consume_for_transport_payment`, `get_consumed_amount`, `open_supplier_advances`, `open_transporter_advances`) are used identically across Tasks 2/3/4/5/10. `describe_supplier_balance`/`describe_transporter_balance`'s return shape (`total_due`, `open_advances`, `net_balance`, `last_advance`, `last_payment`) is used identically across Tasks 5/6/8/10/11 and mirrored exactly in the frontend `PartyBalance` type (Task 14). `LedgerEntry`'s `{type, date, amount, reference, note, proof_url}` shape is produced identically by both `SupplierLedgerService`/`TransporterLedgerService` (Task 10) and consumed identically by both ledger views (Tasks 17/18).


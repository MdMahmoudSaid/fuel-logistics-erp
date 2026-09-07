# Facture client = quantité reçue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La facture client reflète la quantité réellement reçue (pas la quantité chargée), et les termes correctifs « perte supportée par l'entreprise » disparaissent de la marge et du distribuable (ils faisaient double emploi).

**Architecture:** `DeliveryService.record_client_verification` propage la quantité corrigée à `Sale` + `Invoice` via une nouvelle méthode `InvoiceService.adjust_delivered_quantity` (brouillon → modif directe, validée → `InvoiceCorrection` auditée, payée → refus). Une fois `revenue` basé sur la quantité reçue, `TripProfitService.get_cost_breakdown` et `ShareholderProfitPreviewService.get_preview` retirent leur soustraction explicite de `company_absorbed_loss` (double comptage). Les ajouts d'affichage du "point 1" (session courante) sont défaits. Le grand livre client et l'écran facture gagnent les quantités chargée/reçue côte à côte.

**Tech Stack:** Django + DRF (backend `backend/`, pytest, PostgreSQL), Vue 3 + TypeScript + Vitest (frontend `frontend/`), reportlab (PDF).

**Spec:** `docs/superpowers/specs/2026-09-07-facture-quantite-recue-design.md`

## Global Constraints

- Tests backend : `docker compose exec -T backend python -m pytest <path> -q`. La 1ʳᵉ exécution après un changement de schéma/données nécessite `--create-db` une fois (staleness `--reuse-db` connue dans cet env, sinon `Role.DoesNotExist`).
- Tests frontend : `cd frontend && npx vitest run <path>`. Typecheck : `npx vue-tsc --noEmit -p tsconfig.app.json` (une erreur pré-existante `ProfitView.spec.ts(22)` à ignorer, non liée).
- Messages de commit : terminer par `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Branche de travail : `feature/facture-quantite-recue` (déjà créée, spec déjà committée dessus). Ne pas committer sur `main`.
- i18n : 3 locales `fr` / `en` / `ar` — toute nouvelle clé va dans les 3 fichiers `frontend/src/locales/{fr,en,ar}.json`.
- Montants : `Decimal` partout côté backend ; `Sale.save()` recalcule `subtotal = delivered_quantity × unit_selling_price` quantizé à `0.01`.
- Ne PAS toucher : `record_delivery`, `DeliveryControlForm.vue`, `sync_transport_shortage_deduction`, `CustomerOrderService`, le moteur de coût `TripCostService`. Pas de migration de données rétro.
- `apps.trips.services` importe déjà `from apps.sales.services import CustomerOrderService` au niveau module — ajouter `InvoiceService` à cette ligne est sûr (pas de cycle : `apps.sales.services` n'importe que `apps.sales.models`).

---

## Task 1 : `InvoiceService.adjust_delivered_quantity`

**Files:**
- Modify: `backend/apps/sales/services.py` (classe `InvoiceService`, ~ligne 121 ; exceptions ~ligne 104)
- Test: `backend/apps/sales/tests.py`

**Interfaces:**
- Consumes: `Invoice`, `Sale`, `InvoiceCorrection` (déjà importés en tête de `apps/sales/services.py`).
- Produces:
  - `InvoiceService.adjust_delivered_quantity(invoice_id: int, new_quantity: Decimal, *, reason: str, actor) -> Invoice`
  - `InvoicePaidCorrectionUnsupported(ValueError)` — levée quand la facture est `PARTIALLY_PAID` / `PAID` / `CANCELLED`.

- [ ] **Step 1: Write the failing tests**

Ajouter à `backend/apps/sales/tests.py` (vérifier les helpers existants en tête du fichier ; sinon réutiliser le pattern de `_make_delivered_trip_with_sale` de `apps/reports/tests.py` en l'important, ou créer un helper local `_sale_with_invoice(status)` qui crée `Trip` minimal + `Sale(delivered_quantity=45000, unit_selling_price=900)` + `Invoice(sale=sale, total_amount=sale.subtotal, status=status, invoice_number=..., issued_date="2026-08-18")`).

```python
from decimal import Decimal
import pytest
from apps.sales.models import Invoice, InvoiceCorrection
from apps.sales.services import (
    InvoiceService,
    InvoicePaidCorrectionUnsupported,
)


@pytest.mark.django_db
def test_adjust_delivered_quantity_draft_edits_directly_no_correction_row():
    sale, invoice = _sale_with_invoice(Invoice.Status.DRAFT)  # 45000 L x 900 = 40,500,000

    result = InvoiceService.adjust_delivered_quantity(
        invoice.id, Decimal("44800.00"), reason="Vérification client", actor=_actor()
    )

    sale.refresh_from_db()
    result.refresh_from_db()
    assert sale.delivered_quantity == Decimal("44800.00")
    assert sale.subtotal == Decimal("40320000.00")
    assert result.total_amount == Decimal("40320000.00")
    assert InvoiceCorrection.objects.filter(invoice=invoice).count() == 0


@pytest.mark.django_db
def test_adjust_delivered_quantity_validated_writes_correction_row():
    sale, invoice = _sale_with_invoice(Invoice.Status.VALIDATED)

    InvoiceService.adjust_delivered_quantity(
        invoice.id, Decimal("44800.00"),
        reason="Vérification client : quantité reçue corrigée de 45000.00 L à 44800.00 L",
        actor=_actor(),
    )

    sale.refresh_from_db()
    invoice.refresh_from_db()
    assert sale.delivered_quantity == Decimal("44800.00")
    assert invoice.total_amount == Decimal("40320000.00")
    correction = InvoiceCorrection.objects.get(invoice=invoice)
    assert correction.field_name == "delivered_quantity"
    assert correction.previous_value == "45000.00"
    assert correction.new_value == "44800.00"
    assert "Vérification client" in correction.reason


@pytest.mark.django_db
@pytest.mark.parametrize("status", [Invoice.Status.PARTIALLY_PAID, Invoice.Status.PAID])
def test_adjust_delivered_quantity_paid_is_refused(status):
    sale, invoice = _sale_with_invoice(status)

    with pytest.raises(InvoicePaidCorrectionUnsupported):
        InvoiceService.adjust_delivered_quantity(
            invoice.id, Decimal("44800.00"), reason="x", actor=_actor()
        )

    sale.refresh_from_db()
    assert sale.delivered_quantity == Decimal("45000.00")


@pytest.mark.django_db
def test_adjust_delivered_quantity_noop_when_unchanged():
    sale, invoice = _sale_with_invoice(Invoice.Status.VALIDATED)

    InvoiceService.adjust_delivered_quantity(
        invoice.id, Decimal("45000.00"), reason="x", actor=_actor()
    )

    assert InvoiceCorrection.objects.filter(invoice=invoice).count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest apps/sales/tests.py -k adjust_delivered_quantity --create-db -q`
Expected: FAIL — `ImportError: cannot import name 'InvoicePaidCorrectionUnsupported'` / `AttributeError: adjust_delivered_quantity`.

- [ ] **Step 3: Add the exception class**

Dans `backend/apps/sales/services.py`, après `class UnsupportedCorrectionField(ValueError):` (~ligne 116) :

```python
class InvoicePaidCorrectionUnsupported(ValueError):
    """Raised when a delivered-quantity adjustment is attempted on an
    invoice that is already (partially) paid or cancelled - reducing it
    would create a customer overpayment/credit, which has no automated
    handling yet (spec 2026-09-07). The operator must resolve the payment
    situation manually first."""
```

- [ ] **Step 4: Add the method**

Dans `class InvoiceService`, après `correct_invoice` :

```python
    @staticmethod
    @transaction.atomic
    def adjust_delivered_quantity(invoice_id, new_quantity, *, reason, actor) -> Invoice:
        """Set an invoice's billed quantity to `new_quantity` (the quantity
        the client actually received - spec 2026-09-07). Sole owner of a
        post-creation Sale.delivered_quantity mutation.

        DRAFT      -> Sale + Invoice edited directly, no audit row.
        VALIDATED  -> same, plus an InvoiceCorrection row.
        (PARTIALLY_)PAID / CANCELLED -> InvoicePaidCorrectionUnsupported.
        No-op if new_quantity already equals the current delivered_quantity.
        """
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
        sale = invoice.sale
        new_quantity = Decimal(str(new_quantity))

        if new_quantity == sale.delivered_quantity:
            return invoice

        if invoice.status in (
            Invoice.Status.PARTIALLY_PAID,
            Invoice.Status.PAID,
            Invoice.Status.CANCELLED,
        ):
            raise InvoicePaidCorrectionUnsupported(
                f"La facture {invoice.invoice_number} est {invoice.status} ; "
                "la correction de la quantité d'une facture encaissée ou "
                "annulée n'est pas prise en charge automatiquement."
            )

        previous_value = str(sale.delivered_quantity)
        sale.delivered_quantity = new_quantity
        sale.save()  # recomputes subtotal via Sale.save()
        invoice.total_amount = sale.subtotal
        invoice.save(update_fields=["total_amount", "updated_at"])

        if invoice.status == Invoice.Status.VALIDATED:
            InvoiceCorrection.objects.create(
                invoice=invoice,
                field_name="delivered_quantity",
                previous_value=previous_value,
                new_value=str(new_quantity),
                corrected_by=actor,
                reason=reason,
            )
        return invoice
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest apps/sales/tests.py -k adjust_delivered_quantity -q`
Expected: PASS (5 cases incl. parametrize).

- [ ] **Step 6: Commit**

```bash
git add backend/apps/sales/services.py backend/apps/sales/tests.py
git commit -m "feat(sales): InvoiceService.adjust_delivered_quantity for received-qty billing

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 2 : `correct_invoice` accepte `delivered_quantity`

**Files:**
- Modify: `backend/apps/sales/services.py` (`InvoiceService.correct_invoice`, ~ligne 147-187)
- Test: `backend/apps/sales/tests.py`

**Interfaces:**
- Consumes: `InvoiceService.correct_invoice(invoice_id, field, new_value, reason, actor)` (existant).
- Produces: `field == "delivered_quantity"` désormais accepté (VALIDATED-only, comme les autres) → écrit `Sale.delivered_quantity`, recalcule `Invoice.total_amount`, ligne `InvoiceCorrection`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_correct_invoice_supports_delivered_quantity_field():
    sale, invoice = _sale_with_invoice(Invoice.Status.VALIDATED)  # 45000 x 900

    InvoiceService.correct_invoice(
        invoice.id, "delivered_quantity", "44750.00",
        reason="Client conteste 250 L", actor=_actor(),
    )

    sale.refresh_from_db()
    invoice.refresh_from_db()
    assert sale.delivered_quantity == Decimal("44750.00")
    assert invoice.total_amount == Decimal("40275000.00")
    correction = InvoiceCorrection.objects.get(invoice=invoice, field_name="delivered_quantity")
    assert correction.previous_value == "45000.00"
    assert correction.new_value == "44750.00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest apps/sales/tests.py::test_correct_invoice_supports_delivered_quantity_field --create-db -q`
Expected: FAIL — `UnsupportedCorrectionField: 'delivered_quantity' is not a correctable invoice field.`

- [ ] **Step 3: Add the branch**

Dans `correct_invoice`, entre la branche `unit_selling_price` et la branche `total_amount` :

```python
        elif field == "delivered_quantity":
            previous_value = str(sale.delivered_quantity)
            sale.delivered_quantity = Decimal(str(new_value))
            sale.save()  # recomputes subtotal via Sale.save()
            invoice.total_amount = sale.subtotal
            invoice.save(update_fields=["total_amount", "updated_at"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T backend python -m pytest apps/sales/tests.py::test_correct_invoice_supports_delivered_quantity_field -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/sales/services.py backend/apps/sales/tests.py
git commit -m "feat(sales): allow delivered_quantity as a correctable invoice field

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 3 : `record_client_verification` propage la quantité à la facture

**Files:**
- Modify: `backend/apps/trips/services.py` (import ~ligne 23 ; `record_client_verification` ~ligne 660-738 ; docstring)
- Test: `backend/apps/trips/tests.py`

**Interfaces:**
- Consumes: `InvoiceService.adjust_delivered_quantity` (Task 1), `InvoicePaidCorrectionUnsupported` (Task 1).
- Produces: `DeliveryService.record_client_verification` met à jour `Sale.delivered_quantity` + `Invoice.total_amount` quand `received_qty` diffère et que la facture existe. Lève `InvoicePaidCorrectionUnsupported` (→ 400 via la vue) si facture payée/annulée.

- [ ] **Step 1: Write the failing tests**

Ajouter à `backend/apps/trips/tests.py`. Réutiliser le helper `_deliverable_trip(fx, ref)` (crée un trajet à `ARRIVED_AT_CLIENT` avec client). Il faut ensuite `record_delivery` puis `record_client_verification`. Configurer un prix via `ProductSellingPriceHistory` (déjà importé dans ce fichier — cf. `test_api_status_bar_rejects_manual_delivered_and_completed`).

```python
@pytest.mark.django_db
def test_client_verification_reduces_a_draft_invoice_to_the_received_quantity():
    fx = _fixtures_with_customer("CV-DRAFT-INV")
    trip = _deliverable_trip(fx, "TRIP-CV-DRAFT-INV-001")  # quantity_loaded 45000
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("900.0000"), changed_by=fx["admin_user"],
    )
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE, controller=fx["admin_user"],
    )
    trip.refresh_from_db()
    invoice = trip.sale.invoice
    assert invoice.status == Invoice.Status.DRAFT
    assert trip.sale.delivered_quantity == Decimal("45000.00")
    assert invoice.total_amount == Decimal("40500000.00")

    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44800.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )

    trip = Trip.objects.get(pk=trip.id)
    assert trip.sale.delivered_quantity == Decimal("44800.00")
    invoice.refresh_from_db()
    assert invoice.total_amount == Decimal("40320000.00")
    assert InvoiceCorrection.objects.filter(invoice=invoice).count() == 0


@pytest.mark.django_db
def test_client_verification_on_a_validated_invoice_writes_a_correction_row():
    fx = _fixtures_with_customer("CV-VALID-INV")
    trip = _deliverable_trip(fx, "TRIP-CV-VALID-INV-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("900.0000"), changed_by=fx["admin_user"],
    )
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE, controller=fx["admin_user"],
    )
    trip.refresh_from_db()
    invoice = trip.sale.invoice
    InvoiceService.validate_invoice(invoice.id, fx["admin_user"])

    DeliveryService.record_client_verification(
        trip_id=trip.id, received_qty=Decimal("44800.00"),
        verified_at=date.today(), actor=fx["admin_user"],
    )

    invoice.refresh_from_db()
    assert invoice.total_amount == Decimal("40320000.00")
    correction = InvoiceCorrection.objects.get(invoice=invoice)
    assert correction.field_name == "delivered_quantity"
    assert "Vérification client" in correction.reason


@pytest.mark.django_db
def test_client_verification_is_blocked_when_the_invoice_is_paid():
    fx = _fixtures_with_customer("CV-PAID-INV")
    trip = _deliverable_trip(fx, "TRIP-CV-PAID-INV-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("900.0000"), changed_by=fx["admin_user"],
    )
    DeliveryService.record_delivery(
        trip_id=trip.id, control_date="2026-08-18",
        method=DeliveryControl.Method.MANUAL_GAUGE, controller=fx["admin_user"],
    )
    trip.refresh_from_db()
    invoice = trip.sale.invoice
    InvoiceService.validate_invoice(invoice.id, fx["admin_user"])
    Invoice.objects.filter(pk=invoice.id).update(status=Invoice.Status.PAID)

    with pytest.raises(InvoicePaidCorrectionUnsupported):
        DeliveryService.record_client_verification(
            trip_id=trip.id, received_qty=Decimal("44800.00"),
            verified_at=date.today(), actor=fx["admin_user"],
        )

    trip = Trip.objects.get(pk=trip.id)
    assert trip.status == Trip.Status.DELIVERED  # not completed
    assert trip.sale.delivered_quantity == Decimal("45000.00")
    assert DeliveryControl.objects.get(trip=trip).verified_at is None


@pytest.mark.django_db
def test_client_verification_api_returns_400_when_invoice_paid():
    fx = _fixtures_with_customer("CV-PAID-API")
    trip = _deliverable_trip(fx, "TRIP-CV-PAID-API-001")
    ProductSellingPriceHistory.objects.create(
        product=fx["product"], customer=fx["customer"],
        price=Decimal("900.0000"), changed_by=fx["admin_user"],
    )
    client = APIClient()
    client.force_authenticate(fx["admin_user"])
    client.post(f"/api/trips/{trip.id}/delivery-control/",
                {"control_date": "2026-08-18", "method": "MANUAL_GAUGE"})
    trip.refresh_from_db()
    invoice = trip.sale.invoice
    InvoiceService.validate_invoice(invoice.id, fx["admin_user"])
    Invoice.objects.filter(pk=invoice.id).update(status=Invoice.Status.PAID)

    resp = client.post(f"/api/trips/{trip.id}/client-verification/",
                       {"received_quantity": "44800.00", "verified_at": "2026-08-18"})
    assert resp.status_code == 400
    assert "encaiss" in resp.data["detail"].lower()
```

Vérifier les imports en tête de `apps/trips/tests.py` : ajouter `InvoiceCorrection` (`from apps.sales.models import ...`), `InvoiceService`, `InvoicePaidCorrectionUnsupported` (`from apps.sales.services import ...`) si absents.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest apps/trips/tests.py -k client_verification_reduces -k "reduces or validated_invoice or blocked_when or api_returns_400_when" --create-db -q`

(ou simplement `-k "CV-DRAFT-INV or CV-VALID-INV or CV-PAID-INV or CV-PAID-API"` selon les noms)
Expected: FAIL — l'invoice reste à `40 500 000` (la propagation n'existe pas encore).

- [ ] **Step 3: Add the import**

`backend/apps/trips/services.py` ligne ~23 :

```python
from apps.sales.services import CustomerOrderService, InvoiceService
```

- [ ] **Step 4: Propagate to the invoice in `record_client_verification`**

Dans `record_client_verification`, juste avant `sale = getattr(trip, "sale", None)` / `DeliveryService.sync_transport_shortage_deduction(...)` (après `control.save(...)`), insérer :

```python
        sale = getattr(trip, "sale", None)
        if sale is not None and getattr(sale, "invoice", None) is not None:
            # Spec 2026-09-07: the client pays for what actually arrived.
            # Propagate the corrected quantity to the Sale + Invoice (DRAFT
            # -> direct, VALIDATED -> audited, PAID -> refused).
            InvoiceService.adjust_delivered_quantity(
                sale.invoice.id,
                received_qty,
                reason=(
                    "Vérification client : quantité reçue corrigée de "
                    f"{sale.delivered_quantity} L à {received_qty} L"
                ),
                actor=actor,
            )
            sale.refresh_from_db()
```

Puis remplacer le `sale = getattr(trip, "sale", None)` qui suit (juste avant `DeliveryService.sync_transport_shortage_deduction`) — il est maintenant redondant, garder une seule assignation. `sync_transport_shortage_deduction` utilise `sale.unit_selling_price` (inchangé).

Mettre à jour le docstring de la méthode : retirer « Never touches Sale/Invoice ("Delivered Quantity is Commercial Truth" stays frozen) », le remplacer par une phrase indiquant que la quantité reçue est propagée à la facture (spec 2026-09-07).

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest apps/trips/tests.py -k "CV-DRAFT-INV or CV-VALID-INV or CV-PAID-INV or CV-PAID-API" -q`
Expected: PASS.

- [ ] **Step 6: Run the trips suite for regressions**

Run: `docker compose exec -T backend python -m pytest apps/trips/ -q`
Expected: PASS. Si `test_api_repeated_truck_scenario_450000_litres` casse (il facture désormais 45000 mais `_drive_trip_through_delivery` verifie avec 45000 = pas de changement, donc OK) — sinon ajuster.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/trips/services.py backend/apps/trips/tests.py
git commit -m "feat(trips): client verification bills the received quantity, not the loaded one

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 4 : Marge — retirer le terme `- company_absorbed_loss_amount`

**Files:**
- Modify: `backend/apps/reports/services/profit.py` (`get_cost_breakdown`, ~ligne 168-175)
- Test: `backend/apps/reports/tests.py` (réécrire `test_margin_subtracts_company_absorbed_loss`), `backend/apps/reports/test_production_like_scenario.py` (étape 11)

**Interfaces:**
- Consumes: `record_client_verification` propage désormais à la Sale (Task 3).
- Produces: `TripProfitService.get_cost_breakdown(trip)["margin"] == revenue + transporter_loss_indemnity - real_total_cost`. Les clés `company_absorbed_loss_quantity` / `company_absorbed_loss_amount` restent dans le dict retourné (affichage seul).

- [ ] **Step 1: Rewrite the failing test**

Dans `backend/apps/reports/tests.py`, remplacer `test_margin_subtracts_company_absorbed_loss` par (le helper `_make_delivered_trip_with_sale` ne crée pas d'Invoice → utiliser le pattern `_deliver_trip_with_transporter_loss` de `test_queries.py`, ou créer localement un trajet via `record_delivery`) :

```python
@pytest.mark.django_db
def test_margin_reflects_absorbed_loss_via_reduced_revenue_not_a_separate_term():
    """Spec 2026-09-07: once the invoice bills the received quantity, the
    tolerance-absorbed loss shows up as a lower revenue - subtracting
    company_absorbed_loss_amount again would double-count it. The amount is
    still exposed for display, just not a formula term."""
    admin_user = _make_admin("ABSORBED2")
    trip = _deliver_via_services(
        "ABSORBED2", admin_user,
        loaded=Decimal("45000.00"), received=Decimal("44920.00"),  # 80 L, all within tolerance
        unit_selling_price=Decimal("900.0000"),
    )
    breakdown = TripProfitService.get_cost_breakdown(trip)

    # A hypothetical no-loss version of the same trip:
    no_loss_margin = (
        Decimal("45000.00") * Decimal("900.0000")
        + Decimal("0.00")  # no transporter indemnity
        - breakdown["real_total_cost"]
    )
    assert breakdown["margin"] == (no_loss_margin - Decimal("80.00") * Decimal("900.0000")).quantize(Decimal("0.01"))
    # still exposed, for the greyed "information" line on the trip screen:
    assert breakdown["company_absorbed_loss_quantity"] == Decimal("80.00")
    assert breakdown["company_absorbed_loss_amount"] == Decimal("72000.00")
```

Ajouter le helper `_deliver_via_services` en tête de `apps/reports/tests.py` (copier/adapter `_deliver_trip_with_transporter_loss` de `test_queries.py`, ou importer directement `from apps.reports.test_queries import _deliver_trip_with_transporter_loss` si pytest le permet — sinon dupliquer un helper minimal). `_deliver_via_services` doit : créer le trajet, `record_delivery` (crée Sale+Invoice DRAFT à `loaded`), `record_client_verification(received)` (propage → Sale à `received`).

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest apps/reports/tests.py::test_margin_reflects_absorbed_loss_via_reduced_revenue_not_a_separate_term --create-db -q`
Expected: FAIL — `margin` est trop bas de `72000` (le terme est encore soustrait).

- [ ] **Step 3: Remove the term**

`backend/apps/reports/services/profit.py`, dans `get_cost_breakdown` :

```python
        real_total_cost = cost_basis["total_cost"]
        margin = (
            revenue
            + transporter_loss_indemnity
            - real_total_cost
        ).quantize(Decimal("0.01"))
```

Remplacer le commentaire `Client modifications (2026-09-04): the tolerated portion ...` (juste au-dessus du calcul de `company_absorbed_loss_quantity`) par une note courte : le montant est calculé pour l'affichage uniquement ; il n'est plus soustrait de la marge depuis la spec 2026-09-07 (la facture reflète la quantité reçue, donc `revenue` l'intègre déjà).

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T backend python -m pytest apps/reports/tests.py::test_margin_reflects_absorbed_loss_via_reduced_revenue_not_a_separate_term -q`
Expected: PASS.

- [ ] **Step 5: Fix `test_production_like_scenario.py` étape 11**

Dans `backend/apps/reports/test_production_like_scenario.py`, l'étape « 11. Benefices » : la marge attendue devient `40 365 000 + 45 000 − 36 000 000 = 4 410 000` :

```python
    report.check("11. Benefices", "benefice trajet", "40 365 000 + 45 000 - 36 000 000", money(4410000), profit_breakdown["margin"])
```

(retirer `- 90 000` du libellé). La ligne `report.check(... "perte absorbee par l'entreprise" ... company_absorbed_loss_amount)` reste (toujours exposé, `money(90000)`).

- [ ] **Step 6: Run the reports suite for regressions**

Run: `docker compose exec -T backend python -m pytest apps/reports/tests.py apps/reports/test_production_like_scenario.py -q`
Expected: PASS. (Les tests `test_current_margin_*` de `apps/reports/tests.py` utilisent `_make_delivered_trip_with_sale` sans verification → pas de perte → inchangés.)

- [ ] **Step 7: Commit**

```bash
git add backend/apps/reports/services/profit.py backend/apps/reports/tests.py backend/apps/reports/test_production_like_scenario.py
git commit -m "fix(reports): drop the double-counting company-absorbed-loss term from trip margin

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 5 : Distribuable — retirer le terme `- total_company_absorbed_loss`

**Files:**
- Modify: `backend/apps/finance/services.py` (`ShareholderProfitPreviewService.get_preview`, ~ligne 2253-2315)
- Test: `backend/apps/reports/test_queries.py` (réécrire les 2 tests distributable + `test_transporter_loss_indemnity_stays_visible_and_is_not_double_counted`)

**Interfaces:**
- Consumes: marge sans le terme (Task 4).
- Produces: `get_preview()["distributable_result"] == working_capital.total - supplier_debt - transporter_debt - other_debts - capital` (sans terme perte). `get_preview()["total_company_absorbed_loss"]` **reste** dans le dict (toujours calculé, affiché sur le détail trajet, consommé par `dashboard.py`).

- [ ] **Step 1: Rewrite the failing tests**

`backend/apps/reports/test_queries.py` :

`test_distributable_result_reconciles_to_net_profit_once_debts_paid` (~ligne 850-906, le nom exact peut varier — celui qui finit par `assert preview["distributable_result"] == preview["net_profit"]`) : garder tel quel SI l'assertion `== net_profit` tient encore (elle devrait : `net_profit` = marge sans terme, `distributable` = trésorerie − capital, et la facture réduite fait encaisser le bon montant). Si l'égalité ne tient plus au centime près, remplacer par une vérification directe de la formule :

```python
    wc = preview["working_capital"]
    expected = (
        wc["total"] - wc["supplier_debt_total"] - wc["transporter_debt_total"]
        - wc["other_debts"] - wc["capital"]
    )
    assert Decimal(str(preview["distributable_result"])) == expected
```

`test_distributable_result_still_counts_company_absorbed_loss_after_same_day_distribution` (~ligne 910) : **supprimer** ce test (sa prémisse — le distribuable soustrait la perte — n'existe plus). Le remplacer par :

```python
@pytest.mark.django_db
def test_distributable_result_no_longer_subtracts_company_absorbed_loss():
    """Spec 2026-09-07: the client now pays the received quantity, so the
    lower treasury already reflects the absorbed loss - distributable_result
    is a clean treasury/debts/capital figure with no separate loss term."""
    admin_user = _make_admin("DISTNOLOSS")
    fx = _deliver_trip_with_transporter_loss(
        "DISTNOLOSS", admin_user,
        received_qty=Decimal("44600.00"), base_amount=Decimal("5000000.00"),
    )
    from apps.reports.services.profit import TripProfitService
    breakdown = TripProfitService.get_cost_breakdown(fx["trip"])
    assert breakdown["company_absorbed_loss_amount"] == Decimal("90000.00")  # still exposed

    _settle_all_debts_and_collect_customer(fx, admin_user)
    preview = ShareholderProfitPreviewService.get_preview()

    wc = preview["working_capital"]
    assert Decimal(str(preview["distributable_result"])) == (
        wc["total"] - wc["supplier_debt_total"] - wc["transporter_debt_total"]
        - wc["other_debts"] - wc["capital"]
    )
    # the key is still there, just not a term:
    assert "total_company_absorbed_loss" in preview
```

`test_transporter_loss_indemnity_stays_visible_and_is_not_double_counted` (~ligne 972) : lire le test et ajuster la marge attendue (elle change car `revenue` est maintenant reçu-basé et le terme absorbed n'est plus soustrait). Recalculer à partir des nombres du fixture.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest apps/reports/test_queries.py -k "distributable or transporter_loss_indemnity_stays" --create-db -q`
Expected: FAIL (le terme est encore soustrait).

- [ ] **Step 3: Remove the term from the formula**

`backend/apps/finance/services.py`, `get_preview` :

```python
        working_capital = WorkingCapitalService.get_working_capital()
        distributable_result = (
            working_capital["total"]
            - working_capital["supplier_debt_total"]
            - working_capital["transporter_debt_total"]
            - working_capital["other_debts"]
            - working_capital["capital"]
        )
```

Garder le calcul de `total_company_absorbed_loss` (les lignes `loss_rows = ...` / `total_company_absorbed_loss = sum(...)`) — il reste dans le `return`. Remplacer le gros pavé de commentaires « Bug fix (recette critique, 2026-09-06 ...) » (~ligne 2253-2294) par une note courte : « `total_company_absorbed_loss` reste calculé pour l'affichage (détail trajet) ; il n'est plus soustrait de `distributable_result` depuis la spec 2026-09-07 — la facture reflète la quantité reçue, donc la trésorerie l'intègre déjà. »

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest apps/reports/test_queries.py -k "distributable or transporter_loss_indemnity_stays" -q`
Expected: PASS.

- [ ] **Step 5: Full reports + finance regression**

Run: `docker compose exec -T backend python -m pytest apps/reports/ apps/finance/ -q`
Expected: PASS. Ajuster tout test résiduel qui encodait l'ancienne formule (chercher `total_company_absorbed_loss` dans les assertions).

- [ ] **Step 6: Commit**

```bash
git add backend/apps/finance/services.py backend/apps/reports/test_queries.py
git commit -m "fix(finance): drop the company-absorbed-loss term from distributable_result

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 6 : Défaire l'affichage "point 1" — PDF Bénéfices

**Files:**
- Modify: `backend/apps/reports/services/profit_pdf.py` (`wc_rows`, ~ligne 314-340 ; labels `companyAbsorbedLoss` ~ligne 56/97)
- Test: `backend/apps/reports/test_profit_pdf.py`

**Interfaces:**
- Consumes: `preview["total_company_absorbed_loss"]` toujours présent (Task 5).
- Produces: le PDF Bénéfices ne contient plus de ligne « Perte supportée par l'entreprise » dans la ventilation fond de roulement.

- [ ] **Step 1: Update the test**

`backend/apps/reports/test_profit_pdf.py` : supprimer `test_render_profit_report_pdf_shows_company_absorbed_loss_row_when_nonzero` (ajouté au point 1). Garder la clé `"total_company_absorbed_loss": Decimal("0.00")` dans le fixture `_preview` (toujours dans le contrat du preview). Ajouter une assertion négative dans un test existant si utile (optionnel).

- [ ] **Step 2: Revert `wc_rows`**

`backend/apps/reports/services/profit_pdf.py`, dans `_working_capital_section` (ou la fonction qui construit `wc_rows`) : retirer le bloc ajouté au point 1 :

```python
    wc_rows = [
        (labels["treasuryAvailable"], _format_money(wc["treasury_available"])),
        (labels["customerReceivables"], _format_money(wc["customer_receivables"])),
        (labels["gross"], _format_money(wc["gross"])),
        (labels["supplierDebt"], _format_money(wc["supplier_debt_total"])),
        (labels["transporterDebt"], _format_money(wc["transporter_debt_total"])),
        (labels["customsDebt"], _format_money(other_debts_breakdown["customs"])),
        (labels["transitDebt"], _format_money(other_debts_breakdown["transit"])),
        (labels["roadTransitDebt"], _format_money(other_debts_breakdown["road_transit"])),
        (labels["otherDebt"], _format_money(other_debts_breakdown["other"])),
        (
            labels["totalDebts"],
            _format_money(
                wc["supplier_debt_total"] + wc["transporter_debt_total"] + wc["other_debts"]
            ),
        ),
        (labels["totalWorkingCapital"], _format_money(wc["total"])),
        (labels["capital"], _format_money(wc["capital"])),
        (labels["distributableResult"], _format_money(preview["distributable_result"])),
    ]
    wc_table = Table(wc_rows, colWidths=[110 * mm, 60 * mm])
    wc_table.setStyle(_SUMMARY_TABLE_STYLE)
    wc_table.setStyle(TableStyle([_bold_row(idx) for idx in (2, 9, 10, 12)]))
```

Retirer la clé de label `"companyAbsorbedLoss"` des dicts `fr` et `en` de `PROFIT_PDF_LABELS`.

- [ ] **Step 3: Run the PDF tests**

Run: `docker compose exec -T backend python -m pytest apps/reports/test_profit_pdf.py --create-db -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/apps/reports/services/profit_pdf.py backend/apps/reports/test_profit_pdf.py
git commit -m "revert(reports): remove company-absorbed-loss row from the profit PDF

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 7 : Défaire l'affichage "point 1" — ProfitView + DashboardView

**Files:**
- Modify: `frontend/src/modules/finance/ProfitView.vue`, `frontend/src/modules/dashboard/DashboardView.vue`, `frontend/src/modules/dashboard/DashboardView.spec.ts`, `frontend/src/modules/finance/__tests__/ProfitView.spec.ts`
- (Laisser : `backend/apps/reports/views/dashboard.py` `total_company_absorbed_loss` — toujours renvoyé, inoffensif ; `types.ts` — champ gardé typé ; clés i18n `companyAbsorbedLoss` — inoffensives, garder.)

**Interfaces:**
- Consumes: néant (suppression pure).
- Produces: la section DISTRIBUTION de la page Bénéfices et le bloc FOND DE ROULEMENT du dashboard n'affichent plus de ligne « Perte supportée par l'entreprise ».

- [ ] **Step 1: Update the specs (remove the point-1 tests)**

`frontend/src/modules/finance/__tests__/ProfitView.spec.ts` : supprimer le test `it('shows a "Perte supportée par l'entreprise" card in Distribution when non-zero', ...)`. Dans le test `it('shows fond de roulement brut, dettes ouvertes ...')`, retirer la ligne `expect(wrapper.find('[data-test="profit-company-absorbed-loss-card"]').exists()).toBe(false)`. Garder `total_company_absorbed_loss: '0.00'` dans le mock `fetchShareholderProfitPreview`.

`frontend/src/modules/dashboard/__tests__/DashboardView.spec.ts` : supprimer le test `it('shows the "Perte supportée par l'entreprise" line when non-zero, hides it at zero', ...)`. Garder `total_company_absorbed_loss: '0.00'` dans le mock `summary.shareholders_summary`.

- [ ] **Step 2: Run specs to verify they fail**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ProfitView.spec.ts src/modules/dashboard/__tests__/DashboardView.spec.ts`
Expected: PASS after deletion (the deleted tests no longer run; nothing else asserts the card). If a leftover assertion fails, remove it.

- [ ] **Step 3: Remove the ProfitView card**

`frontend/src/modules/finance/ProfitView.vue`, section DISTRIBUTION : supprimer le `<div v-if="Number(preview.total_company_absorbed_loss) > 0" data-test="profit-company-absorbed-loss-card" ...>...</div>` (inséré avant la carte `profit-distributable-result-card`).

- [ ] **Step 4: Remove the DashboardView lines**

`frontend/src/modules/dashboard/DashboardView.vue` :
- Dans le `computed workingCapitalCard`, retirer `const absorbedLoss = ...`, `companyAbsorbedLoss: absorbedLoss`, `companyAbsorbedLossParts: ...`.
- Dans le bloc FOND DE ROULEMENT `<dl>`, retirer le `<div v-if="workingCapitalCard.companyAbsorbedLoss > 0" data-test="working-capital-company-absorbed-loss" ...>`.
- Dans la section actionnaires, retirer le `<div v-if="Number(summary.shareholders_summary.total_company_absorbed_loss) > 0" ...>` inséré avant `shareholdersDistributableResult`.

- [ ] **Step 5: Run specs + typecheck**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/ProfitView.spec.ts src/modules/dashboard/__tests__/DashboardView.spec.ts && npx vue-tsc --noEmit -p tsconfig.app.json`
Expected: PASS ; typecheck clean (hormis l'erreur pré-existante).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/finance/ProfitView.vue frontend/src/modules/dashboard/DashboardView.vue frontend/src/modules/finance/__tests__/ProfitView.spec.ts frontend/src/modules/dashboard/__tests__/DashboardView.spec.ts
git commit -m "revert(ui): remove company-absorbed-loss display lines from Profit/Dashboard

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 8 : `SaleSerializer` expose `quantity_loaded`

**Files:**
- Modify: `backend/apps/sales/serializers.py` (`SaleSerializer`, ~ligne 78-113)
- Test: `backend/apps/sales/tests.py` (ou `apps/customers/tests.py`)

**Interfaces:**
- Produces: `SaleSerializer` renvoie `quantity_loaded` (string, 2 décimales) = `trip.quantity_loaded`. Disponible dans `sale_detail` de `InvoiceSerializer` → dans chaque ligne `invoices[]` de `GET /api/customers/{id}/ledger/`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_customer_ledger_invoice_exposes_loaded_and_received_quantities():
    # build a trip whose invoice was reduced by a client verification
    ... (réutiliser _deliver_via_services / helper trip -> record_delivery -> record_client_verification 44800)
    client = APIClient(); client.force_authenticate(admin_user)
    resp = client.get(f"/api/customers/{customer.id}/ledger/")
    assert resp.status_code == 200
    row = resp.data["invoices"][0]
    assert row["sale_detail"]["quantity_loaded"] == "45000.00"
    assert row["sale_detail"]["delivered_quantity"] == "44800.00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest apps/sales/tests.py::test_customer_ledger_invoice_exposes_loaded_and_received_quantities --create-db -q`
Expected: FAIL — `KeyError: 'quantity_loaded'`.

- [ ] **Step 3: Add the field**

`backend/apps/sales/serializers.py`, `SaleSerializer` :

```python
    trip_reference = serializers.CharField(source="trip.reference", read_only=True)
    quantity_loaded = serializers.DecimalField(
        source="trip.quantity_loaded", max_digits=14, decimal_places=2, read_only=True
    )
```

et ajouter `"quantity_loaded"` à `Meta.fields` (et donc `read_only_fields = fields` le couvre).

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T backend python -m pytest apps/sales/tests.py::test_customer_ledger_invoice_exposes_loaded_and_received_quantities -q`
Expected: PASS.

- [ ] **Step 5: Run sales + customers suites**

Run: `docker compose exec -T backend python -m pytest apps/sales/ apps/customers/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/sales/serializers.py backend/apps/sales/tests.py
git commit -m "feat(sales): expose trip quantity_loaded on SaleSerializer for the client ledger

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 9 : Grand livre client — colonnes Qté chargée / Qté reçue (écran)

**Files:**
- Modify: `frontend/src/modules/finance/CustomerLedgerView.vue`, `frontend/src/modules/finance/types.ts` (`CustomerLedgerInvoice`), `frontend/src/locales/{fr,en,ar}.json`
- Test: `frontend/src/modules/finance/__tests__/CustomerLedgerView.spec.ts`

**Interfaces:**
- Consumes: `invoice.sale_detail.quantity_loaded` / `.delivered_quantity` (Task 8).

- [ ] **Step 1: Add the i18n keys**

Dans `finance.customerLedger.table` des 3 fichiers, après `"issued"` :
- fr : `"loadedQuantity": "Qté chargée", "receivedQuantity": "Qté reçue"`
- en : `"loadedQuantity": "Loaded qty", "receivedQuantity": "Received qty"`
- ar : `"loadedQuantity": "الكمية المحمّلة", "receivedQuantity": "الكمية المستلمة"`

- [ ] **Step 2: Update the type**

`frontend/src/modules/finance/types.ts`, `CustomerLedgerInvoice` : ajouter

```ts
  sale_detail?: {
    quantity_loaded: string
    delivered_quantity: string
  }
```

- [ ] **Step 3: Write the failing spec**

`frontend/src/modules/finance/__tests__/CustomerLedgerView.spec.ts` : dans le mock du ledger, ajouter `sale_detail: { quantity_loaded: '45000.00', delivered_quantity: '44800.00' }` à la facture, puis :

```ts
it('shows loaded and received quantity columns per invoice', async () => {
  const wrapper = /* mount with ledger mock */
  await flushPromises()
  const text = wrapper.text().replace(/[⁦⁩]/g, '')
  expect(text).toContain('Qté chargée')
  expect(text).toContain('Qté reçue')
  expect(text).toContain('45 000 L')
  expect(text).toContain('44 800 L')
})
```

- [ ] **Step 4: Run spec to verify it fails**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/CustomerLedgerView.spec.ts`
Expected: FAIL.

- [ ] **Step 5: Add the columns**

`frontend/src/modules/finance/CustomerLedgerView.vue`, tableau FACTURES :
- `<thead>` : après le `<th>` « Émise », insérer 2 `<th class="px-2 py-1.5 font-medium text-right">{{ t('finance.customerLedger.table.loadedQuantity') }}</th>` et `receivedQuantity`.
- `<tbody>` `<tr v-for>` : après la cellule `issued_date`, insérer
  ```html
  <td class="px-2 py-1.5 text-right"><MonoValue :value="formatQuantity(invoice.sale_detail?.quantity_loaded ?? 0)" /></td>
  <td class="px-2 py-1.5 text-right"><MonoValue :value="formatQuantity(invoice.sale_detail?.delivered_quantity ?? 0)" /></td>
  ```
- importer `formatQuantity` depuis `@/utils/currency` (vérifier l'import existant `formatMoney`).
- Ligne vide : `colspan="5"` → `colspan="7"`.

- [ ] **Step 6: Run spec + typecheck**

Run: `cd frontend && npx vitest run src/modules/finance/__tests__/CustomerLedgerView.spec.ts && npx vue-tsc --noEmit -p tsconfig.app.json`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/finance/CustomerLedgerView.vue frontend/src/modules/finance/types.ts frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json frontend/src/modules/finance/__tests__/CustomerLedgerView.spec.ts
git commit -m "feat(ui): loaded/received quantity columns in the customer ledger

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 10 : Grand livre client PDF — mêmes colonnes

**Files:**
- Modify: `backend/apps/customers/views.py` (`ledger_pdf`, `invoices_section` ~ligne 143-160), `backend/apps/reports/services/ledger_pdf.py` (`FIELD_LABELS_FR` ~ligne 232, dict `en` équivalent)
- Test: `backend/apps/reports/test_ledger_pdf.py`

**Interfaces:**
- Consumes: `invoice.sale.trip.quantity_loaded`, `invoice.sale.delivered_quantity`.

- [ ] **Step 1: Add the field labels**

`backend/apps/reports/services/ledger_pdf.py`, `FIELD_LABELS_FR` : ajouter `"quantity_loaded": "Qté chargée"`, `"delivered_quantity": "Qté reçue"`. Idem dans le dict de labels EN (chercher `FIELD_LABELS_EN` ou équivalent ; s'il n'y en a pas et que EN retombe sur FR, ne rien faire). Vérifier que `quantity_loaded` / `delivered_quantity` sont traités comme colonnes quantité (`_QUANTITY_FIELDS` — chercher le registre) pour un rendu « 45 000 L » ; sinon les y ajouter.

- [ ] **Step 2: Write the failing test**

`backend/apps/reports/test_ledger_pdf.py` : un test qui construit un customer avec 1 facture (Sale `delivered_quantity=44800`, trip `quantity_loaded=45000`), appelle `render_ledger_pdf` via le chemin `CustomersViewSet.ledger_pdf` (ou directement avec un `extra_sections` `invoices_section` contenant les 2 clés), et vérifie que le PDF bytes commencent par `%PDF` et — si le fichier a déjà un helper d'extraction texte — que « Qté chargée » / « 45 000 L » apparaissent. Sinon, se contenter d'un test « ne crashe pas » avec les 2 nouvelles clés dans `invoices_section`.

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest apps/reports/test_ledger_pdf.py -k loaded --create-db -q`
Expected: FAIL (KeyError ou colonne absente).

- [ ] **Step 4: Add the columns to `invoices_section`**

`backend/apps/customers/views.py`, `ledger_pdf`, la compréhension `invoices_section` :

```python
        invoices_section = [
            {
                "invoice_number": invoice.invoice_number,
                "issued_date": invoice.issued_date,
                "quantity_loaded": invoice.sale.trip.quantity_loaded,
                "delivered_quantity": invoice.sale.delivered_quantity,
                "total_amount": invoice.total_amount,
                "outstanding": PaymentAllocationService.get_invoice_outstanding(invoice),
                "status": invoice.status,
            }
            for invoice in invoices
        ]
```

Ajouter `.select_related("sale__trip")` au queryset `invoices` en tête de `ledger_pdf` (actuellement `.select_related("sale")`).

- [ ] **Step 5: Run test + PDF suite**

Run: `docker compose exec -T backend python -m pytest apps/reports/test_ledger_pdf.py apps/customers/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/customers/views.py backend/apps/reports/services/ledger_pdf.py backend/apps/reports/test_ledger_pdf.py
git commit -m "feat(reports): loaded/received quantity columns in the customer ledger PDF

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 11 : Écran facture — quantité chargée + `delivered_quantity` corrigible

**Files:**
- Modify: `frontend/src/modules/sales/InvoiceDetail.vue`, `frontend/src/modules/sales/types.ts` (`CORRECTABLE_INVOICE_FIELDS`), `frontend/src/locales/{fr,en,ar}.json`
- Test: `frontend/src/modules/sales/__tests__/InvoiceDetail.spec.ts`

**Interfaces:**
- Consumes: `invoice.sale_detail.quantity_loaded` (Task 8), `correct_invoice` accepte `delivered_quantity` (Task 2).

- [ ] **Step 1: Add i18n keys**

`sales.invoiceDetail` des 3 fichiers :
- `loadedQuantity` : fr « Quantité chargée » / en « Loaded quantity » / ar « الكمية المحمّلة »
- `correctionFields` (objet) : `{ unit_selling_price: "Prix de vente unitaire" | "Unit selling price" | "...", total_amount: "Montant total" | "Total amount" | "...", delivered_quantity: "Quantité livrée" | "Delivered quantity" | "..." }`

- [ ] **Step 2: Extend the constant**

`frontend/src/modules/sales/types.ts` :

```ts
export const CORRECTABLE_INVOICE_FIELDS = ['unit_selling_price', 'total_amount', 'delivered_quantity'] as const
```

- [ ] **Step 3: Write the failing spec**

`frontend/src/modules/sales/__tests__/InvoiceDetail.spec.ts` : ajouter `sale_detail.quantity_loaded: '45000.00'` au mock invoice, puis :

```ts
it('shows the loaded quantity next to the received quantity', async () => {
  /* mount */
  const text = wrapper.text().replace(/[⁦⁩]/g, '')
  expect(text).toContain('Quantité chargée')
  expect(text).toContain('45 000 L')
})

it('offers delivered_quantity as a correctable field', async () => {
  /* mount a VALIDATED invoice, open the correction form */
  const options = wrapper.find('#correction_field').findAll('option').map(o => o.text())
  expect(options).toContain('Quantité livrée')
})
```

- [ ] **Step 4: Run spec to verify it fails**

Run: `cd frontend && npx vitest run src/modules/sales/__tests__/InvoiceDetail.spec.ts`
Expected: FAIL.

- [ ] **Step 5: Implement**

`frontend/src/modules/sales/InvoiceDetail.vue` :
- Après le bloc « deliveredQuantity » (~ligne 212-221), ajouter un bloc « loadedQuantity » identique avec `formatQuantity(invoice.sale_detail?.quantity_loaded ?? 0)` et le libellé `t('sales.invoiceDetail.loadedQuantity')`.
- Le `<select id="correction_field">` (~ligne 297-303) : remplacer `{{ f }}` par `{{ t(\`sales.invoiceDetail.correctionFields.\${f}\`) }}`.

- [ ] **Step 6: Run spec + typecheck**

Run: `cd frontend && npx vitest run src/modules/sales/__tests__/InvoiceDetail.spec.ts && npx vue-tsc --noEmit -p tsconfig.app.json`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/sales/InvoiceDetail.vue frontend/src/modules/sales/types.ts frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json frontend/src/modules/sales/__tests__/InvoiceDetail.spec.ts
git commit -m "feat(ui): show loaded quantity + allow delivered_quantity correction on the invoice screen

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Task 12 : Bloc RENTABILITÉ DU TRAJET — « Perte supportée » en information (Version A)

**Files:**
- Modify: `frontend/src/modules/trips/TripDetail.vue` (bloc marge, ligne `company-absorbed-loss-row` ~ligne 838-861), `frontend/src/locales/{fr,en,ar}.json`
- Test: `frontend/src/modules/trips/__tests__/TripDetail.spec.ts`

**Interfaces:**
- Consumes: `margin.company_absorbed_loss_amount` / `_quantity` (toujours renvoyés par `fetchTripMargin` — Task 4 ne les retire pas du dict).

- [ ] **Step 1: Add the i18n key**

`trips.detail` des 3 fichiers : `companyAbsorbedLossInfoNote` — fr « information — déjà reflété dans le chiffre d'affaires » / en « information — already reflected in revenue » / ar « معلومة — منعكسة مسبقًا في رقم الأعمال ».

- [ ] **Step 2: Write the failing spec**

`frontend/src/modules/trips/__tests__/TripDetail.spec.ts` : trouver le test qui rend le bloc marge avec `company_absorbed_loss_amount > 0` (mock `fetchTripMargin`). Assertions :

```ts
const row = wrapper.find('[data-test="company-absorbed-loss-row"]')
expect(row.exists()).toBe(true)
// plus une classe critique -> grisé
expect(row.find('.text-critique').exists()).toBe(false)
expect(wrapper.text().replace(/[⁦⁩]/g, '')).toContain('information')
```

Et vérifier que la marge nette affichée = `revenue + indemnité − coûts` (sans le terme) — ajuster le nombre attendu du mock si un test l'assertait.

- [ ] **Step 3: Run spec to verify it fails**

Run: `cd frontend && npx vitest run src/modules/trips/__tests__/TripDetail.spec.ts`
Expected: FAIL.

- [ ] **Step 4: Restyle the line**

`frontend/src/modules/trips/TripDetail.vue`, le `<div v-if="Number(margin.company_absorbed_loss_amount) > 0" data-test="company-absorbed-loss-row" ...>` :
- retirer `class="text-critique"` sur le `<MonoValue>` de la valeur ; mettre `class="text-texte-3"`.
- retirer le préfixe `-` si présent (`:value="formatMoney(margin.company_absorbed_loss_amount)"`, plus de `-${...}`) — c'est une information, pas une déduction.
- ajouter sous le libellé (dans le `<span class="text-texte-3 block text-xs">` existant qui affiche `companyAbsorbedLossDetail`) une 2ᵉ ligne ou un suffixe `· {{ t('trips.detail.companyAbsorbedLossInfoNote') }}`.

- [ ] **Step 5: Run spec + full frontend suite + typecheck**

Run: `cd frontend && npx vitest run && npx vue-tsc --noEmit -p tsconfig.app.json`
Expected: PASS (hormis l'erreur pré-existante `ProfitView.spec.ts(22)`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/trips/TripDetail.vue frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json frontend/src/modules/trips/__tests__/TripDetail.spec.ts
git commit -m "feat(ui): show trip absorbed-loss line as information, not a deduction

$(printf 'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')"
```

---

## Vérification finale (après Task 12)

- [ ] **Backend complet :** `docker compose exec -T backend python -m pytest --create-db -q` → tout vert.
- [ ] **Frontend complet :** `cd frontend && npx vitest run` → tout vert ; `npx vue-tsc --noEmit -p tsconfig.app.json` → propre (hormis `ProfitView.spec.ts(22)`).
- [ ] **PDF Bénéfices :** régénérer depuis la base live (shell Django : `ShareholderProfitPreviewService.get_preview()` + `WorkingCapitalService.get_other_debts_breakdown()` + `MarginReportQuery.run()` → `render_profit_report_pdf`) et vérifier : plus de ligne « Perte supportee par l'entreprise » ; `distribuable == total − dettes − capital`.
- [ ] **Reproduction métier live** (shell) : sur un trajet avec `record_delivery` puis `record_client_verification(received < loaded)` — `trip.sale.delivered_quantity == received`, `invoice.total_amount == received × prix`, `get_cost_breakdown["margin"]` = trajet-sans-perte − `company_absorbed_loss_amount`, `get_preview["distributable_result"]` réconcilie avec la trésorerie.
- [ ] **Navigateur** (si login possible) : compte client → colonnes Qté chargée/reçue ; facture → quantité chargée affichée ; détail trajet → « Perte supportée » grisée « information ».
- [ ] Mettre à jour la mémoire projet (`project_ui_ux_fixes_pass_2026-09-07.md`) : marquer le point 2 comme livré.

---

## Self-review (rempli à l'écriture du plan)

**Spec coverage :**
- Spec §1 (vérification → facture, 3 états) → Tasks 1, 2, 3. ✓
- Spec §2 (marge retire le terme, montant gardé en affichage) → Task 4 (backend) + Task 12 (affichage Version A). ✓
- Spec §3 (distribuable retire le terme + défaire point 1) → Task 5 (formule) + Task 6 (PDF) + Task 7 (ProfitView/Dashboard). ✓
- Spec §4 (grand livre client 2 colonnes + PDF) → Task 8 (serializer) + Task 9 (écran) + Task 10 (PDF). ✓
- Spec §5 (écran facture : libellé exact + qté chargée + champ corrigible) → Task 11. ✓
- Spec « non-changements » → contraintes globales + rien ne les touche. ✓
- Spec « impact tests » → chaque task réécrit/ajoute ses tests ; Tasks 4/5/6/7 traitent explicitement les tests du point 1 et de `2026-09-04`. ✓

**Placeholder scan :** Tasks 5, 9, 10, 11, 12 laissent au réalisateur le soin de « lire le test X et ajuster le nombre » quand le nombre dépend d'un fixture non recopié ici — c'est délibéré (le fixture est dans le fichier, le recopier intégralement dans le plan serait moins fiable que de le lire). Les helpers `_sale_with_invoice` / `_deliver_via_services` sont décrits (quoi créer) sans code complet — le réalisateur suit le pattern `_deliver_trip_with_transporter_loss` cité. Acceptable pour un dev qualifié ; pas de « TODO » ni de logique métier laissée floue.

**Type consistency :** `adjust_delivered_quantity(invoice_id, new_quantity, *, reason, actor)` — signature identique Tasks 1 et 3. `InvoicePaidCorrectionUnsupported` — même nom Tasks 1, 3. `CORRECTABLE_INVOICE_FIELDS` avec `'delivered_quantity'` — Tasks 2 (backend accepte), 11 (frontend liste). `sale_detail.quantity_loaded` — Task 8 (produit), 9/11 (consommé). `company_absorbed_loss_amount` reste une clé du dict `get_cost_breakdown` et du dict `get_preview` (`total_company_absorbed_loss`) — cohérent Tasks 4, 5, 12.

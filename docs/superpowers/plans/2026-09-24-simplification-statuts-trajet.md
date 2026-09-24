# Simplification du parcours de statuts d'un trajet — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (exécution **native**, une seule session, sans sous-agents — voir « Règles d'exécution économes »). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Raccourcir le parcours de statuts d'un trajet : retirer `GOING_TO_CLIENT` / `GOING_TO_COMPANY_STOCK`, permettre de sauter des statuts (un historique par statut traversé), enchaîner les popups de frais avec « Passer » / « Tout passer », et proposer la « Commission transporteur » dans le formulaire « Ajouter des frais ».

**Architecture:** `TripWorkflowService` calcule un chemin avant (fork client/stock inclus) ; `transition_trip` le traverse atomiquement et renvoie `trip.traversed_statuses`, exposé par `POST /trips/{id}/status/`. Le frontend enchaîne une file de popups de frais à partir de cette liste. La commission reste un `TransportPayment` (aucune fusion de modèle) : l'option du sélecteur bascule la fenêtre vers `TransportPaymentForm`.

**Tech Stack:** Django/DRF + pytest (`backend/`), Vue 3 + Vitest + vue-i18n (`frontend/`).

**Spec:** `docs/superpowers/specs/2026-09-24-simplification-statuts-trajet-design.md`

## Règles d'exécution économes en tokens

- **Native, une session.** Pas de sous-agents. Une seule relecture finale, à la demande de l'utilisateur.
- **Ne jamais lire en entier** `backend/apps/trips/tests.py` (3 700 lignes), `TripDetail.vue` (1 500 lignes) ni `TripDetail.spec.ts` (1 550 lignes). Utiliser `grep -n` + `sed -n 'a,bp'` sur les ancres données. Ne pas relire un fichier après `Edit`.
- **Tests ciblés uniquement** pendant les tâches 1-5, avec sortie tronquée : `... 2>&1 | tail -n 15`. Les suites complètes ne tournent **qu'une fois**, tâche 6.
- **Backend :** depuis `backend/`, `.venv/bin/python -m pytest <fichier> -q -x --create-db 2>&1 | tail -n 15`. `--create-db` est nécessaire au premier lancement (sinon `Role.DoesNotExist`) puis facultatif ; la DB Postgres du `docker-compose` écoute déjà sur 55435. Baseline vérifiée : `apps/trips/tests.py` = 123 passed (~20 s).
- **Frontend :** depuis `frontend/`, `npx vitest run <fichier> 2>&1 | tail -n 20`. Formater seulement les fichiers touchés (`npx prettier --write <fichiers>`), jamais `src/` entier.
- **Pas d'automatisation navigateur.** La recette est manuelle, par l'utilisateur (tâche 6).
- Un commit par tâche, message terminé par `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. Branche : `feature/simplification-statuts-trajet` (déjà créée, contient la spec).

## Global Constraints

- Statuts supprimés : uniquement `GOING_TO_CLIENT` et `GOING_TO_COMPANY_STOCK`. `LOADED`, `ARRIVED_AT_COMPANY_STOCK`, `STOCKED` restent.
- `DELIVERED` et `COMPLETED` ne sont **jamais** franchis par un saut ni acceptés par `POST /status/` (`_FORM_ONLY_STATUSES`, `views.py`) ; le saut s'arrête au plus loin à `ARRIVED_AT_CLIENT` / `ARRIVED_AT_COMPANY_STOCK` / `STOCKED`.
- `TripStatusHistory` est append-only : jamais modifié par la migration ; les libellés i18n / rapports des statuts supprimés (`fr.json`, `en.json`, `ar.json`, `report_labels.py`, `ledger_pdf.py`) sont **conservés** pour l'affichage de l'historique.
- Aucun changement du contrôle de livraison, de la vérification client, de la facturation, ni fusion des modèles `Expense` / `TransportPayment`.
- Textes UI en français (clés i18n ajoutées dans `fr.json`, `en.json`, `ar.json`).

## Review Focus

- Trajet hérité `BLOCKED` dont la dernière entrée d'historique a `previous_status` = statut supprimé : la reprise doit viser `CUSTOMS`, jamais un statut inexistant (test tâche 1).
- Client attribué **après** le début du parcours puis saut : le fork suit le client au moment de l'appel, pas celui de la création (test tâche 2).
- Cible invalide (retour arrière, statut inconnu) : zéro ligne d'historique écrite, statut inchangé (test tâche 2).
- Aucun chemin — service ou API — ne permet d'atteindre `DELIVERED`/`COMPLETED` par un saut (tests tâche 2).
- Utilisateur sans droit `finance:create` : après un saut, aucun popup et aucune file bloquée (test tâche 4).

## File Structure

| Fichier | Rôle |
|---|---|
| `backend/apps/trips/models.py` | enum `Status` sans les 2 statuts + `RETIRED_STATUS_REMAP` |
| `backend/apps/trips/migrations/0010_retire_going_to_statuses.py` | remap des trajets + `AlterField` choices |
| `backend/apps/trips/services.py` | `_next_step`, `_skip_path`, `get_path_to`, `transition_trip` multi-historique |
| `backend/apps/trips/views.py` | `POST /status/` renvoie `traversed_statuses` |
| `backend/apps/sales/services.py`, `reports/views/dashboard.py` | retrait d'une référence / d'un commentaire |
| `backend/apps/trips/tests.py`, `reports/test_production_like_scenario.py` | mise à jour + nouveaux tests |
| `frontend/src/modules/trips/{types.ts,api.ts,TripStatusBoard.vue,TripDetail.vue}` | statuts, file de frais, option commission |
| `frontend/src/modules/finance/{ExpenseForm.vue,TransportPaymentForm.vue}` | `cancelLabel`, option commission |
| `frontend/src/locales/{fr,en,ar}.json` | clés `skipFee`, `skipAllFees`, `transportCommission` |

---

### Task 1: Retirer les deux statuts (backend)

**Files:**
- Modify: `backend/apps/trips/models.py` (enum lignes ~33 et ~39, commentaire ligne ~65)
- Modify: `backend/apps/trips/services.py` (`FORWARD_TRANSITIONS` ~330-351, `get_allowed_targets` ~363-399, `_status_before_blocked` ~401-408)
- Modify: `backend/apps/sales/services.py:28`, `backend/apps/reports/views/dashboard.py:400`
- Create: `backend/apps/trips/migrations/0010_retire_going_to_statuses.py`
- Test: `backend/apps/trips/tests.py`, `backend/apps/reports/test_production_like_scenario.py`

**Interfaces:**
- Produces: `Trip.RETIRED_STATUS_REMAP: dict[str, str]`, `TripWorkflowService._next_step(trip, status) -> Status | None` (utilisé tâche 2).

- [ ] **Step 1: Écrire les tests qui échouent** — ajouter à la fin de `backend/apps/trips/tests.py` :

```python
@pytest.mark.django_db
def test_retired_going_statuses_are_gone_from_the_enum():
    assert not hasattr(Trip.Status, "GOING_TO_CLIENT")
    assert not hasattr(Trip.Status, "GOING_TO_COMPANY_STOCK")


@pytest.mark.django_db
def test_customs_leads_straight_to_arrived_at_client_or_company_stock():
    fx = _setup_fixtures("RETIRED-FORK")
    stock_trip = _make_trip(
        fx, _make_truck("TRK-RETIRED-1"), "TRIP-RETIRED-001", status=Trip.Status.CUSTOMS
    )
    assert Trip.Status.ARRIVED_AT_COMPANY_STOCK in TripWorkflowService.get_allowed_targets(stock_trip)
    assert Trip.Status.ARRIVED_AT_CLIENT not in TripWorkflowService.get_allowed_targets(stock_trip)

    client_trip = _make_trip(
        fx, _make_truck("TRK-RETIRED-2"), "TRIP-RETIRED-002", status=Trip.Status.CUSTOMS
    )
    client_trip.client = Customer.objects.create(name="Client retired fork")
    client_trip.destination_type = Trip.DestinationType.CUSTOMER
    client_trip.save()
    allowed = TripWorkflowService.get_allowed_targets(client_trip)
    assert Trip.Status.ARRIVED_AT_CLIENT in allowed
    assert Trip.Status.ARRIVED_AT_COMPANY_STOCK not in allowed


@pytest.mark.django_db
def test_stocked_trip_with_client_goes_straight_to_arrived_at_client():
    fx = _setup_fixtures("RETIRED-STOCKED")
    trip = _make_trip(
        fx, _make_truck("TRK-RETIRED-3"), "TRIP-RETIRED-003", status=Trip.Status.STOCKED
    )
    trip.client = Customer.objects.create(name="Client retired stocked")
    trip.destination_type = Trip.DestinationType.CUSTOMER
    trip.save()

    TripWorkflowService.transition_trip(trip.id, Trip.Status.ARRIVED_AT_CLIENT, fx["admin_user"])
    trip.refresh_from_db()
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT


@pytest.mark.django_db
def test_migration_0010_moves_trips_in_retired_statuses_to_customs_and_keeps_history():
    import importlib

    from django.apps import apps as django_apps

    migration = importlib.import_module("apps.trips.migrations.0010_retire_going_to_statuses")
    fx = _setup_fixtures("RETIRED-MIG")
    going_client = _make_trip(fx, _make_truck("TRK-MIG-1"), "TRIP-MIG-001", status=Trip.Status.CUSTOMS)
    going_stock = _make_trip(fx, _make_truck("TRK-MIG-2"), "TRIP-MIG-002", status=Trip.Status.CUSTOMS)
    untouched = _make_trip(fx, _make_truck("TRK-MIG-3"), "TRIP-MIG-003", status=Trip.Status.BORDER)
    Trip.objects.filter(pk=going_client.pk).update(status="GOING_TO_CLIENT")
    Trip.objects.filter(pk=going_stock.pk).update(status="GOING_TO_COMPANY_STOCK")
    TripStatusHistory.objects.create(
        trip=going_client, previous_status="CUSTOMS", new_status="GOING_TO_CLIENT",
        changed_by=fx["admin_user"],
    )

    migration.remap_retired_statuses(django_apps, None)

    going_client.refresh_from_db()
    going_stock.refresh_from_db()
    untouched.refresh_from_db()
    assert going_client.status == Trip.Status.CUSTOMS
    assert going_stock.status == Trip.Status.CUSTOMS
    assert untouched.status == Trip.Status.BORDER
    assert going_client.status_history.filter(new_status="GOING_TO_CLIENT").count() == 1


@pytest.mark.django_db
def test_resuming_a_legacy_trip_blocked_from_a_retired_status_targets_customs():
    fx = _setup_fixtures("RETIRED-BLOCK")
    trip = _make_trip(fx, _make_truck("TRK-RETIRED-4"), "TRIP-RETIRED-004", status=Trip.Status.BLOCKED)
    TripStatusHistory.objects.create(
        trip=trip, previous_status="GOING_TO_CLIENT", new_status=Trip.Status.BLOCKED,
        changed_by=fx["admin_user"],
    )

    assert TripWorkflowService.get_allowed_targets(trip) == {Trip.Status.CUSTOMS}
```

- [ ] **Step 2: Mettre à jour les tests existants qui référencent les statuts supprimés** (`backend/apps/trips/tests.py`, repérer avec `grep -n "GOING_TO" apps/trips/tests.py`) :
  - `FULL_SEQUENCE_AFTER_ASSIGNED` (~l.129) : supprimer la ligne `Trip.Status.GOING_TO_CLIENT,`.
  - `COMPANY_STOCK_SEQUENCE_AFTER_CUSTOMS` (~l.139) : supprimer `Trip.Status.GOING_TO_COMPANY_STOCK,`.
  - `_advance_to_completed` et `_advance_to_arrived_at_client` (~l.287 et ~l.307) : remplacer `target == Trip.Status.GOING_TO_CLIENT` par `target == Trip.Status.ARRIVED_AT_CLIENT`.
  - `test_workflow_blocks_client_statuses_without_customer_and_routes_to_company_stock` (~l.572-580) : remplacer les 5 lignes d'assertions/`raises` par
    ```python
    assert Trip.Status.ARRIVED_AT_CLIENT not in allowed
    assert Trip.Status.QUANTITY_CONTROL not in allowed
    assert Trip.Status.ARRIVED_AT_COMPANY_STOCK in allowed

    with pytest.raises(InvalidTripTransition):
        TripWorkflowService.transition_trip(
            trip.id, Trip.Status.ARRIVED_AT_CLIENT, fx["admin_user"]
        )
    ```
  - `test_workflow_allows_client_statuses_after_customer_assignment` (~l.691-692) : `assert Trip.Status.ARRIVED_AT_CLIENT in allowed` / `assert Trip.Status.ARRIVED_AT_COMPANY_STOCK not in allowed`.
  - Liste `_FORWARD_SEQUENCE_STATUS_NAMES` (~l.1046) : supprimer `"GOING_TO_CLIENT",`.
  - `backend/apps/reports/test_production_like_scenario.py` : supprimer `Trip.Status.GOING_TO_CLIENT,` (~l.383) et `Trip.Status.GOING_TO_COMPANY_STOCK,` (~l.656) ; sur ~l.665 et ~l.669 remplacer `GOING_TO_CLIENT` par `ARRIVED_AT_CLIENT` (libellés compris) ; supprimer la ligne ~l.770 `stock_trip = ...transition_trip(stock_trip.id, Trip.Status.GOING_TO_CLIENT, user)` (la ligne suivante passe déjà à `ARRIVED_AT_CLIENT`, désormais atteignable depuis `STOCKED`).

- [ ] **Step 3: Vérifier l'échec**

Run: `cd backend && .venv/bin/python -m pytest apps/trips/tests.py -q -k "retired or migration_0010" --create-db 2>&1 | tail -n 15`
Expected: FAIL (enum contient encore les statuts / module de migration absent).

- [ ] **Step 4: Implémenter le modèle et le service**

`backend/apps/trips/models.py` — supprimer `GOING_TO_COMPANY_STOCK = ...` et `GOING_TO_CLIENT = ...` de l'enum, corriger le commentaire (`STOCKED/GOING_TO_CLIENT/ARRIVED_AT_CLIENT/` → `STOCKED/ARRIVED_AT_CLIENT/`), et ajouter après `NON_OCCUPYING_STATUSES = ...` :

```python
    # Statuses retired 2026-09-24 (docs/superpowers/specs/2026-09-24-
    # simplification-statuts-trajet-design.md). Trips sitting in one were moved
    # to CUSTOMS by migration 0010; history rows (append-only) still carry the
    # old names, so anything reading a *previous_status* back out of history
    # must map it through this table before treating it as a live status.
    RETIRED_STATUS_REMAP = {
        "GOING_TO_CLIENT": "CUSTOMS",
        "GOING_TO_COMPANY_STOCK": "CUSTOMS",
    }
```

`backend/apps/trips/services.py` — dans `FORWARD_TRANSITIONS`, remplacer `Trip.Status.CUSTOMS: Trip.Status.GOING_TO_CLIENT,` par `Trip.Status.CUSTOMS: Trip.Status.ARRIVED_AT_CLIENT,` et supprimer les entrées `GOING_TO_CLIENT: ARRIVED_AT_CLIENT` et `GOING_TO_COMPANY_STOCK: ARRIVED_AT_COMPANY_STOCK`. Ajouter, avant `get_allowed_targets` :

```python
    @classmethod
    def _next_step(cls, trip: Trip, status):
        """The single forward status after `status` for this trip, resolving
        the client/stock fork: a trip with neither a client nor a customer
        order leaves CUSTOMS for the company stock instead of a client."""
        has_customer = bool(trip.client_id or trip.customer_order_id)
        if status == Trip.Status.STOCKED:
            return Trip.Status.ARRIVED_AT_CLIENT if has_customer else None
        forward = cls.FORWARD_TRANSITIONS.get(status)
        if forward == Trip.Status.ARRIVED_AT_CLIENT and not has_customer:
            return Trip.Status.ARRIVED_AT_COMPANY_STOCK
        return forward
```

Dans `get_allowed_targets`, remplacer tout le bloc `forward = cls.FORWARD_TRANSITIONS.get(current_status) ... allowed.add(Trip.Status.GOING_TO_CLIENT)` (les deux `if` avant `if current_status in cls.CANCELLABLE_FROM`) par :

```python
        forward = cls._next_step(trip, current_status)
        if forward:
            allowed.add(forward)
```

`_status_before_blocked` — remplacer la dernière ligne par :

```python
        if not last_block_entry:
            return None
        previous = last_block_entry.previous_status
        return Trip.RETIRED_STATUS_REMAP.get(previous, previous)
```

`backend/apps/sales/services.py` — supprimer la ligne `"GOING_TO_CLIENT",` de `_LOADED_ONWARD_STATUSES`. `backend/apps/reports/views/dashboard.py:400` — remplacer `GOING_TO_COMPANY_STOCK/earlier` par `earlier`.

- [ ] **Step 5: Créer la migration**

Run: `cd backend && .venv/bin/python manage.py makemigrations trips -n retire_going_to_statuses`
Puis éditer le fichier généré `0010_retire_going_to_statuses.py` : ajouter en haut du module

```python
RETIRED = ["GOING_TO_CLIENT", "GOING_TO_COMPANY_STOCK"]


def remap_retired_statuses(apps, schema_editor):
    """A trip 'on the road to the client/stock' is past customs and not yet
    arrived - exactly CUSTOMS in the new flow. History rows stay untouched."""
    Trip = apps.get_model("trips", "Trip")
    Trip.objects.filter(status__in=RETIRED).update(status="CUSTOMS")
```

et insérer en **première** opération de `operations` : `migrations.RunPython(remap_retired_statuses, migrations.RunPython.noop),` (l'`AlterField` généré suit).

- [ ] **Step 6: Vérifier**

Run: `cd backend && .venv/bin/python -m pytest apps/trips/tests.py apps/reports/test_production_like_scenario.py -q --create-db 2>&1 | tail -n 15`
Expected: tout vert (les 5 nouveaux tests inclus). `makemigrations --check` : `.venv/bin/python manage.py makemigrations --check --dry-run | tail -n 3` → « No changes detected ».

- [ ] **Step 7: Commit**

```bash
git add backend/apps/trips backend/apps/sales/services.py backend/apps/reports
git commit -m "feat(trips): retire GOING_TO_CLIENT and GOING_TO_COMPANY_STOCK statuses

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Saut de statuts (backend)

**Files:**
- Modify: `backend/apps/trips/services.py` (`get_allowed_targets`, `transition_trip`)
- Modify: `backend/apps/trips/views.py` (action `status`, ~l.145-176)
- Test: `backend/apps/trips/tests.py`

**Interfaces:**
- Consumes: `_next_step` (tâche 1).
- Produces: `TripWorkflowService._skip_path(trip) -> list[Status]`, `TripWorkflowService.get_path_to(trip, target_status) -> list[Status]` (`[]` si refusé), `trip.traversed_statuses: list[Status]` sur l'instance renvoyée par `transition_trip`, clé JSON `traversed_statuses` dans la réponse de `POST /status/`.

- [ ] **Step 1: Réécrire le test obsolète** — `test_trip_workflow_requires_road_transit_before_transit` (~l.381) devient (renommer aussi la fonction) :

```python
@pytest.mark.django_db
def test_trip_workflow_lets_a_trip_skip_ahead_from_loaded():
    fx = _setup_fixtures("ROAD")
    truck = _make_truck("TRK-ROAD")
    trip = _make_trip(fx, truck, "TRIP-ROAD-001", status=Trip.Status.LOADED)

    assert TripWorkflowService.get_allowed_targets(trip) == {
        Trip.Status.ROAD_TRANSIT,
        Trip.Status.IN_TRANSIT,
        Trip.Status.BORDER,
        Trip.Status.CUSTOMS,
        Trip.Status.ARRIVED_AT_COMPANY_STOCK,
        Trip.Status.STOCKED,
        Trip.Status.CANCELLED,
        Trip.Status.BLOCKED,
    }

    TripWorkflowService.transition_trip(trip.id, Trip.Status.IN_TRANSIT, fx["admin_user"])
    trip.refresh_from_db()
    assert trip.status == Trip.Status.IN_TRANSIT
```

- [ ] **Step 2: Écrire les nouveaux tests** (fin de `tests.py`) :

```python
def _client_trip(fx, code, status):
    trip = _make_trip(fx, _make_truck(f"TRK-{code}"), f"TRIP-{code}-001", status=status)
    trip.client = Customer.objects.create(name=f"Client {code}")
    trip.destination_type = Trip.DestinationType.CUSTOMER
    trip.save()
    return trip


@pytest.mark.django_db
def test_skip_records_one_history_row_per_traversed_status_and_notes_on_the_last():
    fx = _setup_fixtures("SKIP-HIST")
    trip = _make_trip(fx, _make_truck("TRK-SKIP-HIST"), "TRIP-SKIP-HIST-001")

    result = TripWorkflowService.transition_trip(
        trip.id, Trip.Status.CUSTOMS, fx["admin_user"], notes="direct"
    )

    S = Trip.Status
    assert result.status == S.CUSTOMS
    assert result.traversed_statuses == [
        S.SENT_FOR_LOADING, S.LOADING, S.LOADED, S.ROAD_TRANSIT, S.IN_TRANSIT, S.BORDER, S.CUSTOMS,
    ]
    rows = list(
        result.status_history.order_by("id").values_list("previous_status", "new_status", "notes")
    )
    assert rows == [
        (S.ASSIGNED, S.SENT_FOR_LOADING, ""),
        (S.SENT_FOR_LOADING, S.LOADING, ""),
        (S.LOADING, S.LOADED, ""),
        (S.LOADED, S.ROAD_TRANSIT, ""),
        (S.ROAD_TRANSIT, S.IN_TRANSIT, ""),
        (S.IN_TRANSIT, S.BORDER, ""),
        (S.BORDER, S.CUSTOMS, "direct"),
    ]


@pytest.mark.django_db
def test_skip_fork_follows_the_client_assigned_at_call_time():
    fx = _setup_fixtures("SKIP-FORK")
    trip = _client_trip(fx, "SKIP-FORK", Trip.Status.LOADED)

    allowed = TripWorkflowService.get_allowed_targets(trip)
    assert Trip.Status.ARRIVED_AT_CLIENT in allowed
    assert Trip.Status.ARRIVED_AT_COMPANY_STOCK not in allowed
    assert Trip.Status.STOCKED not in allowed

    TripWorkflowService.transition_trip(trip.id, Trip.Status.ARRIVED_AT_CLIENT, fx["admin_user"])
    trip.refresh_from_db()
    assert trip.status == Trip.Status.ARRIVED_AT_CLIENT


@pytest.mark.django_db
def test_skip_never_reaches_delivered_or_completed():
    fx = _setup_fixtures("SKIP-FORM")
    trip = _client_trip(fx, "SKIP-FORM", Trip.Status.CUSTOMS)

    allowed = TripWorkflowService.get_allowed_targets(trip)
    assert Trip.Status.DELIVERED not in allowed
    assert Trip.Status.COMPLETED not in allowed
    for target in (Trip.Status.DELIVERED, Trip.Status.COMPLETED):
        with pytest.raises(InvalidTripTransition):
            TripWorkflowService.transition_trip(trip.id, target, fx["admin_user"])
    trip.refresh_from_db()
    assert trip.status == Trip.Status.CUSTOMS


@pytest.mark.django_db
def test_invalid_skip_target_writes_no_history_and_keeps_the_status():
    fx = _setup_fixtures("SKIP-BACK")
    trip = _make_trip(fx, _make_truck("TRK-SKIP-BACK"), "TRIP-SKIP-BACK-001", status=Trip.Status.LOADED)

    with pytest.raises(InvalidTripTransition):
        TripWorkflowService.transition_trip(trip.id, Trip.Status.LOADING, fx["admin_user"])
    with pytest.raises(InvalidTripTransition):
        TripWorkflowService.transition_trip(trip.id, "NOT_A_STATUS", fx["admin_user"])

    trip.refresh_from_db()
    assert trip.status == Trip.Status.LOADED
    assert trip.status_history.count() == 0


@pytest.mark.django_db
def test_block_and_resume_after_a_skip_returns_to_the_skipped_to_status():
    fx = _setup_fixtures("SKIP-BLOCK")
    trip = _make_trip(fx, _make_truck("TRK-SKIP-BLOCK"), "TRIP-SKIP-BLOCK-001")

    TripWorkflowService.transition_trip(trip.id, Trip.Status.BORDER, fx["admin_user"])
    TripWorkflowService.transition_trip(trip.id, Trip.Status.BLOCKED, fx["admin_user"], notes="x")
    trip.refresh_from_db()
    assert TripWorkflowService.get_allowed_targets(trip) == {Trip.Status.BORDER}

    TripWorkflowService.transition_trip(trip.id, Trip.Status.BORDER, fx["admin_user"])
    trip.refresh_from_db()
    assert trip.status == Trip.Status.BORDER


@pytest.mark.django_db
def test_api_status_skip_returns_traversed_statuses_and_refuses_form_only_targets():
    fx = _setup_fixtures("API-SKIP")
    trip = _make_trip(fx, _make_truck("TRK-API-SKIP"), "TRIP-API-SKIP-001")
    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    allowed = client.get(f"/api/trips/{trip.id}/allowed-statuses/")
    assert "CUSTOMS" in allowed.data["statuses"]
    assert "DELIVERED" not in allowed.data["statuses"]

    response = client.post(f"/api/trips/{trip.id}/status/", {"new_status": "LOADING"})
    assert response.status_code == 200, response.data
    assert response.data["status"] == "LOADING"
    assert response.data["traversed_statuses"] == ["SENT_FOR_LOADING", "LOADING"]

    refused = client.post(f"/api/trips/{trip.id}/status/", {"new_status": "DELIVERED"})
    assert refused.status_code == 400
```

- [ ] **Step 3: Vérifier l'échec**

Run: `cd backend && .venv/bin/python -m pytest apps/trips/tests.py -q -k "skip" 2>&1 | tail -n 15`
Expected: FAIL (`_skip_path`/`traversed_statuses` absents, sauts refusés).

- [ ] **Step 4: Implémenter** — dans `services.py`, ajouter avant `get_allowed_targets` :

```python
    @classmethod
    def _skip_path(cls, trip: Trip) -> list:
        """Statuses reachable by moving forward from trip.status, in order.
        Stops before DELIVERED/COMPLETED: those are only ever entered one step
        at a time by their own forms (delivery control, client verification)."""
        path = []
        status = trip.status
        while True:
            status = cls._next_step(trip, status)
            if status is None or status in {Trip.Status.DELIVERED, Trip.Status.COMPLETED}:
                return path
            path.append(status)

    @classmethod
    def get_path_to(cls, trip: Trip, target_status) -> list:
        """Statuses a transition to `target_status` walks through (target
        last); [] when the target isn't allowed from the trip's status."""
        if target_status not in cls.get_allowed_targets(trip):
            return []
        skip_path = cls._skip_path(trip)
        if target_status in skip_path:
            return skip_path[: skip_path.index(target_status) + 1]
        return [target_status]
```

Dans `get_allowed_targets`, juste après `allowed.add(forward)` (bloc `if forward:`), ajouter `allowed.update(cls._skip_path(trip))`.

Dans `transition_trip`, remplacer le bloc allowed-check + écriture d'historique (de `allowed = cls.get_allowed_targets(trip)` jusqu'au `TripStatusHistory.objects.create(...)` inclus) par :

```python
        path = cls.get_path_to(trip, target_status)
        if not path:
            raise InvalidTripTransition(
                f"Impossible de faire passer le trajet {trip.reference} de "
                f"{current_status} a {target_status}."
            )

        previous_status = trip.status
        trip.status = target_status
        trip.save(update_fields=["status", "updated_at"])

        # One history row per traversed status keeps the audit trail complete
        # when several statuses are skipped in one action; the note rides on
        # the last row (the status the user actually picked).
        step_from = previous_status
        for index, step in enumerate(path):
            TripStatusHistory.objects.create(
                trip=trip,
                previous_status=step_from,
                new_status=step,
                changed_by=actor,
                notes=notes if index == len(path) - 1 else "",
            )
            step_from = step
        trip.traversed_statuses = path
```

`views.py`, action `status` : remplacer la dernière ligne `return Response(TripSerializer(trip, context={"request": request}).data)` par :

```python
        data = TripSerializer(trip, context={"request": request}).data
        data["traversed_statuses"] = trip.traversed_statuses
        return Response(data)
```

- [ ] **Step 5: Vérifier**

Run: `cd backend && .venv/bin/python -m pytest apps/trips/tests.py apps/reports/test_production_like_scenario.py -q 2>&1 | tail -n 15`
Expected: tout vert.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/trips
git commit -m "feat(trips): skip ahead across statuses with one history row per status

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Statuts côté frontend

**Files:**
- Modify: `frontend/src/modules/trips/types.ts`, `TripStatusBoard.vue` (~l.94, ~l.120), `TripDetail.vue` (`customsReachedStatuses` ~l.166-169)
- Modify: `frontend/src/modules/trips/api.ts` (`postTripStatus`)
- Test: `frontend/src/modules/trips/__tests__/TripDetail.spec.ts`, `TripStatusBoard.spec.ts`

**Interfaces:**
- Produces: `TripStatusChange = Trip & { traversed_statuses?: TripStatus[] }` exporté par `api.ts`; `postTripStatus(...) : Promise<TripStatusChange>`.

- [ ] **Step 1: Retirer les statuts** : dans `types.ts`, supprimer `'GOING_TO_COMPANY_STOCK'` et `'GOING_TO_CLIENT'` de l'union `TripStatus`, de `TRIP_STATUSES` et de `TRIP_PIPELINE_STATUSES` (3 endroits chacun) ; corriger le commentaire « The 14 statuses ». `TripDetail.vue` : supprimer les 2 lignes de `customsReachedStatuses`. `TripStatusBoard.vue` : filtre `to-deliver` → `['ARRIVED_AT_CLIENT'].includes(t.status)` ; commentaire ~l.94 : retirer `GOING_TO_COMPANY_STOCK`. **Ne pas toucher** aux libellés `trips.status.*` des locales (historique).

- [ ] **Step 2: Typer la réponse** — dans `api.ts` (vérifier l'import de `TripStatus` depuis `./types`) :

```ts
export type TripStatusChange = Trip & { traversed_statuses?: TripStatus[] }

export function postTripStatus(
  tripId: number,
  newStatus: string,
  notes = '',
): Promise<TripStatusChange> {
  return apiClient
    .post<TripStatusChange>(`/trips/${tripId}/status/`, { new_status: newStatus, notes })
    .then((r) => r.data)
}
```

- [ ] **Step 3: Corriger les tests** : `grep -rn "GOING_TO" frontend/src --include="*.ts" --include="*.vue" | grep -v locales` — remplacer chaque occurrence restante dans les specs (`TripDetail.spec.ts`, `TripStatusBoard.spec.ts`) par `ARRIVED_AT_CLIENT` (ou supprimer la ligne si redondante).

- [ ] **Step 4: Vérifier**

Run: `cd frontend && npx vitest run src/modules/trips src/modules/dashboard 2>&1 | tail -n 20` puis `npx vue-tsc -b 2>&1 | tail -n 10`
Expected: vert, aucune erreur de type.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/trips
git commit -m "refactor(trips-ui): drop the retired statuses and type the status-change response

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: File de popups de frais avec « Passer » / « Tout passer »

**Files:**
- Modify: `frontend/src/modules/finance/ExpenseForm.vue` (prop `cancelLabel` + bouton Annuler)
- Modify: `frontend/src/modules/finance/TransportPaymentForm.vue` (idem — `grep -n "common.cancel"`)
- Modify: `frontend/src/modules/trips/TripDetail.vue`
- Modify: `frontend/src/locales/{fr,en,ar}.json` (clés `trips.detail.skipFee`, `trips.detail.skipAllFees`, à côté de `addTransportFee`)
- Test: `frontend/src/modules/trips/__tests__/TripDetail.spec.ts`

**Interfaces:**
- Consumes: `postTripStatus(...) : Promise<TripStatusChange>` (tâche 3).
- Produces: prop `cancelLabel?: string` sur les deux formulaires ; dans `TripDetail.vue` : `feeQueue: Ref<TripStatus[]>`, `inFeeQueue: Ref<boolean>`, `showNextFee(): void`, `skipAllFees(): void`, `openAutomaticFeePopup(status): boolean`.

- [ ] **Step 1: Écrire les tests qui échouent** — dans `TripDetail.spec.ts`, après le test `opens a transit expense popup after ROAD_TRANSIT -> IN_TRANSIT...` (~l.1443-1460), ajouter (réutilise `mountAt`, `setUser`, `makeTrip`, `postTripStatus`, `allowedStatusesToReturn`, `tripResourceGet` déjà définis en tête de fichier) :

```ts
  async function applyStatus(wrapper: Awaited<ReturnType<typeof mountAt>>, status: string) {
    await wrapper.find('#next_status').setValue(status)
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Appliquer')!
      .trigger('click')
    await flushPromises()
  }
  const buttonNamed = (wrapper: Awaited<ReturnType<typeof mountAt>>, label: string) =>
    wrapper.findAll('button').find((b) => b.text() === label)

  it('chains one fee popup per skipped status, each with a "Passer" button', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'ASSIGNED' }))
    allowedStatusesToReturn = ['LOADING']
    postTripStatus.mockResolvedValueOnce({
      ...makeTrip({ status: 'ROAD_TRANSIT' }),
      traversed_statuses: ['SENT_FOR_LOADING', 'LOADING', 'LOADED', 'ROAD_TRANSIT'],
    })

    const wrapper = await mountAt()
    await applyStatus(wrapper, 'LOADING')

    // 1) transporter commission
    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(true)
    await buttonNamed(wrapper, 'Passer')!.trigger('click')
    await flushPromises()
    // 2) loading fee
    expect((wrapper.find('#category').element as HTMLSelectElement).value).toBe('loading')
    await buttonNamed(wrapper, 'Passer')!.trigger('click')
    await flushPromises()
    // 3) road transit fee (LOADED carries none)
    expect((wrapper.find('#category').element as HTMLSelectElement).value).toBe('road_transit')
    await buttonNamed(wrapper, 'Passer')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('#category').exists()).toBe(false)
    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(false)
  })

  it('"Tout passer" closes the whole fee queue at once', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'ASSIGNED' }))
    allowedStatusesToReturn = ['LOADING']
    postTripStatus.mockResolvedValueOnce({
      ...makeTrip({ status: 'CUSTOMS' }),
      traversed_statuses: ['SENT_FOR_LOADING', 'LOADING', 'ROAD_TRANSIT', 'CUSTOMS'],
    })

    const wrapper = await mountAt()
    await applyStatus(wrapper, 'LOADING')
    await buttonNamed(wrapper, 'Tout passer')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('#category').exists()).toBe(false)
    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(false)
  })

  it('opens no fee popup and stays usable after a skip without finance create permission', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'ASSIGNED' }))
    allowedStatusesToReturn = ['LOADING']
    postTripStatus.mockResolvedValueOnce({
      ...makeTrip({ status: 'LOADING' }),
      traversed_statuses: ['SENT_FOR_LOADING', 'LOADING'],
    })

    const wrapper = await mountAt()
    await applyStatus(wrapper, 'LOADING')

    expect(wrapper.find('#category').exists()).toBe(false)
    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(false)
    expect(wrapper.find('#next_status').exists()).toBe(true)
  })
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd frontend && npx vitest run src/modules/trips/__tests__/TripDetail.spec.ts -t "fee popup|Tout passer|without finance create" 2>&1 | tail -n 20`
Expected: FAIL (pas de bouton « Passer »).

- [ ] **Step 3: Locales** — ajouter à côté de `addTransportFee` dans chaque fichier (`grep -n addTransportFee frontend/src/locales/*.json`) : fr `"skipFee": "Passer", "skipAllFees": "Tout passer"` ; en `"Skip"`, `"Skip all"` ; ar `"تخطي"`, `"تخطي الكل"`.

- [ ] **Step 4: Formulaires** — dans `ExpenseForm.vue`, ajouter `cancelLabel?: string` aux props et remplacer `{{ t('common.cancel') }}` du bouton Annuler par `{{ cancelLabel ?? t('common.cancel') }}` ; même chose dans `TransportPaymentForm.vue` (props + bouton Annuler).

- [ ] **Step 5: TripDetail.vue** — (a) remplacer la fonction `openAutomaticFeePopup` entière (`sed -n '/^function openAutomaticFeePopup/,/^}/p'` pour la retrouver) par une version qui **retourne un booléen** (`false` à chaque `return` de garde, `true` après ouverture d'un formulaire) :

```ts
function openAutomaticFeePopup(targetStatus: TripStatus): boolean {
  if (!canManageExpenses.value || !trip.value) return false
  if (targetStatus === 'SENT_FOR_LOADING') {
    // Internal (flotte propre) trips never owe a commission, and a trip has
    // exactly one settlement (see 2026-09-10 bug fix).
    if (!trip.value.transporter || trip.value.transporter_detail?.is_internal) return false
    if (transportPayments.value.length) return false
    automaticTransportTitle.value = t('trips.detail.autoExpense.transporterCommission')
    showTransportPaymentForm.value = true
    return true
  }
  const expense = automaticExpenseByStatus[targetStatus]
  if (!expense) return false
  automaticExpense.value = expense
  showExpenseForm.value = true
  return true
}
```

(b) juste après cette fonction, ajouter la file :

```ts
// Fee popups still to show after a status change or a multi-status skip: one
// per traversed status that carries a fee, in path order. "Passer" (the form's
// cancel button, relabelled while inFeeQueue) moves on to the next one.
const feeQueue = ref<TripStatus[]>([])
const inFeeQueue = ref(false)

function showNextFee() {
  while (feeQueue.value.length) {
    if (openAutomaticFeePopup(feeQueue.value.shift()!)) return
  }
  inFeeQueue.value = false
}

function skipAllFees() {
  feeQueue.value = []
  inFeeQueue.value = false
  showExpenseForm.value = false
  showTransportPaymentForm.value = false
  automaticExpense.value = null
  automaticTransportTitle.value = null
}

function onExpenseCancel() {
  showExpenseForm.value = false
  automaticExpense.value = null
  editingExpense.value = null
  if (inFeeQueue.value) showNextFee()
}

function onTransportPaymentCancel() {
  showTransportPaymentForm.value = false
  automaticTransportTitle.value = null
  editingTransportPayment.value = null
  transportPaymentFormMode.value = 'edit'
  if (inFeeQueue.value) showNextFee()
}
```

(c) `onChangeStatus` : remplacer `await postTripStatus(...)` par `const result = await postTripStatus(tripId.value, nextStatus.value, statusNotes.value)` et la ligne finale `openAutomaticFeePopup(targetStatus)` par :

```ts
    feeQueue.value = [...(result?.traversed_statuses ?? [targetStatus])]
    inFeeQueue.value = true
    showNextFee()
```

(d) `onExpenseSaved` et `onTransportPaymentSaved` : ajouter à la toute fin de chacune `if (inFeeQueue.value) showNextFee()`.

(e) Template : sur `<ExpenseForm>` remplacer le handler `@cancel="…"` par `@cancel="onExpenseCancel"` et ajouter `:cancel-label="inFeeQueue ? t('trips.detail.skipFee') : undefined"` ; sur `<TransportPaymentForm>` idem avec `@cancel="onTransportPaymentCancel"`. Dans chacun des deux overlays, juste après la fermeture du formulaire (dans le `div.max-h-[90vh]`), ajouter :

```vue
          <div v-if="inFeeQueue && feeQueue.length" class="mt-2 flex justify-end">
            <Button variant="ghost" data-test="skip-all-fees" @click="skipAllFees">
              {{ t('trips.detail.skipAllFees') }}
            </Button>
          </div>
```

- [ ] **Step 6: Vérifier**

Run: `cd frontend && npx vitest run src/modules/trips/__tests__/TripDetail.spec.ts src/modules/finance 2>&1 | tail -n 20`
Expected: vert (les anciens tests de popups unitaires passent inchangés : `traversed_statuses` absent → file `[targetStatus]`).

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(trips-ui): chain fee popups after a status skip with Passer / Tout passer

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: « Commission transporteur » dans « Ajouter des frais »

**Files:**
- Modify: `frontend/src/modules/finance/ExpenseForm.vue`
- Modify: `frontend/src/modules/trips/TripDetail.vue` (bouton séparé ~l.981-990, overlay `ExpenseForm`)
- Modify: `frontend/src/locales/{fr,en,ar}.json` (`finance.expense.transportCommission` à côté de `paidByCustomer` ; suppression de `trips.detail.addTransportFee`)
- Test: `frontend/src/modules/trips/__tests__/TripDetail.spec.ts`

**Interfaces:**
- Consumes: `inFeeQueue` (tâche 4).
- Produces: prop `commissionAvailable?: boolean` et événement `select-commission` sur `ExpenseForm` ; valeur sentinelle `'__transport_commission__'`.

- [ ] **Step 1: Réécrire les 2 tests du bouton séparé** (~l.750-776 de `TripDetail.spec.ts`, `hides "Add transport fee"…` et `still shows "Add transport fee"…`) en :

```ts
  const COMMISSION_VALUE = '__transport_commission__'
  const openAddExpense = async (wrapper: Awaited<ReturnType<typeof mountAt>>) => {
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Ajouter un frais'))!
      .trigger('click')
    await flushPromises()
  }

  it('no longer shows a separate "Add transport fee" button', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    const wrapper = await mountAt()
    expect(wrapper.text()).not.toContain('Ajouter des frais de transport')
  })

  it('offers "Commission transporteur" in the add-expense category list and switches to the commission form', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    const wrapper = await mountAt()
    await openAddExpense(wrapper)

    const option = wrapper.find(`#category option[value="${COMMISSION_VALUE}"]`)
    expect(option.exists()).toBe(true)
    expect(option.text()).toBe('Commission transporteur')

    await wrapper.find('#category').setValue(COMMISSION_VALUE)
    await flushPromises()

    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(true)
    expect(wrapper.find('#category').exists()).toBe(false)
  })

  it('hides the commission option once a payment exists for the trip', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    transportPaymentsToReturn = [makeTransportPayment()]
    const wrapper = await mountAt()
    await openAddExpense(wrapper)

    expect(wrapper.find(`#category option[value="${COMMISSION_VALUE}"]`).exists()).toBe(false)
  })

  it('hides the commission option for an internal (company fleet) transporter', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(
      makeTrip({ transporter_detail: { id: 2, name: 'Flotte propre', is_internal: true } }),
    )
    const wrapper = await mountAt()
    await openAddExpense(wrapper)

    expect(wrapper.find(`#category option[value="${COMMISSION_VALUE}"]`).exists()).toBe(false)
  })
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd frontend && npx vitest run src/modules/trips/__tests__/TripDetail.spec.ts -t "commission|transport fee" 2>&1 | tail -n 20`
Expected: FAIL (option absente, bouton encore présent).

- [ ] **Step 3: ExpenseForm.vue** — props : ajouter `commissionAvailable?: boolean` ; émissions : `defineEmits<{ success: [customerId: number | null]; cancel: []; 'select-commission': [] }>()` ; après `const categoryLabel = ...` :

```ts
// Sentinel category: the transporter commission is a TransportPayment (own
// debt/deduction/correction lifecycle), not an Expense - picking it hands the
// modal over to TransportPaymentForm (TripDetail.vue) instead of submitting here.
const TRANSPORT_COMMISSION_VALUE = '__transport_commission__'
```

et, après la déclaration de `form` :

```ts
watch(
  () => form.value.category,
  (category) => {
    if (category === TRANSPORT_COMMISSION_VALUE) emit('select-commission')
  },
)
```

Template : après le `<option v-for="c in categories" ...>…</option>` du `<select id="category">` ajouter

```vue
            <option
              v-if="commissionAvailable && !editingExpense"
              :value="TRANSPORT_COMMISSION_VALUE"
            >
              {{ t('finance.expense.transportCommission') }}
            </option>
```

- [ ] **Step 4: TripDetail.vue** — ajouter (près de `canManageExpenses`, après la déclaration de `transportPayments`) :

```ts
// One settlement per trip, external transporters only (same rule as the
// automatic popup at SENT_FOR_LOADING).
const canAddCommission = computed(
  () =>
    canManageExpenses.value &&
    !!trip.value?.transporter &&
    !trip.value.transporter_detail?.is_internal &&
    !transportPayments.value.length,
)

function onSelectCommission() {
  showExpenseForm.value = false
  automaticExpense.value = null
  editingExpense.value = null
  automaticTransportTitle.value = null
  showTransportPaymentForm.value = true
}
```

Sur `<ExpenseForm>` ajouter `:commission-available="canAddCommission && !inFeeQueue"` et `@select-commission="onSelectCommission"`. **Supprimer** le second `<Button>` (celui avec `addTransportFee`, ~l.981-990).

- [ ] **Step 5: Locales** — ajouter `finance.expense.transportCommission` : fr « Commission transporteur », en « Transporter commission », ar « عمولة الناقل » ; supprimer `trips.detail.addTransportFee` des 3 fichiers après avoir vérifié `grep -rn addTransportFee frontend/src | grep -v locales` (doit être vide).

- [ ] **Step 6: Vérifier**

Run: `cd frontend && npx vitest run src/modules/trips src/modules/finance 2>&1 | tail -n 20`
Expected: vert.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(trips-ui): add transporter commission to the add-expense category list

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Vérification finale et recette

**Files:** aucun changement attendu (correctifs éventuels seulement).

- [ ] **Step 1: Suites complètes, une seule fois**

Run (backend) : `cd backend && .venv/bin/python -m pytest -q --create-db 2>&1 | tail -n 8`
Expected : tout vert (baseline connue avant chantier : 1 065 tests).
Run (frontend) : `cd frontend && npx vitest run 2>&1 | tail -n 8 && npx vue-tsc -b 2>&1 | tail -n 5 && npx eslint $(git diff --name-only main -- 'frontend/src/**/*.ts' 'frontend/src/**/*.vue' | sed 's#^frontend/##') 2>&1 | tail -n 10`
Expected : vert, 0 erreur de type, 0 erreur lint. Formater les fichiers touchés si besoin : `npx prettier --check $(git diff --name-only main -- frontend/src | sed 's#^frontend/##')`.

- [ ] **Step 2: Migration sur la vraie base de dev** (idempotente, sans risque) : `cd backend && .venv/bin/python manage.py migrate trips 2>&1 | tail -n 3`.

- [ ] **Step 3: Recette manuelle par l'utilisateur (0 token)** — demander à l'utilisateur de vérifier dans l'app :
  1. Trajet neuf → sélecteur : tous les statuts suivants sont proposés ; sauter d'Assigné à Douane → popups enchaînés (commission, chargement, route, transit, frontière, douane), « Passer » puis « Tout passer » fonctionnent ; la timeline montre une ligne par statut.
  2. Trajet sans client : après Douane → « Arrivé stock » puis « Stocké » ; avec client → « Arrivé chez le client » ; « Livré »/« Terminé » jamais proposés dans le sélecteur.
  3. « Ajouter des frais » : « Commission transporteur » apparaît (transporteur externe, sans commission existante), bascule vers le formulaire au litre ; absente sinon ; plus de bouton « Ajouter des frais de transport ».
  4. Un ancien trajet « En route vers… » apparaît maintenant à « Douane ».

- [ ] **Step 4: Clôture** — après accord de l'utilisateur, invoquer `superpowers:finishing-a-development-branch` (merge/PR selon son choix) et enregistrer une entrée mémoire courte (`project_trip_status_simplification_2026-09-24.md` + ligne dans `MEMORY.md`) : décisions D1-D4, branche, résultats de tests.

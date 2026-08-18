# Plan d'Action Technique - Phase 3 : Customer Orders and Truck Operations

Ce document présente le plan de développement détaillé pour la **Phase 3** de l'ERP Fuel Logistics. L'objectif principal est de modéliser la règle métier centrale de l'architecture : **Camion ≠ Trajet (Trip) ≠ Commande Client**. 

Les commandes clients représentent des enveloppes de demande commerciale globales. Elles sont honorées par des trajets indépendants qui peuvent réutiliser les mêmes camions physiques à plusieurs reprises.

---

## 1. Choix de Conception & Règles Métier Clés

### A. Séparation Stricte : Camion (Truck) ≠ Trajet (Trip) ≠ Commande Client (CustomerOrder)
- Un camion physique (`Truck`) peut effectuer plusieurs voyages successifs (rotations) pour honorer une ou plusieurs commandes clients.
- Chaque rotation est modélisée par une ligne distincte dans la table `Trip`.
- La commande client (`CustomerOrder`) agrège dynamiquement les quantités de ses trajets associés.

### B. Fusion du Trajet (Trip) et du Chargement (Loading)
- Le trajet et l'événement de chargement partagent le même cycle de vie au moment de la création (quantité chargée, lettre de cession, bon de livraison, date de chargement).
- Pour éviter une jointure 1:1 superflue en BDD, ils sont modélisés dans une seule table `Trip` (comme préconisé dans la spécification §12/§42).

### C. Machine à États Finit (State Machine) & Historique des Statuts
- Le statut d'un trajet progresse de manière ordonnée à travers les 14 étapes définies dans la spécification §13.
- Les changements de statut sont gérés exclusivement par un service backend (`TripWorkflowService`) et sont historisés dans une table immuable `TripStatusHistory` (lecture seule absolue, aucune modification ni suppression autorisée).
- Le statut opérationnel du camion (`Truck.status`) est synchronisé de manière automatique en fonction du cycle de vie des trajets actifs.

### D. Gestion de la Disponibilité des Camions & Verrouillage
- Un camion ne peut pas être affecté à un nouveau trajet s'il a déjà un trajet "actif" (statut avant `Completed` ou `Cancelled`), à moins d'un forçage explicite (`force=true`) effectué par un utilisateur ayant le rôle **Admin**. Ce forçage sera historisé.
- Lors de l'affectation d'un trajet, un verrouillage pessimiste (`select_for_update`) est appliqué sur le camion concerné pour éviter les double-affectations concurrentes.

---

## 2. Plan d'Action Détaillé et Séquentiel

### Étape 1 : Initialisation des Applications Django (`sales` et `trips`)
- [ ] **Créer l'application Django `sales`** :
  ```bash
  python manage.py startapp sales apps/sales
  ```
- [ ] **Créer l'application Django `trips`** :
  ```bash
  python manage.py startapp trips apps/trips
  ```
- [ ] **Enregistrer les nouvelles applications** dans `INSTALLED_APPS` dans [`backend/config/settings/base.py`](file:///Users/mohamed/Downloads/fuel-logistics-erp/backend/config/settings/base.py) :
  ```python
  "apps.sales",
  "apps.trips",
  ```
- [ ] **Ajouter les routes d'API globales** dans [`backend/config/urls.py`](file:///Users/mohamed/Downloads/fuel-logistics-erp/backend/config/urls.py) :
  ```python
  path("api/", include("apps.sales.urls")),
  path("api/", include("apps.trips.urls")),
  ```

### Étape 2 : Modèle de Données Sales (`apps.sales`)
- [ ] **Définir le modèle `CustomerOrder`** dans `backend/apps/sales/models.py` :
  - `customer` (ForeignKey vers `customers.Customer`, `on_delete=models.PROTECT`)
  - `product` (ForeignKey vers `core.Product`, `on_delete=models.PROTECT`)
  - `quantity_ordered` (DecimalField, `max_digits=14`, `decimal_places=2`)
  - `expected_price` (DecimalField, `max_digits=14`, `decimal_places=4`, nullable=True)
  - `status` (CharField, choix: `DRAFT`, `CONFIRMED`, `PARTIALLY_ASSIGNED`, `IN_PROGRESS`, `PARTIALLY_DELIVERED`, `DELIVERED`, `CLOSED`, `CANCELLED`, default=`DRAFT`)
  - `notes` (TextField, blank=True)
  - Hérite de `TimeStampedModel`.
  - Contrainte de base de données `CheckConstraint` pour s'assurer que `quantity_ordered > 0`.
- [ ] **Créer et exécuter la migration** pour l'application `sales`.

### Étape 3 : Modèles de Données Trips (`apps.trips`)
- [ ] **Définir le modèle `Trip`** dans `backend/apps/trips/models.py` :
  - `reference` (CharField, unique, max_length=50, index=True) - ex: `TRIP-000001` (généré automatiquement).
  - `truck` (ForeignKey vers `transport.Truck`, `on_delete=models.PROTECT`)
  - `transporter` (ForeignKey vers `transport.Transporter`, `on_delete=models.PROTECT`)
  - `driver` (ForeignKey vers `transport.Driver`, `on_delete=models.PROTECT`, nullable=True)
  - `supplier` (ForeignKey vers `suppliers.Supplier`, `on_delete=models.PROTECT`)
  - `supplier_order` (ForeignKey vers `purchasing.SupplierOrder`, `on_delete=models.PROTECT`)
  - `cession_letter` (ForeignKey vers `purchasing.CessionLetter`, `on_delete=models.PROTECT`)
  - `product` (ForeignKey vers `core.Product`, `on_delete=models.PROTECT`)
  - `quantity_loaded` (DecimalField, `max_digits=14`, `decimal_places=2`)
  - `client` (ForeignKey vers `customers.Customer`, `on_delete=models.PROTECT`, nullable=True - pour vente directe)
  - `customer_order` (ForeignKey vers `sales.CustomerOrder`, `on_delete=models.PROTECT`, nullable=True, related_name='trips')
  - `loading_date` (DateField)
  - `bl_reference` (CharField, max_length=100)
  - `status` (CharField, choix correspondant aux 14 statuts, default=`ASSIGNED`)
  - `notes` (TextField, blank=True)
  - `created_by` (ForeignKey vers `accounts.User`, `on_delete=models.PROTECT`)
  - Hérite de `TimeStampedModel`.
  - Contrainte BDD `CheckConstraint` : `quantity_loaded > 0`.
- [ ] **Définir le modèle `TripStatusHistory`** dans `backend/apps/trips/models.py` :
  - `trip` (ForeignKey vers `Trip`, `on_delete=models.CASCADE`, related_name='status_history')
  - `previous_status` (CharField, max_length=30)
  - `new_status` (CharField, max_length=30)
  - `changed_by` (ForeignKey vers `accounts.User`, `on_delete=models.PROTECT`)
  - `changed_at` (DateTimeField, auto_now_add=True)
  - `notes` (TextField, blank=True)
  - Surcharger `save()` pour interdire les modifications/suppressions ultérieures (immuabilité).
- [ ] **Créer et exécuter la migration** pour l'application `trips`.

### Étape 4 : Services Métier du Domaine (`apps.trips.services`)
- [ ] **Créer `TruckAvailabilityService`** dans `backend/apps/trips/services.py` :
  - Méthode `is_truck_available(truck_id)` : Renvoie `True` si le camion n'a aucun trajet actif (statuts exclus : `COMPLETED`, `CANCELLED`).
  - Méthode `get_active_trip(truck_id)` : Renvoie le trajet en cours s'il existe.
  - Méthode `get_available_trucks()` : Renvoie le QuerySet des camions disponibles.
- [ ] **Créer `TripWorkflowService`** dans `backend/apps/trips/services.py` :
  - Définir le dictionnaire des transitions autorisées :
    - `ASSIGNED` -> `SENT_FOR_LOADING`
    - `SENT_FOR_LOADING` -> `LOADING`
    - `LOADING` -> `LOADED`
    - `LOADED` -> `IN_TRANSIT`
    - `IN_TRANSIT` -> `BORDER`
    - `BORDER` -> `CUSTOMS`
    - `CUSTOMS` -> `GOING_TO_CLIENT`
    - `GOING_TO_CLIENT` -> `ARRIVED_AT_CLIENT`
    - `ARRIVED_AT_CLIENT` -> `QUANTITY_CONTROL`
    - `QUANTITY_CONTROL` -> `DELIVERED`
    - `DELIVERED` -> `COMPLETED`
    - Tout statut initial -> `BLOCKED` (exceptionnel)
    - Statuts éligibles (avant livraison) -> `CANCELLED`
    - `BLOCKED` -> statut de retour autorisé
  - Méthode `transition_trip(trip_id, target_status, actor, notes)` encapsulée dans `@transaction.atomic` et verrouillant le `Trip` via `select_for_update()`.
  - Mettre à jour `trip.status`.
  - Créer l'enregistrement `TripStatusHistory`.
  - Si le statut devient `COMPLETED` ou `CANCELLED`, libérer le statut opérationnel du camion (mettre à jour `truck.status` à `AVAILABLE` si stocké en dur, ou s'assurer que les filtres de disponibilité le captent).
  - Mettre à jour dynamiquement le statut de la commande client associée (`CustomerOrder`) si nécessaire.

### Étape 5 : Sérialiseurs et Validations DRF
- [ ] **Définir `CustomerOrderSerializer`** dans `backend/apps/sales/serializers.py` :
  - Inclure les champs calculés dynamiquement par agrégation des trajets : `assigned_quantity`, `loaded_quantity`, `delivered_quantity`, `remaining_quantity`.
- [ ] **Définir `TripSerializer`** dans `backend/apps/trips/serializers.py` :
  - Validation de la quantité chargée : appeler `SupplierStockService.validate_and_lock_reliquat()` sur la lettre de cession pour vérifier que `quantity_loaded <= remaining_quantity`.
  - Validation de la disponibilité du camion : vérifier si le camion est disponible. Si non disponible, rejeter à moins que le paramètre `force=True` soit passé ET que l'utilisateur soit **Admin**. Si forcé, générer un log d'audit.
- [ ] **Définir `TripStatusHistorySerializer`** dans `backend/apps/trips/serializers.py` :
  - Sérialiseur simple en lecture seule.

### Étape 6 : API Views et Permissions DRF
- [ ] **Créer `CustomerOrderViewSet`** dans `backend/apps/sales/views.py` :
  - Permissions : `HasModulePermission` avec `module = "sales"`.
  - Endpoint personnalisé `/api/customer-orders/{id}/trips/` pour lister tous les trajets liés à une commande.
- [ ] **Créer `TripViewSet`** dans `backend/apps/trips/views.py` :
  - Permissions : `HasModulePermission` avec `module = "operations"`.
  - Assurer la génération séquentielle unique du champ `reference` lors de la création.
  - Endpoint personnalisé `@action` : `POST /api/trips/{id}/status/` prenant en paramètres `{new_status, notes}` et appelant le service métier sous verrou.
  - Endpoint personnalisé `@action` : `GET /api/trips/{id}/history/` pour récupérer le journal d'historique de statut.
- [ ] **Étendre `TruckViewSet`** dans `backend/apps/transport/views.py` :
  - Ajouter l'action `/api/trucks/{id}/trips/` pour lister chronologiquement tous les voyages d'un camion spécifique.

### Étape 7 : Tests d'Intégration et de Recette (Backend)
- [ ] **Créer la suite de tests** `backend/apps/trips/tests.py` :
  - **Test du scénario de recette obligatoire (§44)** : Commande client de 450 000 L. 6 camions différents effectuent un premier voyage (ex: 45 000 L chacun = 270 000 L). 4 de ces camions reviennent pour un second voyage (ex: 45 000 L chacun = 180 000 L). Valider que la quantité totale livrée finale est égale à 450 000 L, que le reliquat est de 0, et que les camions réutilisés possèdent bien deux lignes de trajets indépendantes.
  - **Test de Verrouillage Camion** : Tenter d'affecter un trajet à un camion déjà actif sans l'option `force` (rejet 400). Valider qu'avec l'option `force` par un Admin, le trajet est créé.
  - **Test d'Immuabilité de l'Historique** : Tenter d'éditer ou supprimer un enregistrement de `TripStatusHistory` via l'API et vérifier que l'action est rejetée.
  - **Test Vente Directe** : Valider la création d'un trajet sans commande client (`customer_order` à null).

---

## 3. Plan d'Action Interface Frontend (Vue 3)

### Étape 8 : Routes et Navigation
- [ ] **Enregistrer les nouvelles routes** dans [`frontend/src/router/index.ts`](file:///Users/mohamed/Downloads/fuel-logistics-erp/frontend/src/router/index.ts) :
  - `/customer-orders` -> `CustomerOrderList.vue`
  - `/customer-orders/:id` -> `CustomerOrderForm.vue`
  - `/trips` -> `TripStatusBoard.vue` (Kanban)
  - `/trips/:id` -> `TripDetail.vue`
- [ ] **Ajouter les entrées** dans [`frontend/src/modules/shell/AppShell.vue`](file:///Users/mohamed/Downloads/fuel-logistics-erp/frontend/src/modules/shell/AppShell.vue) :
  - "Customer Orders" (liée au module `sales`)
  - "Trips & Loading" (liée au module `operations`)

### Étape 9 : Composants de la Phase 3 (`frontend/src/modules/`)
- [ ] **Créer `CustomerOrderList.vue`** : Liste les commandes, leur quantité ordonnée, quantité assignée et statut général.
- [ ] **Créer `CustomerOrderForm.vue`** : Affiche les informations de la commande ainsi qu'une **barre de progression avancée** (Quantité Ordonnée / Assignée / Chargée / Livrée).
- [ ] **Créer `TripForm.vue`** (Formulaire de Chargement) :
  - Sélection dynamique de la lettre de cession (Phase 2).
  - Sélection du camion : affiche uniquement les camions disponibles avec filtre `AVAILABLE` par défaut, et un interrupteur "Afficher les camions occupés (Admin uniquement)" pour activer l'override `force=true`.
  - Saisie du bon de livraison (BL) et de la quantité.
- [ ] **Créer `TripStatusBoard.vue`** :
  - Tableau de bord type Kanban ou grille interactive répartissant les trajets en cours d'exécution dans les différentes colonnes correspondant aux 14 statuts opérationnels (frontière, douane, en transit, etc.).
- [ ] **Créer `TripDetail.vue`** :
  - Affiche les détails du voyage et une frise chronologique (timeline) représentant l'historique complet tiré de `TripStatusHistory`.
  - Permet aux opérateurs d'effectuer la transition de statut suivante à l'aide de boutons d'action contrôlés par le backend.

---

## 4. Scénario de Recette Manuel (Validation Finale)

1. **Création Commande Client** : Enregistrer une commande client de **450 000 L** de Gasoil.
2. **Premier Voyage (6 camions)** :
   - Émettre une lettre de cession pour couvrir la quantité.
   - Créer 6 trajets de **45 000 L** chacun en sélectionnant 6 camions disponibles.
   - Faire transiter ces 6 trajets vers le statut `COMPLETED`.
3. **Disponibilité des camions** : Vérifier que les camions sont de nouveau listés comme `AVAILABLE` après complétion.
4. **Second Voyage (Réutilisation)** :
   - Sélectionner 4 des camions précédemment utilisés et créer 4 nouveaux trajets de **45 000 L** chacun pour la même commande client.
5. **Vérification finale** :
   - Valider que la commande affiche une quantité livrée totale de **450 000 L** et passe automatiquement au statut `DELIVERED` ou `COMPLETED`.
   - Vérifier sur la fiche individuelle d'un camion utilisé deux fois qu'il possède bien deux trajets distincts dans son historique.

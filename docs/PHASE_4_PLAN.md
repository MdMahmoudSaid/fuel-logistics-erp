# Plan d'Action Technique - Phase 4 : Delivery, Discharge and Reliquat Management

Ce document présente le plan de développement détaillé pour la **Phase 4** de l'ERP Fuel Logistics. Cette phase assure le bouclage du cycle opérationnel en enregistrant la livraison effective, en calculant les pertes, en appliquant les déductions financières aux transporteurs et en facturant les clients sur la base des quantités reçues (et non chargées).

---

## 1. Choix de Conception & Règles Métier Clés

### A. Quantité Reçue comme Vérité Commerciale (Spec §19)
- Les ventes et la facturation client doivent obligatoirement s'appuyer sur la **quantité reçue** (`received_quantity`) mesurée lors de la décharge au dépôt client, et jamais sur la quantité chargée.
- L'entité `Sale` (Vente) copie cette quantité de manière immuable au moment de la confirmation de livraison.

### B. Moteur de Pertes & Tolérance Historisée (Spec §15)
- Chaque décharge calcule la perte : 
  $$\text{Perte} = \text{Quantité Chargée} - \text{Quantité Reçue}$$
- La perte facturable au transporteur (hors-tolérance) est calculée en fonction d'un seuil configurable :
  $$\text{Perte Chargeable} = \max(0, \text{Perte} - \text{Tolérance Configurée})$$
- **Règle de gel historique** : La tolérance appliquée lors de la confirmation doit être enregistrée en dur sur le modèle de contrôle de livraison (`DeliveryControl`) pour préserver les règles du passé en cas de modification de configuration générale ultérieure.

### C. Déduction Transporteur Isolée (Spec §15)
- Les pertes chargeables hors-tolérance donnent lieu à une transaction de déduction distincte (`TransportDeduction`) sur le compte du transporteur. 
- On ne modifie pas directement le coût brut du transport afin de conserver une traçabilité comptable (Audit Trail).

### D. Gestion des Anomalies de Décharge (Spec §15)
- Si la quantité reçue est supérieure à la quantité chargée ($\text{Quantité Reçue} > \text{Quantité Chargée}$), la validation automatique de l'API est bloquée (Erreur 422). 
- Le passage requiert une confirmation manuelle et explicite par un utilisateur habilité (`anomaly_confirmed_by`), consignant l'anomaly.

### E. Immuabilité et Corrections de Factures (Spec §21)
- Une fois qu'une facture (`Invoice`) est validée (`status="VALIDATED"`), toute modification directe de ses données financières (prix, quantité, total) est bloquée au niveau de l'API.
- Les ajustements se font via un workflow de correction explicite (`/correct/`) qui génère un historique d'audit de modification (`InvoiceCorrection`) contenant l'auteur, la date, l'ancienne valeur, la nouvelle valeur et le motif.

### F. Historique des Prix de Vente
- Le système mémorise le dernier prix de vente pratiqué par produit et client pour le suggérer lors des prochaines ventes. Les ajustements manuels par les rôles autorisés alimentent l'historique des prix (`ProductSellingPriceHistory`).

---

## 2. Plan d'Action Détaillé et Séquentiel

### Étape 1 : Configuration et Singleton de Tolérance (`apps.core`)
- [ ] **Définir le modèle `LossToleranceConfig`** dans `backend/apps/core/models.py` :
  - `tolerance_litres` (DecimalField, `max_digits=10`, `decimal_places=2`, default=`100.00`)
  - `updated_by` (ForeignKey vers `accounts.User`)
  - `updated_at` (DateTimeField, auto_now=True)
  - Limiter la table à une seule ligne (pattern Singleton) au niveau applicatif ou via contrainte de base de données.
- [ ] **Créer et exécuter la migration** pour cette configuration dans `core`.

### Étape 2 : Modèle de Contrôle de Livraison (`apps.trips`)
- [ ] **Définir le modèle `DeliveryControl`** dans `backend/apps/trips/models.py` :
  - `trip` (OneToOneField vers `Trip`, `on_delete=models.PROTECT`, related_name='delivery_control')
  - `loaded_quantity` (DecimalField, `max_digits=14`, `decimal_places=2`) - copié du trajet au moment de la livraison.
  - `received_quantity` (DecimalField, `max_digits=14`, `decimal_places=2`)
  - `loss_quantity` (DecimalField, `max_digits=14`, `decimal_places=2`, calculé automatiquement)
  - `tolerance_quantity` (DecimalField, `max_digits=10`, `decimal_places=2`) - seuil de tolérance gelé au moment de la livraison.
  - `chargeable_loss_quantity` (DecimalField, `max_digits=14`, `decimal_places=2`, calculé automatiquement)
  - `control_date` (DateField)
  - `controller` (ForeignKey vers `accounts.User`, `on_delete=models.PROTECT`)
  - `method` (CharField, ex: `MANUAL_GAUGE`, `METER`)
  - `document` (ForeignKey vers `documents.Document`, `on_delete=models.SET_NULL`, nullable=True) - pour le bon de réception/décharge.
  - `notes` (TextField, blank=True)
  - `anomaly_confirmed_by` (ForeignKey vers `accounts.User`, `on_delete=models.PROTECT`, nullable=True, related_name='confirmed_anomalies')
  - `anomaly_confirmed_at` (DateTimeField, nullable=True)
- [ ] **Créer et exécuter la migration** pour `DeliveryControl`.

### Étape 3 : Modèle de Déduction Transporteur (`apps.finance` ou `apps.transport`)
- [ ] **Définir le modèle `TransportDeduction`** dans `backend/apps/finance/models.py` (ou `transport`) :
  - `trip` (ForeignKey vers `trips.Trip`, `on_delete=models.PROTECT`)
  - `transporter` (ForeignKey vers `transport.Transporter`, `on_delete=models.PROTECT`)
  - `chargeable_quantity` (DecimalField, `max_digits=14`, `decimal_places=2`) - copié de `chargeable_loss_quantity`
  - `unit_price` (DecimalField, `max_digits=14`, `decimal_places=4`) - prix unitaire de perte (généralement le prix d'achat du carburant pour remboursement par le transporteur)
  - `amount` (DecimalField, `max_digits=16`, `decimal_places=2`) - `chargeable_quantity * unit_price`
  - `currency` (CharField, default='XOF', max_length=10)
  - `status` (CharField, choix: `DRAFT`, `VALIDATED`, `CANCELLED`, default=`DRAFT`)
- [ ] **Créer et exécuter la migration** de `TransportDeduction`.

### Étape 4 : Modèles de Vente et Facturation (`apps.sales`)
- [ ] **Définir le modèle `Sale`** dans `backend/apps/sales/models.py` :
  - `trip` (OneToOneField vers `trips.Trip`, `on_delete=models.PROTECT`, related_name='sale')
  - `customer` (ForeignKey vers `customers.Customer`, `on_delete=models.PROTECT`)
  - `product` (ForeignKey vers `core.Product`, `on_delete=models.PROTECT`)
  - `delivered_quantity` (DecimalField, `max_digits=14`, `decimal_places=2`, editable=False) - copié de `received_quantity`
  - `unit_selling_price` (DecimalField, `max_digits=14`, `decimal_places=4`)
  - `currency` (CharField, default='XOF', max_length=10)
  - `subtotal` (DecimalField, `max_digits=16`, `decimal_places=2`, editable=False)
- [ ] **Définir le modèle `ProductSellingPriceHistory`** dans `backend/apps/sales/models.py` :
  - `product` (ForeignKey vers `core.Product`, `on_delete=models.CASCADE`)
  - `customer` (ForeignKey vers `customers.Customer`, `on_delete=models.CASCADE`, nullable=True) - prix global si nul.
  - `price` (DecimalField, `max_digits=14`, `decimal_places=4`)
  - `currency` (CharField, default='XOF', max_length=10)
  - `effective_at` (DateTimeField, auto_now_add=True)
  - `changed_by` (ForeignKey vers `accounts.User`, `on_delete=models.PROTECT`)
- [ ] **Définir le modèle `Invoice`** dans `backend/apps/sales/models.py` :
  - `invoice_number` (CharField, unique=True, max_length=50)
  - `sale` (OneToOneField vers `Sale`, `on_delete=models.PROTECT`, related_name='invoice')
  - `status` (CharField, choix: `DRAFT`, `VALIDATED`, `PARTIALLY_PAID`, `PAID`, `CANCELLED`, default=`DRAFT`)
  - `total_amount` (DecimalField, `max_digits=16`, `decimal_places=2`)
  - `issued_date` (DateField)
- [ ] **Définir le modèle `InvoiceCorrection`** (Journal d'audit) dans `backend/apps/sales/models.py` :
  - `invoice` (ForeignKey vers `Invoice`, `on_delete=models.CASCADE`, related_name='corrections')
  - `field_name` (CharField, max_length=50)
  - `previous_value` (CharField, max_length=100)
  - `new_value` (CharField, max_length=100)
  - `corrected_by` (ForeignKey vers `accounts.User`, `on_delete=models.PROTECT`)
  - `corrected_at` (DateTimeField, auto_now_add=True)
  - `reason` (TextField)
- [ ] **Créer et exécuter la migration** pour l'application `sales`.

### Étape 5 : Services Métier de Livraison et Facturation
- [ ] **Créer le Service de Livraison (`DeliveryService`)** dans `backend/apps/trips/services.py` :
  - Méthode `record_delivery(trip_id, received_qty, control_date, method, controller, anomaly_confirmed_by=None, documents=None)` sous `@transaction.atomic` et verrouillage de `Trip` par `select_for_update()`.
  - Vérifier la tolérance en vigueur (`LossToleranceConfig`).
  - Gérer l'anomalie : Lever une exception si `received_qty > trip.quantity_loaded` et `anomaly_confirmed_by` est absent.
  - Transitionner le statut du `Trip` vers `DELIVERED` via `TripWorkflowService`.
  - Créer `DeliveryControl` en calculant `loss` et `chargeable_loss`.
  - Si perte chargeable > 0, générer automatiquement un enregistrement `TransportDeduction` brouillon.
  - Créer l'enregistrement `Sale` associé en recherchant le dernier prix suggéré par `ProductSellingPriceHistory`.
- [ ] **Créer le Service de Facturation (`InvoiceService`)** dans `backend/apps/sales/services.py` :
  - Méthode `validate_invoice(invoice_id, actor)` : Valide la facture et gèle définitivement ses montants opérationnels.
  - Méthode `correct_invoice(invoice_id, field, new_value, reason, actor)` : Permet d'ajuster une facture validée en écrivant l'historique d'audit `InvoiceCorrection`.

### Étape 6 : Sérialiseurs, Endpoints & Permissions DRF
- [ ] **Ajouter les endpoints DRF** suivants :
  - `POST /api/trips/{id}/delivery-control/` (création du contrôle de livraison et finalisation de trajet)
  - `GET|PATCH /api/settings/loss-tolerance/` (gestion de la tolérance par un administrateur)
  - `GET|POST /api/sales/` (suivi des lignes de ventes générées)
  - `GET|POST /api/invoices/` (gestion des factures clients)
  - `POST /api/invoices/{id}/validate/` (validation de facture)
  - `POST /api/invoices/{id}/correct/` (ajustement sous audit d'une facture validée)
- [ ] **Intégrer les validations dans les sérialiseurs** :
  - Le validateur de `DeliveryControlSerializer` bloque la requête si reçu > chargé et `anomaly_confirmed_by` est manquant.
  - Le validateur de `InvoiceSerializer` rejette les modifications sur les factures au statut `VALIDATED`.

### Étape 7 : Tests d'Intégration & de Recette (Backend)
- [ ] **Créer le fichier de tests** `backend/apps/sales/tests.py` :
  - **Test d'ajustement de pertes (§14/§15)** : Charger 45 000 L. Enregistrer 44 850 L reçus avec tolérance à 100 L. Vérifier que la perte totale calculée est de 150 L, et la perte chargeable déduite de 50 L.
  - **Test d'anomalie de décharge** : Tenter d'enregistrer 46 000 L reçus sur 45 000 L chargés. Vérifier le rejet 422 sans signature d'anomalie, et le passage réussi avec signature d'anomalie.
  - **Test de facturation basée sur la quantité reçue (§19)** : S'assurer que le montant facturé final est basé sur la quantité reçue (ex: 44 850 L) et non sur les 45 000 L d'origine.
  - **Test d'audit de correction de facture (§21)** : Valider qu'un changement de prix sur une facture validée est rejeté en modification directe, mais réussi via l'endpoint de correction `/correct/` en générant un enregistrement `InvoiceCorrection` valide.

---

## 3. Plan d'Action Interface Frontend (Vue 3)

### Étape 8 : Routes et Navigation
- [ ] **Ajouter les routes suivantes** dans [`frontend/src/router/index.ts`](file:///Users/mohamed/Downloads/fuel-logistics-erp/frontend/src/router/index.ts) :
  - `/sales` -> `SaleList.vue`
  - `/invoices` -> `InvoiceList.vue`
  - `/invoices/:id` -> `InvoiceDetail.vue`
  - `/settings/loss-tolerance` -> `LossToleranceSettings.vue`
- [ ] **Mettre à jour la barre latérale** dans [`frontend/src/modules/shell/AppShell.vue`](file:///Users/mohamed/Downloads/fuel-logistics-erp/frontend/src/modules/shell/AppShell.vue) pour donner l'accès aux Factures et Ventes aux rôles autorisés (`finance` / `sales`).

### Étape 9 : Composants de la Phase 4 (`frontend/src/modules/`)
- [ ] **Créer `DeliveryControlForm.vue`** (Formulaire de décharge et contrôle de quantité) :
  - Affiche la quantité initialement chargée en lecture seule.
  - Demande la saisie de la quantité reçue.
  - Calcule en temps réel et affiche la perte et la perte chargeable (déduction transporteur estimée).
  - Affiche une boîte de dialogue de confirmation d'anomalie avec champ de signature autorisé si quantité reçue > quantité chargée.
- [ ] **Créer `InvoiceList.vue` et `InvoiceDetail.vue`** :
  - Liste des factures avec filtres de statut (`DRAFT`, `VALIDATED`, `PAID`).
  - Fiche détaillée de la facture avec bouton d'action "Valider la facture".
  - Si la facture est validée, masquer les champs modifiables standards et afficher un bouton "Corriger la facture" ouvrant un formulaire d'ajustement (demandant la nouvelle valeur et le motif de la correction).
- [ ] **Créer `LossToleranceSettings.vue`** :
  - Interface simple permettant aux administrateurs de configurer le seuil par défaut de la tolérance aux pertes de carburant.

---

## 4. Scénario de Recette Manuel (Validation Finale)

1. **Chargement** : Créer un trajet avec **45 000 L** de carburant.
2. **Décharge & Contrôle** :
   - Accéder au formulaire de livraison du trajet.
   - Saisir une quantité reçue de **44 850 L**.
   - Valider et vérifier le calcul en direct : Perte = 150 L, Perte chargeable = 50 L (si tolérance = 100 L).
3. **Contrôle Déduction** : Vérifier dans le système qu'une déduction de transporteur a été automatiquement émise sur la base des 50 L de perte chargeable.
4. **Vérification Facture** :
   - Ouvrir la facture générée automatiquement.
   - Constater que la quantité facturée est bien de **44 850 L** (quantité reçue).
5. **Ajustement sous Audit** :
   - Valider la facture.
   - Tenter de modifier le prix unitaire directement (vérifier le blocage).
   - Utiliser la fonction de correction pour passer le prix unitaire de 600 à 605 XOF en saisissant le motif "Erreur de saisie contractuelle".
   - Valider que le montant total est recalculé et que le journal d'audit de modification s'affiche au bas de la facture.

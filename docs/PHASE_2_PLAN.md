# Plan d'Action Technique - Phase 2 : Purchasing, Cession and Supplier Reliquat

Ce document présente le plan de développement détaillé pour la **Phase 2** de l'ERP Fuel Logistics. L'objectif est d'implémenter le cycle d'achat de carburant auprès des fournisseurs, la gestion des lettres de cession pour autoriser le chargement, et le suivi dynamique du reliquat fournisseur sans dérive de données.

---

## 1. Choix de Conception & Règles Métier Clés

### A. Calcul Dynamique des Reliquats (Derived Data)
Pour éviter les dérives de données (drift) causées par des annulations, corrections ou erreurs de saisie :
- Le **Reliquat Commande Fournisseur** n'est pas stocké en base de données. Il est calculé ainsi :
  $$\text{Reliquat} = \text{Quantité Achetée} - \sum(\text{Quantité Cédée des Lettres de Cession Actives})$$
- La **Quantité Restante Cession** (Phase 3+) sera calculée ainsi :
  $$\text{Reste Cession} = \text{Quantité Autorisée} - \sum(\text{Chargements Effectifs associés})$$

### B. Verrouillage Concurrentiel (Pessimistic Locking)
Pour empêcher les dépassements de quantité en cas d'appels simultanés à l'API :
- Utilisation systématique de `select_for_update()` dans un bloc `transaction.atomic()` lors de la création ou modification d'une `CessionLetter` (pour verrouiller le `SupplierOrder`) ou lors d'un chargement en Phase 3 (pour verrouiller la `CessionLetter`).

### C. Modèle de Document Générique (Option B)
Conformément à la spécification §35 et aux commentaires de `apps.documents.models.py`, nous utiliserons une relation générique via `GenericForeignKey` pour attacher des fichiers physiques (PDF, scans) à n'importe quel modèle (Commandes, Cessions, Trucks, etc.).

---

## 2. Plan d'Action Détaillé et Séquentiel

### Étape 1 : Initialisation de l'Application Django `purchasing`
- [ ] **Créer l'application Django** `backend/apps/purchasing` contenant les répertoires standards (`migrations/`, `models.py`, `views.py`, `serializers.py`, `services.py`).
- [ ] **Enregistrer l'application** dans `INSTALLED_APPS` dans le fichier [`backend/config/settings/base.py`](file:///Users/mohamed/Downloads/fuel-logistics-erp/backend/config/settings/base.py) :
  ```python
  "apps.purchasing",
  ```
- [ ] **Ajouter les routes de l'application** dans le routeur principal [`backend/config/urls.py`](file:///Users/mohamed/Downloads/fuel-logistics-erp/backend/config/urls.py) en incluant `apps.purchasing.urls`.

### Étape 2 : Implémentation du Modèle de Document Générique (`apps.documents`)
- [ ] **Définir le modèle `Document`** dans [`backend/apps/documents/models.py`](file:///Users/mohamed/Downloads/fuel-logistics-erp/backend/apps/documents/models.py) :
  ```python
  from django.db import models
  from django.contrib.contenttypes.models import ContentType
  from django.contrib.contenttypes.fields import GenericForeignKey
  from apps.core.models import TimeStampedModel

  class Document(TimeStampedModel):
      file = models.FileField(upload_to="documents/%Y/%m/%d/")
      document_type = models.CharField(max_length=50)  # ex: 'purchase_contract', 'cession_pdf'
      reference = models.CharField(max_length=100, blank=True)
      uploaded_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)

      # Generic relation fields
      content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
      object_id = models.PositiveIntegerField()
      content_object = GenericForeignKey("content_type", "object_id")

      class Meta:
          indexes = [
              models.Index(fields=["content_type", "object_id"]),
          ]
  ```
- [ ] **Créer et exécuter la migration** pour le modèle `Document`.
- [ ] **Définir `DocumentSerializer`** dans `backend/apps/documents/serializers.py` et configurer un mixin de sérialisation ou un champ de relation générique pour faciliter l'attachement de documents dans d'autres sérialiseurs.

### Étape 3 : Création des Modèles de Données Purchasing (`apps.purchasing`)
- [ ] **Définir le modèle `SupplierOrder`** dans `backend/apps/purchasing/models.py` :
  - `reference` (CharField, unique, max_length=100)
  - `supplier` (ForeignKey vers `suppliers.Supplier`, `on_delete=models.PROTECT`)
  - `product` (ForeignKey vers `core.Product`, `on_delete=models.PROTECT`)
  - `purchase_date` (DateField)
  - `quantity_litres` (DecimalField, `max_digits=14`, `decimal_places=2`)
  - `unit_price` (DecimalField, `max_digits=14`, `decimal_places=4` - précision élevée)
  - `currency` (CharField, default='XOF', max_length=10)
  - `total_amount` (DecimalField, `max_digits=16`, `decimal_places=2`, calculé automatiquement)
  - `optional_costs` (DecimalField, `max_digits=14`, `decimal_places=2`, nullable=True)
  - `notes` (TextField, blank=True)
  - `status` (CharField, choix: `DRAFT`, `CONFIRMED`, `CANCELLED`, default=`DRAFT`)
  - `created_by` (ForeignKey vers `accounts.User`, `on_delete=models.PROTECT`)
  - Surcharger la méthode `save()` pour recalculer `total_amount = (quantity_litres * unit_price) + (optional_costs or 0)`.
- [ ] **Définir le modèle `CessionLetter`** dans `backend/apps/purchasing/models.py` :
  - `reference` (CharField, unique, max_length=100)
  - `supplier_order` (ForeignKey vers `SupplierOrder`, `on_delete=models.PROTECT`, related_name='cessions')
  - `authorized_quantity` (DecimalField, `max_digits=14`, `decimal_places=2`)
  - `issue_date` (DateField)
  - `status` (CharField, choix: `ACTIVE`, `EXHAUSTED`, `CANCELLED`, default=`ACTIVE`)
  - `notes` (TextField, blank=True)
  - `created_by` (ForeignKey vers `accounts.User`, `on_delete=models.PROTECT`)
  - Ajouter une contrainte de base de données `CheckConstraint` pour s'assurer que `authorized_quantity > 0`.
- [ ] **Créer et exécuter la migration** pour les modèles `SupplierOrder` et `CessionLetter`.

### Étape 4 : Service Métier de Gestion des Stocks (`apps.purchasing.services`)
- [ ] **Créer le fichier** `backend/apps/purchasing/services.py` contenant la classe `SupplierStockService` :
  ```python
  from django.db import transaction
  from django.db.models import Sum
  from decimal import Decimal
  from apps.purchasing.models import SupplierOrder, CessionLetter

  class SupplierStockService:
      @staticmethod
      def get_purchase_loaded_quantity(purchase: SupplierOrder) -> Decimal:
          # Phase 2: Stub à 0 car les chargements de la Phase 3 n'existent pas encore.
          # Sera étendu en Phase 3 : somme des trips associés à cette commande.
          return Decimal("0.00")

      @staticmethod
      def get_purchase_reliquat(purchase: SupplierOrder) -> Decimal:
          """Calcul dynamique : Quantité achetée - Somme des cessions actives/épuisées."""
          cessions_sum = purchase.cessions.exclude(status="CANCELLED").aggregate(
              total=Sum("authorized_quantity")
          )["total"] or Decimal("0.00")
          return purchase.quantity_litres - cessions_sum

      @staticmethod
      def get_cession_remaining(cession: CessionLetter) -> Decimal:
          # Phase 2: stubbé à la quantité autorisée (pas encore de chargements/trips).
          # Phase 3: cession.authorized_quantity - SUM(trips_loaded)
          return cession.authorized_quantity

      @transaction.atomic
      @staticmethod
      def validate_and_lock_reliquat(purchase_id: int, requested_qty: Decimal, exclude_cession_id: int = None) -> SupplierOrder:
          """Verrouille la commande d'achat et valide que le reliquat est suffisant."""
          purchase = SupplierOrder.objects.select_for_update().get(pk=purchase_id)
          
          # Calcul de la somme des cessions en excluant la cession courante (pour les cas d'édition)
          queryset = purchase.cessions.exclude(status="CANCELLED")
          if exclude_cession_id:
              queryset = queryset.exclude(pk=exclude_cession_id)
              
          cessions_sum = queryset.aggregate(total=Sum("authorized_quantity"))["total"] or Decimal("0.00")
          available_reliquat = purchase.quantity_litres - cessions_sum

          if requested_qty > available_reliquat:
              raise ValueError(
                  f"Quantité demandée ({requested_qty} L) supérieure au reliquat disponible ({available_reliquat} L)."
              )
          return purchase
  ```

### Étape 5 : Sérialiseurs et Validation Stricte (Backend)
- [ ] **Définir `SupplierOrderSerializer`** dans `backend/apps/purchasing/serializers.py` :
  - Inclure le champ en lecture seule `reliquat` calculé via `SupplierStockService.get_purchase_reliquat`.
  - Intégrer les documents associés en relation générique (lecture/écriture).
- [ ] **Définir `CessionLetterSerializer`** dans `backend/apps/purchasing/serializers.py` :
  - Inclure les champs calculés `loaded_quantity` et `remaining_quantity`.
  - Implémenter la méthode `validate()` pour appeler `SupplierStockService.validate_and_lock_reliquat()` dans un bloc atomique afin de vérifier la disponibilité du reliquat lors de la création/modification d'une cession.
  - Retourner une erreur HTTP 400 claire si la validation échoue.

### Étape 6 : API Views et Permissions (Backend)
- [ ] **Créer `SupplierOrderViewSet`** dans `backend/apps/purchasing/views.py` :
  - Configurer `permission_classes = [HasModulePermission]` avec `module = "purchasing"`.
  - Ajouter un endpoint personnalisé `@action(detail=True, methods=['get'])` `/api/supplier-orders/{id}/reliquat/`.
- [ ] **Créer `CessionLetterViewSet`** dans `backend/apps/purchasing/views.py` :
  - Configurer `permission_classes = [HasModulePermission]` avec `module = "purchasing"`.
- [ ] **Ajouter l'endpoint du Ledger Fournisseur** dans `backend/apps/suppliers/views.py` ou via une action sur `SupplierViewSet` (`/api/suppliers/{id}/ledger/`) :
  - Cet endpoint doit retourner l'historique des achats du fournisseur (`SupplierOrder`) et le reliquat global agrégé par produit.

### Étape 7 : Tests d'Intégration & Concurrence (Backend)
- [ ] **Créer le fichier de tests** `backend/apps/purchasing/tests.py` :
  - **Test d'Intégrité de base** : Créer un `SupplierOrder` et vérifier que le `total_amount` est correctement calculé et stocké.
  - **Test de Validation de Limite** : Créer une commande de 100 000 L. Créer une cession de 60 000 L. Tenter de créer une deuxième cession de 50 000 L et vérifier que l'API renvoie une erreur 400.
  - **Test de Libération après Annulation** : Créer une cession de 60 000 L, puis la passer en statut `CANCELLED`. Vérifier que le reliquat de la commande redevient disponible.
  - **Test de Concurrence Réelle** : Écrire un test utilisant des threads (ou `asyncio` / simulation de transactions concurrentes) pour tenter de créer simultanément deux cessions de 60 000 L sur une commande de 100 000 L. S'assurer que l'une d'elles échoue proprement grâce au verrou `select_for_update()`.
  - **Test de Droits d'Accès** : Vérifier qu'un utilisateur sans le rôle `purchasing` reçoit un 403 Forbidden sur ces endpoints.

### Étape 8 : Interface Frontend - Configuration des Routes
- [ ] **Créer le module de navigation** dans `frontend/src/modules/purchasing`.
- [ ] **Ajouter les routes de la Phase 2** dans le routeur principal [`frontend/src/router/index.ts`](file:///Users/mohamed/Downloads/fuel-logistics-erp/frontend/src/router/index.ts) sous le layout `AppShell` :
  - `/supplier-orders` -> `SupplierOrderList.vue`
  - `/supplier-orders/new` -> `SupplierOrderForm.vue`
  - `/supplier-orders/:id` -> `SupplierOrderForm.vue` (visualisation / édition / cessions associées)
  - `/cession-letters` -> `CessionLetterList.vue`
  - `/cession-letters/new` -> `CessionLetterForm.vue`
- [ ] **Mettre à jour la barre de navigation** dans [`frontend/src/modules/shell/AppShell.vue`](file:///Users/mohamed/Downloads/fuel-logistics-erp/frontend/src/modules/shell/AppShell.vue) pour inclure un accès direct aux Commandes Fournisseurs :
  ```typescript
  { to: 'supplier-orders', label: 'Supplier Orders', module: 'purchasing' },
  ```

### Étape 9 : Interface Frontend - Composants & Vues Vue 3
- [ ] **Créer `SupplierOrderList.vue`** :
  - Liste des commandes d'achat avec filtres (fournisseur, produit, statut).
  - Affiche les colonnes : Référence, Fournisseur, Produit, Quantité achetée, Reliquat restant, Statut.
- [ ] **Créer `SupplierOrderForm.vue`** :
  - Formulaire de création / édition avec sélection de fournisseur, produit, quantité, prix unitaire, devise (XOF), et coûts optionnels.
  - Section de téléchargement de documents pour joindre le contrat d'achat numérisé.
  - Si la commande existe déjà : afficher la liste imbriquée des lettres de cession émises sur cette commande.
- [ ] **Créer `CessionLetterForm.vue`** :
  - Formulaire d'émission de lettre de cession.
  - Contient un indicateur de progression visuel interactif (barre de chargement/allocation) affichant en temps réel au cours de la saisie :
    - La quantité totale achetée.
    - La quantité déjà allouée à d'autres cessions.
    - La quantité actuellement demandée (avec alerte immédiate si dépassement du reliquat).
  - Zone d'upload pour le document PDF de cession officiel.
- [ ] **Créer `SupplierLedgerView.vue`** (accessible depuis la fiche d'un fournisseur ou en tant qu'onglet) :
  - Vue récapitulative listant toutes les commandes du fournisseur avec leur reliquat disponible respectif.

---

## 3. Plan de Validation et Recette de la Phase 2

### A. Validation Automatisée
- Lancer la suite de tests pour valider les contraintes de reliquat et de verrouillage :
  ```bash
  .venv/bin/pytest apps/purchasing/tests.py
  ```

### B. Scénario de Test Manuel de Recette
1. Connectez-vous en tant qu'utilisateur ayant le rôle **Purchasing**.
2. Créez un achat fournisseur de **500 000 L** de Gasoil à **600 XOF/L**. Attachez un faux document PDF de contrat.
3. Vérifiez sur la liste que le reliquat affiché est de **500 000 L** et le montant total de **300 000 000 XOF**.
4. Émettez une lettre de cession de **300 000 L** sur cet achat. Attachez le PDF de cession.
5. Vérifiez que le reliquat de l'achat est passé à **200 000 L**.
6. Tentez d'émettre une autre cession de **250 000 L** sur cet achat. Le système doit lever une alerte dans l'interface et bloquer la validation côté API (Code 400).
7. Réduisez la deuxième cession à **200 000 L** et validez. Le reliquat de l'achat doit maintenant être de **0 L**.

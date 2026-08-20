# Plan d'Action Technique - Phase 6 : Profit Engine, Stock Projections, Reports & Dashboard

Ce document présente le plan de développement détaillé pour la **Phase 6** de l'ERP Fuel Logistics. L'objectif principal de cette phase est de consolider l'ensemble des données transactionnelles saisies lors des phases 1 à 5 pour offrir une vue décisionnelle et opérationnelle unique : le stock théorique en temps réel, le calcul de rentabilité (moteur de marge), les rapports réglementaires et d'analyse, la recherche globale instantanée et le système d'audit global.

---

## 1. Choix de Conception & Règles Métier Clés

### A. Moteur de Marge Recalculé à la Lecture (Spec §33)
- Pour éviter les dérives financières, la marge nette et le profit d'un trajet ne sont pas stockés de manière statique en base de données. Ils sont calculés dynamiquement à chaque lecture via le service `TripProfitService` :
  $$\text{Marge Trajet} = (\text{Quantité Livrée} \times \text{Prix Vente}) - (\text{Quantité Chargée} \times \text{Prix Achat}) - \sum(\text{Frais de route / Dépenses affectées}) - \text{Frais Transport Brut}$$
- Ce choix permet la recalculation automatique de la rentabilité si une dépense tardive (ex: frais de douane ou pénalités de route) est imputée a posteriori sur un trajet.
- Distinguer trois types de marges :
  1. **Marge Estimée** : Calculée avant le chargement sur la base des prévisions (quantités ordonnées et prix attendus).
  2. **Marge Courante (Recalculée)** : Basée sur les décharges réelles, prix de vente validés et frais courants saisis.
  3. **Marge Finale** : Trajet clôturé financièrement (plus aucune dépense acceptée sans réouverture explicite).

### B. Moteur de Stock Théorique sans Entrepôt Fictif (Spec §32)
- Le carburant est soit en transit dans un camion, soit en attente chez un fournisseur. Il n'y a pas d'entrepôt physique central de stockage.
- Le **Stock Théorique** est calculé dynamiquement :
  $$\text{Stock Théorique} = \text{Somme des Reliquats fournisseurs actifs} + \text{Somme des volumes chargés non vendus (Trips chargés sans Sale)}$$
- Le carburant sort du stock théorique au moment précis de la validation de la décharge / création de la vente (`Sale`).

### C. Inviolabilité des Données et Piste d'Audit (Spec §39)
- Aucun enregistrement financier validé (Facture, Dépense, Paiement) ne peut être physiquement supprimé de la base de données. La suppression est modélisée par un statut `CANCELLED` accompagné d'une entrée de reversement comptable.
- Toutes les modifications de données critiques (quantités, prix, montants, annulations) sont interceptées et historisées dans une table d'audit centralisée immuable `AuditLog` sous forme de diff JSON (valeur précédente vs nouvelle valeur).

### D. Recherche Globale Intégrée (Spec §36)
- Implémentation d'une recherche plein texte (PostgreSQL trigram / search vector) sur un endpoint unique capable de scanner : plaques d'immatriculation (tracteur/citerne), clients, fournisseurs, transporteurs, références BL, factures, lettres de cession et identifiants de trajets.
- Un résultat de recherche sur un camion doit instantanément renvoyer son état complet en direct : statut actuel, trajet en cours, produit, volume, client final et historique des derniers voyages.

---

## 2. Plan d'Action Détaillé et Séquentiel

### Étape 1 : Système d'Audit Global (`apps.audit`)
- [x] **Définir le modèle `AuditLog`** dans `backend/apps/audit/models.py` :
  - `user` (ForeignKey vers `accounts.User`, `on_delete=models.PROTECT`)
  - `timestamp` (DateTimeField, auto_now_add=True, index=True)
  - `action` (CharField, choix: `CREATE`, `UPDATE`, `DELETE`, `CANCEL`, `REVERSE`)
  - `content_type` (ForeignKey vers `ContentType`, `on_delete=models.CASCADE`)
  - `object_id` (PositiveIntegerField)
  - `content_object` (GenericForeignKey)
  - `previous_value` (JSONField, nullable=True) - capture de l'état précédent de l'objet.
  - `new_value` (JSONField) - capture du nouvel état.
  - `reason` (TextField, nullable=True)
- [x] **Créer et exécuter la migration** pour l'application `audit`.
- [x] **Développer un décorateur de modèle ou signal Django** pour intercepter automatiquement les modifications sur les tables cibles (quantités, prix, statuts de factures et paiements, pertes, mouvements de trésorerie).
- [x] **Bloquer la suppression physique (Hard Delete)** au niveau des méthodes `delete()` de ces modèles en levant une exception applicative si l'enregistrement a dépassé l'état de brouillon.

### Étape 2 : Moteur de Marge et Profitabilité (`apps.reports.services`)
- [x] **Créer le service `TripProfitService`** dans `backend/apps/reports/services/profit.py` :
  - Méthode `calculate_estimated_margin(trip)` : Utilise les prix de vente théoriques et les coûts planifiés.
  - Méthode `calculate_current_margin(trip)` : Récupère la vente associée (`Sale`), le prix d'achat fournisseur de la commande, le coût brut de transport de la ligne de règlement et toutes les dépenses ventilées via `ExpenseAllocation` liées à ce trajet.
  - Méthode `calculate_final_margin(trip)` : Gèle les calculs si le trajet est fermé.
  - Méthode `get_cost_breakdown(trip)` : Retourne la décomposition détaillée des revenus et coûts (achat carburant, transport, douane, route, etc.).

### Étape 3 : Service de Stock Théorique (`apps.reports.services`)
- [x] **Créer le service `TheoreticalStockService`** dans `backend/apps/reports/services/stock.py` :
  - Méthode `get_supplier_reliquats()` : Somme des reliquats disponibles sur toutes les commandes d'achats fournisseurs actives.
  - Méthode `get_loaded_unsold_quantity()` : Quantité chargée sur les trajets n'ayant pas encore généré de vente (`Sale`).
  - Méthode `get_total_theoretical_stock()` : Retourne la somme des deux composantes ci-dessus.

### Étape 4 : Service et Endpoints de Reporting SQL/Optimisé
- [x] **Créer les classes de requêtes de rapports dédiées** dans `backend/apps/reports/queries/` pour éviter d'alourdir l'ORM (utilisation de requêtes SQL brutes ou agrégats optimisés) :
  - `CustomerStatementQuery` (Historique des transactions et encours client)
  - `SupplierStatementQuery` (Achats et paiements fournisseur)
  - `TransporterStatementQuery` (Voyages, déductions et encours transporteur)
  - `TruckHistoryQuery` (Voyages et rentabilité par camion)
  - `TripReportQuery` (Synthèse opérationnelle des trajets)
  - `FuelStockReportQuery` (État des stocks théoriques)
  - `LossReportQuery` (Suivi des pertes et tolérances)
  - `MarginReportQuery` (Analyse de rentabilité par trajet/client/produit)
  - `TreasuryStatementQuery` (Relevés de comptes de trésorerie avec exclusion des virements internes `TRANSFER`)
- [x] **Ajouter le support de l'exportation** (CSV, Excel avec `openpyxl`, PDF optionnel) sur ces rapports.

### Étape 5 : API Views et ViewSets
- [x] **Créer `DashboardViewSet`** dans `backend/apps/reports/views/dashboard.py` :
  - Endpoint unique `GET /api/dashboard/summary/` prenant en compte le paramètre de filtre de date global (`?range=...&from=...&to=...`) et retournant les 6 sections d'indicateurs (Opérations, Carburant, Ventes, Transport, Finance, Profit).
- [x] **Créer `ReportViewSet`** dans `backend/apps/reports/views/reports.py` :
  - Endpoint `GET /api/reports/{report_type}/` routant dynamiquement vers le bon service de requêtes et gérant le paramètre `?export=csv|xlsx`.
- [x] **Créer `SearchView`** (Recherche Globale) dans `backend/apps/reports/views/search.py` :
  - Endpoint `GET /api/search/?q=` implémentant une recherche insensitive et partielle sur l'ensemble des index textuels. Pour les camions trouvés, retourner l'état opérationnel enrichi (Trip en cours, volume, client, statut).
- [x] **Créer `AuditLogViewSet`** dans `backend/apps/audit/views.py` pour permettre aux administrateurs de consulter l'historique des modifications par objet.

### Étape 6 : Tests d'Intégration & Validation Financière (Backend)
- [x] **Créer la suite de tests** `backend/apps/reports/tests.py` :
  - **Test du calcul du Stock Théorique (§32)** : Valider que le stock équivaut à la somme des reliquats fournisseurs + le carburant des trajets en transit (non encore déchargés/vendus).
  - **Test de Recalcul de Marge Automatique (§33)** : Créer un trajet avec vente et transport. Calculer la marge. Insérer une dépense imprévue (`Expense`) et l'allouer à ce trajet. Relire la marge et valider qu'elle a baissé automatiquement sans action manuelle.
  - **Test de Cohérence Financière (§34)** : Vérifier que la somme des profits par client/camion/commande est strictement égale à la somme des marges de tous les trajets individuels associés.
  - **Test d'Audit Log sur Annulation (§39)** : Annuler une facture validée. Vérifier qu'elle passe au statut `CANCELLED` (pas supprimée) et qu'une ligne `AuditLog` trace les valeurs modifiées.
  - **Test d'exécution des 16 rapports (§37)** : Parcourir les 16 types de rapports de la spécification et s'assurer que l'API renvoie des données structurées valides.

---

## 3. Plan d'Action Interface Frontend (Vue 3)

### Étape 7 : Composant Filtre et Tableau de Bord
- [x] **Créer `DateRangeFilter.vue`** (Composant partagé) :
  - Permet de filtrer par périodes prédéfinies (Aujourd'hui, Hier, Cette semaine, Ce mois, Cette année, Période personnalisée).
- [x] **Créer `DashboardView.vue`** :
  - Affiche les 6 panels de KPIs opérationnels et financiers sous forme de graphiques simples ou de compteurs de performance (revenus, dépenses, volumes transportés, pertes, trésorerie).

### Étape 8 : Rapports, Exportations & Recherche Globale
- [x] **Créer `ReportsView.vue`** :
  - Sélecteur de rapport permettant d'afficher les données sous forme de tableau interactif et de déclencher les téléchargements de fichiers d'export (CSV, Excel).
- [x] **Créer `GlobalSearchBar.vue`** :
  - Champ de recherche global intégré dans l'en-tête principal de l'application.
  - Affiche les résultats catégorisés (Trips, Camions, Factures, Clients).
  - Pour les résultats de type Camion, affiche une infobulle/carte enrichie contenant son statut opérationnel en temps réel (Trip actif, produit transporté, volume et lien vers l'historique complet).
- [x] **Créer `AuditLogViewer.vue`** :
  - Interface d'administration pour inspecter les modifications d'entités avec surbrillance des différences de valeurs (Diff View).

---

## 4. Scénario de Recette Manuel (Validation Finale)

1. **Vérification du Stock Théorique** :
   - Noter le stock théorique actuel.
   - Créer un achat de **100 000 L**. Vérifier que le stock théorique augmente instantanément de **100 000 L**.
   - Créer un trajet (chargement) de **45 000 L** sur cet achat. Le stock théorique global doit rester inchangé.
   - Valider la décharge/vente du trajet. Le stock théorique doit baisser de **45 000 L** (qui ont été livrés et vendus).
2. **Vérification du Moteur de Marge** :
   - Ouvrir la fiche d'un trajet livré et noter sa marge calculée.
   - Créer une dépense de frais de route de **50 000 XOF** et l'allouer à ce trajet.
   - Vérifier immédiatement sur la fiche du trajet que sa marge nette a été réduite de **50 000 XOF**.
3. **Piste d'Audit** :
   - Modifier le prix d'un produit.
   - Accéder à l'interface d'Audit Log en tant qu'Admin et valider la présence de la ligne trançant le changement de prix avec l'ancienne et la nouvelle valeur.
4. **Recherche Globale** :
   - Saisir la plaque d'immatriculation d'un camion actif dans la barre de recherche globale.
   - Valider que le système renvoie le camion avec le nom du client livré, la quantité à bord et son statut opérationnel (ex: `IN_TRANSIT`).

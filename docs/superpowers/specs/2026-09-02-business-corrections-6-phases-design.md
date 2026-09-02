# Corrections métier validées — 6 phases (capital, fond de roulement, dépenses générales, bénéfices, frais trajet, camion/transporteur)

Date: 2026-09-02
Statut: Approuvé par le client, prêt pour plan d'implémentation.

## Contexte et règles générales

Ce chantier regroupe 6 corrections métier indépendantes, validées avec le client. Règles transverses à respecter dans toutes les phases :

- Ne pas casser la logique existante des avances fournisseur/transporteur.
- Ne pas modifier les règles déjà validées de trésorerie et Grand livre.
- Pas de refonte UI large — actions/pages ciblées ajoutées aux écrans existants.
- Tests backend/frontend ciblés par phase.
- Mouvements financiers auditables : pas de suppression silencieuse d'une transaction ayant déjà un impact comptable — utiliser l'annulation/contrepassation.
- Chaque phase se livre et se valide indépendamment (TDD, rouge puis vert), sans mélanger les sujets.

Chaque phase ci-dessous doit être lue avec les patterns actuels du code (`FinancePostingService`, `ControlledDebtPaymentService`, `TripCostService`, `TripProfitService`) — ne pas dupliquer une logique déjà centralisée.

---

## Phase 1 — Apport en capital depuis Actionnaires / Associés

### Règle métier

- On enregistre uniquement l'argent réellement payé (pas de promesse de contribution).
- Un apport associé est une entrée réelle de trésorerie, choisissant exactement un compte : Banque ou Caisse.
- L'apport augmente la trésorerie et le capital de l'entreprise.
- L'apport apparaît dans le Grand livre de l'associé et dans le Journal de trésorerie.
- **Justificatif obligatoire** pour tout nouvel apport (même exigence que les avances fournisseur/transporteur). Seules les données historiques (solde d'ouverture / `Shareholder.contribution` existant, déjà en base) peuvent rester sans justificatif — ce champ n'est pas concerné par cette phase et n'est pas migré vers le nouveau modèle.

### Modèle

Nouveau modèle `ShareholderContribution` (app `finance`, hérite `AuditableModel` + `TimeStampedModel`, même famille que `ShareholderWithdrawal`) :

- `shareholder` FK (`PROTECT`)
- `amount` (`DecimalField`, contrainte `> 0`)
- `bank_account` FK nullable + `cash_account` FK nullable — contrainte DB : exactement un des deux renseigné (identique à `ShareholderWithdrawal`/`SupplierPayment`)
- `date`
- `reference` (`CharField`, blank autorisé)
- `note` (`TextField`, blank autorisé)
- `document` FK vers `documents.Document`, **non-null sur create** (validé en serializer, pas en contrainte DB — même pattern que `SupplierAdvanceSerializer`)
- `recorded_by` FK `accounts.User`

### Service

Le justificatif étant obligatoire (comme les avances), le précédent le plus proche est `AdvanceService.create_supplier_advance` (`backend/apps/finance/services.py:549-587`) — création directe (`Document` + `TreasuryTransaction`), pas d'indirection par `FinancePostingService._post_treasury` (réservée aux flux où le document reste optionnel, comme les retraits associés).

- `ShareholderContributionService.record_contribution(*, shareholder_id, amount, date, reference, notes, bank_account_id=None, cash_account_id=None, attachment, actor)` — `@transaction.atomic`, même forme que `create_supplier_advance` :
  1. `select_for_update` sur le `Shareholder`.
  2. Verrouille le compte cible (banque ou caisse), vérifie exactement un des deux fourni.
  3. Crée la ligne `ShareholderContribution`.
  4. Crée le `Document` (`document_type="shareholder_contribution_proof"`), le lie à la contribution.
  5. Crée la `TreasuryTransaction` (`type=MONEY_IN`, `source_object=contribution`, `document=document`).
- Pas de vérification de solde bancaire (contrairement à un retrait) : un apport augmente le compte, aucune contrainte de solde suffisant à vérifier.

### Capital total

- Nouvelle fonction `get_total_capital()` (service `finance`, réutilisée par Phase 2) = `Shareholder.objects.aggregate(Sum("contribution"))` (solde d'ouverture historique) **+** `ShareholderContribution.objects.aggregate(Sum("amount"))` (nouveaux apports réels).
- Affiché avec libellé explicite distinguant les deux composantes (ex. "Capital (solde d'ouverture + apports)").

### Ledger associé

- **Ne pas** fusionner l'apport dans `ShareholderStatementQuery` (`backend/apps/reports/queries/shareholder_statement.py`) : ce relevé maintient un solde courant dont l'invariant documenté est `balance == ShareholderLedgerService.get_available_balance()` (équité distribuable : parts de bénéfice, retraits, prêts). Un apport en capital n'est pas distribuable — l'ajouter comme ligne de crédit y gonflerait artificiellement ce solde et casserait l'invariant.
- À la place : nouvelle méthode `ShareholderContributionService.get_contribution_history(shareholder_id)` retournant la liste chronologique des `ShareholderContribution` avec un total cumulé de capital (calcul indépendant, pas mélangé à `balance`). Affiché comme section/tab distincte "Capital" dans `ShareholderView.vue`, à côté du relevé existant — répond à l'exigence "le Grand livre de l'associé affiche l'apport" sans toucher au solde validé.
- `ShareholderLedgerService.get_shareholder_summary`/`get_available_balance` : **inchangés**, la contribution n'y entre jamais (elle augmente le capital, pas le solde distribuable).

### UI

- `ShareholderView.vue` : nouveau bouton "Nouvel apport" / "Apport en capital" dans la liste des associés et dans le détail/grand livre d'un associé (préverrouillé sur cet associé, champ associé non modifiable dans ce cas).
- Nouveau `ContributionForm.vue` (calqué sur le futur/existant `ShareholderWithdrawalForm`) : associé, montant, banque ou caisse (radio exclusif), date, référence, note, justificatif image (obligatoire, réutilise `IMAGE_UPLOAD_ACCEPT`).

### Tests

- Apport 10 000 000 XOF vers banque → banque += 10 000 000.
- Une seule `TreasuryTransaction` (`MONEY_IN`) créée par apport.
- Capital total augmente de 10 000 000.
- Grand livre associé affiche la ligne `CONTRIBUTION`.
- Apport sans justificatif → rejeté (`ValidationError`).
- Apport avec banque ET caisse renseignées, ou aucune des deux → rejeté.

---

## Phase 2 — Fond de roulement (formule corrigée, pas de double comptage, avances ouvertes comptées comme un droit)

### Règle métier corrigée

Le capital apporté (Phase 1) est déjà entré en banque/caisse via sa `TreasuryTransaction` — l'additionner une seconde fois au calcul du fond de roulement compterait le même argent deux fois.

Une avance ouverte fournisseur/transporteur est un droit de l'entreprise (l'argent a quitté la banque mais reste dû à l'entreprise sous forme de marchandise/service à recevoir) — elle ne doit pas faire baisser artificiellement le fond de roulement au seul motif que du cash a été transformé en avance. `ControlledDebtPaymentService.describe_supplier_balance`/`describe_transporter_balance` retournent déjà un `net_balance = open_advances - total_due` **signé** (positif = avances nettes en faveur de l'entreprise, négatif = dette nette envers le tiers) ; `supplier_net_total`/`transporter_net_total` dans `DashboardViewSet.summary()` sont la somme de ces `net_balance` signés. La formule doit donc **additionner** ces totaux signés, jamais les soustraire comme s'ils étaient de purs montants de dette :

```
Fond de roulement réel =
  banques + caisses
  + créances clients
  + supplier_net_total   (signé : avances ouvertes fournisseurs − dettes fournisseurs)
  + transporter_net_total (signé : avances ouvertes transporteurs − dettes transporteurs)
  - dettes douane/transit/frais
```

Équivalent : `+ avances ouvertes fournisseurs + avances ouvertes transporteurs - dettes fournisseurs - dettes transporteurs - dettes douane/transit/frais` — mais en pratique on réutilise directement `supplier_net_total`/`transporter_net_total` déjà calculés (ne pas re-décomposer avances/dettes séparément, pour ne jamais désynchroniser avec la logique déjà validée de `ControlledDebtPaymentService`).

Le capital apparaît dans le breakdown à titre **informatif** (source de financement), pas dans le calcul final :

- Capital apporté (info)
- Trésorerie disponible (banques + caisses)
- Créances clients
- Solde net fournisseurs (avances − dettes, signé)
- Solde net transporteurs (avances − dettes, signé)
- Dettes douane/transit/frais
- **Fond de roulement final** (formule ci-dessus, n'inclut pas "Capital apporté")

"Trésorerie disponible" (banques+caisses) reste affichée séparément et distinctement de "Fond de roulement" pour éviter la confusion entre argent disponible réel et vue financière plus large.

### Implémentation

- Nouvelle fonction backend, réutilisant les valeurs déjà calculées dans `DashboardViewSet.summary()` sans re-requêter :
  - `bank_amounts["total"] + cash_amounts["total"]` (trésorerie disponible)
  - `customer_amounts["total"]` (créances clients)
  - `supplier_net_total`, `transporter_net_total` (déjà calculés via `ControlledDebtPaymentService.describe_supplier_balance`/`describe_transporter_balance`, **signés**, additionnés tels quels)
  - `customs_total + transit_total + road_transit_total + other_total` (déjà calculés, buckets `debts`)
  - `get_total_capital()` (Phase 1), affiché seul, non sommé dans le résultat final.
- Ajouté au payload `summary()` sous une clé `working_capital` : `{capital, treasury_available, customer_receivables, supplier_net_balance, transporter_net_balance, other_debts, total}`.
- Frontend : bloc "Fond de roulement" (Dashboard ou Trésorerie — décidé en implémentation selon la place disponible sans refonte large) avec sous-cartes correspondant au breakdown ci-dessus, "Capital apporté" visuellement distinct (ex. carte "info" non incluse dans la somme visuelle) et "Trésorerie disponible" clairement séparée de "Fond de roulement final".

### Tests

- Base avec banque + caisse + capital (via apport Phase 1) + client débiteur + dettes fournisseurs/transporteurs/frais : `working_capital.total` ne compte le capital qu'une fois indirectement (via banque/caisse), jamais deux fois.
- Un apport supplémentaire → `treasury_available` augmente, `working_capital.total` augmente d'autant (pas du double du montant).
- **Avance fournisseur de 2 000 000** : banque diminue de 2 000 000, `supplier_net_total` augmente de 2 000 000 (avance ouverte = droit) → `working_capital.total` **inchangé** (cash transformé en avance, pas de perte de fond de roulement).
- **Paiement d'une dette fournisseur/transporteur déjà due** (pas une avance) : trésorerie baisse, `supplier_net_total`/`transporter_net_total` augmente d'autant (la dette diminue) → effet net sur `working_capital.total` = **0**. Le test doit vérifier explicitement l'égalité avant/après (pas une augmentation).

---

## Phase 3 — Dépenses générales + catégories configurables

### Règle métier

- Dépenses générales = `Expense` non liées à un trajet, payées depuis la trésorerie, diminuent la trésorerie, comptent dans le bénéfice net, jamais dans le coût trajet.
- Catégories générales créables librement par l'utilisateur : loyer, salaires, internet, électricité, administration, réparations, frais bancaires, autres, et toute catégorie personnalisée.
- Catégories système liées aux trajets — **customs, transit, road_transit, road (frontière), loading, transport** — protégées : ne doivent pas être supprimées/renommées/désactivées, car elles pilotent le calcul du coût trajet et les dettes du dashboard.
- Les frais trajet restent liés aux trajets ; la page Dépenses générales ne fait que les afficher en monitoring (lecture seule), sans dupliquer la dette.

**Phase sensible** : la migration `Expense.category` (enum → FK) touche potentiellement un grand nombre de tests existants qui créent des `Expense(category=Expense.Category.X)`. Elle doit être traitée comme une sous-étape isolée à l'intérieur de la Phase 3, avec sa propre passe de tests larges (exécution complète de la suite `finance`/`trips`/`reports` avant et après la migration, pas seulement les tests nouvellement ajoutés) avant de poursuivre sur le reste de la phase.

### Modèle `ExpenseCategory` (nouveau, précédent : `core.Product`)

- `name` (`CharField`)
- `code` (`SlugField`, unique, immuable une fois créé)
- `is_system` (`BooleanField`, default `False`)
- `is_active` (`BooleanField`, default `True`)
- `display_order` (`PositiveIntegerField`, default 0)

Migration de données (une seule migration `RunPython`, non destructive) :
1. Crée une ligne `ExpenseCategory` par valeur actuelle de l'enum `Expense.Category`, avec `code` = valeur enum en minuscule (`customs`, `transit`, `road_transit`, `road`, `loading`, `transport`, `unloading`, `administration`, `rent`, `salary`, `repairs`, `bank_charges`, `other`, `import_intention`).
2. `is_system=True` pour exactement les 6 codes câblés en dur ailleurs : `customs, transit, road_transit, road, loading, transport`.
3. `is_system=False` pour le reste (renommables/désactivables librement).
4. Convertit `Expense.category` (CharField enum) en `ForeignKey(ExpenseCategory, on_delete=PROTECT)`, en mappant chaque ligne existante vers la catégorie de même `code`.

### Ré-encodage des points câblés en dur

Chaque endroit qui compare aujourd'hui à `Expense.Category.X` (enum Python) est réécrit pour comparer à `category.code == "x"` (string), comportement inchangé :
- `backend/apps/trips/services.py` `TripCostService._expenses_by_category`/`calculate_trip_cost_basis` (`known_expense_categories` devient un set de codes).
- `backend/apps/finance/services.py` `ControlledDebtPaymentService._EXPENSE_CATEGORY_BY_DEBT_TYPE`/`_debt_type_for_expense`.
- `backend/apps/reports/queries/margin_report.py` `_EXCLUDED_FROM_ADDITIONAL_COSTS`.
- `backend/apps/finance/labels.py` (map catégorie → libellé Journal).
- `backend/apps/finance/serializers.py` `IndirectSettlementRequestSerializer.category` (passe de `ChoiceField(Expense.Category.choices)` à `PrimaryKeyRelatedField(ExpenseCategory)` ou équivalent).

Validation serializer : `ExpenseCategoryViewSet` (nouveau, CRUD simple) refuse la désactivation/suppression/renommage d'une catégorie `is_system=True` (message clair).

### Page Dépenses générales

- Nouvelle vue `ExpensesView.vue` : liste + création d'`Expense` filtrée sur les catégories `is_system=False` **et** sans `ExpenseAllocation` (le serializer de création pour cette page force l'absence d'allocation).
- Champs formulaire : catégorie (sélecteur existant + option "Créer une catégorie" ouvrant un mini-modal `name` uniquement, `code` auto-généré par slug), montant, compte banque/caisse, date, référence, note, justificatif (optionnel, aligné sur le pattern `Expense` existant — pas de nouvelle exigence).
- Filtre période (réutilise `DateRangeFilter` existant).
- Section "Monitoring frais trajet" en lecture seule : Douane/Transit/Transit routière/Frontière/Chargement/Autres frais trajet, lue depuis `ControlledDebtPaymentService.describe_expense_group` par bucket existant — aucune nouvelle dette créée, aucune duplication.

### Tests

- Création dépense générale avec catégorie existante, payée depuis banque → banque diminue, `TreasuryTransaction` MONEY_OUT créée.
- Création d'une nouvelle catégorie utilisateur (ex. "Internet") puis dépense dans cette catégorie.
- Dépense générale non allouée à un trajet n'apparaît pas dans le coût trajet.
- Frais trajet existants (douane, transit...) : calcul de coût trajet et dettes inchangés après migration FK.
- Tentative de désactiver/renommer/supprimer une catégorie système → rejetée.
- Bénéfice opérationnel inchangé après création d'une dépense générale ; bénéfice net diminue (couvert en détail Phase 4).

---

## Phase 4 — Bénéfice opérationnel vs net

### Règle métier

- Bénéfice opérationnel = bénéfice des trajets uniquement (`Σ TripProfitService.calculate_current_margin`, formule trajet **inchangée** : montant facturé client + indemnisation perte transporteur − coût total réel chargé).
- Dépenses générales période = `Sum(Expense.amount)` pour les `Expense` sans `ExpenseAllocation`, filtrées sur la période demandée.
- Bénéfice net = bénéfice opérationnel − dépenses générales période.
- Pas de double comptage : les dépenses générales n'entrent jamais dans le coût trajet (déjà garanti par la séparation "avec/sans allocation" de Phase 3).

### Implémentation

- Le filtre période s'applique identiquement aux trajets (déjà existant) et aux dépenses générales (nouveau, sur `Expense.date`).
- `ProfitView`/endpoint associé expose `operational_profit`, `general_expenses_total`, `net_profit` en plus du détail trajet existant (tableau trajets = détail de l'opérationnel, inchangé).

### Tests

- Un trajet profitable + une dépense générale sur la même période → `operational_profit` = marge trajet seule, `net_profit` = `operational_profit - dépense`.
- Filtre période personnalisée : dépense hors période exclue du calcul, trajet hors période exclu également.

---

## Phase 5 — Frais trajet : calcul Par litre / Par camion + édition/contrepassation

### Règle métier calcul (restreint aux `Expense` allouées à un trajet)

- Méthodes disponibles pour une `Expense` allouée à un trajet : **Par litre** et **Par camion** uniquement (les autres méthodes `calculation_method` restent possibles pour les dépenses générales non allouées, sans changement).
- **Par litre** : montant saisi = XOF/L. `total = montant_par_litre × quantité_chargée`.
- **Par camion** : montant saisi = montant total pour le camion/trajet. `total = montant_saisi` (pas de multiplication). `coût_par_litre = montant_saisi / quantité_chargée` (calculé côté `TripCostService` pour le prix de revient/L, pas stocké sur `Expense.amount`).
  - Exemple : 10 000 XOF par camion sur 45 000 L → coût/L = 10 000/45 000 ≈ 0,222 XOF/L, total trajet = 10 000 XOF (pas 450 000 000).

### Édition / suppression

- Non payé (`UNPAID`) : modification/suppression autorisée sans changement (comportement actuel conservé), **pas de mouvement de trésorerie inverse** puisqu'aucune sortie n'a encore eu lieu.
- Payé ou partiellement payé (`PAID`/`PARTIALLY_PAID`) :
  - `ExpenseSerializer.validate()` bloque la modification des champs sensibles (`amount`, `calculation_method`, `category`, allocations) avec message clair.
  - Le hard-delete reste bloqué (déjà le cas, `MethodNotAllowed` inconditionnel).
  - Nouvelle action `POST /api/expenses/{id}/cancel/` (nouveau `ExpensePostingService.cancel_paid_expense(expense, user)`, `@transaction.atomic`), qui **respecte le mode de règlement d'origine** :
    - `paid_by_customer_directly=False` (règlement normal via trésorerie) : calcule le montant **réellement sorti** en sommant les `TreasuryTransaction` `MONEY_OUT` déjà liées à cette dépense (pas `expense.amount` brut — pertinent pour un `PARTIALLY_PAID`), crée une `TreasuryTransaction` `MONEY_IN` compensatoire de ce même montant exact, sur le même type de compte (banque/caisse) que la sortie d'origine.
    - `paid_by_customer_directly=True` (réglé indirectement par le client via `IndirectSettlementService`, jamais passé par la trésorerie de l'entreprise) : **aucune** `TreasuryTransaction` n'est créée à l'annulation — il faut inverser l'effet indirect existant (restaurer la créance client correspondante) en s'appuyant sur la logique déjà présente d'`IndirectSettlementService`, à confirmer/adapter précisément en implémentation plutôt que de fabriquer un mouvement banque/caisse qui n'a jamais existé.
    - Dans les deux cas : passe `status=CANCELLED` (déjà dans l'enum), visible au Journal et au Grand livre concerné, rejette si déjà `CANCELLED`.

### Tests

- Frais Par litre : total = montant × quantité.
- Frais Par camion sur 45 000 L, montant 10 000 XOF → total trajet = 10 000 XOF, coût/L ≈ 0,222.
- Modification/suppression d'un frais non payé → OK, aucune `TreasuryTransaction` créée.
- Modification d'un frais payé → rejetée ; annulation via `/cancel/` sur un frais réglé via trésorerie → `status=CANCELLED` + `TreasuryTransaction` `MONEY_IN` inverse créée pour le montant réellement sorti (pas `expense.amount` si `PARTIALLY_PAID`), coût trajet et bénéfice recalculés sans ce frais.
- Annulation d'un frais réglé indirectement par le client (`paid_by_customer_directly=True`) → `status=CANCELLED`, **aucune** `TreasuryTransaction` créée, créance client restaurée en conséquence.
- Prix de revient/L et bénéfice trajet corrects après passage Par camion.

---

## Phase 6 — Camion obligatoire lié à Transporteur (avec exception COMPANY_OWNED)

### Règle métier

- `Truck.owner_transporter` obligatoire si `ownership_type = EXTERNAL`.
- `Truck.owner_transporter` reste nullable si `ownership_type = COMPANY_OWNED` (pas de faux transporteur interne créé — éviterait de mélanger comptes/dettes/avances/grands livres transporteurs).
- Trajet avec camion EXTERNAL : `transporter` du trajet rempli automatiquement depuis `truck.owner_transporter`, champ readonly côté UI, incohérence camion/transporteur interdite côté serializer.
- Trajet avec camion COMPANY_OWNED : `transporter` du trajet reste `null`, aucune dette/paiement transporteur automatique, aucun `TransportDeduction` créé en cas de perte chargeable (la perte reste un manque à gagner reflété par la quantité livrée réduite, sans compensation — **assumption validée par le client**).
- Grand livre transporteur : ne liste que les camions `EXTERNAL` qui lui sont liés (comportement déjà naturel, `owner_transporter` reste optionnel pour COMPANY_OWNED donc jamais rattaché à un transporteur).

### Modifications backend

1. `Truck` : validation serializer — `owner_transporter` requis si `ownership_type=EXTERNAL`, sinon libre.
2. `Trip.transporter` : migration `AlterField(null=True, blank=True)`.
3. `TripSerializer.validate()` (nouvelle logique, aujourd'hui absente) :
   - camion EXTERNAL + `transporter` absent/différent de `truck.owner_transporter` → erreur.
   - camion EXTERNAL → `transporter` auto-dérivé de `truck.owner_transporter` si non fourni.
   - camion COMPANY_OWNED + `transporter` fourni → erreur ("un camion société ne peut pas avoir de transporteur").
4. `DeliveryService.sync_transport_shortage_deduction` (`trips/services.py:571-609`) : si `trip.transporter_id is None`, ne crée/ne met à jour aucun `TransportDeduction` (skip explicite, pas d'exception).
5. `TransportPaymentSerializer.validate()` : message explicite et dédié si `trip.transporter_id is None` ("ce trajet n'a pas de transporteur externe, aucun paiement transport n'est possible") au lieu du message générique "ne correspond pas".
6. `reports/queries/trip_report.py:40` et `reports/views/dashboard.py:328` : `trip.transporter.name if trip.transporter_id else None` (ou libellé "Flotte propre").

### Modifications frontend

- `TruckForm` (camion) : `owner_transporter` requis conditionnellement à `ownership_type=EXTERNAL` dans le formulaire.
- `TripForm.vue` : transporteur readonly et dérivé du camion pour EXTERNAL ; pour COMPANY_OWNED, champ masqué ou libellé clair "Flotte propre / Camion société", payload envoie `transporter: null` (pas de coercition `Number()` aveugle).
- `TripDetail.vue` : popup auto de paiement transport (`ASSIGNED → SENT_FOR_LOADING`) et bouton "Ajouter un paiement transport" masqués si `trip.transporter` est `null`.
- `types.ts` (trips) : `transporter: number | null`.

### Migration des données existantes

- Rapport (management command ou script one-shot, pas de migration silencieuse) listant les camions `EXTERNAL` existants sans `owner_transporter` pour correction manuelle avant d'activer la contrainte bloquante en base — pas d'invention automatique de transporteur.

### Vérification exhaustive avant merge

Avant de fusionner cette phase, recherche exhaustive de tous les accès `.transporter.` (attribut, pas juste les 4 sites déjà identifiés en investigation : `trip_report.py:40`, `dashboard.py:328`, `sync_transport_shortage_deduction`, `TransportPaymentSerializer.validate`) côté backend **et** frontend (`trip.transporter.name`, `trip.transporter_detail?.name`, accès similaires en `.vue`/`.ts`), pour s'assurer qu'aucun ne plante sur `transporter=null`. Cette recherche doit être refaite au moment de l'implémentation (le code a pu changer depuis l'investigation initiale) et documentée dans le résumé final de la phase.

### Tests

- Créer un camion EXTERNAL sans transporteur → échoue.
- Créer un camion COMPANY_OWNED sans transporteur → passe.
- Choisir un camion EXTERNAL dans un trajet → transporteur rempli automatiquement, readonly.
- Choisir un camion COMPANY_OWNED dans un trajet → pas de transporteur, pas de dette transporteur créée, pas de `TransportDeduction` en cas de perte.
- Grand livre transporteur ne liste que ses camions EXTERNAL.
- Impossible d'avoir un trajet avec camion EXTERNAL et un transporteur différent de `truck.owner_transporter`.

---

## Risques résiduels à surveiller en implémentation

- Migration `Expense.category` enum → FK : nécessite de repasser sur tous les tests existants qui créent des `Expense(category=Expense.Category.X)` — mise à jour mécanique mais à grande échelle (nombreux tests).
- `labels.py` a deux maps catégorie→libellé distinctes (Journal vs modal paiement) déjà notées comme désynchronisées dans le code actuel — Phase 3 est l'occasion de les auditer sans les refondre.
- Phase 6 touche un champ FK obligatoire historique (`Trip.transporter`) — même limité à `null=True`, toute requête/rapport non listée ci-dessus qui ferait un `.transporter.` sans garde doit être vérifiée en implémentation (recherche exhaustive avant de merger).

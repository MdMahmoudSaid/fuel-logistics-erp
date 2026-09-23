# Rapports — capital, dépenses générales, dettes et créances — Design

**S'appuie sur :** `docs/superpowers/specs/2026-09-23-rapports-document-comptable-design.md` (cadre « document comptable » : `REPORT_SPECS`, `build_report_document`, `report_labels.py`, `ReportSheet.vue`, `report_pdf.py`, `usePrintScope`). Ce document ajoute **5 types de rapport** à ce cadre ; il ne change ni les 17 rapports existants, ni le format legacy `{report_type, fields, rows}`.

**Branche :** `feature/rapports-capital-dettes-creances`, créée à partir de `feature/rapports-document-comptable` (non fusionnée), car le cadre s'y trouve.

## Contexte

Le client demande cinq rapports supplémentaires, chacun « bien détaillé » : capital, dépenses générales, dettes de frais de trajet (avec un second champ pour choisir le type de frais), dettes générales (fournisseurs + transporteurs + frais de trajet) et créances clients générales.

Deux principes gouvernent tout le document :

1. **Aucun chiffre nouveau.** Chaque montant vient d'un service métier déjà utilisé par les écrans de paiement, le tableau de bord ou l'écran Actionnaires. Les rapports ne recalculent pas un reste directement depuis les modèles (avances, paiements annulés, retenues transporteur, frais alloués et soldes négatifs sont déjà gérés par ces services).
2. **Les totaux se rapprochent des écrans existants** et des tests le prouvent (§Tests).

## Objectifs

1. Cinq nouveaux slugs de rapport rendus comme les 17 autres : feuille à l'écran, impression, PDF fr/en/ar (RTL réel en arabe).
2. Un second sélecteur (type de frais) sur le rapport des dettes de frais de trajet.
3. Comportement temporel explicite par rapport (§Périodes).
4. Aucune régression sur les rapports existants.

## Hors périmètre

- Pas de changement de CSV/XLSX au-delà de ce que `rows_to_csv/xlsx` font déjà avec `FIELDS` + `rows`.
- Pas de nouveau calcul métier : pas de modification de `describe_supplier`, `describe_transport_payment`, `describe_expense`, `PaymentAllocationService` ni des écrans de paiement.
- Pas de graphiques, pas de nouveaux filtres autres que `fee_type`.

## Décisions

| # | Décision | Pourquoi |
|---|---|---|
| N1 | Slugs : `capital-report`, `general-expense-report`, `trip-fee-debt-report`, `general-debt-report`, `general-receivable-report`. | `expense-report` existe déjà (toutes dépenses, non modifié). |
| N2 | Devise XOF ; suffixe XOF **uniquement** sur les colonnes de kind `money`. Dates, pourcentages, références, statuts et nombres n'ont jamais de suffixe. | Règle D1 du cadre. |
| N3 | Les rapports de dettes et de créances montrent **uniquement ce qui reste à régler** (lignes dont le reste ≠ 0). | Choix validé par l'utilisateur. |
| N4 | « Dépenses générales » = toute dépense dont la catégorie n'est **pas** une catégorie système de frais de trajet, même sans rattachement à un trajet. | Choix validé par l'utilisateur. |
| N5 | Lignes `CANCELLED` : conservées pour la traçabilité, exclues de tous les totaux et comptes, comptées dans une ligne de synthèse `cancelled_excluded` (règle D7 du cadre). | Cohérence avec les rapports existants. |
| N6 | Les lignes de dettes sont construites uniquement à partir de `ControlledDebtPaymentService.get_payable_debts()`. Les montants viennent des lignes (`lines`) renvoyées par ce service. Date, référence et trajets, affichés à titre d'information seulement, sont lus sur l'objet source (`SupplierOrder`, `TransportPayment`, `Expense`) retrouvé par l'`id` de la ligne. | Ne pas recalculer un reste, mais avoir des colonnes structurées (le `label` du service est un texte libre). |

## Périodes et situation courante

| Rapport | Comportement temporel | Détail |
|---|---|---|
| **Capital** | Situation actuelle par actionnaire ; détail des apports filtré par la période. | Le tableau « par actionnaire » n'est **jamais** filtré. Le tableau « apports de la période » filtre `ShareholderContribution.date` par `date_from`/`date_to` (sans période : tous les apports). Mode période du document : `range`. |
| **Dépenses générales** | Lignes et totaux filtrés par la période. | Filtre sur `Expense.date`. Mode `range`. |
| **Dettes de frais de trajet** | Situation courante, **sans filtre de période**. | `period_mode="as_of"` (« Situation au jj/mm/aaaa »). |
| **Dettes générales** | Situation courante, sans filtre de période. | `period_mode="as_of"`. |
| **Créances clients** | Situation courante, sans filtre de période. | `period_mode="as_of"`. |

Pour les trois rapports « situation courante », on applique **les deux garde-fous** :

1. **Front :** `REPORT_TYPES` porte un drapeau `periodless: true`. Pour ces types, `ReportsView` masque `DateRangeFilter`, n'envoie aucun paramètre de période (ni pour l'aperçu ni pour l'export PDF) et réinitialise la période quand on change de type.
2. **Back :** leur `run()` accepte `date_from`/`date_to` et les **ignore** (au lieu de lever `TypeError`, ce qui donnerait un 400 via la vue). Un test le prouve.

**Constat (bug existant, vérifié en direct le 2026-09-23) :** `GET /api/reports/customer-outstanding/?from=…&to=…` et `fuel-stock` renvoient **400**, car leur `run()` n'accepte aucun argument alors que la page envoie la période choisie. **Décision proposée :** poser le même drapeau `periodless` sur ces quatre rapports existants (`customer-outstanding`, `supplier-outstanding`, `transporter-outstanding`, `fuel-stock`), en une ligne de données chacun. C'est le même mécanisme et il corrige l'erreur de chargement quand un utilisateur choisit une période. À confirmer à la relecture.

## Changements du cadre (communs aux 5 rapports)

1. **Kind de colonne `percent`** : deux décimales et suffixe `%`, sans XOF. Ajouté à `report_document.py`, `reportCells.ts`, `report_pdf.py`, `ReportColumnKind` (types.ts) et testé.
2. **Plusieurs jeux de lignes dans un même rapport** : les lignes restent une liste plate (contrat legacy inchangé), et chaque ligne porte une clé `section`. `TableSpec` reçoit `section` (optionnel) : le tableau n'affiche que les lignes dont `section` correspond. Le payload `document.tables[i]` expose `section` ; `ReportSheet.vue` et `report_pdf.py` filtrent de la même façon. Sans `section`, tous les tableaux existants se comportent exactement comme avant (le rapport de marges garde ses 3 tableaux sur les mêmes lignes).
3. **Entité « type de frais »** : `_resolve_entity` sait résoudre `fee_type` (valeur fixe traduite via l'espace de noms `feeType`), affichée dans l'en-tête comme « Type de frais : Douane » ou « Tous ».
4. **Espace de noms `feeType`** dans `report_labels.py` : `customs` Douane, `transit` Transit, `road_transit` Transit routier, `border` Frontière, `loading` Chargement, avec `all` = Tous. Les autres espaces réutilisés existent déjà (`expenseCategory`, `expenseStatus`, `expenseCalcMethod`).
5. **Section `labels`** : titres, en-têtes de colonne, libellés de synthèse et de tableau, texte de cas vide pour les 5 rapports, en fr/en/ar.

## Les cinq rapports

### 1. Rapport de capital — `capital-report` (portrait)

**Source :** `ShareholderContributionService.get_total_capital()` est la référence du capital total.

- **Tableau A « Capital par actionnaire »** (`section: shareholder`, **tous** les actionnaires, actifs ou non, pour que le total égale `get_total_capital()`, qui somme tous les `Shareholder.contribution`) :

  | Colonne | Kind | Contenu |
  |---|---|---|
  | Actionnaire | text | nom |
  | % de participation | percent | `Shareholder.participation_percent` : pourcentage de répartition des **bénéfices** enregistré sur l'actionnaire |
  | Apport initial | money | `Shareholder.contribution` |
  | Apports ultérieurs | money | somme de tous ses `ShareholderContribution.amount` (toutes dates) |
  | Capital brut | money | apport initial + apports ultérieurs |
  | % du capital | percent | capital brut de l'actionnaire ÷ capital total (0 si le capital total est nul) |

- **Tableau B « Apports de la période »** (`section: contribution`, filtré par la période) : date, actionnaire, montant (money), compte (banque ou caisse), référence, notes. Tri par date puis id.
- **Synthèse :** total apports initiaux, total apports ultérieurs, **Capital total** (emphase, égal à `get_total_capital()`), total des apports de la période, nombre d'apports de la période. « % de participation » et « % du capital » ont des libellés distincts partout (écran, PDF, catalogue) pour ne jamais être confondus.

### 2. Rapport des dépenses générales — `general-expense-report` (paysage)

**Périmètre :** `Expense` dont la catégorie n'est pas dans `TRIP_FEE_CATEGORY_CODES = {customs, transit, road_transit, road, loading, transport}` (les catégories système de frais de trajet ; `transport` est la catégorie retirée qui pouvait encore porter d'anciens frais de trajet). `unloading` et `import_intention` restent générales, comme dans le sélecteur actuel (`?is_system=true`). Les catégories créées par l'utilisateur sont générales. La constante vit à un seul endroit, avec un test qui la compare aux `SYSTEM_CODES` de la migration 0014.

**Règle de calcul « total / payé / reste »** par dépense, dans une méthode publique unique de `ControlledDebtPaymentService` (`describe_expense_settlement(expense)`), qui **réutilise** `describe_expense` sans le modifier :

- **Total réel :** somme des `allocated_amount` des allocations s'il y en a, sinon `Expense.amount` (jamais `Expense.amount` seul quand il y a des allocations : c'est un tarif au litre pour un frais `PER_LITRE`).
- **Payé directement par le client** (`paid_by_customer_directly=True`) : payé = total réel, reste = 0, sans exiger de `TreasuryTransaction`.
- **Payé par banque/caisse :** payé = somme **nette** des `TreasuryTransaction` ayant cette dépense pour source (`MONEY_OUT` − `MONEY_IN`) ; reste = total réel − payé (couvre le partiellement payé).
- **Annulé (`CANCELLED`) :** ligne conservée, montant total affiché, payé/reste vides ; exclue de tous les totaux.

**Tableau A « Dépenses »** (`section: expense`) :

| Colonne | Kind |
|---|---|
| Date | date |
| Catégorie | enum `expenseCategory` |
| Notes | text |
| Mode de calcul | enum `expenseCalcMethod` |
| Montant total | money |
| Payé | money |
| Reste | money |
| Statut | status `expenseStatus` |

- **Tableau B « Récapitulatif par catégorie »** (`section: category_total`) : catégorie, nombre, total, payé, reste (hors annulés).
- **Synthèse :** nombre de dépenses, total, payé, reste, nombre par statut (non payées / partiellement payées / payées), `cancelled_excluded`.

### 3. Rapport des dettes de frais de trajet — `trip-fee-debt-report` (paysage)

**Paramètre :** `fee_type` ∈ `{all (défaut), customs, transit, road_transit, border, loading}`. Une valeur inconnue lève `ValueError`, que la vue transforme en 400 (comportement existant). Le second sélecteur de la page propose ces six valeurs (§Frontend).

**Source :** `ControlledDebtPaymentService.get_payable_debts(type)` pour chaque type choisi, où l'ensemble « tous » est `supported_debt_types()` privé de `supplier` et `transporter` (donc les cinq types officiels, sans liste dupliquée). Chaque ligne du service (`lines`) donne total, payé, reste et statut.

| Colonne | Kind | Origine |
|---|---|---|
| Type de frais | enum `feeType` | type du groupe |
| Date | date | `Expense.date` (info) |
| Trajets | text | références des allocations (info) |
| Notes | text | `Expense.notes` (info) |
| Total | money | ligne du service |
| Payé | money | ligne du service |
| Reste | money | ligne du service |
| Statut | status `expenseStatus` | ligne du service |

Tri : type de frais (ordre du service) puis date puis id.

**Synthèse :** pour chaque type inclus, total/payé/reste ; puis **Total général** (emphase), nombre de lignes. Le total général des restes égale la somme des restes des groupes et, pour `all`, `customs + transit + road_transit + other` de `WorkingCapitalService.get_other_debts_breakdown()` (donc la carte « dettes douane/transit/frais » du tableau de bord).

### 4. Dettes générales — `general-debt-report` (paysage)

**Source :** exclusivement les mêmes appels que l'écran « Nouveau paiement » : `get_payable_debts("supplier")`, `get_payable_debts("transporter")` et `get_payable_debts(type)` pour les cinq types de frais (`supported_debt_types()`). Aucun reste n'est recalculé depuis les modèles.

- **Tableau A « Dettes fournisseurs »** (`section: supplier`) : fournisseur, commande (référence), date, total, payé (paiements + avances consommées, tel que le service le calcule), reste, statut.
- **Tableau B « Dettes transporteurs »** (`section: transporter`) : transporteur, trajet, date, net à payer, payé, reste, statut. Une ligne au reste négatif (retenue supérieure au net) est affichée avec son signe, car le service la nette dans le total du transporteur ; un transporteur dont le reste total n'est pas positif est absent, comme dans le service.
- **Tableau C « Frais de trajet »** (`section: trip_fee`) : mêmes colonnes que le rapport 3.
- **Synthèse :** sous-total fournisseurs, sous-total transporteurs, sous-total frais de trajet, **Total général des dettes** (emphase), nombre de lignes par famille. Rapprochements testés : sous-total fournisseurs = somme des `remaining_amount` de `get_payable_debts("supplier")` ; sous-total transporteurs idem ; sous-total frais = `customs + transit + road_transit + other` de `get_other_debts_breakdown()`.
- Les avances **non consommées** (soldes créditeurs) ne sont pas déduites en plus : le rapport suit exactement le reste à payer de l'écran de paiement.

### 5. Créances clients — `general-receivable-report` (paysage)

**Formule de référence (par client) :**

```
reste client = Σ factures non annulées − Σ tous les paiements non annulés
```

C'est exactement `PaymentAllocationService.get_customer_outstanding(customer)` : `Invoice` hors `CANCELLED` (les brouillons comptent, comme dans le service) moins `CustomerPayment` avec `is_reversed=False`.

**Lignes affichées, par client :**

- **Une ligne par facture non annulée dont le reste individuel ≠ 0**, avec `reste = total_amount − Σ allocations (paiements non annulés)` (`PaymentAllocationService.get_invoice_outstanding`). Un reste négatif (facture corrigée à la baisse après imputation) est affiché tel quel.
- **Une ligne « Crédit non affecté »** dès que le crédit ≠ 0, avec :

  ```
  crédit non affecté = Σ paiements non annulés − Σ allocations de ces paiements sur des factures non annulées
  ```

  Ce crédit comprend donc : un paiement entièrement non affecté ; le reliquat non affecté d'un paiement partiellement imputé ; une imputation liée à une facture ensuite annulée (qui n'est plus « imputée » à une facture valide) ; une allocation sans facture.

- **Signe.** La ligne « Crédit non affecté » **réduit** le reste : colonne Facturé vide, colonne Encaissé = le crédit (positif), colonne Reste = **−crédit**. Sur toute ligne (facture ou crédit), `Reste = Facturé − Encaissé`.

**Équation de rapprochement (par client) :**

```
Σ restes des factures − crédit non affecté
 = (Σ factures − Σ allocations) − (Σ paiements − Σ allocations)
 = Σ factures − Σ paiements = get_customer_outstanding(client)
```

Les factures soldées (reste 0) ne contribuent à rien, donc les masquer ne change pas le total.

**Clients inclus :** tout client dont le reste ≠ 0, qu'il ait des factures ou seulement des paiements (un paiement d'avance sans facture est un crédit non affecté). Le total général est donc strictement égal à la somme de `get_customer_outstanding` sur tous les clients. **Conséquence à connaître :** le rapport existant « Créances clients » (`customer-outstanding`) ne liste que les clients ayant au moins une facture non annulée ; les deux totaux ne diffèrent que pour un client ayant des paiements mais aucune facture non annulée.

| Colonne | Kind |
|---|---|
| Client | text |
| Facture (ou « Crédit non affecté ») | ref |
| Date | date |
| Trajet | ref |
| Facturé | money |
| Encaissé | money |
| Reste | money |

- **Synthèse :** nombre de clients, nombre de factures ouvertes, total facturé (des lignes affichées), total encaissé, total des crédits non affectés (négatif dans le reste), **Reste total** (emphase). Un sous-total par client est inséré après ses lignes (`emphasis` sur la ligne « Total client »).

## Frontend

- `REPORT_TYPES` reçoit 5 entrées, un champ `periodless?: boolean` et un champ `paramSelect?: { param: string; options: string[]; defaultValue: string }` (utilisé seulement par `trip-fee-debt-report` : `param: 'fee_type'`, options `all/customs/transit/road_transit/border/loading`, défaut `all`).
- `ReportsView.vue` : affiche un second `<select>` traduit (`reports.feeTypes.*`) quand `paramSelect` existe, l'ajoute à `buildParams()`, le réinitialise à son défaut quand on change de type ; masque `DateRangeFilter` et retire `date_from/date_to/preset/range` des paramètres quand `periodless`. L'export PDF utilise les mêmes `buildParams()`.
- Libellés de page : `reports.types.<slug>.label` et `reports.feeTypes.*` en fr/en/ar.
- L'aperçu est la feuille (`ReportSheet`), sans code spécifique par rapport.

## Backend — vue

`REPORT_REGISTRY` reçoit les 5 slugs. `fee_type` passe déjà par `params` (toute clé de requête inconnue est transmise à `run()`). Pas de nouvelle route ni de nouvelle permission : module `reports`, mêmes règles d'accès et d'export.

## Tests

Pour **chaque** rapport : en-tête (logo, société, titre traduit, période, entité), totaux, cas vide, PDF fr et ar (texte extrait, RTL), colonnes larges, et compatibilité `report_type/fields/rows` sans `?document=1`.

Tests précis exigés :

- **Périodes :** capital — le tableau A ignore la période, le tableau B la respecte ; dépenses générales — lignes et totaux filtrés ; les trois rapports « situation courante » — `run(date_from=…, date_to=…)` renvoie les mêmes lignes qu'un appel sans période, le document est en mode `as_of`, et la page n'envoie pas de période (test `ReportsView`).
- **Créances :** paiement partiellement imputé, paiement entièrement non affecté, surpaiement, paiement annulé (`is_reversed`), facture annulée portant une imputation, facture corrigée à la baisse (reste négatif), client sans facture avec paiement ; pour chaque cas, le total du client = `get_customer_outstanding` (égalité stricte) et `Reste = Facturé − Encaissé` sur chaque ligne ; total général = somme sur tous les clients.
- **Dépenses générales :** payée directement par le client (sans `TreasuryTransaction`) → payé = total, reste 0 ; payée par banque ; partiellement payée ; annulée (visible, hors totaux, comptée) ; avec allocations et `PER_LITRE` (total = somme allouée, pas le tarif) ; catégories système de frais exclues, dont `transport` ; catégorie créée par l'utilisateur incluse ; `TRIP_FEE_CATEGORY_CODES` = `SYSTEM_CODES` de la migration.
- **Dettes de frais de trajet :** chaque `fee_type` valide et `all` ; `fee_type` inconnu → 400 ; totaux = `get_payable_debts` et `get_other_debts_breakdown` ; frais payé directement par le client absent.
- **Dettes générales :** sous-totaux égaux aux sorties de `get_payable_debts` (fournisseur, transporteur) et de `get_other_debts_breakdown` ; avance consommée sur une commande ; paiement fournisseur annulé qui rétablit la dette ; ligne transporteur négative ; transporteur absent quand son reste n'est pas positif.
- **Capital :** total = `get_total_capital()` ; actionnaire inactif inclus ; capital nul (pas de division par zéro) ; libellés « % de participation » et « % du capital » distincts ; pourcentages et dates sans suffixe XOF, montants avec XOF (écran et PDF).
- **Cadre :** kind `percent` (écran + PDF) ; filtrage par `section` sans effet sur les tableaux existants (rapport de marges à 3 tableaux inchangé).
- **Non-régression :** les 17 rapports existants gardent leur payload `report_type/fields/rows` ; suites backend et frontend complètes aux points de contrôle.

## Points signalés à la relecture

1. Le drapeau `periodless` sur les 4 rapports « situation courante » **déjà existants** (correction du 400 constaté) : recommandé, mais cela modifie le comportement de rapports existants.
2. `unloading` et `import_intention` sont traités comme dépenses générales (comme le sélecteur actuel) ; `transport` (catégorie retirée) est traité comme frais de trajet.
3. Le rapport « Créances clients générales » inclut les clients sans facture mais avec un paiement ; `customer-outstanding` ne les inclut pas.
4. Les brouillons de facture comptent dans les créances, comme dans `get_customer_outstanding`.

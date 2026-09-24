# Rapports capital / dépenses générales / dettes / créances — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (Native) ou subagent-driven-development. Volontairement terse : **la spec fait foi** — lire la section citée avant chaque bloc, elle n'est pas recopiée ici.

**Goal:** 5 nouveaux rapports + `periodless` sur 4 rapports existants, dans le cadre « document comptable » existant.
**Architecture:** une requête `apps/reports/queries/*` + une entrée `REPORT_SPECS` + libellés fr/en/ar par rapport ; le cadre gagne `percent`, `section`, `fee_type`, libellés de catégories.
**Spec:** `docs/superpowers/specs/2026-09-23-rapports-capital-dettes-creances-design.md` (commit 66c9617, validée). N1–N6 = ses décisions ; « §X » = ses sections.

## Global Constraints

- Backend depuis `backend/` : `.venv/bin/python -m pytest <chemin> -q` (`--reuse-db`). Frontend depuis `frontend/` : `npx vitest run <chemin>`.
- Pas de Postgres par défaut (`.env` → localhost:55435) : lancer avant le bloc 1 `docker run -d --name rapports-test-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=fuel_erp_empty_test -p 127.0.0.1:55435:5432 postgres:16` ; le supprimer à la fin. `Role.DoesNotExist` après un run complet ⇒ relancer avec `--create-db`.
- Aucun nouveau calcul métier (§Contexte) : montants uniquement via `ControlledDebtPaymentService`, `PaymentAllocationService`, `ShareholderContributionService`, `WorkingCapitalService`. Lookups d'infos d'affichage en une requête (`in_bulk`), jamais une requête par ligne.
- Réutiliser : `_column`/`_resolve_entity`/`_outstanding_summary`/`_split_cancelled` de `report_document.py`, `decimals_to_str`, `formatMoney` de `@/utils/currency`, `reportCells.ts`, `DateRangeFilter`. Rows plats + clé `section` ; `FIELDS` de chaque requête inclut `section` quand il y en a une.
- Commits : un par bloc, `git add` par chemin explicite (jamais `-A`) ; ne pas toucher `docker-compose.yml`, `.claude/`, `backend/apps/reports/management/commands/reset_transactional_data.py`. Trailer `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. Ni push ni merge (décision de l'utilisateur).
- Rythme : uniquement les tests ciblés de chaque bloc ; suites complètes une seule fois au point ⛳ (bloc 6), sauf échec à revérifier.
- Branche déjà créée : `feature/rapports-capital-dettes-creances`.

## Review Focus

1. Noms/notes hostiles ou très longs (`<b>`, `&`, arabe, 600+ car.) dans dépenses générales, capital et créances : pas de crash ni d'injection (Tasks 3.2, 5.1).
2. Base vide : aucun actionnaire / dépense / dette / client → cas vide, capital total 0, pas de division par zéro (3.1, 4.1, 5.1).
3. `fee_type` vide (`?fee_type=`) = `all` ; inconnu = 400 ; jamais 500 (4.1).
4. Export PDF/CSV/XLSX de chaque nouveau slug avec `section` dans les lignes : pas d'erreur (1.1, 6.2).
5. Montants négatifs (reste transporteur, reste client créditeur, crédit non affecté) : signe conservé à l'écran et au PDF (4.2, 5.1).

---

## Block 1 — Cadre : `percent`, `section`, `fee_type`, libellés de catégories (§Changements du cadre, §Libellés des catégories)

### Task 1.1: kind `percent` + tableaux par `section`
**Files:** `apps/reports/services/report_document.py` (`TableSpec.section`, payload `tables[i].section`, `_column` align/kind), `report_pdf.py` (formatage `percent`, filtre des lignes par `section` dans la boucle `document["tables"]`, l.~251), `frontend/src/modules/reports/{types.ts,reportCells.ts,ReportSheet.vue}`.
**Change:** `percent` = 2 décimales + `%`, jamais XOF, aligné à droite comme money ; un tableau avec `section` n'affiche que les lignes de même `section` (colonnes vides/cas vide par tableau) ; sans `section` : comportement inchangé (marges = 3 tableaux sur les mêmes lignes).
**Test:** `test_report_document.py` (payload expose `section`, marges inchangé), `test_report_pdf.py` (percent sans XOF, tableaux filtrés, PDF ar), `ReportSheet.spec.ts` (percent, filtre section, cas vide par tableau).
**Cmd:** `.venv/bin/python -m pytest apps/reports/test_report_document.py apps/reports/test_report_pdf.py -q` puis (frontend) `npx vitest run src/modules/reports/__tests__/ReportSheet.spec.ts`

### Task 1.2: entité `fee_type` + namespace `feeType` + libellés de catégories
**Files:** `report_labels.py` (`feeType`: customs/transit/road_transit/border/loading/all ; `entity.fee_type`), `report_document.py` (`_resolve_entity` : kind `fee_type` = valeur fixe traduite, vide/absent ⇒ `all`), `_column` (pour `expenseCategory` : ajouter à `enum_labels` le `ExpenseCategory.name` des codes personnalisés présents dans `rows`, une seule requête ; fallback code brut, §Libellés). Passer `rows` à `_column` (signature interne uniquement).
**Test:** `test_report_document.py` : entité « Type de frais : Douane/Tous » en fr/en/ar ; `fournitures_bureau` → nom, standard → traduction ; `expense-report` existant : payload legacy identique.
**Cmd:** `.venv/bin/python -m pytest apps/reports/test_report_document.py -q`

**Commit:** `feat(reports): percent kind, per-table sections, fee_type entity, custom expense category labels`
**Points de contrôle du bloc :** tests 1.1 + 1.2 verts ; le PDF de `margin-report` reste identique (test existant).

---

## Block 2 — `periodless` sur les 4 rapports existants (§Périodes, décision validée)

### Task 2.1: backend — accepter et ignorer les dates
**Files:** `apps/reports/queries/{customer_outstanding_report,supplier_outstanding_report,transporter_outstanding_report,fuel_stock_report}.py` (`run(cls, *, date_from=None, date_to=None)`, ignorés, commentaire d'une ligne).
**Test:** `test_views.py` : pour chacun, `GET …/?from=2026-01-01&to=2026-09-23` → 200 et payload **égal** à l'appel sans dates ; `?document=1` idem (mode `as_of`).
**Cmd:** `.venv/bin/python -m pytest apps/reports/test_views.py -k "periodless or outstanding or stock" -q`

### Task 2.2: frontend — drapeau `periodless` + `paramSelect`
**Files:** `frontend/src/modules/reports/types.ts` (`periodless?`, `paramSelect?: {param, options, defaultValue}` ; `periodless: true` sur les 4 types existants), `ReportsView.vue` (masquer `DateRangeFilter` si `periodless`, `buildParams()` sans `date_from/date_to/preset/range`, réinit. période et `paramSelect` au changement de type ; second `<select>` traduit `reports.feeTypes.<v>` ; export PDF via `buildParams()`).
**Test:** `ReportsView.spec.ts` : filtre absent + aucune période envoyée (aperçu et export) pour un type `periodless` ; filtre présent pour les autres ; `paramSelect` envoyé et réinitialisé (test avec un type factice ajouté dans le bloc 6 pour le slug réel).
**Cmd:** `npx vitest run src/modules/reports/__tests__/ReportsView.spec.ts`

**Commit:** `fix(reports): outstanding and fuel-stock reports accept and ignore period params; hide the period filter`

---

## Block 3 — Capital + Dépenses générales (§1, §2)

### Task 3.1: capital
**Files:** create `apps/reports/queries/capital_report.py` (`CapitalReportQuery.run(*, date_from=None, date_to=None)` : lignes `section=shareholder` pour **tous** les actionnaires, lignes `section=contribution` filtrées) ; `report_document.py` (`REPORT_SPECS["capital-report"]`, portrait, 2 tableaux, `_capital_summary`, `period_mode="range"`) ; `report_labels.py` (titre, colonnes « % de participation » ≠ « % du capital », synthèse, vide) ; `views/reports.py` (`REPORT_REGISTRY`).
**Change:** capital total = `ShareholderContributionService.get_total_capital()` (référence de la synthèse) ; % du capital = capital brut ÷ total (0 si total nul).
**Test:** create `apps/reports/test_capital_expense_reports.py` : total = `get_total_capital()`, actionnaire inactif inclus, période filtre B seulement, capital 0, libellés distincts, XOF seulement sur money, en-tête + PDF fr/ar via vue `?document=1` et `?export=pdf`.
**Cmd:** `.venv/bin/python -m pytest apps/reports/test_capital_expense_reports.py -k capital -q`

### Task 3.2: dépenses générales
**Files:** `apps/finance/services.py` (`TRIP_FEE_CATEGORY_CODES` + `ControlledDebtPaymentService.describe_expense_settlement(expense)` selon §2 : réutilise `describe_expense` sans le modifier ; direct client ⇒ payé = total ; sinon net `MONEY_OUT − MONEY_IN`) ; create `apps/reports/queries/general_expense_report.py` (`run(*, category=None, date_from=None, date_to=None)`, lignes `section=expense` incl. CANCELLED + lignes `section=category_total` hors annulés) ; `REPORT_SPECS["general-expense-report"]` (paysage, `_split_cancelled`, comptes par statut) ; labels ; registry.
**Test:** même fichier `-k expense` : direct client sans `TreasuryTransaction`, banque, partiel, annulé (visible, hors totaux, compté), allocations `PER_LITRE` (somme allouée), catégories système dont `transport` exclues, `unloading`/`import_intention` et catégorie personnalisée incluses, `TRIP_FEE_CATEGORY_CODES` = `SYSTEM_CODES` de `finance/migrations/0014_expensecategory.py`, même libellé dans tableau et récapitulatif, période filtre lignes et totaux.
**Cmd:** `.venv/bin/python -m pytest apps/reports/test_capital_expense_reports.py -q`

**Commit:** `feat(reports): capital and general expense reports`

---

## Block 4 — Dettes (§3, §4)

### Task 4.1: dettes de frais de trajet
**Files:** create `apps/reports/queries/trip_fee_debt_report.py` (`run(*, fee_type="all", date_from=None, date_to=None)` ; `""`/`all` ⇒ `supported_debt_types()` moins supplier/transporter ; inconnu ⇒ `ValueError` ; lignes via `get_payable_debts(type)[0]["lines"]`, infos date/trajets/notes via `Expense` `in_bulk` + `allocations`) ; `REPORT_SPECS["trip-fee-debt-report"]` (paysage, `as_of`, `entity=("fee_type","fee_type")`, synthèse par type + total) ; labels ; registry.
**Test:** create `apps/reports/test_debt_receivable_reports.py` : chaque type + `all` + `fee_type=` vide, inconnu ⇒ 400, totaux = `get_payable_debts` et `get_other_debts_breakdown`, frais payé directement absent, dates ignorées.
**Cmd:** `.venv/bin/python -m pytest apps/reports/test_debt_receivable_reports.py -k trip_fee -q`

### Task 4.2: dettes générales
**Files:** create `apps/reports/queries/general_debt_report.py` (`run(*, date_from=None, date_to=None)` ; sections `supplier`, `transporter`, `trip_fee` ; lignes uniquement via `get_payable_debts`, infos via `SupplierOrder`/`TransportPayment`/`Expense` `in_bulk`) ; `REPORT_SPECS["general-debt-report"]` (paysage, `as_of`, 3 tableaux, 3 sous-totaux + total général) ; labels ; registry.
**Test:** même fichier `-k general_debt` : sous-totaux = `get_payable_debts`/`get_other_debts_breakdown`, avance consommée, paiement fournisseur annulé rétablit la dette, ligne transporteur négative signée, transporteur à reste non positif absent, base vide.
**Cmd:** `.venv/bin/python -m pytest apps/reports/test_debt_receivable_reports.py -k "trip_fee or general_debt" -q`

**Commit:** `feat(reports): trip-fee debt and general debt reports`

---

## Block 5 — Créances clients (§5)

### Task 5.1: créances
**Files:** create `apps/reports/queries/general_receivable_report.py` (`run(*, date_from=None, date_to=None)` ; par client : factures non annulées avec reste individuel ≠ 0 via `PaymentAllocationService.get_invoice_outstanding`, crédit non affecté = Σ paiements non annulés − Σ allocations sur factures non annulées, lignes `line_type` ∈ `invoice|credit|customer_total`, clients avec reste ≠ 0 y compris sans facture ; agrégats en requêtes groupées, pas de requête par facture) ; `REPORT_SPECS["general-receivable-report"]` (paysage, `as_of`, `emphasis` sur `line_type == customer_total`) ; labels (« Crédit non affecté », « Total client ») ; registry.
**Test:** `test_debt_receivable_reports.py -k receivable` : paiement partiellement imputé, non affecté, surpaiement, paiement annulé (`is_reversed`), facture annulée avec imputation, facture corrigée à la baisse (reste négatif), client sans facture avec paiement, brouillon compté ; pour chaque cas total client = `get_customer_outstanding` (égalité stricte) et `Reste = Facturé − Encaissé` par ligne ; total général = somme sur tous les clients ; noms hostiles ; base vide.
**Cmd:** `.venv/bin/python -m pytest apps/reports/test_debt_receivable_reports.py -k receivable -q`

**Commit:** `feat(reports): general receivable report`

---

## Block 6 — Frontend, i18n, non-régression, contrôle final

### Task 6.1: sélecteur et libellés
**Files:** `frontend/src/modules/reports/types.ts` (5 entrées `REPORT_TYPES` ; `general-expense-report` et `capital-report` avec filtre de période ; `trip-fee-debt-report` `periodless` + `paramSelect {param:'fee_type', options:['all','customs','transit','road_transit','border','loading'], defaultValue:'all'}` ; `general-debt-report`, `general-receivable-report` `periodless`), `frontend/src/locales/{fr,en,ar}.json` (`reports.types.<slug>.label`, `reports.feeTypes.*`).
**Test:** `ReportsView.spec.ts` : pour les 5 slugs — libellé traduit, `fee_type` envoyé (aperçu + export), filtre masqué/affiché selon le type ; test de complétude des 3 locales si un existe déjà (`grep -rn "locales" src/**/__tests__`).
**Cmd:** `npx vitest run src/modules/reports`

### Task 6.2: non-régression backend
**Files:** `apps/reports/test_views.py` / `test_export.py` (ajouts).
**Test:** `report_type/fields/rows` des 17 rapports existants inchangés sans `?document=1` (TripDetail, DashboardView, ProfitView) ; exports CSV/XLSX/PDF des 5 nouveaux slugs répondent 200 avec `section` dans `rows`.
**Cmd:** `.venv/bin/python -m pytest apps/reports/test_views.py apps/reports/test_export.py -q`

**Commit:** `feat(reports-ui): report selector entries, fee type selector, translations`

### ⛳ Task 6.3: contrôle final (une seule fois)
- [ ] Backend : `.venv/bin/python -m pytest -q` (si `Role.DoesNotExist` : `--create-db`). Frontend : `npx vitest run`, `npx vue-tsc --noEmit`, `npx eslint` sur les fichiers touchés.
- [ ] QA navigateur réel (recette Playwright de la mémoire projet, jeu de données de test) : chacun des 5 rapports en fr, et 1 rapport en ar (RTL) ; impression : seule la feuille sort ; filtre de période masqué sur les rapports `periodless` ; second sélecteur des frais ; rapprochement visuel de 3 totaux avec les écrans de paiement.
- [ ] Revue de branche par un sous-agent neuf (modèle le plus capable) ; corriger Critical/Important en une passe (test RED→GREEN) ; mineurs listés.
- [ ] Supprimer le conteneur `rapports-test-db`, mettre à jour la mémoire projet, puis skill `finishing-a-development-branch` (menu ; ni merge ni push sans décision).

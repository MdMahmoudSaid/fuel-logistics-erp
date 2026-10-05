# Périodes indépendantes des opérations — plan d'implémentation

> Exécution : native (le client a demandé une exécution autonome jusqu'au bout
> ou jusqu'à une question). Code **production uniquement** : copie locale de
> travail = `scratchpad/prod` (git local pour les diffs), tests sur image Docker
> isolée + Postgres jetable `periodfix-testdb`, jamais la base de prod.

**Goal :** la clôture ne fait que répartir + remettre à zéro ; toute opération
ultérieure (même sur un trajet/dette d'une période clôturée) marche comme avant
et compte dans la période ouverte.

**Spec :** `docs/superpowers/specs/2026-10-05-periodes-independantes-design.md`

## Global Constraints

- Aucune écriture sur la base de prod ; déploiement seulement après
  confirmation explicite du client.
- `FIELDS` des rapports inchangés (labels/export fr-en-ar non touchés) : les
  nouvelles clés de ligne (`trip_id`, `revenue`, `supplier_cost`,
  `is_adjustment`) sont des clés JSON en plus, ignorées par les exports.
- Montants des périodes déjà clôturées jamais recalculés.
- Invariant : en "Période en cours",
  `Σ marge lignes − dépenses générales payées + report − autres répartitions = bénéfice à distribuer`.

## Review Focus

1. Trajet vendu au moment de la clôture puis annulé/vente supprimée → ligne
   d'ajustement négative (absent des lignes actuelles mais présent dans la photo).
2. Clôture déficitaire (rien réparti) → report affiché, invariant tenu.
3. Répartition validée/annulée hors clôture après la clôture → ligne de
   rapprochement, invariant tenu.
4. Réouverture → photo supprimée, référence = clôture précédente.
5. Aucune période clôturée → "Période en cours" = tout l'historique, invariant tenu.

## Tâches

### Task 1 — Supprimer le verrou
Fichiers : `audit/mixins.py`, `trips/models.py`, `finance/models.py`
(ExpenseAllocation), `sales/models.py` (Invoice.save), `finance/services.py:314`,
`finance/tests.py` (test de l'échappatoire supprimé),
`reports/date_range.py` (commentaire), `audit/test_profit_period_scope.py`
(réécrit : tout passe), `finance/test_profit_periods.py` (test du verrou réécrit).
Tests : contrôle client 45 000/44 800/tolérance 70 sur trajet d'une période
clôturée → perte entreprise 70, retenue 130, facture 44 800 ; correction de
facture ; frais ajouté ; suppression dépense impayée ; quantité chargée modifiée.

### Task 2 — Photo à la clôture
Fichiers : `finance/models.py` (+ `ShareholderProfitPeriodTripSnapshot`
{period, trip, margin, data JSON}, + champs période
`general_expenses_paid_snapshot`, `distributed_total_snapshot`), migration
`0027`, `finance/profit_periods.py` (nouveau : `latest_closed_period`,
`general_expenses_paid_total`, `general_expenses_paid_between`,
`take_snapshot`, `rows_since_last_closure`), `finance/services.py`
(`close_period` prend la photo après validation de la répartition ;
`reopen_period` la supprime), commande `backfill_profit_period_snapshot`
(dernière période clôturée, idempotente).
Tests : photo créée à la clôture, supprimée à la réouverture, backfill.

### Task 3 — Lignes et chiffres de la période
Fichiers : `reports/queries/margin_report.py` (clés `trip_id`, `revenue`,
`supplier_cost`, `is_adjustment` ; filtre de dates sur `sale__created_at__date` ;
`since_last_closure=True` → nouveaux trajets + ajustements), 
`reports/date_range.py` (`is_current_period(params)`),
`reports/views/reports.py` (passe le drapeau à margin-report),
`finance/services.py` (`get_preview(..., since_last_closure)` : dépenses par
delta ou par date de paiement, clés `revenue`, `carried_over`,
`distributions_since_closure`), `finance/views.py` (preview + PDF),
`reports/views/dashboard.py` (revenus / dépenses / bénéfice opérationnel de la
période = preview), `reports/queries/sales_report.py` (date de vente).
Tests : cas réel (trajet chargé avant clôture, vendu après → ligne normale) ;
frais tardif → ajustement négatif ; Review Focus 1-5 ; invariant.

### Task 4 — Frontend
Fichiers : `ProfitView.vue` (somme `revenue`/`supplier_cost` des lignes, badge
"Ajustement", lignes report / autres répartitions), `finance/types.ts`,
`locales/{fr,en,ar}.json`, spec Vitest de ProfitView.
Tests : `npx vitest run` sur les specs concernées + `vue-tsc`.

### Task 5 — Vérification complète
Suite backend complète (base jetable recréée), specs frontend, build frontend,
puis demande de confirmation de déploiement (backend + frontend + commande de
backfill).

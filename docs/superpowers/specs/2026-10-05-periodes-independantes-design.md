# Périodes de bénéfices indépendantes des opérations — conception

Date : 2026-10-05
Statut : validé oralement par le client, en attente de relecture du document
Portée : **production uniquement** (`/home/bouye/apps/.releases/fuel-customer-credit-d52eeb3`).
La fonctionnalité `ShareholderProfitPeriod` n'existe pas dans le dépôt local ; ce
document sert de trace.

## 1. Problème

Depuis l'arrivée des périodes (ouverture / clôture / réouverture), deux
mécanismes font dépendre les opérations courantes de la période d'origine d'un
trajet ou d'une dette :

1. **Le verrou de période clôturée** (`assert_profit_period_dates_unlocked`,
   `AuditableModel._assert_profit_period_unlocked`, `Trip.save`,
   `ExpenseAllocation.save`). Même réduit le 2026-10-05 aux seuls champs
   montant/quantité/prix, il bloque encore :
   - le contrôle de quantité client d'un trajet d'une période clôturée
     (`DeliveryService.record_client_verification` modifie
     `DeliveryControl.received_quantity`, `Sale.delivered_quantity`, la facture
     et `TransportPayment.deduction_amount`) — la perte entreprise (tolérance)
     et la retenue transporteur ne sont jamais appliquées ;
   - les corrections : facture, contrôle client, commission transporteur,
     modification de commande fournisseur ;
   - la suppression d'une dépense impayée datée d'une ancienne période.
2. **Le filtre "Période en cours"** range un trajet selon sa `loading_date`
   (`MarginReportQuery`, carte "Revenus de la période" du tableau de bord). Un
   trajet chargé dans l'ancienne période mais vendu après la clôture compte bien
   dans "Bénéfice à distribuer" (20 925 000 XOF dans le cas réel) mais
   n'apparaît ni dans "Bénéfice opérationnel", ni dans le tableau des trajets.

## 2. Règle métier (décision client 2026-10-05)

> La clôture d'une période ne fait que **répartir le bénéfice courant** entre les
> associés et **remettre les compteurs à zéro**. Tout ce qui se passe ensuite —
> terminer un trajet, contrôle de quantité, frais, paiement de dette, correction —
> compte dans la période ouverte, même si le trajet ou la dette vient d'une
> période clôturée.

Conséquences validées :

- **Aucun verrou sur les opérations.** Le moteur (coûts, pertes, tolérance,
  retenues, factures, paiements, dettes) fonctionne exactement comme avant les
  périodes.
- **Argent déjà réparti :** jamais repris aux associés. Une baisse sur un ancien
  trajet (frais tardif, perte au contrôle) vient en déduction de la prochaine
  répartition. Si le résultat devient négatif, la clôture ne répartit rien et le
  déficit est reporté jusqu'à être couvert. C'est déjà le comportement de
  `distributable_result = bénéfice net tous trajets − répartitions validées`.
- Les montants figés des périodes déjà clôturées ne sont jamais recalculés.
- Ce qui reste lié aux périodes, volontairement : le montant figé et réparti à
  la clôture, la réouverture avec motif, l'affichage "Période en cours".

## 3. Conception

### 3.1 Suppression du verrou

- Supprimer `assert_profit_period_dates_unlocked`, `_PROFIT_AFFECTING_MODELS` et
  `_assert_profit_period_unlocked` dans `audit/mixins.py`, ainsi que le paramètre
  `_skip_profit_period_lock`.
- Retirer l'appel dans `Trip.save` et `ExpenseAllocation.save`.
- Supprimer de `Invoice.save` le chemin spécial
  `allow_closed_period_payment_status_sync` et le retirer de tous ses appelants
  dans le même changement.
- La protection contre la suppression physique (`is_locked_for_deletion`,
  `HardDeleteBlocked`) et le journal d'audit restent **inchangés**.

### 3.2 Photo des trajets à la clôture

Nouveau modèle `ShareholderProfitPeriodTripSnapshot` (app finance) :

| champ | type |
|---|---|
| `period` | FK `ShareholderProfitPeriod`, `on_delete=CASCADE` |
| `trip` | FK `Trip`, `on_delete=PROTECT` |
| `margin` | Decimal(16,2) — `current_margin` du trajet au moment de la clôture |
| `revenue` | Decimal(16,2) — `sale.subtotal` au moment de la clôture |

Contrainte d'unicité `(period, trip)`.

Et sur `ShareholderProfitPeriod`, un champ
`general_expenses_paid_snapshot` (Decimal, null) : total tous temps des dépenses
générales PAYÉES au moment de la clôture.

- `close_period` : dans la même transaction, enregistre une ligne par trajet
  vendu (`MarginReportQuery.run()` sans filtre) et le total des dépenses
  générales payées.
- `reopen_period` : supprime la photo de la période rouverte (elle redevient
  ouverte ; la période de référence redevient la clôture précédente).

### 3.3 Chiffres de la "Période en cours"

Référence = la dernière période CLOTURÉE (s'il n'y en a aucune : tout compte,
comme aujourd'hui sans filtre).

- **Lignes du tableau des trajets** = chaque trajet vendu dont la marge actuelle
  diffère de sa marge dans la photo (absent de la photo = 0) :
  - trajet nouveau depuis la clôture → ligne normale, bénéfice complet ;
  - ancien trajet modifié → ligne marquée **"Ajustement"**, colonne bénéfice =
    différence (ex. −90 000 XOF de frais tardifs, ou la perte du contrôle).
- **Bénéfice opérationnel** = somme de ces lignes.
- **Chiffre d'affaires / Revenus de la période** = même principe sur
  `sale.subtotal`.
- **Dépenses générales payées** = total payé actuel − `general_expenses_paid_snapshot`.
- **Report** : si la dernière clôture était déficitaire (rien réparti), son
  déficit est affiché sur une ligne "Report période précédente" pour que
  Bénéfice opérationnel − Dépenses générales + Report = Bénéfice à distribuer.
  Si une répartition validée hors clôture existe depuis, elle est aussi
  affichée comme ligne de rapprochement.
- **Trajets en cours** (tableau de bord) = tous les trajets actifs, sans filtre
  de date.

Invariant testé : avec la "Période en cours", la somme affichée sur la page
Bénéfices est égale au "Bénéfice à distribuer".

### 3.4 Autres filtres de dates (Mois, Année, dates libres)

Pas de photo pour ces plages. Le bénéfice des trajets, le chiffre d'affaires et
le rapport des ventes rangent un trajet selon **la date de sa vente**
(`Sale.created_at`, date système du contrôle de livraison), plus selon sa date
de chargement. Les dépenses générales payées : selon la date du paiement
(`TreasuryTransaction.date` lié à la dépense).

Inchangés, car ce sont des listes opérationnelles où la date de chargement est
la bonne : rapport des trajets, historique camion, quantité chargée du tableau
de bord. Rapport des pertes : reste sur la date du contrôle.

### 3.5 Données existantes

Migration de données pour la **dernière** période clôturée seulement (les
précédentes ne servent plus de référence) : photo = trajets dont la vente a été
créée avant `closed_at`, avec leur marge actuelle ; dépenses générales = celles
payées (date de trésorerie) au plus tard à `end_date`. Limite : une modification
faite sur ces trajets entre la clôture et le déploiement est absorbée dans la
photo (le "Bénéfice à distribuer" reste juste ; seule la ligne d'ajustement ne
s'affiche pas).

### 3.6 Frontend

`ProfitView.vue` et `DashboardView.vue` : badge "Ajustement" sur les lignes
concernées, ligne "Report période précédente" si non nulle. Traductions
fr / en / ar. Rien d'autre ne change dans l'interface.

## 4. Tests (copie isolée + Postgres jetable, jamais la base de prod)

Sur des trajets chargés dans une période déjà clôturée :

1. contrôle de quantité 45 000 L chargés / 44 800 reçus / tolérance 70 : passe,
   70 L en perte entreprise, 130 L retenus au transporteur, facture sur 44 800 ;
2. frais ajouté après clôture : ligne "Ajustement" négative ;
3. correction de facture, correction de commission, modification de commande
   fournisseur, paiement de dette, changement de statut : passent ;
4. trajet chargé avant la clôture, vendu après : ligne normale dans la période
   en cours (cas réel des 20 925 000 XOF) ;
5. invariant page Bénéfices = "Bénéfice à distribuer", y compris avec un
   report déficitaire ;
6. réouverture : photo supprimée, chiffres recalculés sur la clôture
   précédente ;
7. suite backend complète + tests frontend concernés.

## 5. Hors périmètre

- Reprise automatique d'argent déjà versé aux associés.
- Recalcul des périodes déjà clôturées.
- Portage de la fonctionnalité des périodes vers le dépôt local.

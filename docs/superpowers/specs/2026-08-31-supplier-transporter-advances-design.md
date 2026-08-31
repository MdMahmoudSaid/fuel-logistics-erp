# Avances fournisseur / transporteur — Design

**Validé avec l'utilisateur par échange conversationnel (brainstorming architectural), 5 sections approuvées.**

## Contexte

Aujourd'hui, une avance versée à un fournisseur ou à un transporteur n'est pas correctement modélisée :

- `SupplierPayment.is_advance=True` existe mais n'est **jamais consommé** contre une dette précise — il réduit seulement l'agrégat de `SupplierOutstandingReportQuery`, sans toucher au reste-à-payer par commande utilisé par `Nouveau paiement` (`ControlledDebtPaymentService.describe_supplier_order`, qui l'exclut explicitement).
- `TransporterAdvance` existe, mais (a) ne crée **aucune** `TreasuryTransaction` à la création — un vrai bug, l'argent ne "sort" jamais de la trésorerie — et (b) n'est consommé que **manuellement**, un seul à la fois, via la sélection `TransportPayment.advance_applied` au moment de créer un règlement, sans logique FIFO ni consommation partielle multi-avances.
- Les cartes Dashboard "Fournisseurs"/"Transporteurs" (soldes par partie) et les Grands livres n'ont aucune notion de solde net avance/dette.

Ce document spécifie l'ajout d'une gestion complète, prudente et auditable de l'avance pour les deux types de tiers.

## Règles métier (rappel)

- Une avance = sortie de trésorerie immédiate, sans dette ouverte préalable nécessaire.
- Elle devient un crédit en faveur de l'entreprise, consommé plus tard par un achat fournisseur confirmé ou une commission transporteur.
- Elle n'est jamais un coût/dépense de bénéfice tant qu'elle n'a pas d'objet ; le bénéfice ne dépend que des opérations métier réelles (achat, trajet, frais...).
- `net_balance = avances_ouvertes − total_dû` : négatif ⟹ l'entreprise doit de l'argent au tiers (dette réelle) ; positif ⟹ le tiers doit encore de la valeur à l'entreprise (avance non consommée) ; zéro ⟹ aucun solde ouvert.

**Invariant central** : la consommation FIFO étant automatique et immédiate à la création de toute dette, `total_dû > 0` et `avances_ouvertes > 0` ne peuvent jamais coexister pour un même tiers. `net_balance` a donc toujours un signe qui pilote sans ambiguïté à la fois l'affichage Dashboard et la visibilité des boutons `Nouveau paiement` / `Nouvelle avance`.

## Modèle de données

### `SupplierAdvance` (nouveau, `backend/apps/finance/models.py`)

Mirroir de `TransporterAdvance` : `supplier` (FK, PROTECT), `bank_account`/`cash_account` (exactement l'un des deux — même `CheckConstraint` que `TreasuryTransaction`/`SupplierPayment`), `amount` (> 0), `date`, `reference`, `notes`, `document` (FK nullable vers `documents.Document` — nullable **uniquement** pour accueillir les avances migrées historiques, obligatoire via le serializer pour toute création nouvelle).

Pas de champ `settled` : le statut « ouvert/consommé » est calculé via `remaining_amount` (propriété ou annotation = `amount − Σ(AdvanceConsumption.amount où reversed_at IS NULL)`).

### `TransporterAdvance` (étendu)

Ajout de `bank_account`/`cash_account` (même contrainte « exactement un des deux », **nullable en base pour ne pas casser les lignes existantes**, mais rendus obligatoires par le serializer pour toute création nouvelle) et `document` (FK nullable). `settled` (booléen existant) devient une propriété dérivée `remaining_amount == 0`, conservée en lecture pour compatibilité mais plus jamais écrite manuellement — c'est `AdvanceConsumptionService` qui pilote `remaining_amount`.

### `AdvanceConsumption` (nouveau, table de jonction)

- `supplier_advance` / `transporter_advance` — FK nullable, exactement l'une des deux (contrainte DB)
- `debt_content_type` / `debt_object_id` — FK générique vers `SupplierOrder` ou `TransportPayment` (pattern identique à `TreasuryTransaction.source_object`)
- `amount` (> 0)
- `reversed_at` (nullable, datetime) — réversion traçable, **jamais de suppression** de ligne
- `created_at`

`remaining_amount` d'une avance et « reste dû » d'une dette excluent toujours les lignes `reversed_at IS NOT NULL`.

### `TransportPayment` (modifié)

`advance_applied` (FK existante) devient **legacy, lecture seule** (plus jamais écrite pour de nouveaux enregistrements — conservée uniquement pour l'historique déjà en base). `net_amount` est recalculé dans `save()` comme `base_amount − deduction_amount − Σ(AdvanceConsumption non-reversed pour ce paiement)`, ce total étant lui-même plafonné par construction (le service de consommation ne consomme jamais plus que `base_amount − deduction_amount`).

**Changement de comportement UI** : l'écran de création d'un règlement transporteur perd son sélecteur manuel d'avance ; la consommation devient automatique et invisible à la saisie (affichée en lecture seule après coup, via le Grand livre).

### `SupplierOrder` (modifié)

Aucun nouveau champ. `save()` détecte la transition de statut (comparaison avec la valeur en base avant écriture) :
- `→ CONFIRMED` (depuis `DRAFT` ou à la création directe en `CONFIRMED`) : déclenche `AdvanceConsumptionService.consume_for_supplier_debt(order)`.
- `CONFIRMED → CANCELLED` : déclenche `AdvanceConsumptionService.reverse_for_supplier_debt(order)` (pose `reversed_at` sur les `AdvanceConsumption` non déjà réversées liées à cette commande).
- Aucun déclenchement pour `DRAFT`, `CANCELLED`, ou une resauvegarde d'une commande déjà `CONFIRMED` (idempotence stricte).

`TransportPayment` n'a pas de statut `CANCELLED` et son `destroy()` est bloqué (`MethodNotAllowed`) — aucune logique de réversion nécessaire côté transporteur.

## `AdvanceConsumptionService` (nouveau, `backend/apps/finance/services.py`)

```
consume_for_supplier_debt(order) / consume_for_transport_debt(payment):
  - select_for_update() sur les avances ouvertes du même tiers, triées (date, id) — FIFO strict
  - même tiers obligatoire (avance.supplier == order.supplier / avance.transporter == payment.transporter)
  - pour chaque avance ouverte, tant que la dette a un reste à couvrir:
      montant = min(avance.remaining_amount, dette.remaining_amount)
      si montant <= 0: continuer/arrêter
      créer AdvanceConsumption(advance, debt, montant)
  - jamais de nouvelle TreasuryTransaction (pure compensation comptable)

reverse_for_supplier_debt(order):
  - pose reversed_at = now() sur les AdvanceConsumption non réversées liées à cette commande
  - aucune TreasuryTransaction créée/modifiée
```

## Trésorerie et bénéfice

- Création d'avance ⟹ **exactement une** `TreasuryTransaction` (`MONEY_OUT`), immédiate, atomique avec la création de l'avance et du document justificatif (`select_for_update` sur le compte + vérification de solde suffisant, même garde-fou que `ControlledDebtPaymentService.record_payment`).
- Consommation d'avance ⟹ **aucune** `TreasuryTransaction`.
- `SupplierAdvance`, `TransporterAdvance`, `AdvanceConsumption` ne sont référencés nulle part par `TripProfitService`/`MarginReportQuery`/`ShareholderProfitPreviewService` — le bénéfice ne dépend que de `SupplierOrder.unit_price`, `TransportPayment.base_amount`, `Expense`. Un test explicite pin ce non-impact (avant/après création et consommation d'avance, marge identique).

## Source unique de vérité

Extension de `ControlledDebtPaymentService` (pas de nouveau service séparé) :

```
describe_supplier_balance(supplier) / describe_transporter_balance(transporter) -> {
    total_due: Decimal,        # = describe_supplier(supplier)["remaining_amount"] (déjà la source de Nouveau paiement)
    open_advances: Decimal,    # Σ remaining_amount des avances ouvertes du tiers
    net_balance: Decimal,      # open_advances - total_due
    last_advance: {date, amount} | None,
    last_payment: {date, amount} | None,
}
```

Consommé par : Journal de trésorerie (visibilité boutons), Grand livre fournisseur, Grand livre transporteur, Dashboard `party_balances`.

Nouvelle action `GET /api/treasury-transactions/party-balances/?debt_type=supplier|transporter` — liste tous les tiers du type demandé avec `net_balance`/`total_due`/`open_advances`, une seule source réseau pour piloter les boutons partout (Journal + Grands livres).

**Correctif inclus** : `SupplierOutstandingReportQuery.run()` (utilisé par le Dashboard) utilise encore un agrégat simpliste (`Σ total_amount commandes confirmées − Σ tous les SupplierPayment.amount`), incohérent avec `describe_supplier`. `TransporterOutstandingReportQuery` a déjà été aligné sur `ControlledDebtPaymentService.describe_transporter` dans un commit récent — `SupplierOutstandingReportQuery` sera aligné de la même façon sur `describe_supplier`, pour que Dashboard, Nouveau paiement et Grand livre ne divergent jamais. Le chiffre affiché pour certains fournisseurs changera légèrement (dans le sens de la correction).

## Endpoints avances

- `POST /api/supplier-advances/` (nouveau `SupplierAdvanceViewSet`)
- `POST /api/transporter-advances/` (extension du viewset existant)

Chaque création, en transaction atomique avec `select_for_update` sur le compte choisi :
1. Rejette si `describe_supplier_balance(supplier)["net_balance"] < 0` (ou transporteur équivalent) → dette ouverte réelle, message clair.
2. Vérifie exactement banque OU caisse renseignée, solde suffisant.
3. Crée l'avance, la `TreasuryTransaction` (`MONEY_OUT`, `source_object` = l'avance), le `Document` justificatif (image obligatoire, `validate_image_upload`).

`update`/`destroy` restent bloqués (même politique que `SupplierPayment`/`TransportPayment`) — une avance créée est immuable, seule sa consommation (via `AdvanceConsumption`) évolue.

## Grand livre

Extraction de `SupplierLedgerService` / `TransporterLedgerService` (`backend/apps/finance/services.py` ou fichiers dédiés, sur le modèle de `ShareholderLedgerService` déjà existant) :

- `summary` : `total_due`, `open_advances`, `net_balance`, `last_advance`, `last_payment` (via `describe_*_balance`)
- `entries` : liste chronologique fusionnée (triée date puis id), avec `type` ∈ `{advance_given, debt_created, advance_consumed, payment}`, chacune avec date/montant/référence/note/lien justificatif si applicable.

`SupplierViewSet.ledger` / `TransporterViewSet.ledger` deviennent de fins wrappers : **toutes les clés de réponse actuelles sont conservées** (`orders`, `payments`, `total_purchased`, `total_paid`, `outstanding_balance`, `gross_amount`, `deductions`, `advances_applied`, `settled`, `unsettled_advances`...), avec ajout de `summary` et `entries`. Aucun écran existant n'est cassé par ce changement de forme de réponse.

## Migration des données existantes

Migration Django (`finance` app) : pour chaque `SupplierPayment(is_advance=True)`, création d'une `SupplierAdvance` correspondante (même fournisseur, montant, date, compte, référence ; `document=None` — nullable réservé exclusivement à ce cas historique). **Aucune** nouvelle `TreasuryTransaction` n'est créée (l'argent est déjà sorti via le paiement d'origine, qui reste inchangé et immuable). Ces avances migrées deviennent immédiatement disponibles pour consommation FIFO future.

**Anti double-comptage** : `SupplierLedgerService`/`describe_supplier_balance` cessent de sommer les `SupplierPayment.amount` où `is_advance=True` — ils sont désormais représentés uniquement par `SupplierAdvance`. `SupplierPaymentSerializer` refuse toute nouvelle création avec `is_advance=True` (400 explicite) : la seule voie officielle pour une nouvelle avance fournisseur devient `POST /api/supplier-advances/`. Le champ `is_advance` reste en lecture sur les enregistrements historiques déjà en base.

## Frontend

### `AdvanceForm.vue` (nouveau, `frontend/src/modules/finance/`)

Calqué sur `DebtPaymentForm.vue` : props `initialPartyType`/`initialPartyId`/`lockPartyType`/`lockParty`, même verrouillage de sélecteur. Champs : type (Fournisseur/Transporteur), tiers, banque/caisse, montant, date, référence, note, justificatif (`imageUpload.ts`/`isAllowedImageFile`, obligatoire). Soumission multipart vers `/api/supplier-advances/` ou `/api/transporter-advances/` selon le type. En mode libre, le sélecteur de tiers n'affiche que ceux avec `net_balance >= 0` (`party-balances`) ; si le backend refuse quand même (état changé entretemps), message d'erreur clair affiché inline.

### Boutons

- `TreasuryLedgerView.vue` : `Nouvelle avance` à côté de `Nouveau paiement`, même `<Modal>`, deep-link `?action=advance` (miroir de `?action=payment`).
- `SupplierLedgerView.vue` / `TransporterLedgerView.vue` : `Nouvelle avance` à côté de `Nouveau paiement`, `lock-party-type lock-party`.
- Règle de visibilité (dérivée de `net_balance` du résumé de la page) : `net_balance < 0` → `Nouveau paiement` visible/actif, `Nouvelle avance` masqué ; `net_balance >= 0` → `Nouvelle avance` visible/actif, `Nouveau paiement` masqué.

### Cartes résumé (Grands livres)

4 cartes alimentées uniquement par `summary` backend (aucun calcul frontend séparé) : Total dû, Avances ouvertes, Solde net, Dernière avance / dernier paiement.

### Tableau Grand livre

Rendu de `entries`, badge/colonne par type (`Avance versée`, `Dette créée`, `Avance imputée`, `Paiement complémentaire`). Justificatif ouvert via le modal image interne déjà existant (pattern `SupplierLedgerView.vue:317-327`, `previewUrl` + `<img>` en `<Modal>`) — jamais de nouvel onglet.

### Dashboard

Cartes "Fournisseurs"/"Transporteurs" de "Soldes par partie" lisent `net_balance` (au lieu de `balance`). Libellé sous le montant :
- `net_balance < 0` → **Dette à payer**
- `net_balance > 0` → **Avance disponible**
- `net_balance == 0` → **Aucun solde ouvert**

## Hors périmètre / ne pas toucher

- Formule de bénéfice (`TripProfitService`, `MarginReportQuery`) — aucune modification, seulement vérifiée par test.
- Logique métier de `ControlledDebtPaymentService.record_payment` (le flux `Nouveau paiement` lui-même) — seul son calcul de reste-à-payer devient advance-aware via `_supplier_order_paid` (inclusion de `AdvanceConsumption` non réversées en plus des `SupplierPayment.is_advance=False`) et via `TransportPayment.net_amount` déjà advance-aware par construction.
- Commandes `DRAFT`/`CANCELLED` : jamais comptées comme dette, jamais consommatrices d'avance.

## Plan de tests

### Backend

- Contraintes modèles : `amount > 0`, exactement un compte banque/caisse (`SupplierAdvance`, `TransporterAdvance` étendu).
- `AdvanceConsumptionService` : FIFO (date, id), même-tiers obligatoire, plafonds (`min(remaining_amount avance, reste dû dette)`), idempotence stricte (resauvegarde d'une commande déjà `CONFIRMED` ne consomme pas deux fois), réversion `CONFIRMED → CANCELLED` (restaure `remaining_amount`, aucune suppression de ligne).
- Déclenchement automatique : `SupplierOrder` (`DRAFT`/`CANCELLED` = aucune consommation ; `→ CONFIRMED` = consommation), `TransportPayment` (consommation à la création, `net_amount` jamais négatif, split sur plusieurs avances si nécessaire).
- Trésorerie : 1 `TreasuryTransaction` à la création d'avance, 0 à la consommation.
- Non-impact bénéfice : marge identique avant/après création et consommation d'une avance.
- `describe_supplier_balance`/`describe_transporter_balance` sur tous les scénarios : dette seule, avance seule, avance consommée partiellement, avance consommée totalement (fournisseur et transporteur) ; création d'avance refusée si dette ouverte réelle ; autorisée si `net_balance >= 0`.
- Cohérence stricte Dashboard = Nouveau paiement (`payable-debts`) = Grand livre, à chaque étape (création avance / création dette / consommation FIFO / paiement complémentaire).
- Exclusion stricte `DRAFT`/`CANCELLED` dans `SupplierOutstandingReportQuery` (aligné) et dans le calcul de consommation.
- Justificatif obligatoire + image uniquement (JPG/JPEG/PNG/WEBP), rejet backend sur type/extension invalide ou absence de fichier, sur les deux endpoints d'avance.
- Migration de données : `SupplierPayment(is_advance=True)` fixtures → `SupplierAdvance` créées correctement, aucune `TreasuryTransaction` dupliquée, aucun double comptage dans `describe_supplier_balance` après migration.

### Frontend (Vitest, conventions de `DebtPaymentForm.spec.ts` / `SupplierLedgerView.spec.ts`)

- `AdvanceForm.spec.ts` : mode libre (Journal, sélecteur filtré `net_balance >= 0`) vs mode verrouillé (Grand livre, tiers préempli/désactivé) ; justificatif obligatoire (soumission bloquée sans fichier) ; rejet fichier non-image côté client.
- Boutons `Nouvelle avance`/`Nouveau paiement` : visibilité correcte selon `net_balance` (positif, négatif, nul) dans `SupplierLedgerView`/`TransporterLedgerView`/`TreasuryLedgerView`.
- Cartes résumé : rendu correct des 4 valeurs depuis `summary` mocké.
- Tableau `entries` : rendu des 4 types de lignes, ouverture justificatif en modal interne (pas de nouvel onglet).
- Dashboard : libellé correct pour `net_balance` négatif / positif / nul.

# Simplification du parcours de statuts d'un trajet (2026-09-24)

Date: 2026-09-24
Statut: Décisions validées avec l'utilisateur (brainstorming). Prêt pour plan d'implémentation.

## Contexte

Retour client : faire avancer un trajet jusqu'à son statut final est **trop long**, surtout quand on traite plusieurs trajets à la suite. Un trajet client traverse aujourd'hui 12 statuts avant `COMPLETED` (`TripWorkflowService.FORWARD_TRANSITIONS`, `backend/apps/trips/services.py`) :

`ASSIGNED → SENT_FOR_LOADING → LOADING → LOADED → ROAD_TRANSIT → IN_TRANSIT → BORDER → CUSTOMS → GOING_TO_CLIENT → ARRIVED_AT_CLIENT → DELIVERED → COMPLETED`

### Ce que fait le code aujourd'hui

- Un statut n'est pas toujours « vide » : `SENT_FOR_LOADING` ouvre le popup de commission transporteur ; `LOADING`, `ROAD_TRANSIT`, `IN_TRANSIT`, `BORDER`, `CUSTOMS` ouvrent un popup de frais pré-rempli (`automaticExpenseByStatus` + `openAutomaticFeePopup`, `TripDetail.vue`). `ARRIVED_AT_CLIENT` donne accès au formulaire de livraison. Seuls `LOADED`, `GOING_TO_CLIENT`, `GOING_TO_COMPANY_STOCK` (et `COMPLETED`, posé par la vérification client) ne déclenchent rien.
- `DELIVERED` et `COMPLETED` sont réservés à leurs formulaires (`_FORM_ONLY_STATUSES`, `views.py`) : contrôle de livraison (prix → Sale + facture) et vérification client (quantité reçue / pertes). Ce garde-fou date du 2026-09-07 et **ne doit pas être affaibli**.
- Le formulaire « Ajouter des frais » du trajet (`ExpenseForm.vue`, mode trajet) n'offre que les catégories système `customs`, `transit`, `road_transit`, `road` (Frontière), `loading`. La **commission transporteur** est un objet différent — `TransportPayment` (dette transporteur, prix au litre, une seule par trajet, transporteur externe uniquement, corrigeable via `TransportPaymentCorrectionService`) — saisi par un **bouton séparé** « Ajouter des frais de transport (au litre) » et par le popup déclenché à `SENT_FOR_LOADING`.

## Décisions

### D1 — Supprimer `GOING_TO_CLIENT` et `GOING_TO_COMPANY_STOCK`

Ce sont des statuts sans action ni montant. `LOADED` est **conservé** (exception demandée). `ARRIVED_AT_COMPANY_STOCK` et `STOCKED` sont conservés tels quels.

Parcours résultants :

- Client : `ASSIGNED → SENT_FOR_LOADING → LOADING → LOADED → ROAD_TRANSIT → IN_TRANSIT → BORDER → CUSTOMS → ARRIVED_AT_CLIENT → DELIVERED → COMPLETED`
- Stock : `… → CUSTOMS → ARRIVED_AT_COMPANY_STOCK → STOCKED`
- Stock puis attribué à un client : `STOCKED → ARRIVED_AT_CLIENT` (remplace `STOCKED → GOING_TO_CLIENT`).

`get_allowed_targets` : le fork client/stock qui portait sur `GOING_TO_CLIENT`/`ARRIVED_AT_CLIENT`/`QUANTITY_CONTROL` s'applique désormais à la sortie de `CUSTOMS` (client ou commande → `ARRIVED_AT_CLIENT`, sinon → `ARRIVED_AT_COMPANY_STOCK`). `QUANTITY_CONTROL` reste mappé (trajets historiques), inchangé.

**Migration de données** (`trips` 0010) : les trajets dont `status` ∈ {`GOING_TO_CLIENT`, `GOING_TO_COMPANY_STOCK`} passent à `CUSTOMS` (leur prédécesseur : la douane est franchie, le trajet n'est pas encore arrivé — même état fonctionnel). `AlterField` des `choices`. Les lignes `TripStatusHistory` ne sont **jamais modifiées** (append-only) ; les anciens libellés restent affichables dans la timeline (clés i18n et labels de rapports conservés pour l'historique).

**Références à mettre à jour** (repérées) : `trips/models.py` (enum + commentaires), `trips/services.py`, `sales/services.py` (`_LOADED_ONWARD_STATUSES`), `reports/views/dashboard.py` (commentaire ligne ~400 + requêtes), `reports/services/report_labels.py`, `reports/services/ledger_pdf.py`, `frontend/.../trips/types.ts`, `TripStatusBoard.vue` (filtre « à livrer » : `['ARRIVED_AT_CLIENT']`), `TripDetail.vue` (`customsReachedStatuses`), tests associés. Le plan d'implémentation devra refaire un `grep` exhaustif avant de coder.

### D2 — Sauter des statuts

Le sélecteur de statut du trajet propose **tous les statuts atteignables plus loin**, pas seulement le suivant (ex. `ASSIGNED → CUSTOMS`).

Backend :

- `TripWorkflowService` gagne un calcul de chemin : suite de statuts intermédiaires entre le statut courant et la cible sur la chaîne avant (avec le fork client/stock de D1). `get_allowed_targets` reste la source de vérité de ce qui est atteignable.
- `transition_trip` traverse le chemin **dans une seule transaction atomique, sous le même verrou de ligne**, et écrit **une ligne `TripStatusHistory` par statut traversé** (audit complet, un seul `changed_by`, la note est portée par la dernière ligne). Les effets de bord aujourd'hui liés à un statut cible (libération du camion, `recompute_status` de la commande) restent évalués sur le statut final.
- Garde-fous **inchangés** : le saut ne franchit jamais `DELIVERED`/`COMPLETED` (formulaires uniquement) → le saut s'arrête au plus loin à `ARRIVED_AT_CLIENT`, `ARRIVED_AT_COMPANY_STOCK` ou `STOCKED`. `CANCELLED`/`BLOCKED` ne sont pas des sauts. Le retour depuis `BLOCKED` reprend exactement le statut d'avant blocage.
- `GET /allowed-statuses/` renvoie la liste élargie (toujours privée de `_FORM_ONLY_STATUSES`) ; `POST /status/` accepte n'importe laquelle de ces cibles. Un saut invalide renvoie le même `InvalidTripTransition` qu'aujourd'hui.

### D3 — Frais des statuts traversés

Après un saut, le frontend enchaîne **un popup après l'autre** pour chaque statut traversé qui en porte un (commission transporteur à `SENT_FOR_LOADING`, puis chargement, route, transit, frontière, douane), dans l'ordre du parcours. Chaque popup a un bouton **« Passer »** et il existe un bouton **« Tout passer »**. On réutilise les formulaires existants — pas de nouvel écran de saisie. Un frais passé se saisit plus tard par le bouton « Ajouter des frais » (D4). Le popup à statut unique (sans saut) gagne le même bouton « Passer ».

### D4 — Commission transporteur dans le formulaire « Ajouter des frais »

Le formulaire « Ajouter des frais » du trajet propose une option de catégorie supplémentaire : **« Commission transporteur »**.

- Elle n'apparaît **que** si le trajet a un transporteur externe (`trip.transporter` non nul, `!transporter_detail.is_internal`) **et** n'a pas déjà de commission active (un trajet = un règlement, règle existante `!transportPayments.length`). Jamais en mode « Dépenses générales ».
- Comme c'est un `TransportPayment` et non une `Expense`, **le modèle n'est pas fusionné** (dette transporteur, déductions de perte, correction, annulation : tout reste tel quel). Sélectionner l'option **bascule la fenêtre** vers `TransportPaymentForm` (prix au litre, transporteur en lecture seule) au lieu d'ajouter des champs incompatibles (répartition, « payée par le client », méthode de calcul) à `ExpenseForm`. Annuler ferme la fenêtre.
- Le bouton séparé « Ajouter des frais de transport (au litre) » est **supprimé** (redondant). Le popup automatique à `SENT_FOR_LOADING` reste, et utilise le même `TransportPaymentForm`.
- L'édition/correction d'une commission existante (boutons de la liste des frais) est inchangée.

## Hors périmètre

- Action groupée depuis la liste (cocher plusieurs trajets et les avancer ensemble) : non incluse. À reconsidérer si le saut ne suffit pas.
- Fusion des modèles `Expense` / `TransportPayment` : non.
- Suppression de `ARRIVED_AT_COMPANY_STOCK` / `STOCKED` (doublon apparent) : non demandée, non faite.
- Aucun changement du contrôle de livraison, de la vérification client, de la facturation ni du moteur de coût.

## Tests attendus

- Backend : chemin de saut (client, stock, stock puis attribué), historique = une ligne par statut traversé, atomicité (échec → aucun statut changé), saut refusé au-delà d'`ARRIVED_AT_*`/`STOCKED`, `DELIVERED`/`COMPLETED` toujours refusés par `/status/`, `BLOCKED` reprend le bon statut, migration 0010 (mapping + historique intact), libération du camion et recalcul de commande sur le statut final.
- Frontend : sélecteur élargi, file de popups avec « Passer » / « Tout passer », option « Commission transporteur » visible/masquée selon transporteur et commission existante, bascule vers `TransportPaymentForm`, bouton séparé retiré, filtres du tableau de bord/`TripStatusBoard` sans les statuts supprimés.
- Recette navigateur (comme les chantiers précédents) : parcourir un trajet complet avec et sans saut, avec un transporteur externe puis interne.

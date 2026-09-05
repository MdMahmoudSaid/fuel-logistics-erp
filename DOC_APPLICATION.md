# Documentation Fonctionnelle — AZUR ÉNERGIE ERP

> Document généré par analyse du code source réel (backend Django/DRF + frontend Vue 3).
> Dernière génération : 20 août 2026.

---

## 1. Vue d'ensemble du système

**AZUR ÉNERGIE ERP** est une application de gestion intégrée pour une entreprise de logistique carburant. Elle couvre l'intégralité du cycle opérationnel et financier :

- **Approvisionnement** : achat de carburant auprès de fournisseurs, autorisations de chargement (lettres de cession), suivi du reliquat disponible.
- **Suivi de flotte & transport** : gestion des camions, transporteurs et chauffeurs, cycle de vie complet d'un trajet (chargement → transit → douane → livraison), contrôle de quantité à la livraison et gestion des écarts (pertes).
- **Ventes & facturation** : commandes clients, génération automatique des ventes et factures à partir des livraisons réelles, corrections auditées.
- **Trésorerie & finance** : comptes banque/caisse, paiements clients et fournisseurs, dépenses, avances et déductions transporteurs, virements internes, grands livres (ledgers) par tiers.
- **Pilotage** : tableau de bord temps réel, rapports exportables, journal d'audit immuable, moteur de calcul de marge (profit engine).

**Stack technique** :
- Backend : Django 5 + Django REST Framework, authentification JWT (`rest_framework_simplejwt`).
- Frontend : Vue 3 (`<script setup>`, TypeScript), Vue Router, Pinia, vue-i18n (français par défaut, anglais disponible).

**Principe architectural central** : la quasi-totalité des soldes, statuts et quantités affichés (solde de caisse/banque, reliquat de commande, quantité restante d'une cession, statut d'une commande client, marge d'un trajet) sont **calculés dynamiquement côté serveur** à partir des mouvements bruts (transactions, trajets, contrôles de livraison), et non stockés en cache. Cela garantit la cohérence des chiffres mais signifie aussi que la logique métier réelle vit dans les *services* backend (`services.py`), pas seulement dans les modèles.

---

## 2. Gestion des Rôles & Utilisateurs

### 2.1 Modèle de permissions

Il n'existe pas de rôles figés en dur dans le code (pas d'énumération `ADMIN/FINANCE/...` verrouillée) : le modèle `Role` porte une **matrice de permissions JSON** entièrement configurable depuis l'écran *Paramètres → Rôles*.

- **Modules** : `operations`, `finance`, `sales`, `purchasing`, `admin`, `reports`
- **Actions** : `view`, `create`, `edit`, `validate`, `cancel`, `export`
- Un rôle définit, pour chaque module, la liste des actions autorisées : `{"finance": ["view", "create", "edit"], "reports": ["view", "export"], ...}`.
- Des noms de rôles « suggérés » existent comme conventions (Admin, Direction/Management, Opérations, Finance) mais rien n'empêche de créer des rôles sur mesure via l'écran Rôles.

### 2.2 Matrice de permissions par section (mapping module ↔ écran)

| Module RBAC | Écrans / entités contrôlées |
|---|---|
| `admin` | Utilisateurs, Rôles, Journal d'audit, Paramètres de tolérance de perte |
| `operations` | Camions, Transporteurs, Chauffeurs, Trajets, Produits (lecture ouverte à tous les utilisateurs connectés, écriture restreinte) |
| `purchasing` | Fournisseurs, Commandes fournisseur, Lettres de cession, Documents |
| `sales` | Clients, Commandes clients, Ventes, Factures |
| `finance` | Comptes banque/caisse, Paiements clients/fournisseurs, Dépenses, Transferts, Avances et déductions transporteurs |
| `reports` | Tableau de bord, Rapports (le droit `export` conditionne spécifiquement le téléchargement CSV/XLSX) |

Chaque action d'API (`list`, `create`, `update`, `validate`, `cancel`, etc.) est traduite en une des 6 actions ci-dessus par un mapping serveur unique (`HasModulePermission`), et vérifiée à chaque appel — le frontend ne fait que masquer les boutons (`auth.can(module, action)`) pour l'ergonomie, **le contrôle réel est toujours côté serveur**. Un compte superutilisateur (Django `is_superuser`) contourne systématiquement la matrice.

### 2.3 Flux de connexion & création d'utilisateur

- **Connexion** : écran `LoginView` → e-mail + mot de passe → `POST /api/auth/login/` (JWT). Un jeton d'accès (1h) et un jeton de rafraîchissement (7 jours, avec rotation) sont émis. En cas d'échec ou de session expirée, redirection vers `/login` avec conservation de la page cible (`redirect`).
- **Création d'utilisateur** : réservée au module `admin` (écran *Paramètres → Utilisateurs*, formulaire générique). Champs : e-mail (identifiant de connexion), nom complet, téléphone, rôle (sélection dans la liste des rôles configurés), mot de passe, statut actif/inactif.
- Chaque utilisateur connecté peut consulter son propre profil via un point d'accès dédié (`/me`), indépendamment de ses permissions de module.

---

## 3. Guide détaillé par vue / module

L'application est organisée en 6 groupes de navigation dans la barre latérale, chacun visible uniquement si l'utilisateur a le droit `view` sur le module correspondant.

### 3.1 Tableau de bord (Dashboard)

**Rôle métier** : donner une vision instantanée de l'activité du jour et une vue agrégée sur une période choisie.

Deux niveaux d'information :

1. **Suivi en direct (aujourd'hui)** :
   - 4 indicateurs clés : quantité livrée aujourd'hui, trajets en cours, taux de perte moyen, paiements encaissés du jour.
   - Bloc « En route maintenant » : cartes des trajets actifs.
   - Graphique de tendance des volumes sur 14 jours.
   - Bloc « À traiter » : pertes non justifiées et trajets bloqués nécessitant une action.
2. **Détail de la période** (piloté par un sélecteur de plage de dates) : 6 blocs agrégés côté serveur — Opérations (trajets/actifs/livrés), Carburant (quantité chargée, stock théorique), Ventes (nombre de ventes, chiffre d'affaires), Transport (règlements, coût), Finance (dépenses, solde de trésorerie global), Profit (marge totale).

**Impacts automatiques** : aucune saisie sur cet écran — il s'agit d'un écran de lecture seule reflétant l'état calculé de toutes les autres données.

### 3.2 Achats & Approvisionnements

#### Fournisseurs
Fiche générique (CRUD) : nom, société, téléphone, adresse, contact, pays, notes, actif/inactif. Chaque fournisseur dispose d'un **grand livre** (`Relevé fournisseur`) : total acheté, total payé, solde dû, reliquat par produit, historique d'achats, paiements et avances.

#### Commandes fournisseur (Supplier Orders)
**Rôle métier** : enregistrer un achat de carburant.

- **Champs clés** : référence, fournisseur, produit, date d'achat, devise, quantité (litres), prix unitaire, coûts optionnels, notes.
- **Montant total** : recalculé automatiquement au format `quantité × prix unitaire + coûts optionnels`.
- **Statut** : `DRAFT` (brouillon, modifiable/supprimable) → `CONFIRMED` (verrouillée, suppression physique bloquée) → `CANCELLED`.
- **Reliquat** (champ calculé, jamais stocké) = quantité achetée − somme des quantités déjà allouées à des lettres de cession (actives ou épuisées). Affiché en rouge si ≤ 0.
- Documents joignables (contrat, reçu…).
- Depuis la fiche, bouton **« Nouvelle cession »** pour démarrer directement une lettre de cession liée.

#### Lettres de cession (Cession Letters)
**Rôle métier** : autoriser le prélèvement (chargement) d'une quantité précise sur une commande fournisseur confirmée — c'est le document qui « débloque » le chargement d'un camion.

- **Champs clés** : référence, commande fournisseur source, quantité autorisée, date d'émission, statut (`ACTIVE` / `EXHAUSTED` / `CANCELLED`), notes, document PDF joignable.
- **Barre d'allocation en direct** dans le formulaire : Acheté / Déjà alloué à d'autres cessions / Demandé — avec alerte visuelle en cas de dépassement. Cet affichage est indicatif ; **la limite réelle est imposée par le serveur** (verrouillage transactionnel empêchant toute sur-allocation, même en cas de saisies concurrentes).
- **Quantité restante** (calculée) = quantité autorisée − somme des quantités déjà chargées sur des trajets liés à cette cession.

### 3.3 Ventes & Livraisons

#### Clients
Fiche générique (CRUD) : nom, société, téléphone, adresse, contact, notes, actif/inactif. Grand livre associé (`Relevé client`, voir §3.5).

#### Commandes clients (Customer Orders)
**Rôle métier** : enveloppe commerciale d'une demande client, pouvant être honorée par plusieurs trajets (livraisons partielles possibles).

- Barre de progression : Commandé / Assigné / Chargé / Livré.
- **Statut** : `DRAFT`, `CONFIRMED` sont posables manuellement ; les statuts intermédiaires (`PARTIALLY_ASSIGNED`, `IN_PROGRESS`, `PARTIALLY_DELIVERED`, `DELIVERED`, `CLOSED`) sont **recalculés automatiquement côté serveur** à partir de l'avancement réel des trajets liés — ils ne sont jamais saisis à la main.
- Bouton « Nouveau trajet » lié directement à la commande.

#### Trajets (Trips)
Voir détails complets dans le flux §4.2 — écran central qui fusionne le chargement et le suivi logistique.

- **Tableau de bord des trajets** (`TripStatusBoard`) : vue tableau (desktop) ou cartes (mobile), filtrable par statut, masque par défaut les trajets terminés/annulés.
- **Fiche détail trajet** : toutes les informations (camion, transporteur, chauffeur, fournisseur/produit, quantité chargée, date, référence BL, client/commande liée), historique complet des changements de statut, jauges livré/chargé/écart.
- **Changement de statut** : select libre parmi tous les statuts possibles, réservé aux utilisateurs avec droit `edit` sur `operations` — mais **le frontend n'encode aucune règle de transition** : c'est le service serveur qui est seul juge de la validité d'une transition.

#### Ventes (Sales) & Factures (Invoices)
**Particularité importante** : il n'existe **aucun bouton « Créer »** sur ces deux écrans. Une vente et sa facture (statut `DRAFT`) sont **générées automatiquement** par le système au moment où une livraison est validée (voir flux §4.2). Ces écrans sont donc essentiellement des écrans de consultation et de gestion post-génération :

- **Ventes** : liste en lecture seule des ventes issues des livraisons.
- **Factures** : liste + fiche détail avec cycle de vie `DRAFT → VALIDATED → PARTIALLY_PAID → PAID` (ou `CANCELLED`).
  - **Valider** (`validate`, droit `sales.validate`) : gèle définitivement les montants de la facture.
  - **Corriger** (`correct`) : une fois validée, toute modification (prix unitaire, montant total) doit obligatoirement passer par une **correction auditée** — champ modifié, nouvelle valeur, motif obligatoire — tracée et affichée dans une timeline de corrections sur la fiche facture. Aucune modification silencieuse n'est possible après validation.

### 3.4 Flotte & Logistique

#### Transporteurs, Chauffeurs, Camions
Fiches génériques CRUD :
- **Camion** : identifiant interne, immatriculation tracteur, immatriculation citerne, capacité (litres), type de propriété (propre à l'entreprise / externe), transporteur propriétaire si externe, chauffeur par défaut.
- **Chauffeur** : nom, téléphone, numéro de permis, notes.
- **Transporteur** : fiche société + grand livre dédié (voir §3.5).

**Disponibilité des camions** : jamais un simple champ statique — elle est **dérivée en temps réel** de l'existence ou non d'un trajet actif en cours sur ce camion. Dans le formulaire de trajet, seuls les camions disponibles apparaissent par défaut (un administrateur peut forcer l'affichage des camions occupés).

### 3.5 Trésorerie & Finance

C'est le pôle le plus dense fonctionnellement : la plupart des actions se font désormais via des **modales**, pas des pages dédiées (les anciennes routes `/customer-payments/new`, `/expenses/new`, `/treasury/transfer` redirigent vers les nouveaux écrans avec modale pré-ouverte).

#### Comptes Banque / Caisse
Fiches génériques : nom, banque/emplacement, numéro de compte (banque uniquement), devise, **solde d'ouverture** (saisi une fois à la création). Le **solde courant affiché n'est jamais ce champ** : il est recalculé à chaque consultation comme `solde d'ouverture + Σ(entrées) − Σ(sorties)` sur l'historique complet des transactions de trésorerie liées à ce compte.

#### Journal de trésorerie (Treasury Ledger)
Vue centrale listant tous les mouvements de trésorerie tous comptes confondus : date, type (badge **Entrée** vert / **Sortie** rouge, + badge spécifique **Transfert**), compte, référence, montant. Affiche en tête le **solde global de trésorerie**. Deux actions disponibles :
- **« Nouvelle dépense »** → ouvre la modale Dépense.
- **« Transfert interne »** → ouvre la modale Transfert.

#### Modale Dépense (ExpenseForm)
- Champs : catégorie de dépense, méthode de calcul du montant (montant fixe / par litre / pourcentage / par commande / par camion / saisie manuelle), montant, date, notes, lignes d'allocation optionnelles (répartition de la dépense sur un trajet, un camion, un client...).
- Case **« Payé directement par le client »** : bascule le formulaire vers un **règlement indirect** — le client règle directement un tiers (ex. frais de douane) au lieu de payer l'entreprise, qui déduit ensuite ce montant de sa facture. Ce flux crée à la fois une dépense marquée comme payée et un paiement client marqué « indirect », imputé à une facture (ou en crédit non affecté), **sans jamais faire transiter d'argent par un compte banque/caisse** (aucune transaction de trésorerie créée, puisque l'argent n'est physiquement jamais passé par l'entreprise).
- Une dépense normale (case décochée) crée une transaction de trésorerie standard et impacte donc le solde du compte sélectionné.

#### Modale Transfert interne (TransferForm)
Virement entre deux comptes internes (Banque ↔ Caisse, ou entre deux comptes du même type). Champs : compte source, compte destination, montant, date, référence. Le frontend bloque si source = destination. Chaque transfert validé crée **deux lignes de transaction appariées** (une sortie sur le compte source, une entrée sur le compte destination), verrouillées en base pour garantir l'atomicité — impossible qu'un transfert ne mette à jour qu'un seul des deux soldes.

#### Modale Paiement client (PaymentAllocationForm)
Utilisée depuis le grand livre client et depuis la liste des factures.
- Champs : client, montant, date, méthode (espèces / virement / chèque / autre), type et sélection du compte de réception (masqué si paiement indirect), référence.
- Section **« Allouer aux factures »** : lignes dynamiques permettant de répartir le paiement sur une ou plusieurs factures impayées du client, avec récapitulatif du montant alloué / non alloué en temps réel.
- L'allocation est contrôlée côté serveur (impossible d'allouer plus que le montant du paiement, ou plus que le solde restant dû d'une facture) et **met à jour automatiquement le statut de la ou des factures concernées** (`VALIDATED → PARTIALLY_PAID → PAID`).

#### Grand livre client (Customer Ledger)
Par client : solde impayé en tête, table des factures (statut avec code couleur, clic → détail facture), table des paiements (méthode, indirect ou non, référence, montant). Bouton « Nouveau paiement » ouvrant la modale ci-dessus pré-remplie pour ce client.

#### Grand livre transporteur (Transporter Ledger)
Écran de lecture seule (aucune action de saisie) présentant 5 indicateurs formant la formule de solde transporteur :
`Gains bruts − Déductions − Avances appliquées − Déjà réglé = Net à payer`
- **Déductions** : montants retenus pour compenser une perte de carburant hors tolérance constatée à la livraison (facturée au prix d'achat fournisseur).
- **Avances** : sommes versées par anticipation à un transporteur, soldées automatiquement lors du règlement final correspondant.
- Table détaillée des règlements par trajet et table des avances.

### 3.6 Paramètres

- **Produits** : référentiel des types de carburant (code, nom, actif).
- **Utilisateurs** / **Rôles** : gestion des comptes et de la matrice de permissions (voir §2).
- **Tolérance de perte** (réglage unique, réservé Admin) : seuil en litres en-deçà duquel un écart de quantité livrée/chargée est considéré comme normal (évaporation, mesure...) et non facturable au transporteur. **Ce seuil est figé sur chaque contrôle de livraison au moment de sa confirmation** — une modification ultérieure du paramètre global n'affecte jamais rétroactivement les trajets déjà contrôlés.
- **Rapports** : sélecteur parmi 16 types de rapports (relevés client/fournisseur/transporteur, historique camion, rapport trajets, achats, ventes, dépenses, impayés client/fournisseur/transporteur, stock carburant, rapport pertes, rapport marge, relevé banque, relevé caisse), avec filtre de dates et export CSV/XLSX (réservé aux utilisateurs disposant du droit `reports.export`).
- **Journal d'audit** : table immuable de toutes les créations/modifications/suppressions/annulations sur les entités sensibles (commandes, cessions, ventes, factures, déductions, transactions de trésorerie…). Chaque ligne cliquable affiche un **diff avant/après** (ancienne valeur barrée en rouge, nouvelle en vert) et le motif de la modification si renseigné. Ce journal ne peut jamais être modifié ni supprimé, y compris par un administrateur.

---

## 4. Flux métiers complets (Workflows)

### 4.1 Flux d'approvisionnement

```
Commande fournisseur (DRAFT) → confirmée (CONFIRMED)
        │
        ▼
Lettre de cession (ACTIVE) — autorise le prélèvement d'une quantité X
        │  la quantité demandée ne peut jamais dépasser le reliquat disponible
        │  (verrouillage transactionnel serveur en cas de saisies simultanées)
        ▼
Chargement du camion (création d'un Trajet)
   - sélection de la cession ACTIVE
   - quantité chargée limitée par la quantité restante de la cession
   - sélection camion (disponible), transporteur, chauffeur
   - le trajet référence directement fournisseur, commande fournisseur,
     cession, produit → traçabilité complète de l'origine du carburant
```

**Étapes détaillées** :
1. Achat : création d'une **Commande fournisseur** en `DRAFT`, saisie quantité/prix, puis passage en `CONFIRMED`.
2. Autorisation : création d'une **Lettre de cession** liée à la commande, pour une quantité ≤ reliquat disponible. Elle passe en `EXHAUSTED` automatiquement une fois entièrement consommée par des chargements.
3. Chargement : création d'un **Trajet**, qui consomme une partie (ou la totalité) de la quantité autorisée par la cession. Le camion doit être disponible (aucun autre trajet actif).

### 4.2 Flux de livraison & vente

```
Trajet créé (ASSIGNED)
   → SENT_FOR_LOADING → LOADING → LOADED
   → IN_TRANSIT → BORDER → CUSTOMS
   → GOING_TO_CLIENT → ARRIVED_AT_CLIENT
   → QUANTITY_CONTROL  ◄── Contrôle de livraison (quantité reçue)
        │
        │  si quantité reçue > quantité chargée SANS confirmation
        │  d'un utilisateur habilité → blocage (anomalie à confirmer)
        │
        ▼
   DELIVERED (automatique, atomique, dans la même opération que le contrôle)
        │
        ├─► si perte > tolérance configurée :
        │      création automatique d'une Déduction transporteur
        │      (perte facturable × prix d'achat fournisseur)
        │
        ├─► détermination automatique du prix de vente
        │      (historique de prix spécifique au client, sinon prix
        │       général du produit ; erreur bloquante si aucun prix connu)
        │
        ├─► création automatique d'une Vente (quantité vendue =
        │      quantité réellement reçue, jamais la quantité chargée —
        │      « la quantité livrée est la vérité commerciale »)
        │
        └─► création automatique d'une Facture (statut DRAFT)
        ▼
   COMPLETED (clôture définitive du trajet)
```

Statuts spéciaux : **BLOCKED** (retour au statut précédent, ex. incident douane) et **CANCELLED** (possible uniquement avant le stade `DELIVERED`). Le camion redevient disponible automatiquement dès qu'un trajet atteint un statut terminal (`COMPLETED` ou `CANCELLED`).

**Après génération de la facture** : elle doit être **validée** manuellement (`DRAFT → VALIDATED`), ce qui gèle les montants. Toute correction ultérieure passe obligatoirement par le mécanisme de correction auditée décrit en §3.3.

**Impact sur la commande client liée** : à chaque changement de statut de trajet, le statut de la commande client parente est **recalculé automatiquement** (assignation partielle, en cours, livraison partielle, livrée, etc.) — jamais posé manuellement.

### 4.3 Flux financier

#### a) Paiement client
1. Depuis le grand livre client (ou la liste des factures), ouverture de la modale Paiement.
2. Saisie montant, méthode, compte de réception (sauf si indirect).
3. Allocation du montant sur une ou plusieurs factures impayées (contrôle serveur : jamais plus que le paiement, jamais plus que le solde de la facture).
4. Résultat : mise à jour automatique du statut de(s) facture(s) concernée(s), et — si paiement direct — création d'une transaction de trésorerie augmentant le solde du compte sélectionné.

#### b) Dépenses
1. Depuis le journal de trésorerie, ouverture de la modale Dépense.
2. Choix de la catégorie et de la méthode de calcul du montant, allocation optionnelle sur une entité (trajet, camion, client…).
3. **Cas standard** : la dépense crée une transaction de trésorerie qui **diminue** le solde du compte payeur.
4. **Cas « payé directement par le client »** (règlement indirect) : aucune transaction de trésorerie n'est créée — la dépense est marquée payée et un paiement client indirect est simultanément enregistré et alloué à une facture, reflétant que l'argent n'a jamais transité par les comptes de l'entreprise.

#### c) Transferts internes (via modale)
1. Depuis le journal de trésorerie, ouverture de la modale Transfert.
2. Sélection compte source / compte destination (types possiblement différents : caisse ↔ banque), montant, date, référence.
3. Création atomique de deux transactions de trésorerie appariées (sortie source / entrée destination), garantissant que les deux soldes évoluent toujours ensemble.

#### d) Gestion des écarts / Tolérance de perte
1. Un seuil de tolérance (en litres) est configuré globalement dans *Paramètres*.
2. À chaque **contrôle de livraison**, ce seuil est **figé** dans l'enregistrement du contrôle (valeur historique, non rétroactive si le paramètre change plus tard).
3. Écart = quantité chargée − quantité reçue.
   - Si écart ≤ tolérance : aucune conséquence financière.
   - Si écart > tolérance : le surplus (« perte facturable ») déclenche automatiquement une **Déduction transporteur**, valorisée au prix d'achat fournisseur, qui viendra réduire le net à payer au transporteur (visible dans son grand livre).
4. Si la quantité reçue est **supérieure** à la quantité chargée (anomalie), le système bloque la validation du contrôle tant qu'un utilisateur habilité (droit `operations.validate`) n'a pas explicitement confirmé l'anomalie.

#### e) Règlement transporteur
Le net à payer à un transporteur pour un trajet donné = montant de base convenu − déduction pour perte éventuelle − avances déjà appliquées. Les avances versées par anticipation sont marquées automatiquement « soldées » dès qu'un règlement les consomme.

---

## 5. Points d'architecture transverses à retenir

- **Rien n'est jamais stocké quand ça peut être recalculé** : soldes de comptes, reliquats, statuts de commande client, marges de trajet sont systématiquement des valeurs dérivées, garantissant qu'il ne peut jamais y avoir de désynchronisation entre l'affichage et la réalité des mouvements.
- **Les transitions de statut sensibles (trajet, facture) ne sont jamais décidées par le frontend** : il propose les actions possibles selon les permissions, mais la validité métier de chaque transition est arbitrée exclusivement par les services serveur.
- **Traçabilité totale** : toute création/modification/suppression sur les entités financières et commerciales sensibles passe par le journal d'audit immuable, avec diff avant/après et motif pour les corrections.
- **Verrouillage transactionnel** systématique sur toutes les opérations à risque de sur-allocation concurrente (reliquat de commande, quantité de cession, comptes lors d'un transfert, allocation de paiement) pour garantir l'intégrité des chiffres même en usage multi-utilisateur simultané.

---

## 6. Annexe : structure des points d'accès API principaux

Toutes les routes sont préfixées par `/api/`.

| Domaine | Endpoints |
|---|---|
| Authentification | `auth/login/`, `auth/refresh/` |
| Comptes & rôles | `accounts/users/` (+ `me/`), `accounts/roles/` |
| Référentiel | `products/`, `settings/loss-tolerance/` |
| Achats | `suppliers/`, `supplier-orders/`, `cession-letters/` (+ `reliquat`) |
| Documents | `documents/` |
| Ventes | `customers/`, `customer-orders/` (+ `trips/`), `sales/` (lecture seule), `invoices/` (+ `validate/`, `correct/`) |
| Flotte | `transporters/`, `drivers/`, `trucks/` |
| Logistique | `trips/` (+ `status/`, `history/`, `delivery-control/`) |
| Finance | `bank-accounts/`, `cash-accounts/`, `customer-payments/`, `supplier-payments/`, `transporter-advances/`, `transport-payments/`, `expenses/` (+ `record-indirect/`), `treasury-transactions/` (+ `transfer/`) |
| Pilotage | `dashboard/summary/`, `reports/{type}/`, `search/`, `audit-logs/` (lecture seule) |
| Documentation technique | `schema/`, `docs/` (OpenAPI/drf-spectacular) |

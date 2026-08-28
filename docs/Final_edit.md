# Prompt final pour Codex — Refonte Dashboard et simplification de l'application

## Contexte

L'application `fuel-logistics-erp` fonctionne déjà avec les modules achats, ventes, trajets, trésorerie, bénéfices et actionnaires. L'objectif maintenant n'est pas de reconstruire toute la logique métier, mais de simplifier l'interface et de rendre les pages plus claires pour un utilisateur métier non technique.

Il faut garder les calculs et les règles existantes quand elles sont correctes. Si une donnée existe déjà dans un `grand livre`, un rapport ou un service backend, il faut la réutiliser au lieu de créer une nouvelle logique parallèle.

La devise officielle de toute l'application est `XOF / CFA`.

---

## Objectif général

Refondre le `Tableau de bord` et simplifier les pages principales pour que l'utilisateur comprenne rapidement :

- combien l'entreprise a gagné sur la période ;
- combien elle a dépensé ;
- combien elle doit payer ;
- combien les clients doivent à l'entreprise ;
- combien il y a en banque et en caisse ;
- combien de carburant est en stock entreprise ;
- quelles opérations demandent une action ;
- où cliquer pour voir les détails.

L'application doit être simple, directe et orientée décision.

---

## 1. Refonte du Tableau de bord

### 1.1 Filtre de période en haut

Sous le titre `Tableau de bord`, afficher directement un filtre de période :

- `Aujourd'hui`
- `Cette semaine`
- `Ce mois-ci`
- `Période personnalisée`

Les indicateurs de période doivent suivre ce filtre : chiffre d'affaires, bénéfice, dépenses, encaissements, volumes, trajets, etc.

Les soldes actuels comme banques, caisses, dettes ouvertes et stock entreprise peuvent rester des indicateurs de situation actuelle, mais il faut que ce soit clair dans les libellés.

### 1.2 Première section : résumé financier clair

Afficher en haut des cartes simples :

- `Chiffre d'affaires de la période`
- `Encaissements de la période`
- `Dépenses payées de la période`
- `Bénéfice comptable de la période`
- `Solde trésorerie actuel`

Règle importante :

`Bénéfice comptable` n'est pas la même chose que `Solde trésorerie`.

Le bénéfice est calculé à partir des ventes et des coûts comptabilisés. Le solde trésorerie représente l'argent réellement disponible dans les banques et les caisses.

### 1.3 Cartes dettes et soldes par partie

Créer une section `Soldes par partie`, avec des cartes cliquables :

- `Clients`
- `Fournisseurs`
- `Transporteurs`
- `Actionnaires / Associés`
- `Douane / Transit / autres frais` si ces dettes sont gérées séparément

Règle d'affichage :

- montant positif `+` = argent dû à l'entreprise ;
- montant négatif `-` = argent que l'entreprise doit payer ;
- `0 XOF` = rien à régler.

Chaque carte doit afficher un résumé utile et être cliquable vers la page concernée.

Exemples :

Carte `Clients` :

- total dû par les clients ;
- nombre de clients avec solde ouvert ;
- plus gros client débiteur ;
- clic vers la page Clients ou le détail des créances clients.

Carte `Fournisseurs` :

- total dû aux fournisseurs ;
- nombre de fournisseurs avec dette ;
- plus gros solde impayé ;
- clic vers Fournisseurs.

Carte `Transporteurs` :

- total dû aux transporteurs ;
- nombre de transporteurs avec solde ouvert ;
- plus gros solde net ;
- clic vers Transporteurs.

Carte `Actionnaires / Associés` :

- bénéfices restants non retirés ;
- total retiré ;
- avances ouvertes ;
- solde net global des associés ;
- clic vers Actionnaires / Associés.

### 1.4 Ajouter une section Stock de l'entreprise

Ajouter une carte ou section `Stock de l'entreprise`.

Elle doit afficher :

- quantité totale en stock entreprise ;
- nombre de trajets actuellement en stock ;
- détail rapide par produit, par exemple `Gasoil`, `Essence` ;
- bouton ou clic vers une page de détail du stock.

Le stock entreprise correspond aux trajets/chargements qui sont arrivés au stock de l'entreprise ou qui n'ont pas encore été attribués à un client.

Dans le détail du stock, afficher :

- référence trajet ;
- camion ;
- fournisseur ;
- transporteur ;
- produit ;
- quantité restante ;
- date d'entrée au stock ;
- statut ;
- action `Attribuer à un client`.

Important : une quantité arrivée au stock entreprise ne doit jamais disparaître du suivi. Elle doit être visible dans le Dashboard et dans une page de détail.

### 1.5 Section opérations

Après les cartes financières et stock, afficher les indicateurs opérationnels :

- volume chargé sur la période ;
- volume livré sur la période ;
- trajets en cours ;
- trajets à contrôler ;
- trajets bloqués ou nécessitant une action ;
- écart moyen ;
- encaissements de la période.

### 1.6 Section `À traiter`

Ajouter une zone `À traiter` avec les alertes métier :

- écarts de quantité non justifiés ;
- trajets arrivés au stock sans client ;
- trajets avec frais manquants ;
- factures partiellement payées ou impayées ;
- paiements sans justificatif si ce sont d'anciens paiements ;
- dettes importantes à payer ;
- avances associées ouvertes.

Chaque élément doit être cliquable vers la page exacte où l'action peut être faite.

---

## 2. Réorganisation de la navigation latérale

Réorganiser le menu pour suivre la logique métier, pas la logique technique.

Proposition :

```text
Tableau de bord

Opérations
- Trajets & chargements
- Stock de l'entreprise
- Écarts à traiter

Achats
- Fournisseurs
- Commandes fournisseurs
- Lettres de cession

Ventes
- Clients
- Commandes clients
- Ventes
- Factures

Trésorerie
- Journal de trésorerie
- Comptes bancaires
- Comptes de caisse

Résultats & associés
- Bénéfices
- Actionnaires / Associés

Logistique
- Transporteurs
- Chauffeurs
- Camions

Paramètres
- Produits
- Utilisateurs
- Rôles
- Tolérance de perte
- Rapports
- Journal d'audit
```

Ne pas créer une page séparée `Nouveau paiement` dans le menu si le bouton existe déjà dans `Journal de trésorerie`. Garder l'action comme bouton principal dans les pages concernées.

---

## 3. Simplification des pages Clients, Fournisseurs et Transporteurs

### 3.1 Principe général

Les pages de liste doivent afficher un résumé rapide. Les pages `Grand livre` doivent devenir des pages de détail.

Renommer le bouton `Grand livre` en `Détail` ou `Compte`.

Titres recommandés :

- `Compte client — [Nom]`
- `Compte fournisseur — [Nom]`
- `Compte transporteur — [Nom]`

### 3.2 Page Clients

Dans la liste Clients, ajouter des colonnes utiles :

- `Nom`
- `Téléphone`
- `Total facturé`
- `Total encaissé`
- `Solde impayé`
- `Factures ouvertes`
- `Dernier paiement`
- `Statut`
- actions : `Détail`, `Modifier`, `Désactiver`

Le but est que l'utilisateur voie directement quels clients doivent encore de l'argent.

### 3.3 Détail client

Dans `Compte client` / `Détail client`, conserver :

- solde impayé ;
- liste des factures ;
- liste des paiements.

Ajouter dans le tableau des paiements une colonne `Justificatif`.

Pour chaque paiement client, afficher :

- date ;
- méthode ;
- référence ;
- montant ;
- justificatif.

Si un justificatif existe, afficher un lien ou bouton `Voir justificatif`.

Si aucun justificatif n'existe pour un ancien paiement, afficher `—`.

### 3.4 Paiement facture client : justificatif obligatoire

Dans la modale ou page de paiement d'une facture client, rendre le champ `Justificatif` obligatoire.

Règles :

- un paiement client ne peut pas être enregistré sans justificatif ;
- le justificatif peut être une image ou un document ;
- si l'utilisateur tente d'enregistrer sans justificatif, afficher :

```text
Le justificatif de paiement est obligatoire.
```

Le justificatif doit être visible depuis :

- la facture concernée ;
- le journal de trésorerie ;
- le compte/détail client.

### 3.5 Page Fournisseurs

Dans la liste Fournisseurs, ajouter :

- `Nom`
- `Société`
- `Pays`
- `Téléphone`
- `Total acheté`
- `Total payé`
- `Solde impayé`
- `Reliquat total (L)`
- `Dernier paiement`
- `Statut`
- actions : `Détail`, `Modifier`, `Désactiver`

Ne pas dupliquer tout le grand livre dans la liste. Afficher seulement les chiffres essentiels.

### 3.6 Détail fournisseur

Dans `Compte fournisseur`, conserver ou organiser :

- total acheté ;
- total payé ;
- solde impayé ;
- reliquat par produit ;
- historique des achats ;
- paiements et avances.

### 3.7 Page Transporteurs

Dans la liste Transporteurs, ajouter :

- `Nom`
- `Société`
- `Téléphone`
- `Brut gagné`
- `Déductions`
- `Avances appliquées`
- `Déjà réglé`
- `Solde net`
- `Statut`
- actions : `Détail`, `Modifier`, `Désactiver`

Règle du `Solde net` :

- positif = l'entreprise doit payer le transporteur ;
- négatif = le transporteur doit régulariser ou a une avance non couverte ;
- zéro = rien à régler.

### 3.8 Détail transporteur

Dans `Compte transporteur`, conserver :

- brut gagné ;
- déductions ;
- avances appliquées ;
- déjà réglé ;
- solde net ;
- règlements par trajet ;
- avances.

---

## 4. Simplification de la page Actionnaires / Associés

La page actuelle mélange trop d'actions dans une seule longue page. La transformer en page avec onglets :

```text
Résumé
Associés
Répartition des bénéfices
Avances
Retraits
Grand livre
```

### 4.1 Onglet Résumé

Afficher une carte par associé :

- nom ;
- pourcentage ;
- bénéfice indicatif actuel ;
- bénéfice validé restant ;
- total retiré ;
- avances données ;
- avances reçues ;
- solde net disponible.

Règle de contrôle :

- un associé ne peut pas prendre une avance de lui-même ;
- un associé ne peut pas prêter plus que son solde disponible ;
- un retrait ne peut pas dépasser le solde disponible de l'associé ;
- un retrait ne peut pas dépasser le solde disponible du compte banque/caisse utilisé.

### 4.2 Onglet Associés

Afficher la liste des associés avec :

- nom ;
- pourcentage ;
- téléphone ;
- statut ;
- bouton modifier.

Le total des pourcentages actifs doit être contrôlé selon la logique existante.

### 4.3 Onglet Répartition des bénéfices

Afficher :

- période ;
- bénéfice total ;
- statut ;
- détail par associé.

Pré-remplir le bénéfice total avec le bénéfice de la période quand c'est possible, mais laisser l'utilisateur valider selon la logique existante.

### 4.4 Onglet Avances

Afficher clairement :

- prêteur ;
- emprunteur ;
- montant ;
- solde restant ;
- statut ;
- remboursements.

### 4.5 Onglet Retraits

Afficher :

- associé ;
- date ;
- montant ;
- compte utilisé ;
- notes ;
- historique des retraits.

### 4.6 Onglet Grand livre

Permettre de sélectionner un associé et voir toutes ses opérations :

- bénéfices attribués ;
- retraits ;
- avances données ;
- avances reçues ;
- remboursements ;
- solde final.

---

## 5. Simplification de la page Trajets & chargements

La page contient trop de statuts en filtres horizontaux. Remplacer ou compléter avec des filtres plus simples :

- `Tous`
- `En cours`
- `Stock entreprise`
- `À livrer`
- `À contrôler`
- `Livrés`

Garder un filtre avancé pour les statuts détaillés si nécessaire.

Dans le tableau, afficher :

- référence ;
- camion ;
- transporteur ;
- fournisseur ;
- client ou `Stock de l'entreprise` ;
- produit ;
- quantité ;
- statut ;
- prochaine action.

Ajouter des indicateurs visuels si :

- client non attribué ;
- frais manquants ;
- contrôle de quantité requis ;
- écart non justifié.

Les lignes doivent être cliquables vers le détail du trajet.

---

## 6. Simplification de la page Factures

Ajouter des cartes en haut :

- `Total facturé`
- `Total encaissé`
- `Reste à encaisser`
- `Factures impayées`
- `Factures partiellement payées`

Dans le tableau, afficher :

- numéro facture ;
- client ;
- total ;
- déjà payé ;
- reste à payer ;
- date émission ;
- statut ;
- action paiement/détail.

Le bouton `+ Nouveau paiement` sur la page Factures doit servir au paiement client/facture, pas au paiement fournisseur ou transporteur.

Le paiement client doit respecter la règle du justificatif obligatoire.

---

## 7. Simplification de la page Journal de trésorerie

La page est déjà plus claire. Ajouter des filtres :

- période ;
- type : entrée, sortie, transfert ;
- compte ;
- source/bénéficiaire ;
- avec justificatif ;
- sans justificatif.

Ajouter des cartes en haut :

- `Solde banques`
- `Solde caisses`
- `Total trésorerie`
- `Entrées de la période`
- `Sorties de la période`

Dans le tableau, conserver/afficher :

- date ;
- type ;
- source / bénéficiaire ;
- compte ;
- référence ;
- note ;
- montant ;
- justificatif.

Exemples de source/bénéficiaire :

- `Client - Mohamed`
- `Fournisseur - Ahmed`
- `Transporteur - Trans Recette MULTI-A`
- `Douane`
- `Transit`
- `Transfert Banque BOA Recette -> Caisse Recette`

L'utilisateur doit comprendre immédiatement pourquoi l'argent est entré ou sorti.

---

## 8. Page Bénéfices : clarification

La page `Bénéfices` doit rester une page d'analyse, pas une page de paiement.

Clarifier la signification des montants :

- `Coût fournisseur comptabilisé`
- `Coût transport comptabilisé`
- `Frais douane comptabilisés`
- `Frais transit comptabilisés`
- `Frais frontière comptabilisés`
- `Frais chargement comptabilisés`
- `Autres frais comptabilisés`

Ajouter une indication visible :

```text
Ces montants sont les coûts comptabilisés dans le prix de revient. Ils ne représentent pas forcément les paiements déjà effectués.
```

Rappel de calcul :

```text
Prix de revient/L =
Prix fournisseur/L
+ frais transport/L
+ frais douane/L
+ frais transit/L
+ frais frontière/L
+ frais chargement/L
+ autres frais/L

Bénéfice/L = Prix de vente/L - Prix de revient/L

Bénéfice total = Bénéfice/L × quantité vendue ou livrée utilisée par la logique existante
```

Si le bénéfice affiché ne correspond pas visiblement à `bénéfice/L × quantité`, afficher ou rendre disponible le détail de calcul pour éviter la confusion.

---

## 9. Devise et formatage global

Appliquer partout la devise `XOF / CFA`.

Règles :

- montants totaux : `23 576 205 XOF`
- prix par litre : `810 XOF/L`
- quantités : `45 000 L`
- pourcentages : `10.00 %`

Ne plus afficher de montant d'argent sans devise.

Ne pas utiliser `MRU`.

Créer ou réutiliser des helpers centralisés :

- `formatMoney(value)` -> `23 576 205 XOF`
- `formatUnitMoney(value)` -> `810 XOF/L`
- `formatQuantity(value)` -> `45 000 L`

Appliquer dans :

- Dashboard ;
- Bénéfices ;
- Journal de trésorerie ;
- Comptes bancaires ;
- Comptes de caisse ;
- Paiements ;
- Dettes ;
- Fournisseurs ;
- Transporteurs ;
- Clients ;
- Trajets ;
- Ventes ;
- Factures ;
- Actionnaires / Associés ;
- Rapports ;
- Journal d'audit si des montants sont affichés.

---

## 10. Journal d'audit

Améliorer la lisibilité du tableau d'audit.

Ne pas afficher uniquement des noms techniques comme :

- `finance.treasurytransaction`
- `finance.supplierpayment`
- `sales.invoice`

Afficher plutôt des informations métier :

- date/heure ;
- action : création, modification, suppression, paiement, validation ;
- module : trésorerie, facture, paiement client, paiement fournisseur, trajet ;
- objet concerné avec référence lisible ;
- utilisateur ;
- résumé court.

Exemples :

- `Paiement fournisseur - Ahmed - 46 080 000 XOF`
- `Paiement client - Mohamed - 30 000 000 XOF`
- `Facture FAC-202608-0005 modifiée`
- `Transaction trésorerie - Banque BOA Recette`

Au clic sur une ligne, afficher les détails :

- ancienne valeur / nouvelle valeur si modification ;
- montant ;
- compte ;
- client/fournisseur/transporteur concerné ;
- référence ;
- note ;
- justificatif si disponible.

---

## 11. Contraintes importantes

- Ne pas casser les règles métier existantes.
- Réutiliser les services, endpoints et calculs existants quand ils existent.
- Ne pas dupliquer les calculs de dettes, bénéfices ou soldes dans le frontend si le backend les expose déjà.
- Ajouter des endpoints backend seulement si nécessaire.
- Les listes doivent rester rapides et lisibles.
- Les détails complets doivent rester dans les pages `Compte` / `Détail`.
- Tous les montants doivent avoir la devise.
- Les anciennes données sans justificatif peuvent afficher `—`, mais tout nouveau paiement client doit exiger un justificatif.
- Les nouvelles sections doivent être cliquables vers les pages concernées.

---

## 12. Tests et vérification attendus

Vérifier au minimum :

- le Dashboard affiche les bons totaux selon la période ;
- `Stock de l'entreprise` affiche les trajets non attribués à un client ;
- clic sur les cartes Dashboard ouvre les bonnes pages ;
- listes Clients/Fournisseurs/Transporteurs affichent les soldes corrects ;
- `Détail client` affiche les justificatifs de paiement ;
- un paiement client sans justificatif est refusé ;
- Journal de trésorerie affiche source/bénéficiaire, note, référence et justificatif ;
- tous les montants affichent `XOF` ou `XOF/L` ;
- la navigation latérale reste claire et fonctionnelle ;
- les anciens paiements sans justificatif ne cassent pas l'affichage.

---

## Résultat attendu

À la fin, l'application doit être plus simple à utiliser :

- le Dashboard donne une vision immédiate de l'entreprise ;
- les pages listes montrent les soldes essentiels ;
- les détails restent disponibles dans les pages `Compte` ;
- le stock entreprise est visible et actionnable ;
- les paiements clients sont contrôlés avec justificatif obligatoire ;
- la trésorerie et les bénéfices sont plus compréhensibles ;
- la navigation suit le travail réel de l'utilisateur.

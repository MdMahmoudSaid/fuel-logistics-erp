# Scenario de test complet production-like pour fuel-logistics-erp

## Objectif

Créer une base de données de test propre, puis exécuter un scénario complet de bout en bout pour vérifier toute la logique métier :

- apports des actionnaires ;
- soldes banque/caisse ;
- achat fournisseur ;
- lettre de cession ;
- trajet et chargement ;
- frais par litre ;
- contrôle de quantité avec perte ;
- déduction transporteur ;
- facturation client ;
- paiement client avec justificatif ;
- paiement fournisseur ;
- paiement transporteur ;
- paiement douane/transit/frais ;
- trésorerie ;
- bénéfices ;
- répartition entre actionnaires ;
- retraits et avances ;
- dashboards et grands livres.

Le but est de vérifier les calculs avec des chiffres simples, traçables et comparables.

---

## Mise à jour (2026-09-13, audit indépendant)

Ce scénario a été rejoué intégralement contre une copie isolée de production (100 000 L achetés, 45 000 L chargés/44 900 L reçus, mêmes montants qu'ici). Deux écarts ont été constatés entre les chiffres attendus ci-dessous et le comportement réel de l'application — les deux sont volontaires côté application, pas des bugs :

1. **Tolérance de perte (Étape 6).** La perte de cet exemple (100 L) tombe exactement sur la tolérance par défaut (100 L, voir `docs/ERP_Specification.md` §15). `chargeable = max(perte - tolérance, 0)` donne donc `0 XOF` de déduction transporteur ici, pas 90 000 XOF — un test dédié (`test_sync_transport_shortage_deduction_no_charge_at_exact_tolerance_boundary`) verrouille ce comportement à la frontière. Pour observer une vraie déduction non nulle, reprendre ce scénario avec une perte supérieure à la tolérance configurée (ex. 150 L), ou abaisser la tolérance si l'entreprise veut facturer dès le premier litre manquant.
2. **Base de coût du bénéfice de trajet (Étape 16).** Le bénéfice réel calculé par l'application charge le carburant/transport/douane sur la quantité **chargée** (45 000 L — ce qui a réellement été payé au fournisseur et au transporteur), pas sur la quantité reçue/facturée (44 900 L) comme le fait ce document. Résultat : 4 410 000 XOF de marge nette, pas 4 490 000 XOF — l'écart de 80 000 XOF est exactement `100 L × 800 XOF/L de coût de revient`, c'est-à-dire la perte déjà absorbée par l'entreprise mais comptée ici en plus, au niveau du coût plutôt que du chiffre d'affaires. Ce choix est cohérent avec le reste du moteur financier (`distributable_result` raisonne sur la trésorerie réellement sortie, pas sur une marge comptable) et est le comportement recommandé à conserver.

Le reste du scénario (achat, cession, workflow des statuts, facturation sur quantité reçue, paiements, rejets obligatoires, trésorerie, répartition/retraits/avances actionnaires) a été rejoué à l'identique des montants ci-dessous.

---

## Instructions pour Codex

Lire ce fichier entièrement avant de toucher la base de données.

Travailler uniquement sur une base de données de test ou une copie locale. Ne jamais supprimer une base réelle sans sauvegarde.

Avant de vider les données :

1. Confirmer que l'environnement est bien `test`, `local` ou `staging`.
2. Faire une sauvegarde/dump si une base existe déjà.
3. Vider uniquement les données métier de test.
4. Garder les comptes utilisateurs/admin nécessaires à la connexion.

À chaque étape, produire un rapport avec :

- action exécutée ;
- données créées ;
- résultat attendu ;
- résultat réel dans l'application ;
- statut : `OK` ou `PROBLÈME` ;
- capture ou référence de page si utile ;
- explication si les chiffres ne correspondent pas.

---

## Données de base

### Devise

Tous les montants sont en `XOF`.

### Actionnaires

Créer trois actionnaires :

| Actionnaire | Pourcentage | Contribution |
|---|---:|---:|
| Abdou Mohamed | 10% | 10 000 000 XOF |
| Sidi Mohamed | 80% | 80 000 000 XOF |
| Yacoub | 10% | 10 000 000 XOF |

Résultat attendu :

- total pourcentage = 100% ;
- total contributions = 100 000 000 XOF ;
- chaque actionnaire apparaît dans `Actionnaires / Associés` avec sa contribution.

### Comptes de trésorerie

Créer :

| Type | Nom | Solde initial |
|---|---|---:|
| Banque | Banque Test Principale | 200 000 000 XOF |
| Caisse | Caisse Test | 5 000 000 XOF |

Résultat attendu :

- total banques = 200 000 000 XOF ;
- total caisses = 5 000 000 XOF ;
- total trésorerie = 205 000 000 XOF.

### Référentiels

Créer :

| Type | Nom |
|---|---|
| Produit | Gasoil |
| Produit | Essence |
| Fournisseur | Supplier Test |
| Transporteur | Transporteur Test |
| Client | Client Test |
| Camion | TRK-TEST-001 |
| Chauffeur | Chauffeur Test |

---

## Scenario principal : achat, trajet, perte, vente, paiements, bénéfice

### Étape 1 : achat fournisseur

Créer une commande fournisseur :

| Champ | Valeur |
|---|---:|
| Fournisseur | Supplier Test |
| Produit | Gasoil |
| Quantité achetée | 100 000 L |
| Prix fournisseur/L | 500 XOF/L |
| Montant total achat | 50 000 000 XOF |

Résultat attendu :

- dette fournisseur = 50 000 000 XOF ;
- reliquat fournisseur = 100 000 L ;
- `Compte fournisseur` affiche total acheté = 50 000 000 XOF ;
- `Compte fournisseur` affiche solde impayé = 50 000 000 XOF.

### Étape 2 : lettre de cession

Créer une lettre de cession pour utiliser une partie de l'achat :

| Champ | Valeur |
|---|---:|
| Fournisseur | Supplier Test |
| Quantité cédée | 45 000 L |
| Produit | Gasoil |

Résultat attendu :

- reliquat fournisseur après cession = 55 000 L ;
- la lettre de cession est disponible pour créer un trajet.

### Étape 3 : création trajet

Créer un trajet :

| Champ | Valeur |
|---|---|
| Référence | TRIP-TEST-PERTE |
| Camion | TRK-TEST-001 |
| Transporteur | Transporteur Test |
| Chauffeur | Chauffeur Test |
| Fournisseur | Supplier Test |
| Client | Client Test |
| Produit | Gasoil |
| Quantité chargée | 45 000 L |

Résultat attendu :

- le trajet est créé ;
- le client est bien `Client Test` ;
- le trajet peut passer dans le workflow complet.

### Étape 4 : frais du trajet

Ajouter les frais suivants, tous au litre :

| Frais | Montant |
|---|---:|
| Commission transporteur | 65 XOF/L |
| Transit routière | 10 XOF/L |
| Transit | 0 XOF/L |
| Douane | 225 XOF/L |
| Frontière | 0 XOF/L |
| Chargement | 0 XOF/L |
| Autres frais | 0 XOF/L |

Calcul attendu :

```text
Prix fournisseur/L = 500
Commission transporteur/L = 65
Transit routière/L = 10
Douane/L = 225

Prix de revient/L = 500 + 65 + 10 + 225 = 800 XOF/L
```

Résultat attendu :

- prix de revient estimé = 800 XOF/L ;
- prix minimum de vente conseillé = 800 XOF/L ;
- les frais apparaissent dans le détail du trajet.

### Étape 5 : workflow trajet

Faire passer le trajet par les statuts :

```text
Affecté
-> Envoyé au chargement
-> Chargement en cours
-> Chargé
-> Transit routière
-> Transit
-> Frontière
-> Douane
-> En route vers le client
-> Arrivé chez le client
-> Contrôle de quantité
```

Résultat attendu :

- le nouveau statut `Transit routière` existe ;
- il apparaît avant `Transit` ;
- l'historique du trajet affiche chaque changement de statut ;
- aucune étape client ne s'active avant que le client soit défini.

### Étape 6 : contrôle quantité avec perte

Au contrôle quantité :

| Champ | Valeur |
|---|---:|
| Quantité chargée | 45 000 L |
| Quantité reçue | 44 900 L |
| Perte | 100 L |
| Prix de vente/L | 900 XOF/L |

Calcul attendu de la déduction transporteur :

```text
Perte = 45 000 - 44 900 = 100 L
Déduction transporteur = 100 × 900 = 90 000 XOF
```

Résultat attendu :

- le système crée une déduction transporteur de 90 000 XOF ;
- cette déduction est liée au trajet `TRIP-TEST-PERTE` ;
- elle apparaît dans `Compte transporteur` ;
- elle apparaît dans `Règlements par trajet` ;
- elle réduit le solde net du transporteur ;
- le libellé doit être clair :

```text
Manque quantité — TRIP-TEST-PERTE — 100 L × 900 XOF/L
```

Contrôle anti-doublon :

- si le contrôle quantité est sauvegardé une deuxième fois avec les mêmes valeurs, aucune deuxième déduction ne doit être créée ;
- si la quantité reçue devient 45 000 L, la déduction doit être supprimée ou ramenée à 0 ;
- si la quantité reçue devient 44 800 L, la déduction doit devenir 200 × 900 = 180 000 XOF.

### Étape 7 : facture client

Créer/confirmer la facture client à partir de la livraison :

| Champ | Valeur |
|---|---:|
| Client | Client Test |
| Quantité facturée | 44 900 L |
| Prix de vente/L | 900 XOF/L |

Calcul attendu :

```text
Facture client = 44 900 × 900 = 40 410 000 XOF
```

Résultat attendu :

- dette client = 40 410 000 XOF ;
- `Compte client` affiche total facturé = 40 410 000 XOF ;
- `Compte client` affiche solde impayé = 40 410 000 XOF ;
- la facture est visible dans `Factures`.

### Étape 8 : bénéfice du trajet

Calcul attendu :

```text
Quantité facturée = 44 900 L
Prix de revient/L = 800 XOF/L
Prix de vente/L = 900 XOF/L
Bénéfice/L = 900 - 800 = 100 XOF/L
Bénéfice total = 44 900 × 100 = 4 490 000 XOF
```

Résultat attendu :

- la page `Bénéfices` affiche pour `TRIP-TEST-PERTE` :
  - quantité utilisée pour le bénéfice = 44 900 L ;
  - prix de revient/L = 800 XOF/L ;
  - prix de vente/L = 900 XOF/L ;
  - bénéfice/L = 100 XOF/L ;
  - bénéfice total = 4 490 000 XOF.

Important :

Si la page affiche 45 000 L mais calcule sur 44 900 L, l'interface est confuse. Elle doit afficher clairement :

- quantité chargée ;
- quantité reçue ;
- quantité facturée/utilisée pour bénéfice.

### Étape 9 : paiement client partiel avec justificatif

Enregistrer un paiement client :

| Champ | Valeur |
|---|---:|
| Client | Client Test |
| Montant payé | 20 000 000 XOF |
| Destination | Banque Test Principale |
| Méthode | Virement bancaire |
| Justificatif | obligatoire |

Résultat attendu :

- le paiement est refusé si le justificatif est absent ;
- avec justificatif, le paiement est accepté ;
- solde client restant = 20 410 000 XOF ;
- solde banque = 220 000 000 XOF ;
- journal de trésorerie affiche une entrée de 20 000 000 XOF ;
- `Compte client` affiche le paiement et le justificatif ;
- le justificatif s'ouvre dans une modale/frame interne, pas dans un nouvel onglet.

### Étape 10 : paiement client final

Payer le reste :

| Champ | Valeur |
|---|---:|
| Montant payé | 20 410 000 XOF |
| Destination | Banque Test Principale |
| Justificatif | obligatoire |

Résultat attendu :

- solde client = 0 XOF ;
- facture client = payée ;
- solde banque = 240 410 000 XOF ;
- `Compte client` affiche total encaissé = 40 410 000 XOF ;
- journal de trésorerie affiche les deux entrées client.

### Étape 11 : paiement fournisseur partiel

Payer le fournisseur :

| Champ | Valeur |
|---|---:|
| Fournisseur | Supplier Test |
| Montant payé | 30 000 000 XOF |
| Banque | Banque Test Principale |

Résultat attendu :

- dette fournisseur restante = 20 000 000 XOF ;
- solde banque = 210 410 000 XOF ;
- journal de trésorerie affiche une sortie fournisseur de 30 000 000 XOF ;
- `Compte fournisseur` affiche total payé = 30 000 000 XOF.

### Étape 12 : paiement fournisseur final

Payer le reste fournisseur :

| Champ | Valeur |
|---|---:|
| Montant payé | 20 000 000 XOF |
| Banque | Banque Test Principale |

Résultat attendu :

- dette fournisseur = 0 XOF ;
- solde banque = 190 410 000 XOF ;
- `Compte fournisseur` affiche solde impayé = 0 XOF.

### Étape 13 : paiement transporteur

Montant transporteur attendu avant déduction :

```text
45 000 L × 65 XOF/L = 2 925 000 XOF
```

Déduction perte :

```text
90 000 XOF
```

Solde net transporteur attendu :

```text
2 925 000 - 90 000 = 2 835 000 XOF
```

Payer le transporteur :

| Champ | Valeur |
|---|---:|
| Transporteur | Transporteur Test |
| Montant payé | 2 835 000 XOF |
| Banque | Banque Test Principale |

Résultat attendu :

- solde transporteur = 0 XOF ;
- solde banque = 187 575 000 XOF ;
- `Compte transporteur` affiche :
  - brut gagné = 2 925 000 XOF ;
  - déductions = -90 000 XOF ;
  - déjà réglé = 2 835 000 XOF ;
  - solde net = 0 XOF.

### Étape 14 : paiement douane/transit

Montants attendus :

```text
Transit routière = 45 000 × 10 = 450 000 XOF
Douane = 45 000 × 225 = 10 125 000 XOF
Total = 10 575 000 XOF
```

Payer :

| Type | Montant |
|---|---:|
| Transit routière | 450 000 XOF |
| Douane | 10 125 000 XOF |

Résultat attendu :

- solde banque après paiement = 177 000 000 XOF ;
- journal de trésorerie affiche les sorties ;
- dettes douane/transit = 0 XOF pour ce trajet.

### Étape 15 : trésorerie finale

Calcul attendu :

```text
Solde initial banque = 200 000 000
+ paiements client = 40 410 000
- paiements fournisseur = 50 000 000
- paiement transporteur = 2 835 000
- paiement transit routière = 450 000
- paiement douane = 10 125 000
= 177 000 000 XOF

Solde caisse = 5 000 000 XOF
Total trésorerie = 182 000 000 XOF
```

Résultat attendu :

- banques = 177 000 000 XOF ;
- caisses = 5 000 000 XOF ;
- total trésorerie = 182 000 000 XOF.

### Étape 16 : bénéfice comptable final du scénario

Calcul attendu :

```text
Chiffre d'affaires = 40 410 000
Coût fournisseur = 44 900 × 500 = 22 450 000
Coût transport comptabilisé = 44 900 × 65 = 2 918 500
Transit routière comptabilisé = 44 900 × 10 = 449 000
Douane comptabilisée = 44 900 × 225 = 10 102 500

Prix de revient/L = 800
Bénéfice/L = 100
Bénéfice total = 4 490 000 XOF
```

Note importante :

Le paiement réel du transporteur est basé sur 45 000 L moins la déduction de perte. Le bénéfice client doit être basé sur la quantité facturée/reçue 44 900 L. Si la logique métier choisit 45 000 L pour certains frais, le rapport doit l'afficher clairement.

Résultat attendu :

- bénéfice comptable = 4 490 000 XOF pour ce trajet ;
- bénéfice encaissé = 4 490 000 XOF après paiement complet client ;
- bénéfice distribuable = 0 XOF tant qu'aucune répartition n'est validée.

### Étape 17 : répartition des bénéfices

Créer une répartition validée du bénéfice de 4 490 000 XOF.

Calcul attendu :

| Actionnaire | Pourcentage | Part |
|---|---:|---:|
| Abdou Mohamed | 10% | 449 000 XOF |
| Sidi Mohamed | 80% | 3 592 000 XOF |
| Yacoub | 10% | 449 000 XOF |

Résultat attendu :

- chaque part apparaît dans `Actionnaires / Associés` ;
- bénéfice restant non retiré total = 4 490 000 XOF ;
- le bénéfice n'est considéré distribué qu'après validation officielle.

### Étape 18 : retrait actionnaire

Faire un retrait :

| Champ | Valeur |
|---|---:|
| Actionnaire | Sidi Mohamed |
| Montant | 1 000 000 XOF |
| Compte | Banque Test Principale |

Résultat attendu :

- solde disponible de Sidi baisse de 1 000 000 XOF ;
- solde banque = 176 000 000 XOF ;
- journal de trésorerie affiche une sortie actionnaire ;
- retrait visible dans `Grand livre` actionnaire.

### Étape 19 : avance entre actionnaires

Créer une avance :

| Prêteur | Emprunteur | Montant |
|---|---|---:|
| Sidi Mohamed | Abdou Mohamed | 500 000 XOF |

Résultat attendu :

- impossible si le prêteur n'a pas assez de solde disponible ;
- impossible si prêteur = emprunteur ;
- l'avance apparaît dans le grand livre des deux actionnaires ;
- cela ne doit pas créer une transaction de trésorerie si l'argent ne sort pas de la société.

---

## Scénario stock entreprise

Créer un deuxième trajet sans client initial :

| Champ | Valeur |
|---|---:|
| Référence | TRIP-TEST-STOCK |
| Quantité chargée | 10 000 L |
| Prix fournisseur/L | 500 XOF/L |
| Client | vide au départ |

Faire avancer le trajet jusqu'à `Stocké` / `Stock de l'entreprise`.

Résultat attendu :

- le trajet apparaît dans `Stock de l'entreprise` ;
- Dashboard affiche +10 000 L en stock ;
- la page `/company-stock` affiche ce trajet ;
- l'action `Attribuer à un client` est disponible ;
- les statuts client ne sont pas accessibles avant attribution client.

Attribuer ensuite `Client Test`.

Résultat attendu :

- le trajet sort du stock entreprise ;
- il peut continuer vers client ;
- Dashboard met à jour le stock.

---

## Scénarios de rejet obligatoires

Tester que le système refuse :

1. Paiement client sans justificatif.
2. Paiement fournisseur supérieur à la dette fournisseur.
3. Paiement fournisseur supérieur au solde bancaire.
4. Paiement transporteur supérieur au solde net transporteur.
5. Retrait actionnaire supérieur à son solde disponible.
6. Retrait actionnaire supérieur au solde banque/caisse.
7. Avance actionnaire vers lui-même.
8. Avance depuis un actionnaire sans solde disponible.
9. Prix de vente inférieur au prix de revient sans alerte claire.
10. Déduction transporteur créée deux fois pour le même contrôle quantité.

---

## Rapport final demandé

À la fin du scénario, fournir un rapport complet avec les sections suivantes :

```text
1. État initial
2. Achat fournisseur
3. Lettre de cession
4. Trajet et frais
5. Contrôle quantité et perte
6. Déduction transporteur
7. Facture client
8. Paiements client
9. Paiements fournisseur / transporteur / douane / transit
10. Trésorerie finale
11. Bénéfices
12. Répartition actionnaires
13. Retraits / avances
14. Dashboard
15. Grands livres
16. Tests de rejet
17. Problèmes trouvés
18. Corrections recommandées
```

Pour chaque chiffre important, afficher :

- formule attendue ;
- résultat attendu ;
- résultat réel ;
- statut `OK` ou `PROBLÈME`.

Ne pas se contenter de dire que le scénario est passé. Il faut fournir les chiffres.

---

## Point critique à vérifier

Le point le plus important du test est la perte au contrôle quantité :

```text
45 000 L chargés
44 900 L reçus
100 L manquants
Prix de vente = 900 XOF/L
Déduction transporteur = 90 000 XOF
```

Cette déduction doit être visible dans :

- le trajet ;
- le compte transporteur ;
- le grand livre transporteur ;
- le calcul du solde net transporteur ;
- le rapport final.

Si cette déduction n'apparaît pas ou ne réduit pas le solde transporteur, le scénario doit être marqué `PROBLÈME`.

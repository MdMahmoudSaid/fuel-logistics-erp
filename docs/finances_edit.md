# Prompt Claude Code — Bénéfices et Actionnaires / Associés

Dans le projet `/Users/mohamed/Downloads/fuel-logistics-erp`, implémente cette étape après avoir terminé le travail en cours sur `Nouveau paiement contrôlé`. Ne modifie pas `docs/plan.md` sauf demande explicite de l'utilisateur.

## Objectif

Ajouter une gestion claire des bénéfices et des actionnaires/associés dans `Trésorerie & Finance`, avec contrôle des parts, retraits, avances entre associés, et soldes disponibles.

Le but est que la direction puisse voir :

- le bénéfice actuel de l'entreprise ;
- le bénéfice par période ;
- le bénéfice par trajet ;
- la part de bénéfice de chaque associé selon son pourcentage ;
- ce que chaque associé a déjà retiré ;
- ce qui reste dû à chaque associé ;
- les avances/dettes entre associés avec contrôle strict.

## Pages attendues

Dans `Trésorerie & Finance`, ajouter ou compléter :

- `Bénéfices`
- `Actionnaires / Associés`

La page `Bénéfices` sert à comprendre le profit de l'entreprise.

La page `Actionnaires / Associés` sert à gérer les associés et leurs droits financiers.

## Page Bénéfices

Créer une page claire permettant de sélectionner une période :

```text
Du [Date début] au [Date fin]
```

Afficher :

- bénéfice total actuel ;
- bénéfice de la période sélectionnée ;
- nombre de trajets pris en compte ;
- chiffre d'affaires ;
- coût fournisseur ;
- commission/frais transporteur ;
- frais douane ;
- frais transit ;
- frais frontière ;
- frais chargement ;
- autres frais ;
- bénéfice net ;
- détail par trajet.

Chaque ligne trajet doit afficher :

- référence trajet ;
- client si existe ;
- produit ;
- quantité ;
- prix fournisseur par litre ;
- prix de revient par litre ;
- prix de vente par litre ;
- bénéfice par litre ;
- bénéfice total.

Important :

- utiliser le moteur backend de profit déjà existant ou le compléter ;
- ne pas recalculer les bénéfices uniquement dans Vue ;
- ne pas stocker un bénéfice figé si le projet calcule déjà dynamiquement les marges ;
- les transferts internes ne doivent jamais être comptés comme bénéfice ou dépense ;
- les paiements de dettes ne changent pas le bénéfice si la dépense/dette est déjà comptée dans les frais du trajet.

## Calcul du bénéfice

Le bénéfice doit rester cohérent avec le calcul du prix de revient.

Formule par litre :

```text
Prix de revient par litre =
Prix fournisseur par litre
+ commission transporteur par litre
+ transit par litre
+ frontière par litre
+ douane par litre
+ chargement par litre
+ autres frais par litre
```

```text
Bénéfice par litre =
Prix de vente par litre - Prix de revient par litre
```

```text
Bénéfice total =
Bénéfice par litre × quantité vendue/livrée
```

Exemple :

```text
Prix fournisseur: 500 MRU/L
Commission transporteur: 65 MRU/L
Transit: 10 MRU/L
Douane: 225 MRU/L

Prix de revient: 800 MRU/L
Prix de vente: 850 MRU/L
Bénéfice: 50 MRU/L
```

Si le prix de vente est inférieur au prix de revient, afficher une perte.

## Actionnaires / Associés

La page doit permettre de créer et gérer les associés.

Pour chaque associé :

- nom ;
- téléphone facultatif ;
- pourcentage de participation ;
- actif/inactif ;
- notes ;
- bénéfice dû ;
- montant déjà retiré ;
- avances reçues ;
- avances données ;
- solde disponible.

## Contrôle des pourcentages

Règles :

- le pourcentage d'un associé doit être entre `0` et `100`;
- la somme des associés actifs ne doit pas dépasser `100%`;
- si la somme est inférieure à `100%`, afficher clairement le pourcentage non attribué ;
- les calculs de parts utilisent uniquement les associés actifs.

## Parts de bénéfice en temps réel

Les droits des associés doivent apparaître directement selon le bénéfice actuel, même avant clôture officielle.

Exemple :

```text
Bénéfice actuel: 10 000 000 MRU

Ahmed: 80% = 8 000 000 MRU
Mohamed: 10% = 1 000 000 MRU
Abdallah: 10% = 1 000 000 MRU
```

Pour chaque associé :

```text
Solde disponible =
part de bénéfice actuelle
- retraits déjà effectués
- avances données encore ouvertes
+ avances reçues à rembourser selon le ledger
```

Si l'application choisit une logique ledger différente, garder une seule source de vérité backend et l'expliquer dans les commentaires/tests.

## Retrait d'un associé

Ajouter une action :

```text
Retrait d'argent de l'associé
```

Contrôles obligatoires :

- choisir l'associé ;
- afficher son solde disponible ;
- choisir la banque utilisée ;
- afficher le solde de la banque ;
- montant > 0 ;
- montant <= solde disponible de l'associé ;
- montant <= solde de la banque ;
- créer une sortie `TreasuryTransaction MONEY_OUT`;
- lier la transaction au retrait ;
- mettre à jour le ledger de l'associé.

Si le solde associé est insuffisant :

```text
Solde associé insuffisant.
```

Si le solde bancaire est insuffisant :

```text
Solde bancaire insuffisant.
```

## Avance / Dette entre associés

Ajouter une action :

```text
Avance / Dette entre associés
```

Champs :

- associé demandeur / emprunteur ;
- associé prêteur ;
- montant ;
- date ;
- note ;
- statut ;
- montant remboursé ;
- montant restant.

Contrôles obligatoires :

- un associé ne peut pas prendre une avance de lui-même ;
- le montant doit être supérieur à zéro ;
- le prêteur doit avoir un solde disponible suffisant ;
- le montant de l'avance ne peut pas dépasser le solde disponible du prêteur ;
- le montant remboursé ne peut pas dépasser le montant initial ;
- le statut devient `PARTIALLY_REPAID` ou `REPAID` selon le montant remboursé ;
- l'avance doit apparaître dans le ledger des deux associés.

Messages attendus :

```text
Un associé ne peut pas se prêter de l'argent à lui-même.
```

```text
Solde disponible du prêteur insuffisant.
```

```text
Le montant remboursé dépasse le montant de l'avance.
```

## Ledger associé

Chaque associé doit avoir un détail clair :

- bénéfice dû selon son pourcentage ;
- retraits ;
- avances données ;
- avances reçues ;
- remboursements ;
- solde restant.

Le ledger doit permettre de comprendre pourquoi l'associé a tel solde.

## Dashboard

Si possible, ajouter dans le dashboard une section simple :

- bénéfice actuel ;
- bénéfice distribué / retiré par associés ;
- bénéfice restant non retiré ;
- total avances entre associés ouvertes.

Ne pas surcharger le dashboard si la page `Bénéfices` contient déjà le détail.

## Contraintes techniques

- Garder les calculs financiers dans des services backend.
- Utiliser `Decimal`, jamais `float`.
- Les soldes associés doivent être calculés depuis le ledger, pas saisis manuellement.
- Les retraits associés qui sortent de l'entreprise doivent créer des `TreasuryTransaction MONEY_OUT`.
- Les avances entre associés ne doivent pas créer de transaction trésorerie entreprise si l'argent ne sort pas d'un compte de l'entreprise.
- Ne pas permettre de solde négatif pour un associé ou une banque.
- Ajouter des tests backend pour toutes les règles de contrôle.
- Mettre à jour les types TypeScript, routes Vue, sidebar, textes `fr/en/ar`.

## Tests attendus

Ajouter ou ajuster des tests couvrant :

- création associé avec pourcentage valide ;
- refus pourcentage < 0 ou > 100 ;
- refus somme des associés actifs > 100% ;
- calcul part bénéfice `80/10/10` sur `10 000 000`;
- retrait associé refuse montant supérieur au solde associé ;
- retrait associé refuse montant supérieur au solde bancaire ;
- retrait associé crée `TreasuryTransaction MONEY_OUT`;
- avance entre associés refuse borrower == lender ;
- avance refuse si solde prêteur insuffisant ;
- remboursement refuse montant remboursé supérieur au principal ;
- ledger associé affiche bénéfice dû, retraits, avances données/reçues, solde restant ;
- page `Bénéfices` affiche bénéfice par période et détail par trajet.

## Prompt court à exécuter

Implémente une page `Bénéfices` et complète `Actionnaires / Associés` dans `Trésorerie & Finance`. Les bénéfices doivent être calculés côté backend depuis les trajets/ventes/frais, avec détail par période et par trajet. Les associés ont un pourcentage, une part de bénéfice actuelle visible avant clôture, des retraits contrôlés par solde associé et solde bancaire, et des avances entre associés contrôlées. Interdire qu'un associé se prête à lui-même, interdire une avance si le prêteur n'a pas assez de solde disponible, interdire les retraits au-delà du solde disponible, et créer une `TreasuryTransaction MONEY_OUT` pour les retraits associés depuis une banque. Mettre à jour backend, API, Vue, sidebar, traductions et tests.

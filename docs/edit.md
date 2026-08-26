# Prompt codex — Ajustements page Trajet

Dans le projet `/Users/mohamed/Downloads/fuel-logistics-erp`, ne modifie pas `docs/plan.md`. Implémente uniquement les ajustements suivants sur la page Trajet / Chargement, en gardant la logique existante de l'application.

## Objectif

Corriger le workflow de la page trajet pour que :

- un trajet puisse rester affecté au `Stock de l’entreprise` tant qu’aucun client n’est choisi ;
- le bouton `Attribuer un client` n’apparaisse qu’après la phase `Douane` ;
- les statuts liés au client restent bloqués tant qu’aucun client n’est attribué ;
- si aucun client n’est attribué après la douane, le trajet continue vers le stock de l’entreprise sans bug ;
- certains changements de statut ouvrent automatiquement une fenêtre de saisie des frais du trajet ;
- le `Prix de revient` par litre soit calculé correctement à partir du prix fournisseur + tous les frais par litre ;
- le formulaire de livraison affiche clairement si le prix saisi est rentable ou à perte, avec le détail du calcul.

## Règles métier confirmées

### 1. Client et stock entreprise

Au début, le trajet n’a pas de client obligatoire.

Dans le détail du trajet, afficher :

- `Client`
- `Stock de l’entreprise`
- bouton `Attribuer un client`

Mais le bouton `Attribuer un client` ne doit pas apparaître dès le début.

Il doit apparaître uniquement quand le trajet a terminé ou atteint la phase `Douane`, c’est-à-dire après que les frais logistiques nécessaires ont été saisis.

### 2. Statuts client bloqués avant attribution client

Tant que `trip.client` est vide :

- ne pas permettre `En route vers le client` ;
- ne pas permettre `Arrivé chez le client` ;
- ne pas permettre `Contrôle de quantité` côté client ;
- ne pas afficher ces statuts comme prochaines options disponibles.

Après attribution d’un client :

- afficher/autoriser les statuts client ;
- permettre la suite normale :
  - `En route vers le client`
  - `Arrivé chez le client`
  - `Contrôle de quantité`
  - livraison / vente.

### 3. Cas sans client après douane

Si le trajet arrive après `Douane` et qu’aucun client n’est attribué, le système ne doit pas être bloqué.

Dans ce cas, le trajet doit continuer vers le stock de l’entreprise.

Ajouter ou utiliser un chemin explicite du type :

- `En route vers stock entreprise`
- `Arrivé au stock entreprise`
- `Stocké`

ou l’équivalent déjà existant si le code possède déjà des statuts proches.

Important :

- ne pas forcer l’utilisateur à choisir un client ;
- ne pas créer de vente ;
- ne pas créer de facture ;
- garder la quantité disponible dans le stock entreprise ;
- permettre plus tard l’attribution à un client depuis ce stock si la logique existe ou si elle doit être ajoutée minimalement.

## Popups automatiques des frais

Remplacer l’usage manuel obligatoire de `Frais du trajet -> Ajouter un frais` par une ouverture automatique de popup selon le changement de statut.

La saisie manuelle peut rester disponible, mais le workflow principal doit proposer le popup automatiquement.

### Mapping confirmé

| Changement de statut | Popup automatique |
|---|---|
| `Affecté` -> `Envoyé au chargement` | `Commission du transporteur` par litre |
| `Envoyé au chargement` -> `Chargement en cours` | `Frais de chargement` par litre |
| `Chargement en cours` -> `Chargé` | Aucun frais |
| `Chargé` -> `En transit` | `Frais transit` par litre |
| `En transit` -> `Frontière` | `Frais frontière` par litre |
| `Frontière` -> `Douane` | `Frais douane` par litre |
| Après `Douane` | Afficher `Attribuer un client` |
| `En route vers le client` | Aucun frais |
| `Arrivé chez le client` | Aucun frais |

## Affichage des frais du trajet

Dans la section `Frais du trajet`, afficher clairement tous les frais saisis :

- type du frais ;
- date ;
- montant par litre ;
- quantité du trajet ;
- total calculé ;
- devise.

Exemples de types visibles :

- `Commission transporteur`
- `Transport`
- `Transit`
- `Frontière`
- `Douane`
- `Chargement`
- autres frais éventuels.

Chaque montant affiché doit indiquer l’unité quand c’est un prix par litre, par exemple :

- `65 MRU/L`
- `10 MRU/L`
- `225 MRU/L`

## Calcul correct du prix de revient

Le prix de revient minimum par litre doit être :

```text
Prix de revient par litre =
Prix fournisseur par litre
+ Commission transporteur par litre
+ Frais transit par litre
+ Frais frontière par litre
+ Frais douane par litre
+ Frais chargement par litre
+ Autres frais par litre
```

Ne pas diviser deux fois.
Ne pas utiliser le total du trajet comme prix par litre.
Ne pas oublier les frais par litre.

Exemple confirmé :

```text
Prix fournisseur: 500 MRU/L
Commission transporteur: 65 MRU/L
Transit: 10 MRU/L
Douane: 225 MRU/L

Prix de revient par litre = 500 + 65 + 10 + 225 = 800 MRU/L
```

Dans cet exemple, le système ne doit pas considérer une vente à moins de `800 MRU/L` comme rentable.

## Formulaire prix de vente / livraison

Sous le champ `Prix de vente unitaire`, afficher un bloc clair avec :

- `Prix fournisseur`
- `Commission transporteur`
- `Transit`
- `Frontière`
- `Douane`
- `Chargement`
- `Autres frais`
- `Prix de revient`
- `Prix de vente saisi`
- `Résultat`

Le résultat doit afficher :

- bénéfice par litre si prix de vente > prix de revient ;
- zéro si prix de vente = prix de revient ;
- perte par litre si prix de vente < prix de revient.

Exemple :

```text
Prix fournisseur: 500 MRU/L
Commission transporteur: 65 MRU/L
Transit: 10 MRU/L
Douane: 225 MRU/L
Prix de revient: 800 MRU/L
Prix de vente saisi: 790 MRU/L
Résultat: Perte de 10 MRU/L
```

Si le prix est inférieur au prix de revient :

- afficher une alerte claire `Attention : vente à perte` ;
- bloquer la validation ou demander une confirmation explicite selon la logique déjà prévue dans l’application ;
- ne jamais afficher ce prix comme bénéfice positif.

## Contraintes techniques

- Garder les calculs dans les services backend, pas seulement dans Vue.
- Vue peut afficher une estimation, mais l’autorité finale doit venir de l’API.
- Utiliser `Decimal`, jamais `float`, pour les montants et litres.
- Garder les écritures financières atomiques.
- Ne pas casser les tests existants.
- Ajouter ou ajuster les tests backend pour couvrir :
  - prix de revient `500 + 65 + 10 + 225 = 800`;
  - vente à `790` détectée comme perte de `10`;
  - vente à `800` détectée comme zéro bénéfice;
  - vente à `850` détectée comme bénéfice de `50`;
  - statuts client bloqués sans client;
  - route vers stock entreprise possible sans client après douane;
  - popups/frais automatiques créent les bonnes lignes de frais.




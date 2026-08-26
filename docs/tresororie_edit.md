# Prompt Claude Code — Nouveau paiement contrôlé dans Journal de trésorerie

Dans le projet `/Users/mohamed/Downloads/fuel-logistics-erp`, ne modifie pas `docs/plan.md` sauf si l'utilisateur le demande explicitement. Implémente uniquement l'ajustement suivant : ajouter un paiement contrôlé depuis la page `Journal de trésorerie`.

## Objectif

Dans `Trésorerie & Finance > Journal de trésorerie`, ajouter un seul bouton :

```text
+ Nouveau paiement
```

Après clic, ouvrir une fenêtre/modale où l'utilisateur choisit le type de dette à payer. Le paiement ne doit jamais être une sortie libre sans contrôle. Il doit toujours être lié à une dette existante, à un compte bancaire, et au solde disponible.

## Types de dettes à proposer

La modale doit proposer un champ :

```text
Type de dette
```

Options :

- `Fournisseur`
- `Transporteur`
- `Douane`
- `Transit`
- `Frontière`
- `Chargement`
- `Autres frais du trajet`

Après choix du type, afficher uniquement les dettes non payées ou partiellement payées correspondant à ce type.

## Règles de contrôle obligatoires

Pour chaque paiement :

- l'utilisateur choisit une dette existante dans une liste ;
- le système affiche le montant total de la dette ;
- le système affiche le montant déjà payé ;
- le système affiche le reste à payer ;
- l'utilisateur choisit la banque utilisée ;
- le système affiche le solde actuel de cette banque ;
- le montant payé doit être supérieur à zéro ;
- le montant payé ne doit pas dépasser le reste à payer ;
- le montant payé ne doit pas dépasser le solde disponible de la banque ;
- les paiements se font par banque, pas par caisse, pour ce workflow ;
- après validation, créer une sortie dans `TreasuryTransaction`;
- la sortie doit être liée à l'objet payé avec `source_content_type` et `source_object_id`;
- la dette doit passer à `PARTIALLY_PAID` ou `PAID` selon le reste ;
- le journal de trésorerie doit afficher la transaction comme `Sortie`.

## Comportement attendu par type

### Fournisseur

Payer une dette fournisseur doit :

- être lié à un `SupplierPayment` ou au modèle équivalent déjà existant ;
- utiliser `method = BANK_TRANSFER`;
- exiger un `bank_account`;
- diminuer l'encours fournisseur ;
- créer une transaction `MONEY_OUT` dans le journal ;
- refuser le paiement si le solde bancaire est insuffisant.

### Transporteur

Payer une dette transporteur doit :

- être lié à un `TransportPayment` existant non payé ou partiellement payé ;
- payer uniquement le `net_amount` restant ;
- créer une transaction `MONEY_OUT`;
- mettre à jour le statut du règlement transporteur ;
- refuser le paiement si le montant dépasse le reste ou le solde bancaire.

### Douane / Transit / Frontière / Chargement / Autres frais trajet

Ces frais sont liés aux `Expense` / `ExpenseAllocation` / frais trajet existants.

Le paiement doit :

- afficher les frais non payés ou partiellement payés ;
- garder le lien avec le trajet quand le frais est lié à un trajet ;
- créer une transaction `MONEY_OUT`;
- diminuer le reste à payer ;
- mettre à jour le statut du frais ;
- conserver le frais dans le calcul du `Prix de revient`, même après paiement ;
- refuser le paiement si le montant dépasse le reste ou le solde bancaire.

## Banque et caisse

Le bouton `Nouveau paiement` sert aux sorties contrôlées par banque.

Ne pas utiliser la caisse pour ce workflow, sauf si une règle existante du projet l'impose déjà.

Afficher clairement :

```text
Banque sélectionnée
Solde disponible
Montant à payer
Reste après paiement
```

Si le solde bancaire est insuffisant :

```text
Solde bancaire insuffisant pour effectuer ce paiement.
```

## Dashboard et trésorerie

Garder la cohérence avec les chiffres visibles :

- `Montant total des banques` = somme des soldes courants des comptes bancaires actifs.
- `Montant total des caisses` = somme des soldes courants des comptes de caisse actifs.
- `Solde trésorerie` = banques + caisses.

Si `Montant total des caisses` n'est pas encore visible dans le dashboard, l'ajouter à côté de `Montant total des banques`.

Dans les pages `Comptes de caisse`, afficher aussi le `Solde courant`, pas seulement le `Solde d'ouverture`.

Dans les pages `Comptes bancaires`, afficher aussi le `Solde courant`, pas seulement le `Solde d'ouverture`.

## Contraintes techniques

- Garder les règles financières dans des services backend, pas seulement dans Vue.
- Utiliser `Decimal`, jamais `float`.
- Toute création de paiement + transaction trésorerie + mise à jour de dette doit être atomique.
- Empêcher les doubles écritures : ne pas créer deux `TreasuryTransaction` pour le même paiement.
- Ne pas casser les écritures existantes du journal de trésorerie.
- Ne pas transformer les transferts internes en dépenses ; les transferts restent exclus du profit.
- Ajouter des tests backend pour chaque règle de contrôle.
- Mettre à jour les types TypeScript, les appels API, les textes `fr/en/ar`, et les tests frontend si nécessaire.

## Tests attendus

Ajouter ou ajuster des tests couvrant :

- bouton/endpoint de paiement fournisseur contrôlé ;
- paiement fournisseur refuse un montant supérieur au reste ;
- paiement fournisseur refuse si solde bancaire insuffisant ;
- paiement transporteur diminue le reste à payer ;
- paiement transporteur passe à `PAID` quand tout est payé ;
- paiement frais douane/transit/frontière/chargement crée une sortie banque ;
- paiement frais trajet conserve le frais dans le calcul du prix de revient ;
- `TreasuryTransaction` créée est liée à la dette payée ;
- `Montant total des caisses` apparaît dans le dashboard ;
- `Solde courant` apparaît dans comptes bancaires et comptes de caisse.

## Prompt court à exécuter



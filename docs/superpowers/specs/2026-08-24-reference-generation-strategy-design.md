# Stratégie globale de génération des références — Spécification

Date : 2026-08-24
Statut : Approuvé

## Contexte

Le champ "Référence" est géré de façon incohérente selon les entités :

- **SupplierOrder** (`backend/apps/purchasing/models.py`) : `reference`
  `unique=True`, texte libre saisi par l'utilisateur. Une modification WIP
  non committée dans `SupplierOrderForm.vue` pré-remplit une suggestion
  côté client (`ACH-YYYYMM-XXXX`, suffixe **aléatoire**) mais le champ reste
  éditable et la valeur est envoyée telle quelle au serveur — collisions
  possibles, d'où l'ajout ad hoc d'un `fieldErrors.reference` pour absorber
  les 400 de doublon.
- **CessionLetter** (`backend/apps/purchasing/models.py`) : `reference`
  `unique=True`, champ texte totalement vide par défaut, aucune génération.
  Le `catch` d'erreur ne lit que `authorized_quantity` — un doublon de
  `reference` retombe silencieusement sur un message générique.
- **Trip** (`backend/apps/trips/models.py`) : `reference` déjà généré côté
  serveur, séquentiel (`TRIP-000001`), `read_only` dans le serializer,
  généré dans `TripViewSet.perform_create` avec retry sur `IntegrityError`.
  Fonctionne bien, **ne sera pas modifié**.
- **Invoice** (`backend/apps/sales/models.py`) : `invoice_number` généré par
  `DeliveryService` sous la forme `INV-{trip.reference}` lors de la
  confirmation d'une livraison. `InvoiceViewSet.create()` est désactivé
  (`MethodNotAllowed`) — il n'existe et n'existera aucun formulaire de
  création de facture.

Objectif : une stratégie serveur-autoritaire cohérente pour SupplierOrder et
CessionLetter (nomenclature `PREFIX-YYYYMM-XXXX`, compteur séquentiel
mensuel), un renommage de format pour Invoice, et une gestion homogène des
erreurs 400 par champ sur les formulaires de la chaîne d'approvisionnement.

## 1. Backend — générateur de référence mensuel partagé

Nouveau fichier `backend/apps/core/reference.py` :

```python
def generate_monthly_reference(model, field_name, prefix, width=4, now=None) -> str:
    """PREFIX-YYYYMM-0001, .../0002, ... Compteur mensuel par préfixe.

    Le regex est scopé au format exact généré (préfixe + mois courant +
    N chiffres), donc les références historiques/saisies à la main dans un
    format différent sont ignorées — même technique que
    trips/views.py:_generate_next_reference, qui évite qu'une référence
    "seed" non numérique ne fasse repartir la séquence à zéro.
    """
```

Pas de nouvelle app/dépendance : `core` existe déjà et ne contient
actuellement que des modèles d'audit — c'est l'emplacement naturel pour un
utilitaire partagé entre `purchasing`, `trips` et `sales`.

Ce générateur n'est **pas** utilisé par Trip (format `TRIP-000001` conservé
tel quel, décision validée) — uniquement par SupplierOrder, CessionLetter et
Invoice.

## 2. Backend — génération autoritaire côté serveur

- `SupplierOrderSerializer.Meta.read_only_fields` : ajout de `reference`.
- `CessionLetterSerializer.Meta.read_only_fields` : ajout de `reference`.
- `SupplierOrderViewSet.perform_create` / `CessionLetterViewSet.perform_create` :
  génèrent `reference` via `generate_monthly_reference(..., prefix="ACH")`
  / `prefix="CES"`, avec retry sur `IntegrityError` (même forme que
  `TripViewSet.perform_create`, dupliquée localement plutôt que factorisée
  — la boucle de retry est courte et le contexte de chaque viewset diffère
  assez pour qu'une abstraction commune n'apporte pas grand-chose ici).
- Aucune migration de modèle : les contraintes `unique=True` existent déjà,
  et le scoping par regex isole naturellement les anciennes références
  hors-format.
- `DeliveryService` (`backend/apps/trips/services.py:301`) : remplace
  `invoice_number=f"INV-{trip.reference}"` par
  `generate_monthly_reference(Invoice, "invoice_number", "FAC")`, avec la
  même logique de retry (la création de facture se fait dans une
  transaction déjà ouverte par la confirmation de livraison).

## 3. Backend — endpoint de prévisualisation (non réservant)

Le champ étant désormais en lecture seule, le formulaire ne peut plus
"suggérer puis laisser éditer" : il a besoin d'une valeur à afficher avant
la soumission réelle. Ajout d'une action `GET` par viewset, qui calcule la
prochaine référence **sans la persister** :

- `GET /api/supplier-orders/next-reference/` → `{"reference": "ACH-202608-0007"}`
- `GET /api/cession-letters/next-reference/` → `{"reference": "CES-202608-0012"}`

C'est une prévisualisation, pas une réservation : si deux créations
concurrentes affichent le même aperçu, seule la valeur retournée par la
réponse de création (autoritaire, générée dans `perform_create`) fait foi.
Le champ étant en lecture seule côté formulaire, il n'y a aucun conflit
visible pour l'utilisateur.

## 4. Frontend — formulaires SupplierOrder et CessionLetter

- `SupplierOrderForm.vue` : suppression de `generateReferenceSuggestion()`
  (suffixe aléatoire, WIP). Au montage en mode création, appel à
  `GET .../next-reference/`, champ `reference` rendu en lecture seule
  (`disabled` + libellé d'aide "généré automatiquement"), `autocomplete="off"`
  conservé. Le payload de création n'envoie plus `reference`.
- `CessionLetterForm.vue` : même traitement pour son propre champ
  `reference`. Le `<select>` `supplier_order` (référence de la commande
  liée, affichée dans les options et en lecture seule quand on arrive via
  `?supplier_order=`) n'est pas affecté — il reste indépendant du champ
  `reference` principal du formulaire.
- Les deux formulaires gardent `reference` en lecture seule également en
  mode édition (le serveur rejette de toute façon toute tentative de
  modification côté API).

## 5. Gestion des erreurs 400 par champ (scope ciblé)

Scope validé : uniquement les formulaires de la chaîne d'approvisionnement
directement concernés par ce travail — `SupplierOrderForm`,
`CessionLetterForm`, `TripForm`, `CustomerOrderForm`. Pas d'audit
élargi au reste de l'application.

- Ajout d'un helper partagé `extractFieldErrors(response)` dans
  `frontend/src/i18n/apiErrors.ts` (à côté de `translateApiError`, déjà
  utilisé par certains de ces formulaires) : retourne
  `Record<string, string>` à partir d'un corps d'erreur 400 DRF, en
  ignorant `detail`/`non_field_errors`.
- `SupplierOrderForm.vue` : remplace sa boucle `fieldErrors` ad hoc
  (actuellement WIP, spécifique à `reference`) par le helper partagé.
- `CessionLetterForm.vue` : corrige le bug actuel (seul
  `authorized_quantity` est lu, tout le reste — y compris un futur 400 sur
  un autre champ — retombe sur le message générique) en adoptant le même
  helper, avec affichage par champ dans le template.
- `TripForm.vue` : remplace la logique "premier champ trouvé, peu importe
  lequel" par le helper partagé, avec affichage par champ (actuellement
  seul `bl_reference` a un slot d'erreur dédié dans le template, `reference`
  du Trip n'ayant toujours pas de champ visible — hors scope, cf. décision
  "garder TRIP-000001").
- `CustomerOrderForm.vue` : remplace le `catch` actuel qui ignore
  entièrement le corps de la réponse par le helper partagé.

## 6. Tests et validation

Backend :
- Tests unitaires `generate_monthly_reference` : format, rollover mensuel,
  isolation des références hors-format, comportement en cas de collision
  (retry).
- Tests des endpoints `next-reference` (prévisualisation, non-réservation).
- Tests serializer : un `reference` fourni par le client à la création est
  ignoré (read-only), la valeur générée par le serveur prévaut.
- Test `DeliveryService` : format `FAC-YYYYMM-XXXX` de la facture générée.

Frontend :
- Mise à jour de `SupplierOrderForm.spec.ts` (déjà présent, à adapter :
  champ en lecture seule + appel de prévisualisation, au lieu de
  l'assertion sur le suffixe aléatoire).
- Ajout de specs équivalentes pour `CessionLetterForm.vue`.

Validation bout en bout (manuel, via browser automation) : création
Commande fournisseur → Lettre de cession → Trajet → Facture, en vérifiant
qu'aucune référence ne bloque la soumission et que les erreurs de champ
s'affichent correctement si provoquées.

`npm run build` + suite de tests complète (frontend + backend) en fin de
parcours.

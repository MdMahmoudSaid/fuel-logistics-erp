# Corrections recette client après réunion (2026-09-04)

Date: 2026-09-04
Statut: Règles validées avec le client (prompt client verbatim) + arbitrages contrôleur validés par l'utilisateur avant implémentation (voir "Rulings" par section). Prêt pour plan d'implémentation.

## Contexte et règles générales

6 corrections indépendantes issues d'une réunion de recette client. Règles transverses :

- Ne pas casser la logique existante des avances fournisseur/transporteur, du Grand livre, de la trésorerie.
- Pas de refonte UI large — actions/pages ciblées ajoutées aux écrans existants.
- Ne pas réécrire le moteur de coût trajet (`TripCostService`) ni le moteur de marge (`TripProfitService`'s cost side).
- Mouvements financiers auditables : pas de suppression silencieuse d'une transaction ayant déjà un impact comptable.
- Tests backend/frontend ciblés par correction. Commits séparés par sujet.

Ce chantier est indépendant du chantier "6 phases" précédent (`docs/superpowers/specs/2026-09-02-business-corrections-6-phases-design.md`), déjà mergé sur `main` (capital, ancien fond de roulement signé, dépenses générales/`ExpenseCategory`, `profit_after_capital`). Plusieurs règles ci-dessous **remplacent** des éléments de ce chantier précédent suite à une clarification du client — voir Rulings.

---

## 1. Frais par camion : affichage avec décimales

### Règle métier

- Les coûts unitaires (XOF/L) calculés à partir d'un frais "Par camion" doivent s'afficher avec 2 décimales (`0,22 XOF/L`), jamais arrondis à l'entier.
- Le calcul (précision, montant total du frais) est inchangé — uniquement l'affichage.

### État actuel

- Backend : `TripCostService.calculate_trip_cost_basis` (`backend/apps/trips/services.py:32,153-181`) garde déjà 4 décimales de précision (`_UNIT = Decimal("0.0001")`) — rien à changer côté backend.
- Frontend : `formatUnitMoney()` (`frontend/src/utils/currency.ts:35-37`) route par `formatInteger()` → `Math.round(...)`, donc tout XOF/L affiché via cette fonction est arrondi à 0 décimale (`TripDetail.vue:753,764`, `DeliveryControlForm.vue` `resultText`/component rows). Seul `ExpenseForm.vue:267-272` fait déjà `.toFixed(4)` en aparté, pas via `formatUnitMoney`.

### Correction

Nouvelle fonction `formatUnitMoney` (2 décimales, format `0,22 XOF/L`) dans `frontend/src/utils/currency.ts`, utilisée partout où un XOF/L est affiché (`TripDetail.vue`, `DeliveryControlForm.vue`, `ExpenseForm.vue` preview). `formatMoney`/`formatQuantity` (montants XOF entiers, quantités L) restent arrondis à l'entier — inchangés.

---

## 2. Livraison et perte après livraison client

### Règle métier

- Le trajet passe de `ARRIVED_AT_CLIENT` directement à `DELIVERED` — plus d'étape `QUANTITY_CONTROL` obligatoire sur le chemin normal.
- Par défaut à la livraison : quantité reçue = quantité chargée, perte = 0.
- Après livraison (statut `DELIVERED` ou `COMPLETED`, jamais `CANCELLED`), un bouton dédié ouvre un formulaire de "vérification client" : quantité chargée (lecture seule), quantité reçue par le client, perte calculée automatiquement, partie supportée par l'entreprise, partie facturable au transporteur, notes, date de vérification.
- Seuil validé : perte ≤ 100 L → l'entreprise supporte (diminue la marge du trajet). Perte > 100 L → le transporteur supporte la partie au-delà de 100 L, via la logique de déduction/indemnisation transporteur déjà existante (`TransportDeduction`).

### État actuel

- `Trip.Status` (`backend/apps/trips/models.py:24-45`) a déjà `QUANTITY_CONTROL` entre `ARRIVED_AT_CLIENT` et `DELIVERED`.
- `TripWorkflowService.FORWARD_TRANSITIONS` (`backend/apps/trips/services.py:325-340`) : `ARRIVED_AT_CLIENT → QUANTITY_CONTROL → DELIVERED → COMPLETED`.
- `DeliveryService.record_delivery` (`services.py:507-640`) exige aujourd'hui `received_qty` en entrée (paramètre obligatoire), crée le `DeliveryControl`, transitionne vers `DELIVERED`, crée `Sale`+`Invoice`.
- `DeliveryControl.save()` (`trips/models.py:281-290`) recalcule déjà `loss_quantity`/`chargeable_loss_quantity = max(loss - tolerance, 0)` à chaque sauvegarde — réutilisable tel quel pour la vérification a posteriori (le modèle n'a jamais interdit de re-sauvegarder avec un `received_quantity` mis à jour, seul `tolerance_quantity` est censé rester figé une fois écrit).
- `LossToleranceConfig.DEFAULT_TOLERANCE` (`backend/apps/core/models.py:43`) **vaut déjà 100.00** — le seuil client de 100 L est déjà le défaut système, aucun changement de valeur nécessaire (ruling ci-dessous : garder ce mécanisme configurable, ne pas coder un seuil séparé).
- **Bug existant trouvé en investigation** : `DeliveryService.sync_transport_shortage_deduction` (`services.py:642-692`) calcule `missing_quantity = quantity_loaded - received_qty` **sans soustraire la tolérance** (contrairement à `DeliveryControl.chargeable_loss_quantity` qui le fait) — la déduction transporteur actuelle facture donc potentiellement les 100 premiers litres au transporteur, ce que la règle validée interdit désormais explicitement. À corriger dans cette phase.
- `Sale.delivered_quantity` (`backend/apps/sales/models.py:88-90`) est **`editable=False` par design** ("Delivered Quantity is Commercial Truth", jamais réécrit après coup) — la vérification client ne doit donc jamais réécrire `Sale`/`Invoice`, seulement `DeliveryControl` + la marge calculée doit intégrer la perte non-facturable.
- `TripProfitService.get_cost_breakdown` (`backend/apps/reports/services/profit.py:131-172`) : `margin = revenue + transporter_loss_indemnity - real_total_cost`, où `revenue = sale.delivered_quantity * sale.unit_selling_price`. N'intègre aujourd'hui aucune notion de perte non facturable (tolérée) — à ajouter.

### Rulings (validés par l'utilisateur)

- **Seuil de 100 L** : garder `LossToleranceConfig` configurable, ne pas coder un seuil séparé en dur. Sa valeur par défaut est déjà 100 — vérifier/fixer explicitement en migration de données si une instance en base a une valeur différente.

### Correction

1. `TripWorkflowService.FORWARD_TRANSITIONS[Trip.Status.ARRIVED_AT_CLIENT] = Trip.Status.DELIVERED` (au lieu de `QUANTITY_CONTROL`). L'entrée `QUANTITY_CONTROL: DELIVERED` reste dans le dict pour tout trajet déjà historiquement à ce statut (aucune migration de données, chemin legacy qui continue de fonctionner).
2. `DeliveryService.record_delivery` : `received_qty` devient optionnel (`received_qty: Decimal | None = None`), défaut = `trip.quantity_loaded`. `DeliveryControlRequestSerializer.received_quantity` devient `required=False, allow_null=True` ; la vue (`TripViewSet.delivery_control`) passe `data.get("received_quantity")` (peut être `None`).
3. `DeliveryControl` : ajout d'un champ `verified_at` (`DateField`, `null=True, blank=True`) — date de vérification client, distincte de `control_date` (date de livraison initiale). Ajout d'une propriété `company_absorbed_loss_quantity` (calculée, pas stockée) = `max(loss_quantity, 0) - chargeable_loss_quantity`.
4. Nouveau `DeliveryService.record_client_verification(trip_id, received_qty, verified_at, actor, notes="")` : sous verrou de ligne sur `Trip`, exige `trip.status in {DELIVERED, COMPLETED}` et l'existence d'un `delivery_control`, met à jour `received_quantity`/`notes`/`verified_at` sur le `DeliveryControl` existant (son `save()` recalcule `loss_quantity`/`chargeable_loss_quantity` automatiquement), puis rappelle `sync_transport_shortage_deduction` (corrigé, voir point 5) pour resynchroniser `TransportDeduction`.
5. Fix du bug : `sync_transport_shortage_deduction` doit utiliser la perte **facturable** (`loss - tolerance`, flooré à 0) et non la perte brute — réutiliser `trip.delivery_control.chargeable_loss_quantity` (déjà recalculé) plutôt que recalculer `quantity_loaded - received_qty` en dur.
6. `TripProfitService.get_cost_breakdown` : soustraire `company_absorbed_loss_quantity * sale.unit_selling_price` de la marge — la perte tolérée par l'entreprise (jamais compensée par `transporter_loss_indemnity`, jamais reflétée par `Sale.delivered_quantity` qui reste immuable) doit faire baisser la marge du trajet.
7. Frontend : `TripDetail.vue`/`DeliveryControlForm.vue` — le formulaire de confirmation à `ARRIVED_AT_CLIENT` n'affiche plus de champ "quantité reçue" obligatoire (prix de vente/date/méthode/document optionnel/notes seulement). Nouveau bouton "Vérification client / Déclarer une perte" visible uniquement quand `trip.status` ∈ `{DELIVERED, COMPLETED}`, ouvrant un nouveau `ClientVerificationForm.vue` (quantité chargée en lecture seule, quantité reçue, perte calculée, partie entreprise/partie transporteur affichées en direct, notes, date de vérification).

---

## 3. Fond de roulement / Trésorerie nette client

### Règle métier (formule corrigée par le client)

```
Fond de roulement client =
  Trésorerie disponible (banques + caisses)
  + Créances clients
  + Dettes fournisseurs ouvertes   (positif, brut, PAS net des avances)
  + Dettes transporteurs ouvertes  (positif, brut, PAS net des avances)
  + Dettes douane/transit/frais trajet ouvertes
```

Les dettes ne sont ajoutées en positif que dans cet indicateur. Partout ailleurs (cartes normales, grands livres, écrans de paiement), une dette reste affichée comme dette à payer ; les paiements sortent toujours de la vraie trésorerie (banque/caisse). Ce n'est pas une source de paiement, seulement un indicateur recalculé.

### État actuel (à remplacer)

`DashboardViewSet.summary()` (`backend/apps/reports/views/dashboard.py:343-368`) calcule déjà un `working_capital` (Phase 2 de l'ancien chantier), mais avec une formule **différente et incompatible** : il additionne `supplier_net_total`/`transporter_net_total` — des soldes **nets et signés** (`open_advances - total_due`, cf. `ControlledDebtPaymentService.describe_supplier_balance`/`describe_transporter_balance`, `backend/apps/finance/services.py:1244-1311`), pas les dettes brutes. Le capital y est exclu volontairement du total.

### Ruling (validé par l'utilisateur)

**Remplacer entièrement** `working_capital.total` par la nouvelle formule additive. Ne pas garder les deux indicateurs côte à côte.

### Correction

Nouveau `WorkingCapitalService.get_working_capital()` dans `backend/apps/finance/services.py` (même app que `ControlledDebtPaymentService`/`ShareholderContributionService`, réutilisé par la Section 4 ci-dessous) :

- `treasury_available` = somme `BankAccount.current_balance` (actifs) + `CashAccount.current_balance` (actifs).
- `customer_receivables` = somme des `outstanding` de `CustomerOutstandingReportQuery.run()` (`apps.reports.queries.customer_outstanding_report` — import déjà précédenté dans ce fichier via `MarginReportQuery`, `backend/apps/finance/services.py:40`).
- `supplier_debt_total` = somme des `total_due` (brut, pas `net_balance`) de `ControlledDebtPaymentService.describe_supplier_balance(s)` pour chaque `Supplier` actif.
- `transporter_debt_total` = somme des `total_due` de `describe_transporter_balance(t)` pour chaque `Transporter` actif.
- `other_debts` = somme des `remaining_amount` de `describe_expense_group` pour `CUSTOMS`, `TRANSIT`, `ROAD_TRANSIT`, `BORDER`, `LOADING`, `TRIP_OTHER` (même liste que l'ancien calcul dashboard).
- `capital` = `ShareholderContributionService.get_total_capital()` (informatif, réutilisé par la Section 4).
- `total` = `treasury_available + customer_receivables + supplier_debt_total + transporter_debt_total + other_debts`.

`DashboardViewSet.summary()` remplace son bloc inline (lignes 343-368) par un appel à `WorkingCapitalService.get_working_capital()`. Note : ce service refait ses propres requêtes (pas de partage de queryset avec le reste de `summary()`) — quelques requêtes dupliquées sur un seul endpoint dashboard, accepté en échange d'un point de calcul unique réutilisable aussi par la Section 4 (`ShareholderProfitPreviewService`), qui n'a pas accès aux variables locales de `dashboard.py`.

---

## 4. Les trois bénéfices doivent être distincts

### Règle métier

- **A. Bénéfice opérationnel des trajets** = ventes trajets − coûts trajets. Inchangé (`current_margin`/`operational_profit` existants).
- **B. Bénéfice net** = bénéfice opérationnel − dépenses générales payées. Inchangé, jamais mélangé avec capital/créances/dettes/trésorerie.
- **C. Résultat distribuable après dettes et capital** = Fond de roulement client (Section 3) − dettes fournisseurs ouvertes − dettes transporteurs ouvertes − dettes douane/transit/frais ouvertes − capital apporté.

Libellés UI : "Bénéfice opérationnel des trajets", "Bénéfice net après dépenses générales", "Fond de roulement client", "Résultat distribuable après dettes et capital". Page Bénéfices : les trois blocs (A/B/C) clairement affichés. Dashboard : au minimum FDR + résultat distribuable.

### État actuel (à remplacer)

`ShareholderProfitPreviewService.get_preview()` (`backend/apps/finance/services.py:1993-2066`) calcule déjà A (`operational_profit`) et B (`net_profit`) correctement — **inchangés**. Il calcule aussi `profit_after_capital = net_profit - total_capital_contributed` (ligne 2037) — une formule **différente** de C, à remplacer.

### Ruling (validé par l'utilisateur)

**Remplacer** `profit_after_capital` par `distributable_result` (nouvelle formule C). Ne pas garder les deux côte à côte.

### Correction

Dans `ShareholderProfitPreviewService.get_preview()` :
- Appeler `WorkingCapitalService.get_working_capital()` (Section 3) une fois.
- `distributable_result = working_capital["total"] - working_capital["supplier_debt_total"] - working_capital["transporter_debt_total"] - working_capital["other_debts"] - working_capital["capital"]` (formule C écrite explicitement, terme par terme, pas simplifiée algébriquement — même si elle se réduit mathématiquement à `treasury_available + customer_receivables - capital` compte tenu de la formule FDR, l'écrire en toutes lettres garde la traçabilité si la formule FDR change plus tard).
- Retourner `working_capital` (dict complet) et `distributable_result` à la place de `total_capital_contributed`/`profit_after_capital` (le `capital` reste accessible via `working_capital["capital"]`).
- `DashboardViewSet.summary()` : `shareholders_summary` expose `distributable_result` (au lieu de `profit_after_capital`) et le payload racine expose déjà `working_capital` (Section 3).
- Frontend : `ProfitView.vue` (labels/clés `net_profit`/`operational_profit`/`total_capital_contributed`/`profit_after_capital` aux lignes citées dans l'investigation — `151,259,280,300,312`) et `DashboardView.vue` (`959,993,1004`) mis à jour vers les nouvelles clés + nouveaux libellés ci-dessus, affichage des 3 blocs sur la page Bénéfices, ajout FDR + résultat distribuable sur le Dashboard.

---

## 5. Impression et export PDF des Grands Livres

### Règle métier

- Boutons "Imprimer" + "Exporter PDF" en haut de `SupplierLedgerView.vue`, `TransporterLedgerView.vue`, `CustomerLedgerView.vue`.
- PDF respecte la langue active (FR/AR/EN) ; limite RTL/Arabic documentée si non parfaite plutôt que bloquante.
- Contenu : société, type de compte, nom de la partie, date d'export, résumé des soldes, historique, totaux, statuts.
- Chaque ligne "Règlement par trajet" a une action Imprimer/PDF avec le détail complet du trajet (référence, camion/plaque, transporteur, client, produit, quantité, statuts, montant brut, déductions, net, date, notes).
- Pas de changement de calcul métier — uniquement export/print.

### État actuel

- Aucun bouton print/export sur les 3 pages de ledger actuellement (vérifié par grep).
- `backend/apps/reports/export.py:49-83` (`rows_to_pdf`, reportlab, déjà une dépendance du projet) génère déjà un PDF tabulaire simple pour la page Reports générique (`format=pdf` sur `GET /api/reports/{report_type}/`, `backend/apps/reports/views/reports.py:128`), mais avec des en-têtes générés par `field.replace("_", " ").title()` — **anglais uniquement, aucune traduction, aucun support RTL**.
- Ledgers backend existants : `SupplierLedgerService.get_ledger(supplier)` (`services.py:2077`), `TransporterLedgerService.get_ledger(transporter)` (`services.py:2156`), exposés via `SupplierViewSet.ledger`/`TransporterViewSet.ledger` (`GET /api/suppliers/{id}/ledger/`, `/api/transporters/{id}/ledger/`) ; côté client, `GET /api/customers/{id}/ledger/` (`backend/apps/customers/views.py:24`, appelé par `frontend/src/modules/finance/api.ts` `fetchCustomerLedger`).

### Correction

1. Nouveau module `backend/apps/reports/services/ledger_pdf.py` : `render_ledger_pdf(*, company_name, account_type, party_name, export_date, summary, rows, lang)` — reportlab, header (société/type de compte/partie/date d'export) + table résumé des soldes + table historique/totaux/statuts, réutilisant les dicts déjà retournés par `get_ledger()`. Labels via une petite table i18n `LEDGER_PDF_LABELS = {"fr": {...}, "en": {...}, "ar": {...}}` (pas de refonte de `labels.py` existant, nouvelle table dédiée). Pour `lang="ar"` : alignement des colonnes à droite (minimal RTL) ; **limite documentée en commentaire et dans le rapport final de tâche** : reportlab/Helvetica n'a pas de glyphes arabes ni de reshaping bidi sans dépendance supplémentaire (`arabic-reshaper`/`python-bidi`, non installées) — non ajoutée dans cette phase (hors scope "petite correction sûre") ; fallback : libellés français conservés en `lang="ar"` tant que cette dépendance n'est pas ajoutée, documenté comme limitation connue.
2. `?format=pdf` (ou action dédiée `/pdf/`) sur les 3 endpoints `ledger` existants (`SupplierViewSet.ledger`, `TransporterViewSet.ledger`, endpoint client équivalent), lisant `lang` depuis un paramètre de requête envoyé par le frontend (locale i18n active).
3. Nouvelle action `/api/transport-payments/{id}/pdf/` (ou équivalent existant si un ViewSet `TransportPayment` existe déjà) pour le détail d'un règlement par trajet — champs listés dans la règle métier, réutilisant `Trip`/`TransportPayment`/`TransportDeduction` déjà chargés.
4. Frontend : boutons "Imprimer" (`window.print()`, precedent `ReportsView.vue:131-133`) + "Exporter PDF" (téléchargement blob, precedent `ReportsView.vue:123`) sur les 3 pages de ledger, et action Imprimer/PDF sur chaque ligne "Règlement par trajet".

---

## 6. Justificatif non obligatoire partout

### Règle métier

Aucun justificatif/document ne doit être obligatoire, nulle part. Si un fichier est fourni, les validations de type/taille existantes s'appliquent toujours.

### État actuel — flux à corriger (obligatoires aujourd'hui)

| Flux | Backend | Frontend |
|---|---|---|
| Paiement dette fournisseur/transporteur | `ControlledDebtPaymentRequestSerializer.validate()` (`backend/apps/finance/serializers.py:891-919`) rejette si `not data.get("attachment")` ; `validate_attachment` (922-927) rejette aussi `None` | `DebtPaymentForm.vue` : `validate()` (~168), gate submit (~187), `required` sur l'`<input type="file">` (~354) |
| Avance fournisseur | `SupplierAdvanceSerializer.validate()` (`serializers.py:365,390-392`) rejette si `self.instance is None and not data.get("attachment")` | `AdvanceForm.vue` : `validate()` (172-175), gate submit (180), `required` (~343) |
| Avance transporteur | `TransporterAdvanceSerializer.validate()` (`serializers.py:426,451-453`), même pattern | `AdvanceForm.vue` (formulaire partagé fournisseur/transporteur) |
| Apport en capital (Contributions associés/actionnaires) | `ShareholderContributionSerializer.validate()` (`serializers.py:1174,1203-1205`) **et** `ShareholderContributionService.record_contribution` (`services.py:1716-1719`) — double enforcement | `ContributionForm.vue` : `validate()` (~120), gate submit (~128), `required` (~233) |

Déjà optionnels (rien à changer) : paiement client (`CustomerPaymentSerializer.proof`), dépenses générales/frais trajet (`ExpenseSerializer`), contrôle de quantité livraison (`DeliveryControlRequestSerializer.document`), retrait associé (`ShareholderWithdrawalSerializer`), annulations/contrepassations (`TripCancellationService`), factures/ventes (pas de champ document).

### Correction

- Backend : supprimer les 4 blocs `validate()`/`validate_attachment` listés ci-dessus qui rejettent l'absence de justificatif (`attachment`/`document` déjà `required=False` au niveau champ dans les 4 cas — seule la logique `validate()` impose le caractère obligatoire). Pour `ShareholderContributionService.record_contribution` : la création du `Document` devient conditionnelle (`if attachment: document = Document.objects.create(...)` sinon `document = None`) — `ShareholderContribution.document` est déjà `null=True, blank=True` en base (`models.py:1106-1107`), seule la couche service l'empêchait.
- Frontend : dans `DebtPaymentForm.vue`, `AdvanceForm.vue`, `ContributionForm.vue` — retirer le bloc `if (!attachment.value) { ...; return false }` de `validate()`, retirer `|| !attachment.value` du garde de soumission, retirer l'attribut `required` de l'`<input type="file">`, et étiqueter le champ "(optionnel)". Garder intacte la validation de type/taille déjà en place (`onAttachmentChange`/`validate_image_upload`).

---

## Risques résiduels à surveiller en implémentation

- Section 2 : vérifier qu'aucun autre code ne suppose `DeliveryControl.received_quantity` figé après création (recherche `delivery_control` côté backend/frontend avant de merger).
- Section 3/4 : `WorkingCapitalService` duplique des requêtes déjà faites dans `DashboardViewSet.summary()` — accepté comme compromis simplicité/isolation, à surveiller si le dashboard devient lent.
- Section 5 : limite RTL/Arabic du PDF à documenter clairement dans le rapport de tâche, pas seulement dans le code — le client a explicitement pré-approuvé cette limite si non résolvable proprement en petite correction.
- Section 6 : après suppression de la contrainte "obligatoire" sur l'apport en capital, vérifier qu'aucun test existant du chantier précédent (`backend/apps/finance/test_contributions.py`) ne dépend encore de ce comportement — ces tests devront être mis à jour, pas juste les nouveaux.

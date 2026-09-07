# La facture client reflète la quantité reçue (2026-09-07)

Date: 2026-09-07
Statut: Décisions validées avec l'utilisateur une par une (brainstorming + maquettes). Prêt pour plan d'implémentation.

## Contexte

Chantier issu de la recette client, en deux temps :

- **Point 1 (déjà livré, session courante)** : la ligne « Perte supportée par l'entreprise » (`total_company_absorbed_loss`) était soustraite de `distributable_result` sans aucune ligne visible → rendue visible sur la page Bénéfices, le tableau de bord et le PDF. **Ce point est partiellement défait par le présent chantier** (section 3) : une fois la facture basée sur la quantité reçue, ce terme n'a plus lieu d'être.
- **Point 2 (ce document)** : le client doit payer **la quantité qu'il a réellement reçue**, pas la quantité chargée. Aujourd'hui la facture est figée à la quantité chargée et l'écart est absorbé via un terme correctif dans la marge et dans le distribuable.

### Ce que fait le code aujourd'hui

- `DeliveryControlForm.vue` ne collecte plus la quantité reçue (simplification `2026-09-04-recette-corrections`). `DeliveryService.record_delivery` la fait défaut à `trip.quantity_loaded` → `Sale.delivered_quantity = quantity_loaded`, `Invoice.total_amount = quantity_loaded × prix`.
- La quantité réelle est saisie **plus tard** via `DeliveryService.record_client_verification` (bouton « Vérification client / Déclarer une perte ») : met à jour `DeliveryControl.received_quantity` / `loss_quantity` / `chargeable_loss_quantity`, resynchronise la `TransportDeduction`, clôture le trajet — **ne touche jamais `Sale`/`Invoice`** (invariant « Delivered Quantity is Commercial Truth », `apps/sales/models.py:68`, posé le `2026-09-04`).
- `TripProfitService.get_cost_breakdown` : `margin = revenue + transporter_loss_indemnity − company_absorbed_loss_amount − real_total_cost`, avec `revenue = sale.delivered_quantity × unit_selling_price`.
- `ShareholderProfitPreviewService.get_preview` : `distributable_result = working_capital.total − dettes − capital − total_company_absorbed_loss`.

### Incohérence existante trouvée en investigation

Le terme `− company_absorbed_loss_amount` de la marge n'est **correct que si `Sale.delivered_quantity` = quantité chargée** (cas du flux UI en 2 étapes). Quand `record_delivery` reçoit directement une quantité reçue réduite (ce que font plusieurs tests, ex. `test_production_like_scenario.py` : `Sale.delivered_quantity = 44 850`), le `revenue` est déjà réduit **et** le terme est soustrait une 2ᵉ fois → **double comptage** (marge `4 320 000` au lieu de `4 410 000` dans ce scénario). Le présent chantier supprime le terme et lève cette incohérence.

### Règles transverses (inchangées)

- Ne pas réécrire le moteur de coût trajet (`TripCostService`) ni la partie coûts de `TripProfitService`.
- Mouvements financiers auditables : toute correction d'une facture validée écrit une ligne `InvoiceCorrection`.
- Pas de refonte UI large — colonnes/lignes ajoutées aux écrans existants.
- La `TransportDeduction` (perte facturable au transporteur, valorisée au prix de vente client) est **indépendante** de la facturation client → inchangée.
- Le `SaleBelowCostConfirmationRequired` (prix de vente unitaire vs prix de revient unitaire) est une comparaison au litre → inchangé.
- Fond de roulement / avances fournisseur-transporteur / trésorerie : inchangés.

---

## 1. La vérification client propage la quantité reçue à la facture

### Règle métier

Quand `record_client_verification` enregistre une quantité reçue différente de celle déjà facturée, la `Sale` et l'`Invoice` sont mises à jour pour refléter la quantité reçue, selon l'état de la facture :

| État de la facture | Comportement |
|---|---|
| `DRAFT` | `Sale.delivered_quantity` et `Invoice.total_amount` modifiés directement (données jamais figées, aucune trace nécessaire). |
| `VALIDATED` (non payée) | Correction auditée : `Sale.delivered_quantity` + `Invoice.total_amount` modifiés **et** une ligne `InvoiceCorrection` écrite (motif auto : « Vérification client : quantité reçue corrigée de {ancienne} L à {nouvelle} L »). Aucun mouvement de trésorerie. |
| `PARTIALLY_PAID` ou `PAID` | **La vérification est refusée** : `ValueError` « La facture {num} est déjà encaissée ; la correction d'une facture payée n'est pas prise en charge automatiquement. » Le trajet reste `DELIVERED`, aucune donnée modifiée. |
| `CANCELLED` | Idem refus (cas dégénéré). |

Si `received_qty == Sale.delivered_quantity` (aucun changement de quantité — ex. l'utilisateur a déjà corrigé la facture à la main, ou reçu = chargé), la vérification procède sans toucher la facture, exactement comme aujourd'hui.

### Implémentation

**Nouvelle méthode `InvoiceService.adjust_delivered_quantity(invoice_id, new_quantity, *, reason, actor)`** (`apps/sales/services.py`) — propriétaire unique de la mutation de `Sale.delivered_quantity` :

```
- charge Sale + Invoice sous verrou (select_for_update)
- si new_quantity == sale.delivered_quantity : no-op, retourne l'invoice
- si invoice.status == DRAFT :
    sale.delivered_quantity = new_quantity ; sale.save()  # recalcule subtotal
    invoice.total_amount = sale.subtotal ; invoice.save()
- si invoice.status == VALIDATED :
    idem + InvoiceCorrection.objects.create(field_name="delivered_quantity",
        previous_value=<ancienne>, new_value=<nouvelle>, reason=reason, corrected_by=actor)
- si invoice.status in (PARTIALLY_PAID, PAID, CANCELLED) :
    raise InvoicePaidCorrectionUnsupported(...)  # nouvelle sous-classe de ValueError
```

**`DeliveryService.record_client_verification`** (`apps/trips/services.py`) : entre la mise à jour du `DeliveryControl` et `sync_transport_shortage_deduction`, ajouter :

```
sale = getattr(trip, "sale", None)
if sale is not None and received_qty != sale.delivered_quantity:
    InvoiceService.adjust_delivered_quantity(
        sale.invoice.id, received_qty,
        reason=f"Vérification client : quantité reçue corrigée de {sale.delivered_quantity} L à {received_qty} L",
        actor=actor,
    )
    sale.refresh_from_db()
```

L'`InvoicePaidCorrectionUnsupported` remonte telle quelle (la transaction `@transaction.atomic` de `record_client_verification` annule tout). La vue `TripViewSet.client_verification` la mappe déjà en 400 (`except ValueError`).

Ordre dans la transaction : `DeliveryControl` sauvé → **facture ajustée** → `sync_transport_shortage_deduction` (qui lit `sale.unit_selling_price`, inchangé — seule la quantité bouge) → clôture trajet. Tout ou rien.

### Correction manuelle d'une facture `VALIDATED` (cas « reçu = chargé » puis client conteste plus tard, ou saisie initiale erronée)

`InvoiceService.correct_invoice` (`apps/sales/services.py`) gagne une branche `field == "delivered_quantity"` : identique à la branche `unit_selling_price` (écrit `sale.delivered_quantity`, `sale.save()`, `invoice.total_amount = sale.subtotal`, `InvoiceCorrection`). Reste `VALIDATED`-only comme aujourd'hui.

Frontend : `CORRECTABLE_INVOICE_FIELDS` (`apps/../sales/types.ts`) → `['unit_selling_price', 'total_amount', 'delivered_quantity']`. Le `<select>` du formulaire de correction (`InvoiceDetail.vue`) affiche déjà `{{ f }}` brut — ajouter un libellé i18n `sales.invoiceDetail.correctionFields.*` pour les 3 (`Prix de vente unitaire` / `Montant total` / `Quantité livrée`).

### Cohérence `DeliveryControl` ↔ `Sale`

Après ce chantier, `Sale.delivered_quantity` suit `DeliveryControl.received_quantity` dans le flux normal (les 2 étapes). Le seul chemin qui peut les désynchroniser est une `correct_invoice` manuelle sur `delivered_quantity` sans re-vérification — accepté : la facture est la vérité commerciale, `DeliveryControl` reste la trace opérationnelle du contrôle physique. Aucune assertion d'égalité stricte entre les deux n'est ajoutée.

---

## 2. Marge du trajet : retirer le terme correctif

### Règle métier

`revenue` étant désormais toujours basé sur la quantité **reçue/facturée**, la perte supportée par l'entreprise est déjà reflétée par un `revenue` plus bas (démontré en maquette : marge trajet-avec-perte = trajet-sans-perte − `company_absorbed_loss_amount`). Le terme explicite devient un **double comptage** → supprimé de la formule. Le montant reste **calculé et exposé** pour l'affichage.

### Implémentation

`TripProfitService.get_cost_breakdown` (`apps/reports/services/profit.py`) :

```
margin = (revenue + transporter_loss_indemnity - real_total_cost).quantize(...)
```

(retrait de `- company_absorbed_loss_amount`). Les clés `company_absorbed_loss_quantity` / `company_absorbed_loss_amount` restent dans le dict retourné (affichage). Mettre à jour le docstring `2026-09-04` de la méthode.

`MarginReportQuery` (`apps/reports/queries/margin_report.py`) : `current_margin` vient de `calculate_current_margin` → `get_cost_breakdown["margin"]`, se met à jour tout seul. Les colonnes `company_absorbed_loss_*` du rapport restent exposées.

### Affichage — bloc « RENTABILITÉ DU TRAJET » (`TripDetail.vue`) — Version A

- « Chiffre d'affaires » : inchangé dans le code (déjà `margin.revenue`), affiche désormais le montant à la quantité reçue.
- Ligne « Perte supportée par l'entreprise » (`data-test="company-absorbed-loss-row"`) : reste affichée quand `company_absorbed_loss_amount > 0`, mais **restylée en information** — retirer la classe `text-critique`, la mettre en `text-texte-3` (grisé), et ajouter un badge/mention « information » à côté du libellé (clé i18n `trips.detail.companyAbsorbedLossInfoNote`). Elle n'est déjà pas un `<dt>/<dd>` sommé — aucune ligne de total à recalculer.
- « MARGE NETTE » : inchangée dans le template (`margin.margin`), reflète la nouvelle formule.

---

## 3. Résultat distribuable : retirer le terme + défaire l'affichage du point 1

### Règle métier

La trésorerie encaisse désormais le montant facturé réel (quantité reçue). `distributable_result = trésorerie + créances − dettes − capital` réconcilie seul, sans terme « perte supportée ».

### Implémentation backend

`ShareholderProfitPreviewService.get_preview` (`apps/finance/services.py`) :

- `distributable_result` : retirer `- total_company_absorbed_loss`.
- `total_company_absorbed_loss` : **conserver le calcul et la clé** dans le dict retourné (toujours affiché sur le détail trajet ; utile en transition pour les anciennes factures non corrigées ; le supprimer casserait `profit_pdf` et le type frontend sans gain).
- Supprimer les gros commentaires « Bug fix recette critique 2026-09-06 » devenus faux ; les remplacer par une note courte expliquant que le terme a été retiré le 2026-09-07 quand la facture est passée à la quantité reçue.

`apps/reports/views/dashboard.py` : `shareholders_summary["total_company_absorbed_loss"]` — **conserver** (déjà ajouté au point 1, sert encore au détail ; ne plus l'afficher côté dashboard, cf. ci-dessous).

### Implémentation frontend — défaire l'affichage ajouté au point 1

- `ProfitView.vue` : supprimer la carte `data-test="profit-company-absorbed-loss-card"` de la section DISTRIBUTION.
- `DashboardView.vue` : supprimer la ligne `data-test="working-capital-company-absorbed-loss"` du bloc FOND DE ROULEMENT et la ligne « perte supportée » de la section actionnaires.
- `profit_pdf.py` : retirer la ligne `companyAbsorbedLoss` de `wc_rows` (revenir aux index de gras `(2, 9, 10, 12)`). Garder la clé de label (inoffensive) ou la retirer.
- Les clés i18n `dashboard.final.companyAbsorbedLoss` / `finance.profit.companyAbsorbedLoss` peuvent rester (inoffensives) ou être retirées — au choix de l'implémenteur.
- `ShareholderProfitPreview` / dashboard `types.ts` : `total_company_absorbed_loss` **reste** (toujours renvoyé par l'API, encore consommé par le détail trajet indirectement — en réalité le détail trajet lit `fetchTripMargin`, pas le preview ; donc le champ devient non-consommé côté preview mais on le garde pour ne pas diverger du backend). *Ruling implémenteur : garder le champ typé, ne pas l'afficher.*

---

## 4. Grand livre client : colonnes « Qté chargée » et « Qté reçue »

### Règle métier

Le tableau « FACTURES » du compte client affiche, par facture, la quantité chargée et la quantité reçue/facturée, pour visualiser l'écart.

### Implémentation

**Backend** — exposer la quantité chargée sur la représentation de la vente :

- `SaleSerializer` (`apps/sales/serializers.py`) : ajouter un champ `quantity_loaded = serializers.DecimalField(source="trip.quantity_loaded", ...)` (lecture seule). `delivered_quantity` y est déjà.
- `CustomersViewSet.ledger` (`apps/customers/views.py`) : `InvoiceSerializer` inclut déjà `sale_detail` → `quantity_loaded` + `delivered_quantity` arrivent automatiquement dans chaque ligne `invoices[]`. Rien d'autre à changer sur l'endpoint JSON.
- `CustomersViewSet.ledger_pdf` : la section `invoices_section` (dict par facture) gagne `quantity_loaded` et `delivered_quantity` (lus depuis `invoice.sale.trip.quantity_loaded` / `invoice.sale.delivered_quantity`). `render_ledger_pdf` rend `extra_sections` de façon générique (une colonne par clé) → les 2 colonnes apparaissent sans changement du moteur PDF ; ajouter les libellés dans `get_ledger_pdf_labels`.

**Frontend** — `CustomerLedgerView.vue`, tableau `finance.customerLedger.invoices` :

- 2 nouvelles colonnes après « Émise » : `finance.customerLedger.table.loadedQuantity` (« Qté chargée ») et `finance.customerLedger.table.receivedQuantity` (« Qté reçue »), valeurs `formatQuantity(invoice.sale_detail?.quantity_loaded)` et `formatQuantity(invoice.sale_detail?.delivered_quantity)`, alignées à droite, police mono (`MonoValue`).
- `CustomerLedgerInvoice` (`types.ts`) : ajouter `sale_detail?: { quantity_loaded: string; delivered_quantity: string; ... }` (ou réutiliser le type `Sale` existant si `sale_detail` y est déjà typé — à vérifier).
- Le `colspan` de la ligne vide passe de 5 à 7.

---

## 5. Facture (écran de détail) : libellé exact + quantité chargée

### Implémentation

`InvoiceDetail.vue` :

- Le libellé `sales.invoiceDetail.deliveredQuantity` (« Quantité livrée (reçue, non chargée) ») devient **exact** — le garder tel quel, la valeur `sale_detail.delivered_quantity` est maintenant vraiment la quantité reçue.
- Ajouter un bloc « Quantité chargée » à côté (lecture seule, `formatQuantity(invoice.sale_detail?.quantity_loaded)`), clé i18n `sales.invoiceDetail.loadedQuantity`, pour visualiser l'écart directement sur la facture.

---

## Non-changements explicites

- **`CustomerOrderService.get_delivered_quantity`** (`apps/sales/services.py`) : continue d'utiliser `Trip.quantity_loaded`. Une commande client est « livrée » quand les camions ont été chargés pour elle ; une perte en transit ne rouvre pas la commande. Le statut de commande (`recompute_status`) est inchangé.
- **`DeliveryService.sync_transport_shortage_deduction`** : inchangé. Le transporteur reste redevable de la perte au-delà de la tolérance, valorisée au prix de vente client, indépendamment de la facture.
- **`record_delivery`** : inchangé. Crée toujours la `Sale`/`Invoice` à la quantité chargée (provisoire) puisque le formulaire de livraison ne collecte pas la quantité reçue. Seule `record_client_verification` ajuste.
- **`DeliveryControlForm.vue`** : inchangé (pas de réintroduction du champ « quantité reçue » — décision utilisateur : saisie à l'étape vérification).
- **Données existantes** : les factures déjà émises à la quantité chargée ne sont **pas** rétro-corrigées par migration. Correction au cas par cas via l'écran de correction si besoin. En base de recette, l'utilisateur re-teste avec des données neuves.
- **`Sale.delivered_quantity` `editable=False`** : le flag reste (protège l'admin Django / DRF ModelForm) ; l'affectation par `InvoiceService` en code n'est pas bloquée par ce flag.

---

## Impact tests

### Backend — à réécrire (prémisse changée)

- `apps/reports/tests.py::test_margin_subtracts_company_absorbed_loss` → renommer `test_margin_reflects_absorbed_loss_via_reduced_revenue` : après `record_client_verification`, `revenue` a baissé, `margin` == (trajet sans perte − `company_absorbed_loss_amount`), et `breakdown["company_absorbed_loss_amount"]` reste exposé (non nul) sans être un terme soustrait.
- `apps/reports/test_production_like_scenario.py` étape 11 : marge attendue `40 365 000 + 45 000 − 36 000 000 = 4 410 000` (au lieu de `4 320 000`). Étape 7 (facture = quantité reçue) : déjà correcte, inchangée.
- `apps/reports/test_queries.py::test_distributable_result_reconciles_to_net_profit_*` et `test_distributable_result_still_counts_company_absorbed_loss_after_same_day_distribution` : le distribuable ne soustrait plus le terme → réécrire pour vérifier `distributable_result == total − dettes − capital` (sans terme perte), et supprimer l'assertion `preview["distributable_result"] == explicit_preview["distributable_result"]` liée à l'ancien terme. `total_company_absorbed_loss` reste exposé dans le dict.
- `apps/reports/test_profit_pdf.py::test_render_profit_report_pdf_shows_company_absorbed_loss_row_when_nonzero` (ajouté au point 1) → supprimer ou inverser (la ligne n'est plus dans le PDF). Retirer la clé du fixture `_preview` si la clé de label PDF est retirée.
- `apps/reports/test_views.py` : l'assertion `"total_company_absorbed_loss" in summary` (point 1) reste valide (champ conservé).

### Backend — à ajouter

- `apps/trips/tests.py` : `record_client_verification` avec facture `DRAFT` → `Sale.delivered_quantity` + `Invoice.total_amount` réduits, pas de `InvoiceCorrection`.
- idem facture `VALIDATED` non payée → réduits + 1 `InvoiceCorrection` (`field_name="delivered_quantity"`, motif auto).
- idem facture `PAID` / `PARTIALLY_PAID` → `record_client_verification` lève 400, trajet reste `DELIVERED`, `Sale`/`Invoice` inchangés, pas de `DeliveryControl.verified_at`.
- `record_client_verification` avec `received_qty == delivered_quantity` → aucune écriture facture, comportement actuel.
- `apps/sales/tests.py` (ou `test_invoice*.py`) : `InvoiceService.adjust_delivered_quantity` les 3 branches ; `correct_invoice(field="delivered_quantity", ...)` sur `VALIDATED` → `Sale` + `Invoice` + `InvoiceCorrection`.
- `apps/customers/` : `ledger` JSON expose `sale_detail.quantity_loaded` ; `ledger_pdf` `invoices_section` a les 2 quantités.

### Frontend — à mettre à jour / ajouter

- `ProfitView.spec.ts` : retirer le test « profit-company-absorbed-loss-card » ajouté au point 1 ; retirer `total_company_absorbed_loss` des assertions d'affichage (garder dans le mock).
- `DashboardView.spec.ts` : retirer le test « working-capital-company-absorbed-loss » ajouté au point 1.
- `CustomerLedgerView.spec.ts` : nouvelles colonnes Qté chargée / Qté reçue rendues depuis `sale_detail`.
- `InvoiceDetail.spec.ts` : `delivered_quantity` correctable (option présente dans le `<select>`) ; bloc « Quantité chargée » affiché.
- `TripDetail.spec.ts` : ligne « Perte supportée » rendue en information (pas `text-critique`) quand `> 0`, absente sinon ; marge = formule sans le terme.

---

## Ordre d'implémentation (commits séparés)

1. **Backend cœur** — `InvoiceService.adjust_delivered_quantity` + `correct_invoice` branche `delivered_quantity` + `record_client_verification` propage. Tests backend sales + trips.
2. **Backend marge & distribuable** — retrait des 2 termes correctifs (`get_cost_breakdown`, `get_preview`), réécriture des tests reports concernés, `test_production_like_scenario`.
3. **Frontend défaire point 1** — retrait cartes/lignes `ProfitView` + `DashboardView` + `profit_pdf`, specs.
4. **Frontend facturation** — `SaleSerializer.quantity_loaded`, colonnes grand livre client (`CustomerLedgerView` + PDF), `InvoiceDetail` (libellé + qté chargée + champ correctible), specs.
5. **Frontend bloc trajet** — Version A : ligne « Perte supportée » en information dans `TripDetail.vue`, spec.

Vérification finale : suite backend complète (`--create-db`), suite frontend, `vue-tsc`, et re-génération du PDF Bénéfices + parcours navigateur si possible.

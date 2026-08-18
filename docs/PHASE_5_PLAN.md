# Plan d'Action Technique - Phase 5 : Invoicing, Supplier Deductions and Financial Settlement

Ce document présente le plan de développement détaillé pour la **Phase 5** de l'ERP Fuel Logistics. Cette phase est centrée sur tous les flux financiers : encaissements clients, paiements fournisseurs, règlements des transporteurs (avec gestion des avances et des déductions pour perte excessive), suivi des dépenses (incluant les paiements indirects par les clients), et gestion globale de la trésorerie (comptes bancaires et caisses).

---

## 1. Choix de Conception & Règles Métier Clés

### A. Rapprochement Financier Flexible (Pattern ERPNext)
- Séparation stricte entre l'enregistrement du paiement (`CustomerPayment`) et son imputation aux factures (`PaymentAllocation`).
- Support natif des cas suivants :
  - **Un paiement imputé à une facture unique** (1:1).
  - **Un paiement ventilé sur plusieurs factures** (1:N).
  - **Paiements partiels** (générant un solde restant dû/outstanding).
  - **Crédit non alloué** (paiement d'avance restant en solde créditeur sur le compte du client).

### B. Gestion des Paiements Indirects Clients (Spec §25)
- **Règle métier critique** : Lorsqu'un client paie directement une dépense opérationnelle de l'entreprise (ex: frais de douane), le système crée une dépense (`Expense`) marquée comme payée et un paiement client (`CustomerPayment`) marqué `is_indirect=True`, imputé via `PaymentAllocation` pour réduire la créance du client.
- **Règle de Trésorerie** : Ce flux **ne doit générer aucune transaction de trésorerie** (`TreasuryTransaction` = 0) car l'argent n'a jamais transité par les comptes bancaires ou caisses de l'entreprise.

### C. Déductions Automatiques Transporteurs (Spec §16)
- Le règlement du transporteur (`TransportPayment`) doit obligatoirement déduire :
  - Les déductions pour perte excessive calculées lors de la décharge en Phase 4 (`TransportDeduction` = Litres de perte chargeable $\times$ Prix de vente).
  - Les avances sur frais de route déjà versées (`TransporterAdvance`).
- Le calcul de l'encours net dû au transporteur est :
  $$\text{Net A Payer} = \text{Frais de Transport Brut} - \text{Déductions} - \text{Avances Appliquées}$$

### D. Centralisation de la Trésorerie (Spec §29)
- Les soldes courants de trésorerie (`BankAccount.current_balance` et `CashAccount.current_balance`) sont calculés à la volée en agrégeant les transactions de trésorerie (`TreasuryTransaction`). Ils ne sont jamais stockés en dur pour éviter les dérives.
- Un transfert interne d'un compte à un autre génère **exactement deux transactions de trésorerie** (`MONEY_OUT` sur la source, `MONEY_IN` sur la destination) marquées `type=TRANSFER`. Ces transactions doivent être explicitement exclues du calcul des bénéfices/pertes de l'entreprise.

---

## 2. Plan d'Action Détaillé et Séquentiel

### Étape 1 : Modèles de Paiements & Allocations Clients (`apps.finance`)
- [ ] **Définir le modèle `CustomerPayment`** dans `backend/apps/finance/models.py` :
  - `customer` (ForeignKey vers `customers.Customer`, `on_delete=models.PROTECT`)
  - `amount` (DecimalField, `max_digits=16`, `decimal_places=2`)
  - `payment_date` (DateField)
  - `method` (CharField, choix: `CASH`, `BANK_TRANSFER`, `CHEQUE`, `OTHER`)
  - `account` (ForeignKey vers `BankAccount` ou `CashAccount` via GenericRelation ou nullable FKs distincts, nullable=True - obligatoire sauf si `is_indirect=True`)
  - `reference` (CharField, max_length=100)
  - `is_indirect` (BooleanField, default=False)
  - `recorded_by` (ForeignKey vers `accounts.User`)
  - Hérite de `TimeStampedModel`.
- [ ] **Définir le modèle `PaymentAllocation`** dans `backend/apps/finance/models.py` :
  - `payment` (ForeignKey vers `CustomerPayment`, `on_delete=models.CASCADE`, related_name='allocations')
  - `invoice` (ForeignKey vers `sales.Invoice`, `on_delete=models.PROTECT`, related_name='allocations', nullable=True) - nul signifie appliqué en crédit général sur le compte client.
  - `amount` (DecimalField, `max_digits=16`, `decimal_places=2`)
  - Contrainte : La somme des allocations d'un paiement ne doit pas dépasser le montant total du paiement.
- [ ] **Créer et exécuter la migration** pour ces modèles clients.

### Étape 2 : Modèles de Paiements Fournisseurs (`apps.finance`)
- [ ] **Définir le modèle `SupplierPayment`** dans `backend/apps/finance/models.py` :
  - `supplier` (ForeignKey vers `suppliers.Supplier`, `on_delete=models.PROTECT`)
  - `supplier_order` (ForeignKey vers `purchasing.SupplierOrder`, `on_delete=models.PROTECT`, nullable=True) - nul pour acomptes généraux/avances.
  - `amount` (DecimalField, `max_digits=16`, `decimal_places=2`)
  - `payment_date` (DateField)
  - `method` (CharField, choix: `CASH`, `BANK_TRANSFER`, `CHEQUE`, `OTHER`)
  - `account` (ForeignKey vers un compte de trésorerie, `on_delete=models.PROTECT`)
  - `is_advance` (BooleanField, default=False)
  - `reference` (CharField, max_length=100)
  - `recorded_by` (ForeignKey vers `accounts.User`)
  - Hérite de `TimeStampedModel`.
- [ ] **Créer et exécuter la migration** pour les paiements fournisseurs.

### Étape 3 : Avances et Règlements Transporteurs (`apps.finance`)
- [ ] **Définir le modèle `TransporterAdvance`** dans `backend/apps/finance/models.py` :
  - `transporter` (ForeignKey vers `transport.Transporter`, `on_delete=models.PROTECT`)
  - `amount` (DecimalField, `max_digits=16`, `decimal_places=2`)
  - `date` (DateField)
  - `reference` (CharField, max_length=100, blank=True)
  - `notes` (TextField, blank=True)
  - `settled` (BooleanField, default=False) - passe à True une fois imputé sur un paiement de trajet.
  - Hérite de `TimeStampedModel`.
- [ ] **Définir le modèle `TransportPayment`** dans `backend/apps/finance/models.py` :
  - `trip` (ForeignKey vers `trips.Trip`, `on_delete=models.PROTECT`, related_name='transport_payments')
  - `transporter` (ForeignKey vers `transport.Transporter`, `on_delete=models.PROTECT`)
  - `calculation_method` (CharField, choix: `FIXED`, `PER_LITRE`, `PER_DAY`, `NEGOTIATED`)
  - `base_amount` (DecimalField, `max_digits=16`, `decimal_places=2`) - coût brut du transport.
  - `deduction_amount` (DecimalField, `max_digits=16`, `decimal_places=2`, default=0) - extrait de la `TransportDeduction` associée au trajet.
  - `advance_applied` (ForeignKey vers `TransporterAdvance`, `on_delete=models.SET_NULL`, nullable=True)
  - `net_amount` (DecimalField, `max_digits=16`, `decimal_places=2`, editable=False) - calculé automatiquement : base_amount - deduction_amount - advance.amount.
  - `status` (CharField, choix: `PLANNED`, `PAYABLE`, `PARTIALLY_PAID`, `PAID`, `DEDUCTION_APPLIED`, default=`PLANNED`)
- [ ] **Créer et exécuter la migration** pour les modèles de transporteurs.

### Étape 4 : Gestion des Dépenses & Allocations (`apps.finance`)
- [ ] **Définir le modèle `Expense`** dans `backend/apps/finance/models.py` :
  - `category` (CharField, choix: `customs`, `import_intention`, `transport`, `loading`, `unloading`, `road`, `administration`, `rent`, `salary`, `repairs`, `bank_charges`, `other`)
  - `amount` (DecimalField, `max_digits=16`, `decimal_places=2`)
  - `calculation_method` (CharField, choix: `FIXED`, `PER_LITRE`, `PERCENTAGE`, `PER_ORDER`, `PER_TRUCK`, `MANUAL`)
  - `date` (DateField)
  - `status` (CharField, choix: `UNPAID`, `PARTIALLY_PAID`, `PAID`, `CANCELLED`, default=`UNPAID`)
  - `paid_by_customer_directly` (BooleanField, default=False) - indicateur de paiement indirect.
  - `notes` (TextField, blank=True)
- [ ] **Définir le modèle `ExpenseAllocation`** dans `backend/apps/finance/models.py` :
  - `expense` (ForeignKey vers `Expense`, `on_delete=models.CASCADE`, related_name='allocations')
  - `content_type` (ForeignKey vers `ContentType`, `on_delete=models.CASCADE`, nullable=True)
  - `object_id` (PositiveIntegerField, nullable=True)
  - `content_object` (GenericForeignKey, pour lier à `Trip`, `Truck`, `Customer`, `SupplierOrder`, etc.)
  - `allocated_amount` (DecimalField, `max_digits=16`, `decimal_places=2`)
- [ ] **Créer et exécuter la migration** pour les dépenses.

### Étape 5 : Transactions de Trésorerie (`apps.finance`)
- [ ] **Définir le modèle `TreasuryTransaction`** dans `backend/apps/finance/models.py` :
  - `bank_account` (ForeignKey vers `BankAccount`, `on_delete=models.PROTECT`, nullable=True)
  - `cash_account` (ForeignKey vers `CashAccount`, `on_delete=models.PROTECT`, nullable=True)
  - `type` (CharField, choix: `MONEY_IN`, `MONEY_OUT`, `TRANSFER`)
  - `amount` (DecimalField, `max_digits=16`, `decimal_places=2`)
  - `date` (DateField)
  - `reference` (CharField, max_length=100)
  - `source_content_type` (ForeignKey vers `ContentType`, `on_delete=models.CASCADE`, nullable=True)
  - `source_object_id` (PositiveIntegerField, nullable=True)
  - `source_object` (GenericForeignKey, pointe vers le paiement ou la dépense d'origine)
  - `document` (ForeignKey vers `documents.Document`, `on_delete=models.SET_NULL`, nullable=True)
  - `recorded_by` (ForeignKey vers `accounts.User`)
  - Ajouter une contrainte BDD `CheckConstraint` s'assurant que soit `bank_account` soit `cash_account` est renseigné (exclusivement un seul des deux).
- [ ] **Créer et exécuter la migration** pour `TreasuryTransaction`.

### Étape 6 : Services Métier Financiers (Services du Domaine)
- [ ] **Créer `PaymentAllocationService`** dans `backend/apps/finance/services.py` :
  - Méthode `allocate_payment(payment_id, invoice_allocations_list)` sous verrou `select_for_update` sur `CustomerPayment`. Valider que la somme des allocations ne dépasse pas le paiement. Ajuster le statut des factures (`VALIDATED` -> `PARTIALLY_PAID` -> `PAID`).
  - Méthode `get_invoice_outstanding(invoice)` : Calcul dynamique $\text{Total Facture} - \sum(\text{Allocations})$.
  - Méthode `get_customer_outstanding(customer)` : Calcul dynamique du solde débiteur global.
- [ ] **Créer `IndirectSettlementService`** dans `backend/apps/finance/services.py` :
  - Méthode `record_indirect_payment(customer_id, expense_data, invoice_id=None)` :
    1. Créer et valider l'entité `Expense` (status=`PAID`, `paid_by_customer_directly=True`).
    2. Créer `CustomerPayment` (`is_indirect=True`, `account=None`).
    3. Créer `PaymentAllocation` liée à la facture ou au solde client.
    4. **S'assurer de ne créer aucune TreasuryTransaction**.
- [ ] **Créer `TreasuryService`** dans `backend/apps/finance/services.py` :
  - Méthode `record_transfer(source_account_type, source_account_id, dest_account_type, dest_account_id, amount, date, reference, user)` :
    - Générer une transaction `MONEY_OUT` de type `TRANSFER` sur le compte source.
    - Générer une transaction `MONEY_IN` de type `TRANSFER` sur le compte de destination.
    - Les encapsuler dans un bloc transactionnel atomique avec verrouillage des comptes.

### Étape 7 : Sérialiseurs et Validations DRF
- [ ] **Définir les sérialiseurs** dans `backend/apps/finance/serializers.py` :
  - `CustomerPaymentSerializer` (avec liste d'allocations imbriquée).
  - `SupplierPaymentSerializer`.
  - `TransportPaymentSerializer`.
  - `TransporterAdvanceSerializer`.
  - `ExpenseSerializer` et `ExpenseAllocationSerializer`.
  - `TreasuryTransactionSerializer`.
- [ ] **Ajouter des validations strictes** :
  - Rejeter tout paiement client si la caisse/compte est invalide et qu'il ne s'agit pas d'un paiement indirect.
  - Interdire les transferts vers le même compte.

### Étape 8 : API Views & Ledger Fournisseur/Client/Transporteur
- [ ] **Ajouter les ViewSets et Endpoints** associés dans `backend/apps/finance/views.py` :
  - `/api/customer-payments/`
  - `/api/supplier-payments/`
  - `/api/transport-payments/`
  - `/api/transporter-advances/`
  - `/api/expenses/`
  - `/api/treasury-transactions/`
  - `/api/treasury-transactions/transfer/` (Endpoint dédié au transfert interne)
- [ ] **Implémenter les actions de Ledgers détaillés** :
  - Mettre à jour `/api/customers/{id}/ledger/` pour renvoyer la balance de compte client, la liste des factures et l'état des paiements.
  - Mettre à jour `/api/suppliers/{id}/ledger/` (achats + acomptes/avances fournisseurs).
  - Créer `/api/transporters/{id}/ledger/` retournant la décomposition exacte : Frais bruts gagnés $-$ Déductions $-$ Avances $-$ Règlements $=$ Encours net à payer.

### Étape 9 : Tests d'Intégration & de Recette (Backend)
- [ ] **Créer le fichier de tests** `backend/apps/finance/tests.py` :
  - **Test Facturation Partielle (§22)** : Facturer 40 000 000 XOF, recevoir deux paiements de 10M et 15M, valider que le solde restant dû (outstanding) est exactement de 15 000 000 XOF.
  - **Test Allocation Multiple** : Allouer un paiement unique de 20M sur deux factures de 8M et 12M et s'assurer que les deux factures passent au statut `PAID`.
  - **Test Paiement Indirect Client (§25)** : Enregistrer une dépense de 5M payée par un client débiteur de 50M. Valider que la dépense est enregistrée comme payée, la dette du client réduite à 45M, et **s'assurer qu'aucune ligne n'a été insérée dans la table des transactions de trésorerie**.
  - **Test Rapprochement Transporteur (§16/§31)** : Trajet générant 700 000 XOF de frais brut. Perte de 50 L $\times$ 850 FCFA = 42 500 XOF de déduction. Avance appliquée de 100 000 XOF. Valider que le net à payer est égal à 557 500 XOF.
  - **Test Transfert de Trésorerie** : Effectuer un transfert de 10M de la Banque vers la Caisse. Valider l'insertion des deux transactions de type `TRANSFER` et leur exclusion des rapports financiers.

---

## 3. Plan d'Action Interface Frontend (Vue 3)

### Étape 10 : Configuration Frontend, Routes et Composants
- [ ] **Ajouter les routes de la Phase 5** dans `frontend/src/router/index.ts` :
  - `/customer-payments/new` -> `CustomerPaymentForm.vue`
  - `/expenses/new` -> `ExpenseForm.vue`
  - `/treasury/transactions` -> `TreasuryLedgerView.vue`
  - `/treasury/transfer` -> `TransferForm.vue`
  - `/transporters/:id/ledger` -> `TransporterLedgerView.vue`
- [ ] **Créer les Composants Vue 3** dans `frontend/src/modules/finance/` :
  - **`PaymentAllocationForm.vue`** : Sélection du client, affichage dynamique de ses factures non soldées, et saisie des montants à imputer par ligne.
  - **`ExpenseForm.vue`** : Catégorie, méthode de calcul, et sélecteur d'imputation. Intégrer l'interrupteur "Payé directement par le client" qui désactive et masque le champ de sélection du compte de trésorerie.
  - **`TreasuryLedgerView.vue` & `TransferForm.vue`** : Visualisation du journal de trésorerie globale et formulaire d'exécution de transfert de fonds.
  - **`TransporterLedgerView.vue`** : Tableau de bord récapitulant les gains bruts, les déductions pour perte, les avances consommées, et le montant net à payer avec statut de règlement.
- [ ] **Intégrer les liens** dans `AppShell.vue` sous le module `finance`.

---

## 4. Scénario de Recette Manuel (Validation Finale)

1. **Paiement Partiel** : Créer une facture client de **40 000 000 XOF**. Enregistrer un encaissement de **10 000 000 XOF**. Valider que le statut de la facture passe à `PARTIALLY_PAID` et que l'encours restant affiche **30 000 000 XOF**.
2. **Paiement Multi-Factures** : Créer deux factures (15M et 5M). Enregistrer un paiement de **20 000 000 XOF** et le ventiler sur les deux factures. Constater que les deux factures passent au statut `PAID`.
3. **Paiement Indirect** : Saisir des frais administratifs de **5 000 000 XOF** payés par un client. Activer l'interrupteur "Payé directement par le client". Valider la dépense.
   - Constater que la dette du client diminue de 5M.
   - Constater que le solde de la trésorerie générale reste inchangé.
4. **Calcul Net Transporteur** : Sur un trajet complété, affecter une avance de frais de route de **150 000 XOF** et appliquer une déduction pour perte. Vérifier que la fiche de paie du transporteur déduit bien ces montants du brut de transport pour générer le net à payer.
5. **Virement Interne** : Transférer **5 000 000 XOF** du compte banque vers la caisse. Constater le débit en banque, le crédit en caisse, et le statut neutre de la transaction de transfert.

# Client Modifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the French client requests in `docs/notes-et-demandes-client-modifications-application.md` while preserving the existing ERP invariants: trip workflow, dynamic ledgers, treasury journal, and computed profit.

**Architecture:** Keep formulas in backend services, not Vue components or serializers. Extend existing Django apps where the domain already lives: trips remain the loading/workflow source, finance owns payments/treasury/debts/shareholders, reports owns dashboard aggregates and profit reporting, and Vue only displays API results and submits explicit user choices.

**Tech Stack:** Django + Django REST Framework + PostgreSQL, Vue 3 + TypeScript + vue-i18n, pytest, Vitest.

**Spec:** `docs/notes-et-demandes-client-modifications-application.md`

## Global Constraints

- Do not rewrite or replace the existing Trip/CustomerOrder/Sale/Invoice workflow.
- Do not store duplicated balances that can drift; compute from SupplierOrder, Invoice, PaymentAllocation, TransportPayment, Expense, TreasuryTransaction, and shareholder ledger rows.
- Use `DecimalField` for all money/litre values; never use float.
- Every money movement that enters or leaves company bank/cash must create one `TreasuryTransaction` linked back through `source_content_type` and `source_object_id`.
- Internal transfers remain `is_transfer=True` and must not affect profit.
- Customer indirect payments keep the existing rule: no treasury transaction.
- Supplier debt payment requested by the client must use `BANK_TRANSFER` and a `BankAccount`; no cash supplier settlement for that flow.
- Transport cost per litre must create or update a transporter payable line tied to the trip/transporter.
- Profit and cost breakdown must be delegated to `TripProfitService`.
- Dashboard financial totals must come from backend aggregates, not frontend loops over paginated records.
- Add indexes for new foreign keys and filtered reporting fields used by dashboard/report queries.
- Add backend tests before implementation for every financial rule.
- Update frontend TypeScript types whenever serializer response shape changes.
- Update `fr`, `en`, and `ar` locale files for every visible label.

---

## Current App Logic To Preserve

- `Trip` is the physical loading/voyage record. It already allows `client = null` and `customer_order = null`.
- `DeliveryService.record_delivery()` creates `DeliveryControl`, `Sale`, and draft `Invoice` after the trip reaches delivery control.
- `CustomerOrderService` computes customer order quantities/status from related trips.
- `PaymentAllocationService` owns customer invoice outstanding and customer outstanding.
- `TreasuryTransaction` is the only source for bank/cash current balances.
- `TripProfitService` currently computes trip margin from fuel purchase cost, transport payments, and allocated expenses.
- Existing outstanding reports already compute customer, supplier, and transporter balances.
- `Document` is a generic attachment model, but currently only allows supplier orders and cession letters.
- No shareholder/associate domain exists yet.

## Files To Modify Or Create

Backend:
- Modify `backend/apps/trips/models.py`
- Modify `backend/apps/trips/serializers.py`
- Modify `backend/apps/trips/services.py`
- Modify `backend/apps/trips/views.py`
- Modify `backend/apps/trips/tests.py`
- Modify `backend/apps/finance/models.py`
- Modify `backend/apps/finance/serializers.py`
- Modify `backend/apps/finance/services.py`
- Modify `backend/apps/finance/views.py`
- Modify `backend/apps/finance/urls.py`
- Modify `backend/apps/finance/tests.py`
- Modify `backend/apps/reports/services/profit.py`
- Modify `backend/apps/reports/queries/margin_report.py`
- Modify `backend/apps/reports/views/dashboard.py`
- Modify `backend/apps/reports/test_views.py`
- Modify `backend/apps/reports/test_queries.py`
- Modify `backend/apps/documents/views.py`
- Modify `backend/apps/accounts/models.py`
- Create migrations in `backend/apps/trips/migrations/`, `backend/apps/finance/migrations/`, and `backend/apps/accounts/migrations/`.

Frontend:
- Modify `frontend/src/modules/trips/types.ts`
- Modify `frontend/src/modules/trips/api.ts`
- Modify `frontend/src/modules/trips/TripForm.vue`
- Modify `frontend/src/modules/trips/DeliveryControlForm.vue`
- Modify `frontend/src/modules/trips/TripDetail.vue`
- Modify `frontend/src/modules/finance/types.ts`
- Modify `frontend/src/modules/finance/api.ts`
- Modify `frontend/src/modules/finance/PaymentAllocationForm.vue`
- Modify `frontend/src/modules/finance/TreasuryLedgerView.vue`
- Modify `frontend/src/modules/dashboard/types.ts`
- Modify `frontend/src/modules/dashboard/DashboardView.vue`
- Modify `frontend/src/modules/shell/AppShell.vue`
- Modify `frontend/src/router/index.ts`
- Modify `frontend/src/locales/fr.json`
- Modify `frontend/src/locales/en.json`
- Modify `frontend/src/locales/ar.json`
- Create `frontend/src/modules/finance/ShareholderView.vue`
- Create focused frontend tests beside existing module tests where practical.

---

## Task 1: Backend Trip Cost Basis And Client Assignment

**Files:**
- Modify `backend/apps/trips/models.py`
- Modify `backend/apps/trips/serializers.py`
- Modify `backend/apps/trips/services.py`
- Modify `backend/apps/trips/views.py`
- Modify `backend/apps/trips/tests.py`
- Create migration `backend/apps/trips/migrations/0003_trip_cost_basis.py`

**Interfaces:**
- Produces `Trip.destination_type` with values `COMPANY_STOCK` and `CUSTOMER`.
- Produces `TripCostService.calculate_trip_cost_basis(trip) -> dict`.
- Produces `TripCostService.assign_customer_for_sale(trip_id, customer_id, actor) -> Trip`.
- Later tasks consume `cost_basis["unit_cost"]`, `cost_basis["total_cost"]`, and `cost_basis["expenses_by_category"]`.

- [ ] Add failing tests in `backend/apps/trips/tests.py`:
  - Creating a trip with no `client` and no `customer_order` succeeds and has `destination_type="COMPANY_STOCK"`.
  - Assigning a customer to a delivered/not-yet-sold trip changes `destination_type` to `CUSTOMER`.
  - Assigning a customer after a `Sale` exists is rejected.
  - `GET /api/trips/{id}/cost-basis/` returns fuel purchase cost, transport cost, allocated customs/transit/other expenses, total cost, quantity, and unit cost.

- [ ] Add model field:
  - `Trip.destination_type = models.CharField(max_length=20, choices=DestinationType.choices, default=DestinationType.COMPANY_STOCK)`
  - Add indexes for `destination_type`, `client`, `customer_order`, and `loading_date`.

- [ ] Update `TripSerializer`:
  - Include `destination_type`.
  - Keep `client` and `customer_order` optional.
  - Validate that a trip cannot have both `client` and `customer_order` pointing to different customers.
  - If `client` or `customer_order` is present, normalize `destination_type` to `CUSTOMER`; otherwise use `COMPANY_STOCK`.

- [ ] Create `TripCostService` in `backend/apps/trips/services.py`:
  - Fuel cost = `trip.quantity_loaded * trip.supplier_order.unit_price`.
  - Transport cost = sum `TransportPayment.base_amount` for the trip.
  - Additional expenses = sum `ExpenseAllocation.allocated_amount` for the trip, grouped by `Expense.category`, excluding cancelled expenses.
  - Total cost = fuel + transport + expenses.
  - Unit cost = total cost / `trip.quantity_loaded`.
  - Return Decimals and category breakdown without storing the result.

- [ ] Add `GET /api/trips/{id}/cost-basis/`.

- [ ] Add `POST /api/trips/{id}/assign-customer/` with body `{ "customer": <id> }`.

- [ ] Run backend verification:
  - `cd backend && pytest apps/trips/tests.py`
  - `cd backend && python manage.py makemigrations --check --dry-run`

---

## Task 2: Transporter Fees Per Litre Create Payable Debt

**Files:**
- Modify `backend/apps/finance/models.py`
- Modify `backend/apps/finance/serializers.py`
- Modify `backend/apps/finance/tests.py`
- Modify `frontend/src/modules/finance/types.ts`
- Modify the existing transport payment entry point

**Interfaces:**
- Consumes `Trip.quantity_loaded`.
- Produces `TransportPayment.unit_price_per_litre`.
- Produces serializer behavior where `calculation_method=PER_LITRE` and `unit_price_per_litre` automatically set `base_amount = trip.quantity_loaded * unit_price_per_litre`.

- [ ] Add failing backend tests:
  - Posting a `TransportPayment` with `calculation_method=PER_LITRE`, trip quantity `45000`, and `unit_price_per_litre=60` returns `base_amount=2700000.00`.
  - The row is linked to the selected transporter and appears in transporter outstanding when not `PAID`.
  - A transporter not matching the trip transporter is rejected.

- [ ] Add optional field `unit_price_per_litre = DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)` to `TransportPayment`.

- [ ] Update `TransportPaymentSerializer.validate()`:
  - If `calculation_method=PER_LITRE`, require `unit_price_per_litre`.
  - Force `transporter == trip.transporter`.
  - Compute `base_amount` from trip quantity and unit price inside serializer/service, not from user input.

- [ ] Preserve existing `TransportPayment.save()` net amount formula.

- [ ] Update frontend transport payment form:
  - Add transporter dropdown if missing at entry point.
  - Add price-per-litre input for `PER_LITRE`.
  - Display live calculation `quantity × price = total`.

- [ ] Run verification:
  - `cd backend && pytest apps/finance/tests.py -k "transport"`
  - `cd frontend && npm run test:unit -- --run`

---

## Task 3: Sales Price, Loss Warning, Benefit And Cost Basis In Delivery

**Files:**
- Modify `backend/apps/reports/services/profit.py`
- Modify `backend/apps/trips/views.py`
- Modify `backend/apps/trips/tests.py`
- Modify `frontend/src/modules/trips/api.ts`
- Modify `frontend/src/modules/trips/types.ts`
- Modify `frontend/src/modules/trips/DeliveryControlForm.vue`
- Modify `frontend/src/modules/trips/TripDetail.vue`

**Interfaces:**
- Consumes `TripCostService.calculate_trip_cost_basis()`.
- Produces `TripProfitService.get_cost_breakdown()` with `unit_cost`, `unit_profit`, and `profit`.
- Produces API margin/cost-basis values for Vue display.

- [ ] Add failing backend tests:
  - A trip with supplier cost, transport fee, customs expense, and sale price returns correct unit cost.
  - If selling price is less than unit cost, the delivery endpoint rejects unless `confirm_loss=true`.
  - If `confirm_loss=true`, the sale is created and current margin is negative.

- [ ] Extend `DeliveryControlRequestSerializer` with `confirm_loss = BooleanField(required=False, default=False)`.

- [ ] In `DeliveryService.record_delivery()`:
  - Before creating `Sale`, compute current unit cost using `TripCostService`.
  - If `unit_selling_price < unit_cost` and `confirm_loss` is false, raise `SaleBelowCostConfirmationRequired`.
  - If confirmed, continue and keep the negative margin visible.

- [ ] Update `TripProfitService.get_cost_breakdown()`:
  - Return `unit_cost = total_cost / trip.quantity_loaded`.
  - Return `unit_profit = sale.unit_selling_price - unit_cost`.
  - Keep `margin` as total revenue minus total cost.

- [ ] Update `DeliveryControlForm.vue`:
  - Fetch cost basis on mount.
  - Display price de revient per litre.
  - Display benefit per litre as user edits selling price.
  - Show a warning when price is below cost and require a confirmation checkbox before submit.
  - Send `confirm_loss=true` only after checkbox confirmation.

- [ ] Run verification:
  - `cd backend && pytest apps/trips/tests.py apps/reports/tests.py`
  - `cd frontend && npm run build`

---

## Task 4: Customer Payment Improvements And Evidence Image

**Files:**
- Modify `backend/apps/finance/models.py`
- Modify `backend/apps/finance/serializers.py`
- Modify `backend/apps/finance/services.py`
- Modify `backend/apps/finance/views.py`
- Modify `backend/apps/documents/views.py`
- Modify `backend/apps/finance/tests.py`
- Modify `frontend/src/modules/finance/types.ts`
- Modify `frontend/src/modules/finance/api.ts`
- Modify `frontend/src/modules/finance/PaymentAllocationForm.vue`

**Interfaces:**
- Produces `CustomerPayment.destination` with values `BANK`, `CASH`, `VERS_MOI`, `INDIRECT`.
- Produces `CustomerPayment.note`.
- Allows `Document(document_type="customer_payment_proof")` attached to `CustomerPayment`.
- Creates one `TreasuryTransaction(MONEY_IN)` for direct customer payments to bank/cash/Vers moi.

- [ ] Add failing backend tests:
  - Customer payment serializer exposes `note` and `destination`.
  - `destination=VERS_MOI` is accepted.
  - Direct bank/cash customer payment creates one linked `TreasuryTransaction(MONEY_IN)`.
  - Indirect customer payment still creates no treasury transaction.
  - Documents endpoint accepts `content_type_name=customerpayment` for payment proof upload.
  - Customer ledger returns `outstanding_balance` used by the payment form as “Total de la dette du Client”.

- [ ] Add fields:
  - `CustomerPayment.destination = CharField(max_length=20, choices=Destination.choices, default=Destination.CASH)`.
  - `CustomerPayment.note = TextField(blank=True)`.
  - Keep `reference` for external bank/cash references.

- [ ] Add `FinancePostingService.record_customer_payment_treasury(payment)`:
  - If `payment.is_indirect`, return `None`.
  - If bank account exists, create `MONEY_IN` on bank.
  - If cash account exists, create `MONEY_IN` on cash.
  - Recommended policy for `VERS_MOI`: map it to a dedicated cash account named `Vers moi`, because dashboard treasury must still account for the money.
  - Link transaction to `CustomerPayment` via content type/object id.
  - Prevent duplicate posting if a linked transaction already exists.

- [ ] Update `CustomerPaymentSerializer.create()`:
  - Wrap creation, allocations, and treasury posting in `transaction.atomic`.
  - Preserve existing allocation rules.

- [ ] Update `DocumentViewSet.ALLOWED_ATTACHMENT_MODELS` to include `("finance", "customerpayment")`.

- [ ] Update frontend:
  - Show selected customer's total outstanding balance above invoice allocation lines.
  - Add destination option “Vers moi”.
  - Add note textarea.
  - Add proof image upload after payment creation using `/api/documents/`.

- [ ] Run verification:
  - `cd backend && pytest apps/finance/tests.py`
  - `cd frontend && npm run build`

---

## Task 5: Supplier Debt Payment Must Use Bank Transfer And Update Treasury

**Files:**
- Modify `backend/apps/finance/serializers.py`
- Modify `backend/apps/finance/services.py`
- Modify `backend/apps/finance/views.py`
- Modify `backend/apps/finance/tests.py`
- Modify `frontend/src/modules/finance/types.ts`
- Modify existing supplier payment UI entry point

**Interfaces:**
- Consumes existing `SupplierPayment`.
- Produces one `TreasuryTransaction(MONEY_OUT)` linked to `SupplierPayment`.
- Enforces method/account policy for supplier debt payments.

- [ ] Add failing backend tests:
  - Supplier payment with `method=CASH` is rejected for debt repayment.
  - Supplier payment without `bank_account` is rejected.
  - Supplier payment with `method=BANK_TRANSFER` and `bank_account` creates a linked `TreasuryTransaction(MONEY_OUT)`.
  - Supplier outstanding decreases by the payment amount.
  - Bank account current balance decreases by the payment amount.

- [ ] Update `SupplierPaymentSerializer.validate()`:
  - Require `method == BANK_TRANSFER` for non-advance supplier debt payment.
  - Require `bank_account`.
  - Reject `cash_account`.

- [ ] Add `FinancePostingService.record_supplier_payment_treasury(payment)`.

- [ ] Call the service from `SupplierPaymentSerializer.create()`.

- [ ] Block updating posted financial fields until a reversal/correction flow is designed.

- [ ] Update frontend supplier payment UI:
  - Only show bank accounts.
  - Force method display to “Virement bancaire”.
  - Show supplier outstanding before submission.

- [ ] Run verification:
  - `cd backend && pytest apps/finance/tests.py apps/reports/test_queries.py -k "supplier"`
  - `cd frontend && npm run build`

---

## Task 6: Dashboard Financial Totals And Debt Details

**Files:**
- Modify `backend/apps/reports/views/dashboard.py`
- Modify `backend/apps/reports/test_views.py`
- Modify `frontend/src/modules/dashboard/types.ts`
- Modify `frontend/src/modules/dashboard/DashboardView.vue`
- Modify locale files

**Interfaces:**
- Consumes `CustomerOutstandingReportQuery`, `SupplierOutstandingReportQuery`, `TransporterOutstandingReportQuery`, bank `current_balance`, and expense category totals.
- Produces `summary.debts`, `summary.customer_amounts`, and `summary.bank_amounts`.

- [ ] Add failing dashboard API test:
  - Response includes `debts.total`, `debts.suppliers`, `debts.transporters`, `debts.customs`, `debts.other`, `customer_amounts.total`, `customer_amounts.rows`, `bank_amounts.total`, `bank_amounts.rows`.

- [ ] Implement dashboard aggregation:
  - Supplier debts from `SupplierOutstandingReportQuery.run()`.
  - Transporter debts from `TransporterOutstandingReportQuery.run()`.
  - Customs debts from unpaid/partially paid `Expense` where `category=customs`.
  - Other debts from unpaid/partially paid `Expense` excluding customs and transport when already represented by `TransportPayment`.
  - Customer amounts from `CustomerOutstandingReportQuery.run()`.
  - Bank amounts from active `BankAccount.current_balance`; do not include cash in “Montant total des banques”.

- [ ] Update `DashboardSummary` TypeScript type.

- [ ] Update `DashboardView.vue`:
  - Add “Total des dettes” with details by Fournisseurs, Transporteurs, Douanes, Autres.
  - Add “Montant total des clients” with detail by client.
  - Add “Montant total des banques” with each bank balance.

- [ ] Run verification:
  - `cd backend && pytest apps/reports/test_views.py`
  - `cd frontend && npm run test:unit -- --run`
  - `cd frontend && npm run build`

---

## Task 7: Shareholders / Associates Domain

**Files:**
- Modify `backend/apps/finance/models.py`
- Modify `backend/apps/finance/serializers.py`
- Modify `backend/apps/finance/services.py`
- Modify `backend/apps/finance/views.py`
- Modify `backend/apps/finance/urls.py`
- Modify `backend/apps/finance/tests.py`
- Modify `backend/apps/accounts/models.py`
- Create migration `backend/apps/finance/migrations/0006_shareholders.py`
- Create migration `backend/apps/accounts/migrations/0005_seed_shareholder_permissions.py`
- Create `frontend/src/modules/finance/ShareholderView.vue`
- Modify `frontend/src/modules/finance/api.ts`
- Modify `frontend/src/modules/finance/types.ts`
- Modify `frontend/src/router/index.ts`
- Modify `frontend/src/modules/shell/AppShell.vue`
- Modify locale files

**Interfaces:**
- Produces `Shareholder`.
- Produces `ShareholderProfitDistribution`.
- Produces `ShareholderProfitShare`.
- Produces `ShareholderLoan`.
- Produces `ShareholderWithdrawal`.
- Produces `ShareholderLedgerService.get_shareholder_summary(shareholder_id)`.

- [ ] Add backend tests:
  - Shareholder percentages must be between 0 and 100.
  - Active shareholder percentages cannot exceed 100 total.
  - Creating a distribution for profit amount `1000000` with shareholders `80/10/10` creates shares `800000/100000/100000`.
  - Shareholder withdrawal creates `TreasuryTransaction(MONEY_OUT)` from selected bank/cash and reduces remaining due.
  - Shareholder loan tracks borrower, lender, principal, repaid amount, remaining amount, date, status.
  - Repaid amount cannot exceed principal.

- [ ] Add models:
  - `Shareholder(name, participation_percent, phone, notes, is_active)`.
  - `ShareholderProfitDistribution(period_start, period_end, total_profit, status, created_by, validated_by, validated_at)`.
  - `ShareholderProfitShare(distribution, shareholder, percent_snapshot, amount_due, amount_withdrawn)`.
  - `ShareholderLoan(borrower, lender, amount, date, status, amount_repaid, notes)`.
  - `ShareholderWithdrawal(shareholder, profit_share nullable, amount, date, bank_account nullable, cash_account nullable, notes, recorded_by)`.

- [ ] Add constraints/indexes:
  - Positive money amounts.
  - Percent between 0 and 100.
  - Borrower and lender cannot be the same shareholder.
  - Exactly one treasury account on withdrawal.
  - Index shareholder/date/status fields used by ledger and dashboard.

- [ ] Add service methods:
  - `ShareholderService.validate_total_participation()`.
  - `ShareholderDistributionService.create_distribution(period_start, period_end, actor)`.
  - `ShareholderLedgerService.get_shareholder_summary(shareholder_id)`.
  - `ShareholderWithdrawalService.record_withdrawal(...)`.

- [ ] Add API endpoints:
  - `/api/shareholders/`
  - `/api/shareholder-distributions/`
  - `/api/shareholder-loans/`
  - `/api/shareholder-withdrawals/`
  - `/api/shareholders/{id}/ledger/`

- [ ] Add module permission:
  - Add `"shareholders"` to `Role.MODULES`.
  - Seed Admin and Management with view/create/edit/validate/export; Finance with view/create.

- [ ] Add Vue page:
  - List/create/edit shareholders.
  - Show participation percent.
  - Create profit distribution by period.
  - Show calculated shares.
  - Record advance/debt between associates.
  - Record shareholder withdrawal.
  - Show per-shareholder remaining due and loan balances.

- [ ] Add navigation:
  - Route `/shareholders`.
  - Sidebar under `Trésorerie / Finance`.

- [ ] Run verification:
  - `cd backend && pytest apps/finance/tests.py`
  - `cd frontend && npm run build`

---

## Task 8: Profit Reporting By Trip And Period

**Files:**
- Modify `backend/apps/reports/services/profit.py`
- Modify `backend/apps/reports/queries/margin_report.py`
- Modify `backend/apps/reports/views/reports.py` only if a new slug is needed
- Modify `backend/apps/reports/test_queries.py`
- Modify `frontend/src/modules/reports/types.ts`
- Modify `frontend/src/modules/reports/ReportsView.vue`
- Modify locale files

**Interfaces:**
- Consumes `TripProfitService.get_cost_breakdown()`.
- Produces report rows with quantity, supplier price, transport fees, transit/customs/additional expenses, unit cost, selling price, and benefit.

- [ ] Add failing report tests:
  - `margin-report` row includes `quantity`, `supplier_unit_price`, `transport_cost`, `customs_cost`, `transit_cost`, `additional_costs`, `unit_cost`, `unit_selling_price`, `unit_profit`, `current_margin`.
  - Filtering `from=2026-08-01&to=2026-08-31` returns period total equal to the sum of row margins.

- [ ] Extend `MarginReportQuery.FIELDS` and `run()`:
  - Use `TripProfitService.get_cost_breakdown()` for all cost/profit numbers.
  - Map `Expense.Category.CUSTOMS` to customs.
  - Map transit/import-intention categories to transit/import fees.
  - Put all remaining allocated expenses in `additional_costs`.

- [ ] Update `ReportsView.vue`:
  - Display the expanded margin report fields.
  - Preserve existing export behavior.
  - Use existing `DateRangeFilter` for “Du [Date début] au [Date fin]”.

- [ ] Run verification:
  - `cd backend && pytest apps/reports/test_queries.py apps/reports/test_views.py`
  - `cd frontend && npm run build`

---

## Task 9: Frontend Copy, Navigation, And UAT Flow

**Files:**
- Modify `frontend/src/locales/fr.json`
- Modify `frontend/src/locales/en.json`
- Modify `frontend/src/locales/ar.json`
- Modify `frontend/src/modules/shell/AppShell.vue`
- Modify all touched Vue forms/views
- Modify or add frontend tests

**Interfaces:**
- Consumes all previous API changes.
- Produces a complete user-facing flow matching the client text.

- [ ] Add French labels exactly aligned with client wording:
  - `Total des dettes`
  - `Dettes Fournisseurs`
  - `Dettes Transporteurs`
  - `Dettes Douanes`
  - `Montant total des clients`
  - `Montant total des banques`
  - `Stock de l’entreprise`
  - `Prix de revient`
  - `Bénéfice`
  - `Vente à perte`
  - `Vers moi`
  - `Total de la dette du Client`
  - `Actionnaires / Associés`
  - `Retrait d’argent de l’associé`

- [ ] Update Arabic and English translations with equivalent labels.

- [ ] Add UAT checklist to this task's PR notes:
  - Create trip without client.
  - Add transport fee per litre.
  - Add customs expense allocated to trip.
  - View cost basis.
  - Assign customer.
  - Confirm delivery with profitable selling price.
  - Confirm delivery with below-cost price only after warning.
  - Record customer payment with proof image and note.
  - Pay supplier debt by bank transfer and verify bank balance.
  - Open dashboard and verify debt/client/bank totals.
  - Create shareholders 80/10/10 and distribute profit.
  - Record shareholder withdrawal and loan.

- [ ] Run final verification:
  - `cd backend && pytest`
  - `cd frontend && npm run lint`
  - `cd frontend && npm run test:unit`
  - `cd frontend && npm run build`

---

## Implementation Notes For Claude Code

- Start with backend tests and migrations, then backend services, then API serializers/views, then frontend.
- Keep all financial creation paths atomic.
- Do not put profit formulas in Vue. Vue should call the backend and display returned values.
- Do not add a separate `Loading` table. The project intentionally treats loading as part of `Trip`.
- Do not make `client` required at trip creation. The destination is company stock until a client is assigned.
- Do not make `CustomerPayment` point directly at one invoice. Keep `PaymentAllocation`.
- Do not mutate finalized financial history silently. If a posted payment must change, prefer blocking the edit until a reversal/correction flow is designed.
- Run the listed test command at the end of each task before starting the next one.

## Claude Code Prompt

Read `/Users/mohamed/Downloads/fuel-logistics-erp/docs/notes-et-demandes-client-modifications-application.md` and `/Users/mohamed/Downloads/fuel-logistics-erp/docs/plan.md`. Implement the plan task by task in `/Users/mohamed/Downloads/fuel-logistics-erp`. Preserve the existing architecture: Django services own business rules, `TreasuryTransaction` owns bank/cash balances, `PaymentAllocationService` owns customer outstanding, `TripProfitService` owns all profit/cost formulas, and Vue only displays API results. Use TDD for each financial rule, create migrations, update serializers/views/API types/Vue screens/locales, and run the verification commands listed in each task. Do not make the client mandatory at trip creation; trips begin as `Stock de l’entreprise` until the customer is assigned for sale.

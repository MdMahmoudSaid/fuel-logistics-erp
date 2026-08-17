# Phase 5 — Finance

Spec reference: `docs/ERP_Specification.md` §46 (Phase 5), §16–17, §22–31.

## Goal

All money movement: customer/supplier/transporter payments (with advances and partial/multi-payment support), transporter loss deductions, flexible-method expenses, indirect customer payments, and real bank/cash treasury tracking — with internal transfers explicitly excluded from profit.

## Models (`backend/apps/finance`)

**`CustomerPayment`** — `customer` (FK), `amount`, `payment_date`, `method` (`CASH`/`BANK_TRANSFER`/`CHEQUE`/`OTHER`), `account` (FK → `BankAccount` or `CashAccount`, nullable — null for indirect payments, see below), `reference`, `recorded_by` (FK → `User`), `is_indirect` (bool, default False).

**`PaymentAllocation`** — `payment` (FK → `CustomerPayment`), `invoice` (FK → `Invoice`, nullable — null means applied to general customer balance), `amount`. One payment can fan out across many invoices (§24) via multiple `PaymentAllocation` rows; the sum of allocations must equal the payment amount (validated).

**`SupplierPayment`** — `supplier` (FK), `supplier_order` (FK, nullable — advances aren't tied to one order), `amount`, `payment_date`, `method`, `account` (FK), `is_advance` (bool), `reference`.

**`TransportPayment`** — `trip` (FK), `transporter` (FK), `calculation_method` (`FIXED` / `PER_LITRE` / `PER_DAY` / `NEGOTIATED`), `base_amount` (computed from method + trip data, editable if `NEGOTIATED`), `deduction_amount` (from loss, see below), `advance_applied` (FK → a `TransporterAdvance` row, nullable), `net_amount` (computed: base − deduction − advance), `status` (`PLANNED` / `PAYABLE` / `PARTIALLY_PAID` / `PAID` / `DEDUCTION_APPLIED`).

**`TransporterAdvance`** — `transporter` (FK), `amount`, `date`, `notes`, `settled` (bool) — separate from `TransportPayment` because an advance is issued before a specific trip's cost is even known.

**`Expense`** — `category` (choices per §26: customs, import_intention, transport, loading, unloading, road, administration, rent, salary, repairs, bank_charges, other), `amount`, `calculation_method` (`FIXED` / `PER_LITRE` / `PERCENTAGE` / `PER_ORDER` / `PER_TRUCK` / `MANUAL`), `date`, `status` (`UNPAID` / `PARTIALLY_PAID` / `PAID` / `CANCELLED`), `paid_by_customer_directly` (bool, default False — the §25 indirect-payment flag), `notes`.

**`ExpenseAllocation`** — `expense` (FK), and a generic target: `content_type` + `object_id` (GenericForeignKey) to attach to `Trip`, `Truck`, `Customer`, `Supplier`, `Transporter`, `SupplierOrder`, or nothing (company-level) — matches §26's "may be linked to" list without a wide table of nullable FKs.

**`TreasuryTransaction`** — `account` (FK → `BankAccount` or `CashAccount`, via a small polymorphic wrapper or two nullable FKs with a `CheckConstraint` ensuring exactly one is set), `type` (`MONEY_IN` / `MONEY_OUT` / `TRANSFER`), `amount`, `date`, `reference`, `source_content_type`/`source_object_id` (GenericForeignKey back to the `CustomerPayment`/`SupplierPayment`/`Expense`/etc. that caused it), `document`, `recorded_by`.

## Critical constraints — read these twice

- **Indirect customer payment (§25):** when `Expense.paid_by_customer_directly = True`, the flow creates the `Expense` (status `PAID`) **and** a `CustomerPayment` with `is_indirect=True`, `account=None`, allocated via `PaymentAllocation` to reduce the customer's balance — but **creates zero `TreasuryTransaction` rows**. The service function that handles this must be the *only* path that can create an `Expense` with `paid_by_customer_directly=True`; a code comment there should reference §25 since the "don't touch the bank" behavior is the opposite of every other payment flow and will look like a bug to a future maintainer.
- **Bank-to-bank transfer:** a `TREASURY` transfer between two internal accounts creates exactly two `TreasuryTransaction` rows (`MONEY_OUT` on source, `MONEY_IN` on destination) both tagged `type=TRANSFER`, and the profit/revenue/expense reporting queries in Phase 6 must explicitly exclude `type=TRANSFER` rows (§29, §47 "Financial Transfer").
- **Transporter deduction (§16):** `TransportPayment.deduction_amount = DeliveryControl.chargeable_loss_litres × Sale.selling_price` for that trip, computed once the delivery control and sale both exist; `net_amount = base_amount − deduction_amount − advance_applied.amount`.
- Account balances (`BankAccount.current_balance`, `CashAccount.current_balance`) are computed as `opening_balance + Σ(MONEY_IN) − Σ(MONEY_OUT/TRANSFER-out) + Σ(TRANSFER-in)` over `TreasuryTransaction` — never stored/mutated directly, so there is one source of truth for cash position.

## API Endpoints

- `GET|POST /api/customer-payments/` (body includes allocation list)
- `GET|POST /api/supplier-payments/`
- `GET|POST /api/transport-payments/`, `POST /api/transporter-advances/`
- `GET|POST /api/expenses/` (`paid_by_customer_directly` flag routes to the indirect-payment service)
- `GET /api/treasury-transactions/`, `POST /api/treasury-transactions/transfer/` (source account, destination account, amount)
- `GET /api/customers/{id}/ledger/`, `GET /api/suppliers/{id}/ledger/` (extends Phase 2's stub), `GET /api/transporters/{id}/ledger/`

## Vue Components

- `finance/PaymentAllocationForm.vue` — pick a customer, see open invoices, split one payment across several
- `finance/ExpenseForm.vue` — category + calculation method + optional "customer paid this directly" toggle that hides the account field
- `finance/TreasuryLedgerView.vue`, `TransferForm.vue`
- `finance/TransporterLedgerView.vue` — earned / advances / deductions / paid / outstanding, matching the §31 worked example layout
- `customers/CustomerLedgerView.vue` (extends Phase 1/2 shell)

## Mandatory Integration Tests

- §22 worked example: 40,000,000 invoice, two partial payments (10M, 15M) → outstanding 15,000,000 (§47 "Partial Customer Payment").
- One `CustomerPayment` allocated across two different invoices sums correctly and reduces both outstanding balances.
- §25 worked example: customer owes 50M, pays customs 5M directly → `Expense` recorded paid, customer balance reduced to 45M, **and zero new `TreasuryTransaction` rows exist** (§47 "Customer Indirect Payment" — assert the treasury table row count is unchanged).
- §16 worked example: 50 L chargeable loss × 850 FCFA = 42,500 deduction; transport cost 700,000 → net 657,500 (§47 "Transport Deduction").
- §31 worked example: earned 5,000,000; advance 1,000,000; deduction 200,000; paid 2,000,000 → outstanding 1,800,000 (§47 "Transporter Advance").
- A bank→bank transfer produces two `TreasuryTransaction` rows and is excluded from a profit-report query in the same test (§47 "Financial Transfer").

## Definition of Done (§48 acceptance criteria covered)

- #13 "Calculate transporter deductions."
- #15 "Record multiple customer payments."
- #16 "See customer outstanding balance."
- #17 "Record transport costs and payments."
- #18 "See transporter outstanding balance."
- #19 "Record supplier payments."
- #20 "Record unlimited expenses."
- #21 "Track banks and cash."

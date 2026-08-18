# ERP Implementation Experience Guide
## Production Patterns to Reuse from Existing ERP / TMS Projects

> Purpose: This document is an engineering reference for Claude Code while implementing the custom Fuel Trading and Cross-Border Logistics ERP described in `ERP_Specification.md`.
>
> It does **not** replace the specification. `ERP_Specification.md` remains the business source of truth.
>
> This guide extracts useful architectural experience from:
>
> - VSD Fleet Management System / ERPNext ecosystem
> - ERPNext core accounting and stock patterns
> - Fleetbase / FleetOps
> - OCA Odoo Transport Management System
> - Open mSupply
> - VROOM
> - smaller Django / transport-management examples where useful
>
> The goal is to reuse **proven design ideas**, not to copy unrelated code or force the ERP to behave like these products.

---

# 1. Non-Negotiable Domain Rules

Claude Code must preserve these rules even if an external reference uses a different model.

## 1.1 Truck != Trip != Customer Order

These are three independent concepts.

```text
Truck
  └── reusable physical resource

Trip
  └── one operational movement/load using one truck

CustomerOrder
  └── commercial demand that may be fulfilled by many trips
```

Required relationship:

```text
Truck 1 -------- N Trip N -------- 0..1 CustomerOrder
```

The same physical truck may create several trips for the same customer order.

Never model:

```text
CustomerOrder.truck_id
```

as the main relationship.

Never permanently assign a truck to a customer.

---

## 1.2 Fuel Product is Cargo, Not Vehicle Consumption

The ERP trades fuel such as:

- Gasoil
- Essence

This fuel is commercial inventory/cargo.

It must not be confused with the diesel consumed by a tractor itself.

If vehicle fuel consumption is implemented later, it must be a separate concept.

---

## 1.3 Supplier Cession and Supplier Reliquat are Domain-Specific

No researched project fully implements this exact business rule.

The ERP must therefore implement it explicitly.

```text
SupplierPurchase
      |
      +--> CessionLetter
      |
      +--> Loading(s)
```

Two different balances exist:

```text
Supplier Reliquat
= Purchased Quantity - Valid Loaded Quantity
```

and:

```text
Cession Remaining
= Cession Authorized Quantity - Valid Quantity Loaded Against Cession
```

Both must be controlled independently.

---

## 1.4 Delivered Quantity is Commercial Truth

The customer is invoiced based on actual quantity received, not quantity loaded.

```text
loaded = 45,000 L
received = 44,850 L

invoice quantity = 44,850 L
```

---

## 1.5 Loss and Transporter Deduction

```text
loss = loaded_quantity - received_quantity

chargeable_loss =
    max(loss - configured_tolerance, 0)

transporter_deduction =
    chargeable_loss * applicable_customer_selling_price
```

The deduction must be a separate auditable financial transaction.

Do not silently reduce the transport cost field.

---

## 1.6 Indirect Customer Payment

Example:

```text
Customer receivable:       50,000,000
Customer pays customs:      5,000,000
Remaining receivable:      45,000,000
Company bank movement:              0
```

This must reduce customer receivable and record the expense **without creating fake bank/cash movement**.

---

## 1.7 Financial Operations Must Be Allocation-Based

A payment may cover:

- one invoice;
- several invoices;
- only part of an invoice;
- remain as customer credit/advance.

Therefore use allocation entities rather than putting a direct payment foreign key on an invoice.

---

## 1.8 Trip Profit Must Recalculate

Trip profitability is derived information.

A new expense added later must update the trip margin.

Do not store a final immutable margin while allowing underlying costs to change.

---

# 2. Reference Project Responsibility Map

| Reference | Use It For | Do Not Use It For |
|---|---|---|
| VSD Fleet Management | Cargo/manifest/trip separation, trip financial workflow, approvals, vehicle assignment | Cession/reliquat logic |
| Fleetbase / FleetOps | Operational lifecycle, status flows, timeline, manifests, files/proofs, orchestration concepts | ERP accounting |
| OCA Odoo TMS | Clean Vehicle/Driver/Route/Trip domain separation | Complete production finance |
| ERPNext | Payments, allocations, multi-currency, treasury, reconciliation, accounting discipline, stock-ledger ideas | Exact fuel transport workflow |
| Open mSupply | Weak-connectivity architecture, transaction-oriented stock systems, mobile/responsive operations | Fuel transport finance |
| VROOM | Future vehicle assignment / routing optimization | V1 ERP source of truth |
| Small Django TMS examples | Service-layer/API organization, simple trip constraints | Production accounting/domain rules |

---

# 3. Recommended Django Domain Boundaries

Suggested project structure:

```text
apps/
├── accounts/
├── partners/
│   ├── customers/
│   ├── suppliers/
│   └── transporters/
├── catalog/
│   └── products/
├── fleet/
│   ├── trucks/
│   └── drivers/
├── purchasing/
│   ├── supplier_orders/
│   ├── cessions/
│   └── supplier_stock/
├── operations/
│   ├── customer_orders/
│   ├── trips/
│   ├── loadings/
│   ├── trip_status/
│   └── delivery_control/
├── sales/
│   ├── sales/
│   └── invoices/
├── finance/
│   ├── payments/
│   ├── allocations/
│   ├── expenses/
│   ├── treasury/
│   └── ledgers/
├── profitability/
├── documents/
├── reporting/
└── audit/
```

This separation is inspired by mature ERP/TMS products where transport operations, accounting, fleet resources, and reporting are related but not collapsed into one giant model.

---

# 4. Phase 1 — Foundation

## Scope from Specification

Build:

- authentication;
- users;
- roles;
- products;
- suppliers;
- customers;
- transporters;
- trucks;
- banks;
- cash accounts.

---

## 4.1 Experience from VSD Fleet Management

VSD separates reusable master data from operational transaction records.

Useful masters include:

- vehicles;
- drivers;
- routes;
- expense templates.

### Lesson

`Truck`, `Driver`, `Supplier`, `Customer`, `Transporter`, `Product`, `FinancialAccount` are reusable master records.

Do not put trip-specific information inside these masters.

Bad:

```python
class Truck:
    current_customer
    current_order
    loaded_quantity
    selling_price
```

Better:

```python
class Truck:
    tractor_registration
    tanker_registration
    capacity
    ownership_type
    transporter
    active
```

Trip-specific information belongs to `Trip`.

---

## 4.2 Experience from OCA TMS

OCA separates:

- Vehicle
- Driver
- Route
- Trip

### Lesson

A vehicle is a reusable operational resource.

A trip references the vehicle.

This directly supports the mandatory repeated-truck scenario.

---

## 4.3 Recommended Truck Model

```text
Truck
-----
id
internal_code
tractor_registration
tanker_registration
capacity_litres
ownership_type
transporter_id nullable
default_driver_id nullable
operational_status
active
created_at
updated_at
```

Do not use `current_customer_id`.

Do not use `current_order_id`.

A truck's current operation should be discovered through active Trip state.

---

## 4.4 Truck Availability

The specification says one physical truck should normally have only one active trip.

Use a service-level rule plus database-safe transaction logic.

Pseudo-flow:

```python
with transaction.atomic():
    truck = Truck.objects.select_for_update().get(pk=truck_id)

    if Trip.objects.filter(
        truck=truck,
        status__in=ACTIVE_TRIP_STATUSES
    ).exists():
        raise TruckAlreadyInActiveTrip()

    trip = Trip.objects.create(...)
```

Reason:

Two users may attempt to assign the same truck at the same time.

Frontend validation alone is insufficient.

---

## 4.5 Financial Account Model

ERPNext strongly demonstrates that account identity and account currency should be explicit.

Instead of maintaining two unrelated implementations:

```text
BankAccount
CashAccount
```

prefer one common abstraction if it fits the project:

```text
FinancialAccount
----------------
id
name
account_type = BANK | CASH
currency
opening_balance
active
bank_name nullable
account_reference nullable
```

This simplifies treasury transactions.

If the specification's separate BankAccount/CashAccount entities are retained, they should still share common transaction logic.

---

## 4.6 Phase 1 Acceptance Rules for Claude

Claude must verify:

- truck is independent from customer/order;
- transporter is independent from driver;
- external and company-owned trucks are supported;
- driver is optional;
- money uses `Decimal` / PostgreSQL `NUMERIC`;
- quantities use `Decimal`, not float;
- each financial account has a currency;
- role permissions are explicit.

---

# 5. Phase 2 — Purchasing, Cession and Supplier Reliquat

## Scope

Build:

- supplier orders;
- purchase quantities;
- cession letters;
- supplier reliquat;
- supplier ledger;
- documents.

---

# 5.1 Experience from ERPNext Stock Ledger

ERPNext uses transaction-driven stock logic instead of treating a manually updated balance as the only truth.

### Lesson

Supplier reliquat should be derived from immutable/valid loading transactions.

Do not implement:

```python
purchase.remaining_quantity -= loading.quantity
```

as the only source of truth.

This creates drift after cancellations, corrections, concurrent loading, or manual mistakes.

Prefer:

```text
available =
purchase.quantity
- SUM(valid_loading.quantity)
```

A cached balance may exist for performance, but it must be reconcilable from source transactions.

---

## 5.2 Supplier Purchase Model

```text
SupplierPurchase
----------------
id
reference
supplier_id
product_id
purchase_date
purchased_quantity
unit_price
currency
total_amount
status
created_by
created_at
```

---

## 5.3 Cession Letter Model

```text
CessionLetter
-------------
id
reference
supplier_purchase_id
authorized_quantity
issue_date
status
document_id
notes
created_by
created_at
```

Do not make `remaining_quantity` the authoritative value.

It may be exposed as calculated data:

```text
cession_loaded =
SUM(loadings where cession_id = id and state is effective)

cession_remaining =
authorized_quantity - cession_loaded
```

---

## 5.4 Loading Control Must Lock the Cession

Critical concurrency scenario:

```text
Cession authorized = 50,000 L
Remaining = 45,000 L

User A loads 30,000
User B loads 30,000
```

Without locking, both requests can pass validation.

Use:

```python
with transaction.atomic():
    cession = (
        CessionLetter.objects
        .select_for_update()
        .get(pk=cession_id)
    )

    remaining = calculate_cession_remaining(cession)

    if requested_qty > remaining:
        raise InsufficientCessionQuantity()

    ...
```

The same principle should be applied to SupplierPurchase availability.

---

## 5.5 Supplier Reliquat

Use a dedicated domain service:

```text
SupplierStockService
--------------------
get_purchase_loaded_quantity()
get_purchase_reliquat()
get_supplier_product_reliquat()
validate_available_quantity()
```

Do not duplicate formulas across serializers, views and frontend code.

---

## 5.6 Documents

VSD and Fleetbase both treat operational documents as attachable resources.

Implement generic document ownership.

Recommended pattern:

```text
Document
--------
id
file
document_type
reference
uploaded_by
uploaded_at
```

Then either:

### Option A — explicit nullable relations

```text
supplier_id
purchase_id
cession_id
trip_id
invoice_id
...
```

or:

### Option B — Generic relation / attachment table

```text
DocumentLink
------------
document_id
entity_type
entity_id
```

For Django, explicit relations are easier to enforce, while a generic link is more extensible.

Claude should choose one consistent strategy and document it.

---

## 5.7 Anti-Patterns to Avoid

- decrementing supplier stock without trace;
- deleting an effective loading when correcting quantity;
- allowing loading larger than cession remaining;
- treating cession remaining and supplier reliquat as the same balance;
- storing quantity as float;
- recalculating only in frontend.

---

# 6. Phase 3 — Customer Orders and Truck Operations

## Scope

Build:

- customer orders;
- trip/load creation;
- repeated truck trips;
- loading;
- truck status tracking;
- border/customs stages;
- trip history.

---

# 6.1 Experience from VSD Fleet Management

VSD's high-level lifecycle is approximately:

```text
Cargo Registration
    -> Manifest
    -> Vehicle Assignment
    -> Trip
    -> Funds/Fuel
    -> Settlement
```

### Lesson

Commercial demand and actual trip execution should remain separate.

Your equivalent:

```text
CustomerOrder
    -> Trip Assignment(s)
    -> Loading
    -> Execution
```

A customer order is not the trip itself.

---

# 6.2 Experience from Fleetbase / FleetOps

FleetOps supports:

- create;
- schedule;
- dispatch;
- start;
- cancel;
- complete;
- configurable status flows;
- activity timeline;
- manifests;
- files/proofs;
- vehicle/driver allocation.

### Lesson

Trip workflow should be modeled as a state machine with historical events.

---

# 6.3 Experience from OCA TMS

OCA explicitly separates:

```text
Vehicle
Driver
Route
Trip
```

### Lesson

If reusable routes are later valuable, create a `Route` master rather than storing every route property directly on every truck.

For V1, route can remain optional if the specification does not require a route master.

---

# 6.4 Customer Order Model

```text
CustomerOrder
-------------
id
reference
customer_id
product_id
ordered_quantity
expected_unit_price
status
created_at
confirmed_at
```

Derived quantities:

```text
assigned_quantity
loaded_quantity
delivered_quantity
invoiced_quantity
remaining_quantity
```

These should preferably be calculated from related Trip/Sale records or maintained through robust transactional projections.

---

# 6.5 Trip Model

```text
Trip
----
id
reference
truck_id
transporter_id
driver_id nullable
supplier_id
supplier_purchase_id
cession_letter_id
product_id
customer_id
customer_order_id nullable
planned_quantity
current_status
created_by
created_at
completed_at nullable
```

A direct sale/delivery may exist without `customer_order_id`.

---

# 6.6 Loading Model

Even if there is currently one load per trip, keeping `Loading` separate has advantages:

```text
Loading
-------
id
trip_id
supplier_purchase_id
cession_letter_id
quantity_loaded
loading_date
bl_reference
status
created_by
```

It preserves:

- quantity authorization;
- auditability;
- source purchase;
- cession consumption;
- document ownership.

If V1 guarantees exactly one loading per trip, enforce OneToOne while preserving the separate entity.

---

# 6.7 Trip Status History

Never overwrite history.

```text
Trip
----
current_status

TripStatusHistory
-----------------
id
trip_id
previous_status
new_status
changed_by
changed_at
notes
```

Allowed statuses:

```text
ASSIGNED
SENT_FOR_LOADING
LOADING
LOADED
IN_TRANSIT
BORDER
CUSTOMS
GOING_TO_CLIENT
ARRIVED_AT_CLIENT
QUANTITY_CONTROL
DELIVERED
COMPLETED
BLOCKED
CANCELLED
```

---

# 6.8 State Transition Service

Do not allow arbitrary:

```python
trip.status = request.data["status"]
trip.save()
```

Use:

```text
TripWorkflowService.transition(
    trip,
    target_status,
    actor,
    notes
)
```

Responsibilities:

1. lock Trip;
2. validate current -> target transition;
3. validate required information;
4. update current status;
5. insert history;
6. trigger domain-side effects if required;
7. commit atomically.

---

# 6.9 Suggested Transition Rules

Example:

```text
ASSIGNED -> SENT_FOR_LOADING
SENT_FOR_LOADING -> LOADING
LOADING -> LOADED
LOADED -> IN_TRANSIT
IN_TRANSIT -> BORDER
BORDER -> CUSTOMS
CUSTOMS -> GOING_TO_CLIENT
GOING_TO_CLIENT -> ARRIVED_AT_CLIENT
ARRIVED_AT_CLIENT -> QUANTITY_CONTROL
QUANTITY_CONTROL -> DELIVERED
DELIVERED -> COMPLETED
```

Exceptional states:

```text
* -> BLOCKED
eligible states -> CANCELLED
BLOCKED -> previous/authorized next state
```

Do not hard-code workflow rules in Vue.

Backend owns workflow validity.

---

# 6.10 Repeated Truck Scenario

Mandatory example:

```text
Order = 450,000 L
Fleet = 6 trucks

Round 1:
A B C D E F

Round 2:
A B C D
```

The system must produce ten Trip rows.

Truck A must have two independent Trip rows.

The order remains one commercial entity.

---

# 6.11 Truck Availability

Truck availability is derived from active trips.

Example service:

```text
TruckAvailabilityService
------------------------
is_available(truck)
active_trip(truck)
available_trucks()
```

When a Trip becomes `COMPLETED`, the truck becomes available again.

Avoid manually maintaining contradictory values such as:

```text
truck.status = AVAILABLE
trip.status = IN_TRANSIT
```

If a truck operational status field exists, define clear precedence and synchronization rules.

---

# 7. Phase 4 — Delivery, Quantity Control, Loss, Sales and Invoice

## Scope

Build:

- quantity control;
- loss/tolerance;
- transporter deductions;
- delivery;
- sales;
- invoices;
- customer balances.

---

# 7.1 Experience from Fleetbase

Fleetbase treats completion/proof/activity as explicit operational events.

### Lesson

Delivery is not simply `trip.status = DELIVERED`.

It should record evidence and operational data.

---

# 7.2 Delivery Control Model

```text
DeliveryControl
---------------
id
trip_id
loaded_quantity
received_quantity
loss_quantity
tolerance_quantity
chargeable_loss_quantity
control_date
controller
method
document_id nullable
notes
confirmed_by
confirmed_at
```

Important:

Store the **tolerance used at the time of confirmation**.

Even if the default tolerance changes later, historic trips must retain the rule applied to them.

---

# 7.3 Quantity Formula

Use Decimal only.

```python
loss = loaded_quantity - received_quantity
chargeable_loss = max(loss - tolerance, Decimal("0"))
```

If:

```text
received_quantity > loaded_quantity
```

the workflow must stop normal automatic confirmation and require authorized confirmation.

---

# 7.4 Tolerance Configuration

Do not hard-code `100 L` in services.

Recommended:

```text
OperationalSettings
-------------------
default_loss_tolerance_litres
```

Future enhancement may support tolerance by:

- product;
- route;
- transporter;
- contract.

But V1 must obey the specification's configurable default.

---

# 7.5 Transporter Deduction as Separate Transaction

Recommended:

```text
TransportDeduction
------------------
id
trip_id
transporter_id
reason_type
chargeable_quantity
unit_price
amount
currency
status
created_at
validated_at
```

Reason:

The transporter ledger should clearly show:

```text
transport earned
- deductions
- advances
- payments
= outstanding
```

Do not simply mutate:

```text
transport_cost.net_amount
```

without preserving the deduction transaction.

---

# 7.6 Sale Model

```text
Sale
----
id
trip_id
customer_id
customer_order_id nullable
product_id
delivered_quantity
unit_selling_price
currency
subtotal
created_at
validated_at
```

Critical invariant:

```text
sale.delivered_quantity
==
confirmed DeliveryControl.received_quantity
```

for normal V1 workflow.

---

# 7.7 Invoice Quantity

Never use the planned or loaded quantity automatically.

Invoice source:

```text
confirmed received quantity
```

This must be tested.

---

# 7.8 Selling Price History

The specification requires remembering the latest selling price while preserving history.

Recommended:

```text
ProductSellingPriceHistory
--------------------------
id
product_id
customer_id nullable
price
currency
effective_at
changed_by
```

When sale creation begins:

```text
suggest latest applicable price
```

When authorized user changes it:

```text
save the new historical price
```

Do not overwrite old sale prices.

---

# 7.9 Validated Invoice Editing

ERP accounting experience strongly favors reversals/corrections rather than silent mutation.

Once invoice is validated:

- do not silently rewrite quantity;
- do not silently rewrite price;
- record correction/reversal with reason and actor.

---

# 8. Phase 5 — Finance

## Scope

Build:

- customer payments;
- supplier payments;
- transporter payments;
- advances;
- expenses;
- indirect customer payments;
- banks/cash;
- outstanding balances.

This phase should take the most experience from ERPNext.

---

# 8.1 Experience from ERPNext Payment Entry

ERPNext Payment Entry supports core concepts such as:

- Receive;
- Pay;
- Internal Transfer;
- paid-from account;
- paid-to account;
- account currencies;
- exchange rates;
- references to invoices;
- allocated amount;
- unallocated amount;
- reconciliation.

### Lesson

Payment and payment allocation are separate concerns.

---

# 8.2 Customer Payment Model

```text
CustomerPayment
---------------
id
customer_id
date
amount
currency
financial_account_id
payment_method
reference
document_id nullable
status
created_by
```

Allocation:

```text
CustomerPaymentAllocation
-------------------------
id
payment_id
invoice_id
allocated_amount
currency
```

This gives:

```text
CustomerPayment 1:N CustomerPaymentAllocation
Invoice         1:N CustomerPaymentAllocation
```

---

# 8.3 Why Allocation Entity is Mandatory

It supports:

### one payment -> one invoice

```text
Payment 10M -> Invoice A 10M
```

### one payment -> multiple invoices

```text
Payment 20M
  -> Invoice A 8M
  -> Invoice B 12M
```

### partial payment

```text
Invoice 40M
Payment 10M
Outstanding 30M
```

### unallocated credit

```text
Payment 20M
Allocated 12M
Unallocated 8M
```

Do not force one payment per truck or one payment per invoice.

---

# 8.4 Payment Reconciliation

ERPNext's reconciliation pattern is useful:

```text
Payment
Invoice
Allocation
Outstanding
```

Claude should implement centralized services:

```text
PaymentAllocationService
------------------------
allocate()
unallocate()
get_unallocated_amount()
get_invoice_outstanding()
validate_currency()
```

No duplicate outstanding formulas across APIs.

---

# 8.5 Supplier Payments

Use the same conceptual structure:

```text
SupplierPayment
SupplierPaymentAllocation
```

Possible allocation targets:

- SupplierPurchase;
- supplier invoice if introduced;
- supplier general balance.

Support:

- advance;
- partial;
- multiple payments;
- credit.

---

# 8.6 Transporter Payments

Transporter finance has distinct components:

```text
TransportEarning
TransportDeduction
TransportAdvance
TransportPayment
```

Outstanding calculation:

```text
earned
- deductions
- advances
- payments
= transporter outstanding
```

Do not derive transporter balance from `Trip.transport_cost - last_payment`.

---

# 8.7 Expenses

Recommended:

```text
Expense
-------
id
category
date
description
amount
currency
status
payee_type
payee_id
created_by
```

Allocation:

```text
ExpenseAllocation
-----------------
id
expense_id
allocation_type
trip_id nullable
purchase_id nullable
customer_id nullable
supplier_id nullable
transporter_id nullable
truck_id nullable
allocated_amount
```

Why:

A customs payment may affect several trips.

A general administrative expense may affect company profit but not one trip.

A loading expense may belong to one trip.

---

# 8.8 Expense Calculation Methods

Do not put formula-specific columns everywhere.

Use:

```text
calculation_method:
FIXED
PER_LITRE
PERCENTAGE
PER_ORDER
PER_TRUCK
MANUAL
```

Potential fields:

```text
rate
base_quantity
calculated_amount
manual_amount
```

A domain service should calculate based on method.

---

# 8.9 Indirect Customer-Paid Expense

This is custom logic.

Recommended entity:

```text
IndirectSettlement
------------------
id
customer_id
expense_id
amount
currency
date
reference
affected_trip_id nullable
status
created_by
validated_by
```

Business effect:

```text
1. create/validate Expense
2. credit/reduce Customer Receivable
3. do NOT create TreasuryTransaction
4. record audit trail
```

If full double-entry accounting is not part of V1, preserve the semantic event anyway so later accounting integration remains possible.

---

# 8.10 Treasury Pattern from ERPNext

ERPNext distinguishes:

```text
Receive
Pay
Internal Transfer
```

Use the same concept.

Recommended:

```text
TreasuryTransaction
-------------------
id
transaction_type
date
currency
amount
source_account_id nullable
destination_account_id nullable
source_operation_type
source_operation_id
reference
status
```

Rules:

### Money In

```text
destination_account required
source_account null
```

### Money Out

```text
source_account required
destination_account null
```

### Internal Transfer

```text
source_account required
destination_account required
```

Internal transfer:

- changes account balances;
- does not create revenue;
- does not create expense;
- does not change profit.

---

# 8.11 Multi-Currency

ERPNext experience shows that currency needs to be explicit at transaction and account level.

Every monetary transaction should preserve:

```text
transaction_currency
transaction_amount
exchange_rate
base_currency
base_amount
```

if the project introduces base-currency reporting.

Do not use JavaScript/Python binary float for money.

Use:

```python
Decimal
```

and PostgreSQL:

```sql
NUMERIC(precision, scale)
```

with intentionally selected precision.

---

# 8.12 Financial Validation

Financial validation should be server-side and transactional.

For important financial records use states such as:

```text
DRAFT
VALIDATED
CANCELLED
REVERSED
```

After validation:

- avoid physical deletion;
- cancel/reverse instead;
- preserve audit information.

---

# 9. Phase 6 — Profit, Stock, Dashboard, Reports, Search, Audit

## Scope

Build:

- profit engine;
- theoretical stock;
- dashboard;
- reports;
- search;
- exports;
- audit history.

---

# 9.1 Trip Profit as Derived Financial Projection

Recommended components:

```text
Trip Revenue
- Fuel Purchase Cost Allocated to Delivered/Sold Quantity
- Transport Cost
- Customs Expense Allocation
- Loading/Unloading
- Road Expense
- Other Trip Expense Allocation
+/- Valid Financial Adjustments
= Trip Margin
```

Create:

```text
TripProfitService
-----------------
calculate_estimated_margin()
calculate_current_margin()
calculate_final_margin()
get_cost_breakdown()
```

Do not scatter profitability formulas throughout serializers and dashboard queries.

---

# 9.2 Estimated vs Current vs Final Margin

Suggested semantics:

### Estimated

Before completion, using planned/expected values.

### Current/Recalculated

Based on currently validated deliveries, sale prices and expenses.

### Final

Trip closed and financially complete according to explicit closing rules.

Claude must define and document the exact transition to "final".

Do not call a value final if new expenses are still accepted without reopening.

---

# 9.3 Automatic Recalculation

Any relevant event should invalidate/recalculate profitability:

- sale validated;
- sale price corrected;
- delivery confirmed;
- expense added;
- expense allocation changed;
- transport cost changed;
- transporter deduction changed;
- transaction reversed.

A simple V1 strategy:

```text
calculate on read + optimized summary later
```

or:

```text
maintain TripFinancialSummary with deterministic rebuild service
```

If caching is used, include a rebuild command to detect drift.

---

# 9.4 Theoretical Fuel Stock

Specification rule:

```text
THEORETICAL STOCK
=
UNSOLD FUEL IN LOADED TRUCKS
+
UNLOADED FUEL REMAINING WITH SUPPLIERS
```

Do not model a fictitious physical central warehouse.

Implement two explicit components:

```text
supplier_reliquat
loaded_unsold_trip_quantity
```

and then total.

---

# 9.5 Loaded Unsold Quantity

Claude must define exactly when loaded fuel leaves theoretical stock.

Potential event:

```text
Sale validated / Delivery confirmed
```

The specification should control this choice.

Do not infer based only on trip status if it can cause accounting mismatch.

---

# 9.6 Dashboard Experience from VSD and Fleetbase

VSD demonstrates operational + financial dashboard integration.

Fleetbase demonstrates current activity/timeline thinking.

Dashboard should be composed of backend aggregates, not many frontend loops over raw records.

Recommended APIs:

```text
GET /api/dashboard/operations
GET /api/dashboard/fuel
GET /api/dashboard/sales
GET /api/dashboard/transport
GET /api/dashboard/finance
GET /api/dashboard/profit
```

or one optimized endpoint if performance is acceptable.

Support date filters centrally.

---

# 9.7 Reporting

Use domain-specific report/query services.

Examples:

```text
CustomerStatementQuery
SupplierStatementQuery
TransporterStatementQuery
TruckHistoryQuery
TripReportQuery
FuelStockReportQuery
LossReportQuery
MarginReportQuery
TreasuryStatementQuery
```

Avoid putting report SQL inside DRF serializers.

---

# 9.8 Global Search

Use PostgreSQL capabilities before adding external search infrastructure.

Search fields include:

- truck registration;
- tanker registration;
- customer;
- supplier;
- transporter;
- BL;
- invoice;
- order;
- cession;
- trip reference.

Start with indexed columns and PostgreSQL text search/trigram where useful.

Do not add Elasticsearch/OpenSearch in V1 without evidence it is necessary.

---

# 9.9 Audit Pattern

Every important mutation should preserve:

```text
actor
timestamp
object_type
object_id
action
previous_value
new_value
reason
```

Particularly:

- quantities;
- prices;
- payments;
- expenses;
- invoices;
- loss;
- deduction;
- treasury movement.

Recommended:

```text
AuditLog
--------
id
actor_id
action
entity_type
entity_id
before_json
after_json
reason
created_at
```

Important business records should also have domain-specific histories where necessary.

`AuditLog` is not a replacement for `TripStatusHistory`.

---

# 10. Phase 7 — Production Hardening

## Scope

Build:

- responsive/mobile optimization;
- weak-internet handling;
- security;
- backups;
- permissions;
- testing;
- deployment;
- UAT.

---

# 10.1 Experience from Open mSupply

Open mSupply demonstrates that serious logistics systems often need to operate across:

- server;
- laptop;
- mobile;
- remote locations;
- unreliable connectivity.

But full synchronization is complex.

### Lesson for V1

Follow the specification:

- responsive PWA;
- lightweight pages;
- retry failed network calls;
- local drafts where safe;
- optional offline queue for selected non-financial operations;
- server confirmation for financial validation.

Do not build a full conflict-resolution/sync engine in V1.

---

# 10.2 Idempotency

Weak networks cause users to click twice or clients to retry.

Financial and operational POST endpoints should support idempotent request behavior where duplicate creation is dangerous.

Examples:

- confirm delivery;
- create payment;
- validate loading;
- create deduction;
- validate invoice.

Possible strategy:

```text
Idempotency-Key header
```

Store processed command identifiers.

---

# 10.3 Optimistic UI vs Financial Truth

Frontend may show:

```text
Saving...
Queued...
Retrying...
```

But do not display a financial transaction as fully validated until server confirmation.

---

# 10.4 Permissions

Use role permissions plus business action permissions.

Examples:

```text
operations.update_trip_status
operations.confirm_delivery
operations.override_active_truck
sales.change_validated_price
finance.validate_payment
finance.reverse_payment
finance.validate_expense
```

"Can edit screen" is not granular enough.

---

# 10.5 Backups

At minimum:

- automated PostgreSQL backup;
- object/document storage backup strategy;
- tested restore procedure;
- environment/configuration backup;
- off-server copy.

A backup is not considered valid until restore is tested.

---

# 10.6 Security

At minimum:

- secure authentication;
- server-side authorization;
- CSRF/CORS correctly configured;
- no secrets in repository;
- upload validation;
- object-storage access control;
- rate limiting on authentication;
- audit for sensitive operations;
- HTTPS in production;
- database not publicly exposed.

---

# 11. Future Phase — Routing Optimization with VROOM

VROOM should **not** drive V1 architecture.

It is useful later because it models:

```text
vehicles
jobs
shipments
capacity
pickup
delivery
time windows
```

Potential future use:

```text
CustomerOrder demand
      |
      v
available Trucks
      |
      v
OptimizationService
      |
      v
proposed assignments
      |
      v
human confirmation
      |
      v
actual Trip creation
```

Important:

VROOM suggestions are not business transactions.

Only confirmed ERP Trip records are the source of truth.

---

# 12. Service-Layer Architecture for Claude Code

Avoid "fat serializers" and "fat views".

Recommended command services:

```text
CreateSupplierPurchaseService
CreateCessionLetterService
CreateTripService
ValidateLoadingService
TripWorkflowService
ConfirmDeliveryService
CalculateLossService
ApplyTransportDeductionService
CreateSaleService
ValidateInvoiceService
RecordCustomerPaymentService
AllocateCustomerPaymentService
RecordSupplierPaymentService
RecordTransporterPaymentService
RecordExpenseService
RecordIndirectSettlementService
TreasuryTransferService
TripProfitService
```

Read/query logic may use separate query services.

---

# 13. Transaction Boundaries

Operations that update several connected objects must be atomic.

Example: Confirm Delivery

```text
BEGIN

lock Trip
lock Loading / relevant source
create DeliveryControl
calculate loss
create TransportDeduction if required
update Trip workflow
update order projection
create/update sale candidate
invalidate profitability projection
write audit/history

COMMIT
```

If any mandatory operation fails:

```text
ROLLBACK
```

Never leave:

```text
Delivery confirmed
but
transporter deduction failed
```

without explicit recovery mechanics.

---

# 14. Domain Events

The specification says one operation updates many related values.

A clean internal design can use domain/application events.

Example:

```text
DeliveryConfirmed
```

Consumers:

```text
LossCalculation
TransportDeduction
CustomerOrderProjection
SalesPreparation
TheoreticalStockProjection
TripProfitRecalculation
DashboardProjection
Audit
```

For V1, this does not require Kafka/RabbitMQ.

It may be implemented synchronously in a service layer.

Do not introduce distributed infrastructure before it is needed.

---

# 15. Concurrency Rules Claude Must Implement

Use `transaction.atomic()` and `select_for_update()` for high-risk operations.

At minimum evaluate locking for:

- loading against cession quantity;
- loading against supplier reliquat;
- assigning a truck to a new active trip;
- payment allocation;
- reversal/cancellation of validated financial transactions;
- account transfers if cached balances are stored.

---

# 16. Database Constraints

Business rules should be enforced as close to the database as reasonably possible.

Examples:

```text
quantity > 0
price >= 0
payment amount > 0
capacity > 0
```

Potential unique constraints:

```text
Trip.reference
CustomerOrder.reference
CessionLetter.reference
Invoice.reference
```

Truck registrations may need business-specific uniqueness rules.

Do not rely only on Vue validation.

---

# 17. Cancellation and Reversal

Mature ERP systems preserve history.

For operational/financial records use:

```text
DRAFT
VALIDATED
CANCELLED
REVERSED
```

rather than physical deletion after validation.

When a loading is cancelled:

- supplier reliquat must become available again;
- cession consumed quantity must decrease through effective-transaction calculation;
- audit must record cancellation.

When a payment is reversed:

- allocation must be undone;
- outstanding must recover;
- treasury movement must reverse correctly.

---

# 18. Testing Strategy Based on Real ERP Failure Modes

The hardest ERP bugs are not basic CRUD bugs.

They are:

- duplicate posting;
- incorrect balance after cancellation;
- race condition;
- stale cached total;
- incorrect payment allocation;
- inconsistent margin;
- repeated event execution.

Claude must prioritize transactional tests.

---

## 18.1 Mandatory Business Tests

### Truck reuse

```text
Truck A -> Trip 1
Trip 1 completed
Truck A -> Trip 2
```

Both histories remain independent.

### Same order, repeated truck

```text
Order 450,000 L
Truck A executes Trip 1 and Trip 7
```

### Cession over-allocation

Two concurrent load requests must never exceed authorized quantity.

### Supplier reliquat

```text
Purchased 1,000,000
Loaded 990,000
Reliquat 10,000
```

Cancellation of a 45,000 L loading must restore availability.

### Loss

```text
Loaded 45,000
Received 44,850
Loss 150
Tolerance 100
Chargeable 50
```

### Transporter deduction

```text
50 * 850 FCFA = 42,500 FCFA
```

### Payment allocation

One payment across several invoices.

### Partial payment

Several payments against one invoice.

### Customer advance

Payment not fully allocated remains credit.

### Indirect settlement

Customer pays customs directly:

- customer balance decreases;
- customs expense appears;
- bank/cash unchanged.

### Internal treasury transfer

Bank A -> Bank B:

- source decreases;
- destination increases;
- company profit unchanged.

### Margin recalculation

Adding a new trip expense changes margin immediately.

---

# 19. Vue / TypeScript Frontend Lessons

Frontend must reflect backend domain separation.

Suggested feature modules:

```text
src/
├── modules/
│   ├── dashboard/
│   ├── suppliers/
│   ├── purchases/
│   ├── cessions/
│   ├── customers/
│   ├── customer-orders/
│   ├── fleet/
│   ├── trips/
│   ├── deliveries/
│   ├── sales/
│   ├── invoices/
│   ├── finance/
│   ├── expenses/
│   ├── reports/
│   └── settings/
```

Do not build one giant ERP store.

Use API-generated/typed DTOs where possible.

---

# 20. Operational UX Patterns to Borrow from Fleetbase/VSD

Useful patterns:

- trip summary header;
- current status chip;
- chronological activity timeline;
- documents/proofs section;
- financial summary tab;
- quantity summary;
- exception/blocked state;
- explicit action buttons based on valid next status.

Example Trip screen:

```text
Trip TRP-0015
Truck: AA-123 / BB-456
Customer: Client X
Product: Gasoil
Loaded: 45,000 L
Received: 44,850 L
Loss: 150 L
Chargeable: 50 L
Status: CUSTOMS

[Overview]
[Timeline]
[Loading]
[Delivery]
[Expenses]
[Transport]
[Sale]
[Documents]
[Profit]
```

This is more maintainable than creating isolated screens for every minor event.

---

# 21. What Claude Must NOT Copy from Reference Systems

External projects are architecture references only.

Do not automatically copy:

- ERPNext Doctype names;
- Frappe permission architecture;
- Odoo ORM patterns;
- Fleetbase JavaScript backend structure;
- Open mSupply synchronization architecture;
- VROOM routing objects into core domain;
- accounting complexity excluded by V1.

The target stack remains:

```text
Frontend:
Vue.js + TypeScript

Backend:
Django + Django REST Framework

Database:
PostgreSQL
```

---

# 22. Source-of-Truth Hierarchy

When Claude sees a conflict:

```text
1. ERP_Specification.md
2. this implementation experience guide
3. external project behavior
4. generic framework convention
```

The specification always wins on business behavior.

---

# 23. Phase-by-Phase Reference Checklist

## Phase 1 — Foundation

Study:

- VSD master data separation;
- OCA Vehicle/Driver separation;
- ERPNext account/currency concepts.

Apply:

- clean masters;
- Decimal money/quantity;
- reusable truck;
- financial account currency;
- permissions.

---

## Phase 2 — Purchasing

Study:

- ERPNext transaction-driven stock/ledger thinking.

Apply:

- SupplierPurchase;
- CessionLetter;
- Loading allocation;
- derived reliquat;
- row locks;
- documents.

Custom domain remains authoritative.

---

## Phase 3 — Operations

Study:

- VSD cargo -> manifest -> vehicle -> trip;
- Fleetbase lifecycle/activity flows;
- OCA Vehicle/Route/Trip.

Apply:

- CustomerOrder != Trip;
- Truck != Trip;
- Trip status history;
- controlled transitions;
- repeated truck reuse;
- active-trip locking.

---

## Phase 4 — Delivery & Sales

Study:

- Fleetbase proof/timeline concepts;
- mature ERP validation/reversal discipline.

Apply:

- DeliveryControl;
- received quantity;
- loss;
- configurable tolerance;
- separate TransportDeduction;
- sale from received quantity;
- validated invoice audit.

---

## Phase 5 — Finance

Study heavily:

- ERPNext Payment Entry;
- payment references/allocations;
- reconciliation;
- Receive / Pay / Internal Transfer;
- multi-currency patterns.

Apply:

- payment allocation entities;
- advances;
- supplier/transporter ledgers;
- indirect settlement;
- treasury isolation;
- reversals.

---

## Phase 6 — Management

Study:

- VSD integrated operational/financial reporting;
- ERPNext ledger/report discipline;
- Fleetbase timeline/search UX.

Apply:

- trip profitability service;
- theoretical stock;
- query/report services;
- dashboard aggregates;
- PostgreSQL search;
- audit.

---

## Phase 7 — Hardening

Study:

- Open mSupply constrained-connectivity experience.

Apply:

- PWA;
- retry;
- safe drafts;
- idempotency;
- server-confirmed finance;
- backups;
- security;
- transactional tests.

Do not implement full offline synchronization yet.

---

# 24. External References

These links are for architecture study, not dependencies that must be installed.

## VSD Fleet Management

https://github.com/navariltd/Fleet-Management-System

Key concepts:

- cargo registration;
- manifest;
- vehicle assignment;
- trip execution;
- fund management;
- fuel management;
- financial settlement;
- multi-currency;
- audit;
- cross-border logistics.

---

## Fleetbase / FleetOps

https://github.com/fleetbase/fleetops

Key concepts:

- delivery order lifecycle;
- dispatch;
- routes;
- manifests;
- vehicle/driver assignment;
- configurable activity/status flows;
- files and proof;
- activity timeline.

---

## OCA Transport Management

https://github.com/OCA/stock-logistics-transport

Key concepts:

- Vehicle;
- Driver;
- Route;
- Trip;
- loading/unloading planning.

Use for domain inspiration only; check individual module maturity before considering code reuse.

---

## ERPNext

https://github.com/frappe/erpnext

Payment Entry implementation:

https://github.com/frappe/erpnext/blob/develop/erpnext/accounts/doctype/payment_entry/payment_entry.py

Payment Reconciliation:

https://github.com/frappe/erpnext/blob/develop/erpnext/accounts/doctype/payment_reconciliation/payment_reconciliation.py

Key concepts:

- payment allocation;
- outstanding balances;
- internal transfer;
- paid-from / paid-to accounts;
- account currencies;
- exchange rates;
- unallocated amounts;
- reconciliation;
- transaction-driven accounting.

---

## Open mSupply

https://github.com/msupply-foundation/open-msupply

Key concepts:

- mature logistics operations;
- web/mobile deployment;
- constrained environments;
- reliable transaction-oriented stock systems;
- PostgreSQL/SQLite support.

---

## VROOM

https://github.com/VROOM-Project/vroom

API:

https://github.com/VROOM-Project/vroom/blob/master/docs/API.md

Key concepts for future phases:

- vehicles;
- capacity;
- jobs;
- shipments;
- pickup/delivery;
- route optimization;
- time windows.

Do not make it part of the V1 transactional core.

---

# 25. Final Instructions to Claude Code

When implementing a phase:

1. Read the matching section of `ERP_Specification.md`.
2. Read the matching phase in this guide.
3. Identify invariants before creating models.
4. Create database constraints where possible.
5. Implement transactional domain services.
6. Keep DRF serializers/controllers thin.
7. Implement audit/history for sensitive operations.
8. Add concurrency protection where balances/resources can be consumed.
9. Add tests for cancellation and repeated execution.
10. Never let frontend calculations become financial source of truth.
11. Never collapse Truck, Trip and CustomerOrder.
12. Never create fake treasury movements for indirect customer-paid expenses.
13. Never invoice automatically from loaded quantity.
14. Never silently hide transporter loss deductions inside net transport cost.
15. Never make supplier reliquat depend only on a mutable balance field.
16. Never physically delete validated financial operations.
17. Keep V1 simple enough to ship, but preserve domain correctness.

---

# 26. Core Implementation Principle

The ERP must be implemented as a connected transactional system.

Example:

```text
Confirm Delivery
    |
    +--> DeliveryControl
    +--> received quantity
    +--> loss
    +--> chargeable loss
    +--> TransportDeduction
    +--> CustomerOrder delivered quantity
    +--> Sale / invoice quantity
    +--> theoretical stock
    +--> Trip profitability
    +--> Trip status history
    +--> audit
```

This chain must be consistent inside a reliable transaction boundary.

The goal is not to copy ERPNext, Fleetbase, Odoo or VSD.

The goal is to use the architectural experience of those systems while implementing the exact Senegal–Mali fuel trading workflow defined by `ERP_Specification.md`.

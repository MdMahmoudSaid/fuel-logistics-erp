1. Project Goal

Build a simple internal ERP for a fuel trading and transport company operating mainly between Senegal and Mali.

The system must manage the complete daily business flow:

Fuel Purchase → Cession Authorization → Loading → Truck Trip → Border/Customs → Delivery → Quantity Control → Customer Sale → Customer Payment → Transporter Payment → Expenses → Cash/Bank → Profit

The priority is not to reproduce Excel.

The priority is to make every business operation connected so that information is entered once and all related balances, quantities, debts and profits update automatically.

⸻

2. Core System Principle

The most important architecture rule is:

Truck ≠ Trip ≠ Client Order

These are three separate things.

Truck

A physical vehicle that can be reused many times.

Example:

Truck: AA-123 + Tanker BB-456

It can:

* complete Trip 001;
* return;
* complete Trip 002;
* return;
* complete Trip 003.

Its history must keep all trips separately.

Trip / Load

Every time fuel is loaded into a truck, create a new independent Trip/Load record.

Example:

Truck A:

* Trip 001 → 45,000 L → Client X
* Trip 007 → 45,000 L → Client X
* Trip 012 → 45,000 L → Client Y

Each trip has its own:

* quantity;
* loading;
* documents;
* expenses;
* delivery;
* loss;
* transporter cost;
* sale;
* payment status;
* margin.

Client Order

A customer may order several truckloads at once.

Example:

Client orders:

450,000 litres / approximately 10 truckloads

The order can be fulfilled using:

* Truck A → Trip 1
* Truck B → Trip 2
* Truck C → Trip 3
* Truck D → Trip 4
* Truck E → Trip 5
* Truck A returns → Trip 6
* Truck B returns → Trip 7
* etc.

The system must show:

Ordered: 450,000 L
Assigned: 450,000 L
Delivered: 315,000 L
Remaining: 135,000 L

A customer order must therefore support:

many trips + many trucks + repeated use of the same truck.

⸻

3. Main Modules

A. Dashboard

The management dashboard must immediately show:

Operations

* trucks currently loading;
* trucks loaded;
* trucks in transit;
* trucks at border;
* trucks at customs;
* trucks going to clients;
* trucks delivered;
* blocked trucks;
* trucks available again.

Fuel

* fuel purchased;
* fuel remaining with suppliers;
* fuel currently loaded in unsold trucks;
* theoretical fuel stock;
* litres sold;
* litres delivered;
* total losses.

Sales

* total sales;
* litres sold;
* number of deliveries;
* number of customer orders;
* customer payments received;
* customer outstanding balances.

Transport

* transport costs;
* transporter payments;
* outstanding transporter balances;
* advances;
* loss deductions.

Finance

* bank balances;
* cash balances;
* money received;
* money paid;
* expenses;
* supplier outstanding;
* customer outstanding;
* transporter outstanding.

Profit

* estimated margin;
* final margin;
* profit per trip;
* profit per truck;
* profit per customer;
* profit per order;
* total company profit.

Filters:

* today;
* yesterday;
* this week;
* month;
* year;
* custom dates.

⸻

4. Suppliers

Each supplier has:

* name;
* company name;
* country;
* telephone;
* contact;
* notes;
* documents;
* purchase history;
* payments;
* advances;
* outstanding balance.

Supplier account must show:

Total Purchased
Total Paid
Advances
Credit
Outstanding

⸻

5. Fuel Purchases

User creates a fuel purchase.

Fields:

* supplier;
* product;
* purchase date;
* quantity;
* price per litre;
* currency;
* total;
* optional costs;
* documents;
* notes;
* status.

Initial products:

* Gasoil;
* Essence.

Additional products can be added later.

Use decimal types capable of handling extremely large values.

Never use normal 32-bit integers for money.

Recommended:

DECIMAL / NUMERIC with large precision.

⸻

6. Cession Letters

A supplier order can have multiple cession letters.

A cession letter contains:

* reference;
* supplier order;
* authorized quantity;
* quantity already loaded;
* remaining quantity;
* issue date;
* document;
* notes;
* status.

Critical rule

A truck cannot load fuel unless enough authorized quantity exists.

Example:

Authorized: 200,000 L
Already loaded: 180,000 L
Remaining: 20,000 L

The system must not allow another 45,000 L loading.

⸻

7. Supplier Reliquat

Unused purchased fuel must never disappear.

Example:

Purchased: 1,000,000 L
Loaded: 990,000 L

Remaining:

10,000 L

That quantity stays available in the supplier account.

It can later be used for another loading.

⸻

8. Trucks

Each truck record contains:

* internal ID;
* tractor registration;
* tanker registration;
* capacity;
* ownership type;
* owner/transporter;
* optional driver;
* status;
* documents;
* notes.

Ownership types:

* COMPANY_OWNED
* EXTERNAL / RENTED

A truck can perform unlimited trips.

Never permanently attach a truck to one customer or one order.

⸻

9. Transporters / Truck Owners

External truck owners or transport companies need their own financial account.

Fields:

* name/company;
* phone;
* address;
* trucks;
* documents;
* active/inactive.

Account shows:

* trips completed;
* transport earned;
* deductions;
* advances;
* payments;
* outstanding balance.

⸻

10. Drivers

Driver information should be optional.

Fields:

* name;
* phone;
* licence;
* documents;
* history.

A missing driver must not block operations.

If the company pays drivers separately, support a driver ledger.

Do not assume driver = truck owner.

⸻

11. Client Orders

Customer orders must be optional.

A client can either:

Method A

Create a large order before assigning trucks.

Example:

Client orders:

450,000 L

Then trucks/trips are gradually assigned.

Method B

Create a direct sale/delivery without a previous customer order.

For an order, track:

* client;
* product;
* quantity ordered;
* expected price;
* assigned quantity;
* loaded quantity;
* delivered quantity;
* invoiced quantity;
* remaining quantity;
* status.

Statuses:

* Draft
* Confirmed
* Partially Assigned
* In Progress
* Partially Delivered
* Delivered
* Closed
* Cancelled

⸻

12. Loading / Trip Creation

Whenever a truck is loaded, generate a new Trip / Load.

Trip fields:

* internal reference;
* truck;
* tanker;
* transporter;
* driver;
* supplier;
* purchase order;
* cession letter;
* product;
* quantity loaded;
* client;
* customer order if applicable;
* loading date;
* BL;
* documents;
* status.

A physical truck can only have one active trip at a time unless the administrator explicitly overrides it.

When the trip is completed and the truck returns, that same truck becomes available and can create a new trip.

⸻

13. Trip Status Tracking

Possible statuses:

1. Assigned
2. Sent for Loading
3. Loading
4. Loaded
5. In Transit
6. Border
7. Customs
8. Going to Client
9. Arrived at Client
10. Quantity Control
11. Delivered
12. Completed
13. Blocked
14. Cancelled

Every status change must save:

* previous status;
* new status;
* user;
* date/time;
* notes.

Never overwrite the historical status.

⸻

14. Quantity Control

When the truck arrives:

Record:

* quantity loaded;
* quantity actually received;
* date;
* controller;
* method;
* document/photo;
* notes.

Formula

LOSS = LOADED QUANTITY - RECEIVED QUANTITY

Example:

Loaded: 45,000 L
Received: 44,850 L

Loss:

150 L

⸻

15. Loss Tolerance

Default tolerance:

100 litres

Must be configurable.

Example:

Loss: 150 L
Tolerance: 100 L

Chargeable loss:

50 L

If received quantity > loaded quantity:

show an alert and require authorized confirmation.

⸻

16. Transporter Loss Deduction

Any non-tolerated loss is charged to the transporter/truck owner.

Calculation:

Chargeable Loss × Customer Selling Price

Example:

50 L × 850 FCFA

Deduction:

42,500 FCFA

Transport cost:

700,000

Transporter net amount:

657,500

This deduction must appear clearly in the transporter ledger.

⸻

17. Transport Cost

Transport payment may vary.

Support:

* fixed amount per trip;
* price per litre;
* price per day;
* manually entered negotiated price;
* future configurable methods.

Do not hard-code one payment method.

Transport is normally payable after delivery but should support:

* advance;
* partial payment;
* full payment.

Statuses:

* Planned
* Payable
* Partially Paid
* Paid
* Deduction Applied

⸻

18. Customers

Each customer has:

* name/company;
* phone;
* address;
* contacts;
* orders;
* trips/deliveries;
* invoices;
* payments;
* advances;
* credit;
* outstanding balance;
* documents.

Customer account can be:

* customer owes company;
* company owes customer / customer has credit.

⸻

19. Sales

A sale is linked to:

* customer;
* trip;
* product;
* delivered quantity;
* selling price;
* customer order if applicable;
* invoice.

Critical rule

Customer is charged on the actual quantity received.

Example:

Loaded:

45,000 L

Received:

44,850 L

Invoice quantity:

44,850 L

Never automatically invoice 45,000 L.

⸻

20. Selling Price

Remember the last selling price per product.

When creating a new sale:

* suggest previous price;
* authorized user may modify it;
* save new price as latest price;
* preserve price-change history.

⸻

21. Customer Invoices

Invoice states:

* Draft
* Validated
* Partially Paid
* Paid
* Cancelled

A validated invoice cannot be silently edited.

Changes require:

* previous value;
* new value;
* user;
* date;
* reason.

⸻

22. Customer Payments

A customer invoice can receive unlimited payments.

Example:

Invoice:

40,000,000

Payment 1:

10,000,000

Payment 2:

15,000,000

Outstanding:

15,000,000

Support:

* cash;
* bank transfer;
* cheque;
* other.

Each payment records:

* amount;
* date;
* bank/cash account;
* reference;
* document;
* user.

⸻

23. Customer Ledger

For every customer display:

* invoices;
* deliveries;
* payments;
* advances;
* credits;
* outstanding;
* date of each operation.

Example:

Total invoiced: 500M
Total paid: 350M

Outstanding:

150M

⸻

24. Customer Payment Across Multiple Deliveries

A customer may make one payment that covers several truck deliveries.

The system must support payment allocation to:

* one invoice;
* several invoices;
* customer general balance.

Do not require one payment per truck.

⸻

25. Customer Pays Expense Directly

Support indirect payment.

Example:

Customer owes company:

50M

Customer directly pays customs:

5M

System must:

* record customs expense;
* record customer contribution/payment;
* reduce customer balance by 5M;
* identify affected trucks if needed;
* NOT create fake company bank/cash movement.

⸻

26. Expenses

Allow unlimited expense transactions.

Initial categories:

* customs;
* import intention;
* transport;
* loading;
* unloading;
* road expenses;
* administration;
* rent;
* salary;
* repairs;
* bank charges;
* other.

Expenses may be linked to:

* purchase;
* cession;
* trip;
* truck;
* customer;
* supplier;
* transporter;
* company.

Statuses:

* Unpaid
* Partially Paid
* Paid
* Cancelled

⸻

27. Expense Calculation

Costs must support several calculation methods:

* fixed amount;
* per litre;
* percentage;
* per order;
* per truck;
* manual.

Do not assume every expense is calculated per litre.

⸻

28. Banks and Cash

Create separate financial accounts.

Examples:

* Bank A
* Bank B
* Main Cash
* Secondary Cash

Each account has:

* currency;
* opening balance;
* current balance;
* transaction history.

⸻

29. Treasury Movements

Every real company cash movement records:

* account;
* date;
* type;
* amount;
* reference;
* source operation;
* document;
* user.

Types:

* Money In
* Money Out
* Transfer

Internal transfer:

Bank A → Bank B

must NOT be counted as:

* revenue;
* expense;
* profit.

⸻

30. Supplier Payments

Support:

* advance;
* partial payments;
* multiple payments;
* outstanding supplier balance;
* supplier credit.

Supplier ledger must update automatically.

⸻

31. Transporter Payments

Each transporter has:

* transport earned;
* advances;
* loss deductions;
* payments;
* remaining balance.

Example:

Transport earned:

5,000,000

Advances:

1,000,000

Deductions:

200,000

Paid later:

2,000,000

Outstanding:

1,800,000

⸻

32. Theoretical Fuel Stock

There is no normal physical warehouse assumption.

Official calculation:

THEORETICAL STOCK = UNSOLD FUEL IN TRUCKS + UNLOADED FUEL REMAINING WITH SUPPLIERS

Dashboard shows separately:

* fuel with suppliers;
* fuel in loaded unsold trucks;
* total theoretical stock.

⸻

33. Trip Profit / Margin

Every trip must have its own profit calculation.

Example:

Revenue
− fuel purchase cost
− customs
− transport
− other allocated costs
= trip margin

Show:

* estimated margin;
* recalculated margin;
* final margin.

If a new expense is added later, margin recalculates automatically.

⸻

34. Profit Reporting

Allow management to see:

* profit per trip;
* profit per truck;
* profit per client;
* profit per customer order;
* profit per supplier order;
* profit per litre;
* total profit;
* profit by date range.

⸻

35. Documents

Support:

* PDF;
* image;
* scan;
* receipt;
* invoice;
* BL;
* cession letter;
* customs documents;
* payment proof;
* contracts.

Documents can be attached to:

* supplier;
* purchase;
* cession;
* truck;
* trip;
* delivery;
* customer;
* invoice;
* payment;
* transporter;
* expense.

⸻

36. Global Search

Allow searching by:

* tractor registration;
* tanker registration;
* customer;
* supplier;
* transporter;
* BL;
* invoice;
* order;
* cession letter;
* trip reference.

Searching a truck should immediately show:

* current status;
* current trip;
* product;
* quantity;
* customer;
* location/status;
* complete history.

⸻

37. Reports

V1 reports:

* customer statement;
* supplier statement;
* transporter statement;
* truck history;
* trip report;
* purchase report;
* sales report;
* expense report;
* customer outstanding report;
* supplier outstanding report;
* transporter outstanding report;
* fuel stock report;
* loss report;
* margin/profit report;
* bank statement;
* cash statement.

Exports:

* Excel;
* PDF;
* CSV where useful.

⸻

38. Users and Roles

Initial roles:

Admin

Full access.

Management

Dashboard, operations, sales, finance, reports.

Operations

Trucks, loading, status updates, deliveries, quantity controls, documents.

Finance

Payments, expenses, customers, suppliers, transporters, banks, cash, reports.

Permissions should support:

* View
* Create
* Edit
* Validate
* Cancel
* Export

⸻

39. Audit History

Important operations must be traceable.

Store:

* user;
* date/time;
* previous value;
* new value;
* action;
* object;
* reason where required.

Priority:

* quantities;
* prices;
* payments;
* expenses;
* invoices;
* losses;
* bank/cash movements.

Validated financial transactions should not be physically deleted.

Use:

* cancellation;
* reversal;
* correction.

⸻

40. Access and Devices

The system should work on:

* Windows computers;
* laptops;
* phones;
* tablets;
* iPhone;
* Android.

Recommended V1:

Responsive Web App / PWA

This keeps deployment simple and allows management to access the system from anywhere.

Architecture:

Frontend:
Vue.js + TypeScript

Backend:
Django + Django REST Framework

Database:
PostgreSQL

Document storage:
secure cloud/object storage.

⸻

41. Weak Internet Support

Do not build the full complex Tauri + SQLite synchronization engine in V1 unless proven necessary.

Instead:

* responsive PWA;
* lightweight pages;
* local caching;
* retry failed requests;
* operational drafts where possible;
* offline queue for selected non-financial actions if needed.

Financial validation should preferably require server confirmation.

Full offline synchronization can become Phase 2 if genuinely required.

⸻

42. Important Database Relationships

Core entities:

* User
* Role
* Product
* Supplier
* SupplierOrder
* CessionLetter
* Customer
* CustomerOrder
* Truck
* Transporter
* Driver
* Trip
* TripStatusHistory
* Loading
* DeliveryControl
* Sale
* Invoice
* CustomerPayment
* SupplierPayment
* TransportPayment
* Expense
* ExpenseAllocation
* BankAccount
* CashAccount
* TreasuryTransaction
* Document
* AuditLog

Critical relationships:

CustomerOrder

has many → Trips

Truck

has many → Trips

Trip

belongs to one physical truck

Trip

may belong to one CustomerOrder

CustomerOrder

may use the same truck multiple times through different trips.

This must be implemented correctly.

⸻

43. Main Business Workflow

Purchase

Supplier
→ Purchase Order
→ Quantity
→ Price
→ Cession Letter
→ Authorized Quantity

Loading

Select Truck
→ Create New Trip
→ Assign Cession
→ Load Quantity
→ Reduce Supplier Available Quantity

Transport

Loaded
→ Transit
→ Border
→ Customs
→ Client

Delivery

Arrival
→ Quantity Control
→ Actual Quantity Received
→ Loss Calculation
→ Transport Deduction if required

Sale

Client
→ Delivered Quantity
→ Selling Price
→ Invoice

Customer Finance

Invoice
→ Payment(s)
→ Outstanding Balance

Transport Finance

Transport Cost
→ Deduction
→ Advance
→ Payment(s)
→ Outstanding Balance

Business Result

Revenue
− Product Cost
− Transport
− Customs
− Other Expenses
= Profit

⸻

44. Example: Client Orders 10 Truckloads

Client X orders:

450,000 L

Available fleet:

6 trucks.

First round

Truck A → 45,000
Truck B → 45,000
Truck C → 45,000
Truck D → 45,000
Truck E → 45,000
Truck F → 45,000

Delivered:

270,000 L

Remaining order:

180,000 L

Trucks return.

Second round

Truck A → new Trip
Truck B → new Trip
Truck C → new Trip
Truck D → new Trip

Another:

180,000 L

Final:

Ordered: 450,000
Delivered: 450,000
Remaining: 0

Order status:

Completed

Truck A now has two completely separate trips in its history.

This scenario is mandatory and must be tested.

⸻

45. What NOT to Build in V1

Do not include unless separately approved:

* shareholder management;
* shareholder contribution valuation;
* profit distribution to shareholders;
* fiscal-year closing;
* advanced accounting journal;
* advanced bank reconciliation;
* full desktop offline synchronization engine;
* complex conflict-resolution system;
* AI;
* live GPS tracking;
* WhatsApp automation;
* predictive analytics;
* macOS/Linux native desktop applications.

Architecture should allow these later without requiring the core system to be rewritten.

⸻

46. Development Phases

Phase 1 — Foundation

Build:

* authentication;
* users;
* roles;
* products;
* suppliers;
* customers;
* transporters;
* trucks;
* banks;
* cash accounts.

Phase 2 — Purchasing

Build:

* supplier orders;
* purchase quantities;
* cession letters;
* supplier reliquat;
* supplier ledger;
* documents.

Phase 3 — Truck Operations

Build:

* customer orders;
* trip/load creation;
* repeated truck trips;
* loading;
* truck status tracking;
* border/customs stages;
* trip history.

Phase 4 — Delivery & Sales

Build:

* quantity control;
* loss/tolerance;
* transporter deductions;
* delivery;
* sales;
* invoices;
* customer balances.

Phase 5 — Finance

Build:

* customer payments;
* supplier payments;
* transporter payments;
* advances;
* expenses;
* indirect customer payments;
* banks/cash;
* outstanding balances.

Phase 6 — Management

Build:

* profit engine;
* theoretical stock;
* dashboard;
* reports;
* search;
* exports;
* audit history.

Phase 7 — Production Hardening

Complete:

* responsive/mobile optimization;
* weak-internet handling;
* security;
* backups;
* permissions;
* testing;
* deployment;
* user acceptance testing.

⸻

47. Mandatory Tests

Developer must test at minimum:

Multiple Trucks

One client order fulfilled by 10 different trucks.

Repeated Truck

One physical truck completes two separate trips against the same order.

Partial Delivery

Customer order partially delivered over several days.

Quantity Loss

45,000 loaded → 44,850 received.

Transport Deduction

Loss above tolerance correctly reduces transporter balance.

Partial Customer Payment

Invoice partially paid several times.

Transporter Advance

Advance deducted correctly from transporter outstanding.

Supplier Reliquat

Purchased fuel not yet loaded remains available.

Customer Indirect Payment

Customer pays customs directly without changing bank balance incorrectly.

Financial Transfer

Bank-to-bank transfer does not affect profit.

Margin

New expense added after delivery automatically changes trip margin.

⸻

48. Acceptance Criteria

V1 is complete when the company can perform the following without Excel:

1. Register a fuel purchase.
2. Register supplier quantity.
3. Add cession letters.
4. See supplier remaining quantity.
5. Register trucks and transporters.
6. Create a customer order for several truckloads.
7. Assign several trucks to that order.
8. Reuse the same physical truck for another trip.
9. Track every trip independently.
10. Track border/customs/delivery status.
11. Record actual delivered quantity.
12. Automatically calculate loss.
13. Calculate transporter deductions.
14. Invoice based on received quantity.
15. Record multiple customer payments.
16. See customer outstanding balance.
17. Record transport costs and payments.
18. See transporter outstanding balance.
19. Record supplier payments.
20. Record unlimited expenses.
21. Track banks and cash.
22. Calculate theoretical stock.
23. Calculate margin per trip.
24. Calculate total business profit.
25. Search any truck/client/order/payment.
26. Export the important statements.
27. Use the system securely from computer and phone.

⸻

49. Final Product Principle

The developer must not build isolated screens.

Every operation must update all relevant connected information.

Example:

When Trip 015 is delivered:

* truck status changes;
* delivered litres update;
* client order delivered quantity updates;
* customer invoice is calculated;
* loss is calculated;
* transporter deduction is calculated;
* transporter balance updates;
* theoretical stock updates;
* sales update;
* margin recalculates;
* dashboard updates.

The purpose of the system is:

one source of truth for the entire daily operation.

Management should always be able to answer:

* Where is every truck?
* How much fuel do we control?
* How much has been delivered?
* How much does each customer owe us?
* How much do we owe suppliers?
* How much do we owe transporters?
* What expenses have we paid?
* How much money is in the banks/cash?
* How much did each trip make?
* What is the real profit of the business?

That is the V1 that should be built first.
# Attribution directe d'un client depuis Ventes — design

Date: 2026-11-02. Language of the UI: fr/en/ar (all new strings in the three locales).

## Intent and why

Today "Attribuer un client" (Ventes page) only links a stocked/customs trip to a customer and sends the operator back to the trip page, where they must manually move the status to "Arrivé chez le client" before the delivery form (Prix de revient, selling price) appears. The operator wants the whole sale set up from the popup: pick the customer (registered or walk-in), see the cost price, type the selling price, see profit/loss live, optionally enter the received quantity, and get the invoice.

## Behaviour

### 1. Popup (Ventes > Attribuer un client), after the trips are picked
- Customer select gains a "Client de passage" option (walk-in: unregistered, pays the full amount in cash). Choosing it shows one text field, the name, which is printed on the invoice.
- Once a customer (registered or walk-in) is chosen, show a single line **Prix de revient** (total per litre). An eye icon next to it expands the full cost breakdown (the existing per-litre components: supplier price, carrier commission, road transit, transit, border, customs, loading, other fees).
- A "Prix de vente" per-litre input, prefilled from the existing customer selling-price suggestion when one exists. Live per-litre profit/loss (and total) under it. The existing below-cost "vente à perte" confirmation still applies.
- When several trips are selected (one invoice), there is ONE selling price per litre for all of them (builder may assume same product; if products differ, one price per product — implementer's call). Cost shown is the per-trip cost basis; for several trips show the quantity-weighted figure.
- Quantity step: per trip, "Quantité reçue" defaulting to the loaded quantity, optional.
- Buttons: confirm with quantity, or save without quantity ("Quantité plus tard").
- Walk-in only: when the quantity is confirmed, the user picks the payment account (bank or cash, same picker used by customer payments); nothing else is asked (method follows the account type).

### 2. One atomic operation on submit
Link customer + treat the trip as arrived at the client (no manual "Arrivé chez le client" step any more for a trip that has a customer) + store the selling price. If the quantity is given in the same submit, also run the delivery (Sale + DRAFT invoice via the existing DeliveryService.record_delivery) and, for a walk-in, record a full cash CustomerPayment allocated to that invoice. All or nothing.

### 3. Deferred quantity
If submitted without quantity: the trip stays at ARRIVED_AT_CLIENT with customer + selling price stored, no Sale, no invoice yet. It remains visible as a row "En attente de quantité reçue" in the Ventes list and on the Trajets page, with a button "Saisir la quantité reçue" that opens the quantity step (plus the account picker for a walk-in). Confirming runs the delivery, creates the invoice and, for a walk-in, the full cash payment.

### 4. Removing the manual arrival step
A trip with a customer is considered arrived: the status board / allowed-targets must no longer require the operator to press "Arrivé chez le client" from CUSTOMS / STOCKED paths that now go through the popup. The existing manual path via TripDetail may stay working (backward compatibility) but is no longer needed.

### 5. Walk-in customer
Modelled as a hidden Customer row flagged walk-in, created per sale with the typed name (so Sale/Invoice/ledger code keeps working unchanged), excluded from the customers list, customer selects and customer reports; its single invoice is fully paid at creation so it never shows as a receivable. (Implementer's call: flag + per-sale row; alternative of one shared row would lose the name per invoice.)

## Goals
- Sale set up in one popup, no detour to the trip page.
- Price and profit visible immediately; breakdown one click away.
- Walk-in cash sale leaves no receivable and posts to treasury.

## Non-goals
- No change to the margin/distributable-result formulas, invoice numbering, or client verification (loss) flow.
- No partial payments for walk-ins; no walk-in follow-up screens.

## Anti-goals (failure even if it "works")
- A walk-in appearing in the customers list or receivables.
- A half-done state (customer linked but status/price lost) after an error.
- Invoice billing the loaded quantity when a different received quantity was entered.
- Breaking existing delivery/verification/refusal flows or their tests.

## Constraints
- Reuse DeliveryService.record_delivery, TripCostService.calculate_trip_cost_basis, CustomerPayment + PaymentAllocationService, existing price-history behaviour. Migrations are fuel-deploy-migrated; old prod specs must still type-check.
- Stage explicit files only; backend and frontend suites must stay green.

## Left to the builder
Field names/migration shape for the stored pending price and walk-in flag, endpoint design (single new endpoint vs extending assign-customers), the exact cost-weighting for multi-trip display, and how the pending row is listed in Ventes.

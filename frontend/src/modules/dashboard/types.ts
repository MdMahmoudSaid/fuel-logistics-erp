// Mirrors backend/apps/reports/views/dashboard.py's DashboardViewSet.summary()
// response shape (docs/PHASE_6_PLAN.md Etape 5/7). Money/quantity fields
// arrive as strings (apps.reports.serialization.decimals_to_str keeps
// Decimal precision exact rather than letting DRF coerce to float).
export interface DashboardSummary {
  date_from: string | null
  date_to: string | null
  operations: {
    trips_count: number
    active_trips_count: number
    delivered_trips_count: number
  }
  fuel: {
    quantity_loaded: string
    theoretical_stock: string
  }
  sales: {
    sales_count: number
    revenue: string
  }
  transport: {
    settlements_count: number
    transport_cost: string
  }
  finance: {
    expenses_total: string
    treasury_balance: string
  }
  profit: {
    total_margin: string
  }
  // Point-in-time "currently outstanding" snapshots (total minus paid, as
  // of now) - unlike the sections above, these are NOT scoped by the
  // date_from/date_to range (backend/apps/reports/views/dashboard.py).
  debts: {
    total: string
    suppliers: { total: string; rows: { supplier: string; outstanding: string }[] }
    transporters: { total: string; rows: { transporter: string; outstanding: string }[] }
    customs: string
    transit: string
    road_transit: string
    other: string
  }
  customer_amounts: {
    total: string
    rows: { customer: string; outstanding: string }[]
  }
  bank_amounts: {
    total: string
    rows: { bank: string; balance: string }[]
  }
  cash_amounts: {
    total: string
    rows: { cash_account: string; balance: string }[]
  }
  // Summary only (design doc 2026-08-26-benefices-associes-refinement-
  // design.md) - point-in-time like debts/customer_amounts above, not
  // scoped by date_from/date_to. The Benefices page (/profit) stays the
  // single detailed source; this is never broken down per trip or
  // per shareholder.
  shareholders_summary: {
    current_profit: string
    // Client modifications (2026-09-04): distributable_result replaces the
    // old total_capital_contributed/profit_after_capital pair entirely -
    // single source of truth is ShareholderProfitPreviewService, reused here
    // rather than a second, possibly divergent computation.
    distributable_result: string
    total_withdrawn: string
    remaining_undistributed: string
    open_loans_total: string
  }
  financial_summary: {
    period_revenue: string
    period_collections: string
    period_paid_expenses: string
    period_treasury_in: string
    period_treasury_out: string
    // Trips-only operational profit for the period - kept for other
    // consumers (page Benefices), no longer the dashboard's headline
    // figure (see period_net_profit).
    period_accounting_profit: string
    // Dashboard recette fix (2026-09-04): operational profit minus
    // general expenses actually paid in the period - the dashboard's
    // headline profit card.
    period_net_profit: string
    current_treasury_balance: string
  }
  party_balances: {
    customers: {
      balance: string
      open_count: number
      largest_open: { name: string; amount: string } | null
    }
    suppliers: {
      balance: string
      open_count: number
      largest_open: { name: string; amount: string } | null
    }
    transporters: {
      balance: string
      open_count: number
      largest_open: { name: string; amount: string } | null
    }
    shareholders: {
      balance: string
      remaining_undistributed: string
      total_withdrawn: string
      open_loans_total: string
    }
    customs_and_other: {
      balance: string
      customs: string
      transit: string
      road_transit: string
      other: string
    }
  }
  // "Fond de roulement client" (docs/superpowers/specs/2026-09-04-recette-
  // corrections-design.md, Section 3) - WorkingCapitalService.get_working_capital(),
  // the same single source of truth ShareholderProfitPreviewService's
  // distributable_result uses. A management indicator, NOT the accounting
  // fonds de roulement. Confirmed via actual client recette testing (third
  // pass, 2026-09-04): open debts are ADDED, not subtracted - gross =
  // treasury_available + customer_receivables; total = gross + the 3 debt
  // buckets. Capital is informational only (not part of gross/total).
  // Point-in-time, like debts/party_balances above.
  working_capital: {
    capital: string
    treasury_available: string
    customer_receivables: string
    supplier_debt_total: string
    transporter_debt_total: string
    other_debts: string
    gross: string
    total: string
  }
  company_stock: {
    total_quantity: string
    trips_count: number
    by_product: { product: string; quantity: string }[]
    trips: {
      id: number
      reference: string
      truck: string
      supplier: string
      transporter: string
      product: string
      remaining_quantity: string
      entry_date: string
      status: string
    }[]
  }
  action_items: {
    kind: string
    label: string
    target: string
    object_id: number
    reference: string
  }[]
}

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
}

// Mirrors backend/apps/reports/views/search.py's SearchView response shape
// (docs/PHASE_6_PLAN.md Etape 5/8; ERP_Implementation_Experience_Guide.md
// Section 9.8).
export interface SearchTruckResult {
  id: number
  internal_id: string
  tractor_registration: string
  tanker_registration: string
  current_trip: {
    reference: string
    status: string
    product: string
    quantity_loaded: string
    client: string | null
  } | null
}

export interface SearchNamedResult {
  id: number
  name: string
}

export interface SearchTripResult {
  id: number
  reference: string
  status: string
  product: string
}

export interface SearchInvoiceResult {
  id: number
  invoice_number: string
  status: string
}

export interface SearchOrderResult {
  id: number
  status: string
  quantity_ordered: string
}

export interface SearchCessionResult {
  id: number
  reference: string
  status: string
}

export interface SearchResults {
  trucks: SearchTruckResult[]
  customers: SearchNamedResult[]
  suppliers: SearchNamedResult[]
  transporters: SearchNamedResult[]
  trips: SearchTripResult[]
  invoices: SearchInvoiceResult[]
  orders: SearchOrderResult[]
  cessions: SearchCessionResult[]
}

// Mirrors backend/apps/trips/serializers.py. DRF DecimalField quantities are
// serialized as strings (never float) — convert with Number(...) only where
// arithmetic is needed.

// The 14 statuses from spec §13 / backend/apps/trips/models.py Trip.Status.
// Valid next-transitions are decided exclusively by TripWorkflowService on
// the backend (guide §6.9: "Do not hard-code workflow rules in Vue") — the
// UI offers every status and surfaces whatever the server rejects, rather
// than duplicating the transition table here.
export type TripStatus =
  | 'ASSIGNED'
  | 'SENT_FOR_LOADING'
  | 'LOADING'
  | 'LOADED'
  | 'IN_TRANSIT'
  | 'BORDER'
  | 'CUSTOMS'
  | 'GOING_TO_CLIENT'
  | 'ARRIVED_AT_CLIENT'
  | 'QUANTITY_CONTROL'
  | 'DELIVERED'
  | 'COMPLETED'
  | 'BLOCKED'
  | 'CANCELLED'

export const TRIP_STATUSES: TripStatus[] = [
  'ASSIGNED',
  'SENT_FOR_LOADING',
  'LOADING',
  'LOADED',
  'IN_TRANSIT',
  'BORDER',
  'CUSTOMS',
  'GOING_TO_CLIENT',
  'ARRIVED_AT_CLIENT',
  'QUANTITY_CONTROL',
  'DELIVERED',
  'COMPLETED',
  'BLOCKED',
  'CANCELLED',
]

// Pipeline linéaire de l'affectation à la livraison, utilisé pour la jauge
// de progression (TripCard) et pour repérer les trajets "en route" sur le
// Dashboard. BLOCKED/CANCELLED sortent de ce pipeline (traités à part).
export const TRIP_PIPELINE_STATUSES: TripStatus[] = [
  'ASSIGNED',
  'SENT_FOR_LOADING',
  'LOADING',
  'LOADED',
  'IN_TRANSIT',
  'BORDER',
  'CUSTOMS',
  'GOING_TO_CLIENT',
  'ARRIVED_AT_CLIENT',
  'QUANTITY_CONTROL',
  'DELIVERED',
]

// "En route maintenant" (Dashboard) = pipeline hors trajets déjà livrés.
export function isTripEnRoute(status: TripStatus): boolean {
  return TRIP_PIPELINE_STATUSES.includes(status) && status !== 'DELIVERED'
}

export type TruckStatus = 'AVAILABLE' | 'ON_TRIP' | 'BLOCKED'

export interface TruckBrief {
  id: number
  internal_id: string
  tractor_registration: string
  tanker_registration: string
  capacity_litres: string
  status: TruckStatus
  owner_transporter: number | null
  default_driver: number | null
}

export interface TransporterBrief {
  id: number
  name: string
}

export interface DriverBrief {
  id: number
  name: string
}

export interface SupplierBrief {
  id: number
  name: string
}

export interface ProductBrief {
  id: number
  name: string
  code: string
}

export interface CustomerBrief {
  id: number
  name: string
}

export interface UserBrief {
  id: number
  email: string
  full_name: string
}

export interface Trip {
  id: number
  reference: string
  truck: number
  truck_detail: TruckBrief | null
  transporter: number
  transporter_detail: TransporterBrief | null
  driver: number | null
  driver_detail: DriverBrief | null
  supplier: number
  supplier_detail: SupplierBrief | null
  supplier_order: number
  cession_letter: number
  product: number
  product_detail: ProductBrief | null
  quantity_loaded: string
  client: number | null
  client_detail: CustomerBrief | null
  customer_order: number | null
  loading_date: string
  bl_reference: string
  status: TripStatus
  notes: string
  created_by: number | null
  created_by_detail: UserBrief | null
  // Write-only on the backend (never present in a response) — an
  // Admin-only override accepted on create/update when the truck already
  // has an active trip (backend/apps/trips/serializers.py).
  force?: boolean
  created_at: string
  updated_at: string
}

export interface TripStatusHistoryEntry {
  id: number
  trip: number
  previous_status: string
  new_status: string
  changed_by: number
  changed_by_detail: UserBrief | null
  changed_at: string
  notes: string
}

// Mirrors GET /api/trips/{id}/margin/ (backend/apps/trips/views.py
// TripViewSet.margin, delegating to TripProfitService.get_cost_breakdown) -
// only available once the trip has a Sale (delivery confirmed).
export interface TripMarginBreakdown {
  available: true
  revenue: string
  fuel_purchase_cost: string
  transport_cost: string
  expenses_by_category: Record<string, string>
  total_expenses: string
  margin: string
}
export interface TripMarginUnavailable {
  available: false
}
export type TripMargin = TripMarginBreakdown | TripMarginUnavailable

// Mirrors backend/apps/trips/models.py DeliveryControl.Method.
export type DeliveryMethod = 'MANUAL_GAUGE' | 'METER'

export interface DeliveryControl {
  id: number
  trip: number
  loaded_quantity: string
  received_quantity: string
  loss_quantity: string
  chargeable_loss_quantity: string
  tolerance_quantity: string
  control_date: string
  controller: number
  controller_detail: UserBrief | null
  method: DeliveryMethod
  document: number | null
  notes: string
  anomaly_confirmed_by: number | null
  anomaly_confirmed_by_detail: UserBrief | null
  anomaly_confirmed_at: string | null
  created_at: string
  updated_at: string
}

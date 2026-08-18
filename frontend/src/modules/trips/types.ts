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

// Mirrors backend/apps/trips/serializers.py. DRF DecimalField quantities are
// serialized as strings (never float) — convert with Number(...) only where
// arithmetic is needed.
import type { CessionLetter } from '@/modules/purchasing/types'

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
  | 'ROAD_TRANSIT'
  | 'IN_TRANSIT'
  | 'BORDER'
  | 'CUSTOMS'
  | 'GOING_TO_COMPANY_STOCK'
  | 'ARRIVED_AT_COMPANY_STOCK'
  | 'STOCKED'
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
  'ROAD_TRANSIT',
  'IN_TRANSIT',
  'BORDER',
  'CUSTOMS',
  'GOING_TO_COMPANY_STOCK',
  'ARRIVED_AT_COMPANY_STOCK',
  'STOCKED',
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
  'ROAD_TRANSIT',
  'IN_TRANSIT',
  'BORDER',
  'CUSTOMS',
  'GOING_TO_COMPANY_STOCK',
  'ARRIVED_AT_COMPANY_STOCK',
  'STOCKED',
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

// Phase 6 (docs/superpowers/specs/2026-09-02-business-corrections-6-phases-
// design.md): EXTERNAL always has owner_transporter (backend-enforced);
// COMPANY_OWNED never does - no artificial "internal transporter".
export type TruckOwnershipType = 'COMPANY_OWNED' | 'EXTERNAL'

export interface TruckBrief {
  id: number
  internal_id: string
  tractor_registration: string
  tanker_registration: string
  capacity_litres: string
  status: TruckStatus
  ownership_type: TruckOwnershipType
  owner_transporter: number | null
  default_driver: number | null
}

export interface TransporterBrief {
  id: number
  name: string
  // Bug fix (2026-09-03 recette manuelle): the seeded "Flotte propre /
  // Interne" transporter, standing in for a company-owned truck's trip -
  // never a real payee (no TransportPayment/commission popup for it).
  is_internal?: boolean
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

// Mirrors backend/apps/trips/models.py Trip.DestinationType. Server-derived
// only (TripSerializer._normalize_destination_type): CUSTOMER whenever
// either `client` or `customer_order` is set, COMPANY_STOCK otherwise - the
// "Stock de l'entreprise" first-class state (client modifications plan
// Global Constraints / Task 1). Never settable directly by the frontend.
export type TripDestinationType = 'COMPANY_STOCK' | 'CUSTOMER'

export interface Trip {
  id: number
  reference: string
  truck: number
  truck_detail: TruckBrief | null
  // Phase 6: null only for a COMPANY_OWNED truck's trip - no artificial
  // "internal transporter" is ever created for the company's own fleet.
  transporter: number | null
  transporter_detail: TransporterBrief | null
  driver: number | null
  driver_detail: DriverBrief | null
  supplier: number
  supplier_detail: SupplierBrief | null
  supplier_order: number
  cession_letter: number
  cession_letter_detail?: CessionLetter | null
  // How many times this trip's truck has been loaded under this exact
  // cession letter (counts this trip itself, so a first load reads 1) -
  // backend/apps/trips/serializers.py get_cession_letter_truck_load_count.
  cession_letter_truck_load_count: number
  product: number
  product_detail: ProductBrief | null
  quantity_loaded: string
  client: number | null
  client_detail: CustomerBrief | null
  customer_order: number | null
  destination_type: TripDestinationType
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
  quantity_loaded: string
  quantity_invoiced: string
  transporter_loss_quantity: string
  transporter_loss_indemnity: string
  // UI recette bug (2026-09-04): a post-delivery loss within tolerance is
  // absorbed by the company (never billed to the transporter, never
  // reflected in the frozen Sale.delivered_quantity) - always present,
  // exactly "0.00" when there is no such loss.
  company_absorbed_loss_quantity: string
  company_absorbed_loss_amount: string
  revenue: string
  fuel_purchase_cost: string
  transport_cost: string
  expenses_by_category: Record<string, string>
  total_expenses: string
  real_total_cost: string
  margin: string
  // Client modifications Task 3.
  unit_cost: string
  unit_profit: string
}
export interface TripMarginUnavailable {
  available: false
}
export type TripMargin = TripMarginBreakdown | TripMarginUnavailable

// Mirrors GET /api/trips/{id}/cost-basis/ (backend/apps/trips/views.py
// TripViewSet.cost_basis, delegating to
// TripCostService.calculate_trip_cost_basis) - available from the moment a
// trip is loaded, unlike TripMargin which needs a Sale. Used by
// DeliveryControlForm to show "prix de revient" / live benefit while the
// operator fills in the selling price (client modifications plan Task 3).
export interface TripCostBasis {
  fuel_purchase_cost: string
  transport_cost: string
  expenses_by_category: Record<string, string>
  total_expenses: string
  total_cost: string
  quantity: string
  unit_cost: string
  unit_components_per_litre: {
    supplier: string
    commission_transporter: string
    transit: string
    road_transit: string
    border: string
    customs: string
    loading: string
    other: string
  }
}

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
  // Client modifications (2026-09-04 recette corrections): set by
  // POST /api/trips/{id}/client-verification/ (DeliveryService.
  // record_client_verification()) - optional/absent on a DeliveryControl
  // that was only ever confirmed at delivery time and never verified with
  // the client afterwards.
  verified_at?: string | null
  created_at: string
  updated_at: string
}

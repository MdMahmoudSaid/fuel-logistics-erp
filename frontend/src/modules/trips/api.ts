import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type {
  DeliveryControl,
  DeliveryMethod,
  Trip,
  TripCostBasis,
  TripMargin,
  TripStatus,
  TripStatusHistoryEntry,
} from './types'

export const tripResource = createResourceApi<Trip>('/trips/')

export function fetchTripHistory(tripId: number): Promise<TripStatusHistoryEntry[]> {
  return apiClient.get<TripStatusHistoryEntry[]>(`/trips/${tripId}/history/`).then((r) => r.data)
}

export function fetchAllowedTripStatuses(tripId: number): Promise<string[]> {
  return apiClient
    .get<{ statuses: string[] }>(`/trips/${tripId}/allowed-statuses/`)
    .then((r) => r.data.statuses)
}

// TripProfitService.get_cost_breakdown (guide Section 9.1), only available
// once the trip has a Sale - see TripMarginBreakdown/TripMarginUnavailable.
export function fetchTripMargin(tripId: number): Promise<TripMargin> {
  return apiClient.get<TripMargin>(`/trips/${tripId}/margin/`).then((r) => r.data)
}

// TripCostService.calculate_trip_cost_basis (backend/apps/trips/services.py)
// via TripViewSet.cost_basis - available from the moment a trip is loaded,
// unlike fetchTripMargin above which needs a Sale. Used by
// DeliveryControlForm to show "prix de revient"/live benefit while the
// operator fills in the selling price (client modifications plan Task 3).
export function fetchTripCostBasis(tripId: number): Promise<TripCostBasis> {
  return apiClient.get<TripCostBasis>(`/trips/${tripId}/cost-basis/`).then((r) => r.data)
}

// Backend/apps/trips/services.py TripWorkflowService is the sole authority
// on whether new_status is a valid transition from the trip's current
// status — this just posts the request and lets the caller surface
// whatever the server accepts or rejects.
export type TripStatusChange = Trip & { traversed_statuses?: TripStatus[] }

export function postTripStatus(
  tripId: number,
  newStatus: string,
  notes = '',
): Promise<TripStatusChange> {
  return apiClient
    .post<TripStatusChange>(`/trips/${tripId}/status/`, { new_status: newStatus, notes })
    .then((r) => r.data)
}

export function fetchTruckTrips(truckId: number): Promise<Trip[]> {
  return apiClient.get<Trip[]>(`/trucks/${truckId}/trips/`).then((r) => r.data)
}

// TripCostService.assign_customer_for_sale (backend/apps/trips/services.py)
// via TripViewSet.assign_customer - attaches/replaces this trip's direct
// customer and flips destination_type to CUSTOMER. Rejected by the server
// (400) once the trip already has a Sale - the sold customer is fixed at
// delivery time. Client modifications plan Task 9 gap-closure: this is the
// only way a COMPANY_STOCK trip ever gets a customer assigned post-creation.
export function assignTripCustomer(tripId: number, customerId: number): Promise<Trip> {
  return apiClient
    .post<Trip>(`/trips/${tripId}/assign-customer/`, { customer: customerId })
    .then((r) => r.data)
}

// One customer for several trips billed on a single invoice
// (POST /trips/assign-customers/).
export function assignTripsCustomer(tripIds: number[], customerId: number): Promise<Trip[]> {
  return apiClient
    .post<Trip[]>('/trips/assign-customers/', { customer: customerId, trips: tripIds })
    .then((r) => r.data)
}

export interface DeliveryControlPayload {
  // Client modifications (2026-09-04 recette corrections): now optional -
  // DeliveryControlForm.vue never sends it any more, so the backend
  // (DeliveryService.record_delivery()) always defaults it to the full
  // loaded quantity (zero loss) and the trip goes straight to DELIVERED.
  // Any post-delivery discrepancy is reported separately via
  // postClientVerification() below. Kept optional here (rather than
  // removed) since the backend endpoint still accepts it.
  received_quantity?: string
  control_date: string
  method: DeliveryMethod
  unit_selling_price: string
  anomaly_confirmed_by?: number
  // Client modifications Task 3: only sent once the operator has checked
  // the loss-confirmation box - see DeliveryService.record_delivery()'s
  // SaleBelowCostConfirmationRequired.
  confirm_loss?: boolean
  notes?: string
}

// Backend/apps/trips/services.py DeliveryService.record_delivery() is the
// sole authority on loss/tolerance/anomaly rules (guide §7.3/§15) - this
// just posts the request and surfaces whatever the server accepts (201) or
// rejects (400/422).
export function postDeliveryControl(
  tripId: number,
  payload: DeliveryControlPayload,
): Promise<DeliveryControl> {
  return apiClient
    .post<DeliveryControl>(`/trips/${tripId}/delivery-control/`, payload)
    .then((r) => r.data)
}

export interface ClientVerificationPayload {
  received_quantity: string
  verified_at: string
  notes?: string
}

// DeliveryService.record_client_verification() (backend/apps/trips/
// services.py) via TripViewSet.client_verification() - post-delivery
// quantity check (client modifications 2026-09-04 recette corrections).
// Only valid once the trip is DELIVERED/COMPLETED; the sole authority on
// the loss/tolerance split (company-absorbed vs. transporter-chargeable)
// remains the backend - this just posts the request and surfaces whatever
// it accepts (200, updated DeliveryControl) or rejects (400).
export function postClientVerification(
  tripId: number,
  payload: ClientVerificationPayload,
): Promise<DeliveryControl> {
  return apiClient
    .post<DeliveryControl>(`/trips/${tripId}/client-verification/`, payload)
    .then((r) => r.data)
}

export interface ClientVerificationCorrectionPayload {
  received_quantity: string
  reason: string
}

// DeliveryService.correct_client_verification() (backend/apps/trips/
// services.py) via TripViewSet.correct_client_verification() - audited fix
// for a client verification that was recorded with the wrong received
// quantity (feedback 2026-09-10). Only valid once a first verification
// already exists; a `reason` is required.
export function postClientVerificationCorrection(
  tripId: number,
  payload: ClientVerificationCorrectionPayload,
): Promise<DeliveryControl> {
  return apiClient
    .post<DeliveryControl>(`/trips/${tripId}/correct-client-verification/`, payload)
    .then((r) => r.data)
}

// DeliveryService.get_latest_selling_price() (backend/apps/trips/services.py)
// via TripViewSet.suggested_selling_price() - pre-fills the delivery form's
// price field; `null` when nothing is on file yet for this product/customer.
export function fetchSuggestedSellingPrice(tripId: number): Promise<string | null> {
  return apiClient
    .get<{ price: string | null }>(`/trips/${tripId}/suggested-selling-price/`)
    .then((r) => r.data.price)
}

// --- Customer refusal (client request 2026-10-11) ---

export type CustomerRefusalAction = 'RETURN_TO_STOCK' | 'CHANGE_CUSTOMER'

export interface RefusalSide {
  id: number
  name: string
  balance_before: string
  balance_after: string
}

// GET /trips/{id}/customer-refusal-preview/ (balances: positive = owed).
export interface CustomerRefusalPreview {
  trip_reference: string
  action: CustomerRefusalAction
  delivered: boolean
  status_after: TripStatus
  invoice_number: string | null
  grouped: boolean
  quantity: string | null
  current_unit_price: string | null
  suggested_unit_price: string | null
  unit_price: string | null
  old_amount: string
  new_amount: string
  released_payments: string
  old_customer: RefusalSide
  new_customer: (RefusalSide & { credit_applied: string }) | null
}

export interface CustomerRefusalEntry {
  id: number
  action: CustomerRefusalAction
  previous_customer: string
  new_customer: string | null
  invoice_number: string
  previous_unit_price: string | null
  new_unit_price: string | null
  released_amount: string
  reason: string
  recorded_by: string
  recorded_at: string
}

export function fetchCustomerRefusalPreview(
  tripId: number,
  params: { action: CustomerRefusalAction; customer?: number; unit_selling_price?: string },
): Promise<CustomerRefusalPreview> {
  return apiClient
    .get<CustomerRefusalPreview>(`/trips/${tripId}/customer-refusal-preview/`, { params })
    .then((r) => r.data)
}

export function refuseTripCustomer(
  tripId: number,
  payload: {
    action: CustomerRefusalAction
    reason: string
    customer?: number
    unit_selling_price?: string
  },
): Promise<Trip> {
  return apiClient.post<Trip>(`/trips/${tripId}/customer-refusal/`, payload).then((r) => r.data)
}

export function fetchCustomerRefusals(tripId: number): Promise<CustomerRefusalEntry[]> {
  return apiClient
    .get<CustomerRefusalEntry[]>(`/trips/${tripId}/customer-refusals/`)
    .then((r) => r.data)
}

// Every customer, across the API's pages (the picker must list them all).
export async function listAllCustomers(): Promise<
  { id: number; name: string; is_active?: boolean }[]
> {
  const all: { id: number; name: string; is_active?: boolean }[] = []
  for (let page = 1; ; page++) {
    const { data } = await apiClient.get<{
      next: string | null
      results: { id: number; name: string; is_active?: boolean }[]
    }>('/customers/', { params: { page } })
    all.push(...data.results)
    if (!data.next) return all
  }
}

import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type {
  DeliveryControl,
  DeliveryMethod,
  Trip,
  TripCostBasis,
  TripMargin,
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
export function postTripStatus(tripId: number, newStatus: string, notes = ''): Promise<Trip> {
  return apiClient
    .post<Trip>(`/trips/${tripId}/status/`, { new_status: newStatus, notes })
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

export interface DeliveryControlPayload {
  received_quantity: string
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

// DeliveryService.get_latest_selling_price() (backend/apps/trips/services.py)
// via TripViewSet.suggested_selling_price() - pre-fills the delivery form's
// price field; `null` when nothing is on file yet for this product/customer.
export function fetchSuggestedSellingPrice(tripId: number): Promise<string | null> {
  return apiClient
    .get<{ price: string | null }>(`/trips/${tripId}/suggested-selling-price/`)
    .then((r) => r.data.price)
}

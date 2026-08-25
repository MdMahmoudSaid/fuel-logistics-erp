import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type {
  DeliveryControl,
  DeliveryMethod,
  Trip,
  TripMargin,
  TripStatusHistoryEntry,
} from './types'

export const tripResource = createResourceApi<Trip>('/trips/')

export function fetchTripHistory(tripId: number): Promise<TripStatusHistoryEntry[]> {
  return apiClient.get<TripStatusHistoryEntry[]>(`/trips/${tripId}/history/`).then((r) => r.data)
}

// TripProfitService.get_cost_breakdown (guide Section 9.1), only available
// once the trip has a Sale - see TripMarginBreakdown/TripMarginUnavailable.
export function fetchTripMargin(tripId: number): Promise<TripMargin> {
  return apiClient.get<TripMargin>(`/trips/${tripId}/margin/`).then((r) => r.data)
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

export interface DeliveryControlPayload {
  received_quantity: string
  control_date: string
  method: DeliveryMethod
  anomaly_confirmed_by?: number
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

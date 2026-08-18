import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type { Trip, TripStatusHistoryEntry } from './types'

export const tripResource = createResourceApi<Trip>('/trips/')

export function fetchTripHistory(tripId: number): Promise<TripStatusHistoryEntry[]> {
  return apiClient.get<TripStatusHistoryEntry[]>(`/trips/${tripId}/history/`).then((r) => r.data)
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

import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type { CustomerOrder } from './types'
import type { Trip } from '@/modules/trips/types'

export const customerOrderResource = createResourceApi<CustomerOrder>('/customer-orders/')

export function fetchCustomerOrderTrips(orderId: number): Promise<Trip[]> {
  return apiClient.get<Trip[]>(`/customer-orders/${orderId}/trips/`).then((r) => r.data)
}

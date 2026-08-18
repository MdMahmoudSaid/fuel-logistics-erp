import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type { CustomerOrder, Invoice, Sale } from './types'
import type { Trip } from '@/modules/trips/types'

export const customerOrderResource = createResourceApi<CustomerOrder>('/customer-orders/')

export function fetchCustomerOrderTrips(orderId: number): Promise<Trip[]> {
  return apiClient.get<Trip[]>(`/customer-orders/${orderId}/trips/`).then((r) => r.data)
}

// Read-only: /api/sales/ has no create/update/destroy route (see
// backend/apps/sales/views.py SaleViewSet) - createResourceApi()'s
// create/update/remove simply aren't called for this resource.
export const saleResource = createResourceApi<Sale>('/sales/')

export const invoiceResource = createResourceApi<Invoice>('/invoices/')

export function validateInvoice(invoiceId: number): Promise<Invoice> {
  return apiClient.post<Invoice>(`/invoices/${invoiceId}/validate/`).then((r) => r.data)
}

// Backend/apps/sales/services.py InvoiceService.correct_invoice() is the
// sole authority on which fields are correctable and how the total is
// recomputed - this just posts the request.
export function correctInvoice(
  invoiceId: number,
  field: string,
  newValue: string,
  reason: string,
): Promise<Invoice> {
  return apiClient
    .post<Invoice>(`/invoices/${invoiceId}/correct/`, {
      field,
      new_value: newValue,
      reason,
    })
    .then((r) => r.data)
}

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

// Validate several DRAFT invoices of one customer at once (all or nothing).
export function validateInvoices(invoiceIds: number[]): Promise<Invoice[]> {
  return apiClient
    .post<Invoice[]>('/invoices/bulk-validate/', { invoices: invoiceIds })
    .then((r) => r.data)
}

// Backend/apps/sales/services.py InvoiceService.update_draft_pricing() -
// edits a DRAFT invoice's initial selling price directly (no audit row,
// unlike correctInvoice() below which is VALIDATED-only) and recomputes
// the total from it (feedback 2026-09-10).
export function updateInvoicePrice(
  invoiceId: number,
  unitSellingPrice: string,
  saleId?: number,
): Promise<Invoice> {
  return apiClient
    .post<Invoice>(`/invoices/${invoiceId}/update-price/`, {
      unit_selling_price: unitSellingPrice,
      sale: saleId,
    })
    .then((r) => r.data)
}

// GET /api/invoices/{id}/pdf/?lang=fr|en|ar (backend/apps/sales/views.py
// InvoiceViewSet.pdf) - same per-row PDF export the customer ledger's
// Paiements table already had (feedback 2026-09-10), see
// exportCustomerPaymentPdf in @/modules/finance/api for the sibling call.
export async function exportInvoicePdf(invoiceId: number, lang: string): Promise<void> {
  const response = await apiClient.get(`/invoices/${invoiceId}/pdf/`, {
    params: { lang },
    responseType: 'blob',
  })
  const url = window.URL.createObjectURL(new Blob([response.data]))
  const link = document.createElement('a')
  link.href = url
  link.download = `facture-${invoiceId}.pdf`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

// Backend/apps/sales/services.py InvoiceService.correct_invoice() is the
// sole authority on which fields are correctable and how the total is
// recomputed - this just posts the request.
export function correctInvoice(
  invoiceId: number,
  field: string,
  newValue: string,
  reason: string,
  saleId?: number,
): Promise<Invoice> {
  return apiClient
    .post<Invoice>(`/invoices/${invoiceId}/correct/`, {
      field,
      new_value: newValue,
      reason,
      sale: saleId,
    })
    .then((r) => r.data)
}

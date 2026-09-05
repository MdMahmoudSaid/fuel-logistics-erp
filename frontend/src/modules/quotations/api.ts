import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type { Quotation } from './types'

export const quotationResource = createResourceApi<Quotation>('/quotations/')

export function duplicateQuotation(id: number): Promise<Quotation> {
  return apiClient.post<Quotation>(`/quotations/${id}/duplicate/`).then((r) => r.data)
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

// GET /api/quotations/{id}/pdf/?lang=fr|en|ar (backend/apps/quotations/
// views.py QuotationViewSet.pdf) - mirrors modules/finance/api.ts's
// exportLedgerPdf blob-download pattern.
export async function exportQuotationPdf(id: number, reference: string, lang: string): Promise<void> {
  const response = await apiClient.get(`/quotations/${id}/pdf/`, {
    params: { lang },
    responseType: 'blob',
  })
  downloadBlob(new Blob([response.data]), `devis-${reference}.pdf`)
}

// Commercial documents (spec 2026-10-11 documents-commerciaux): one generic
// API for the four document kinds, plus the delivery note's trip pre-fill.
import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type { PaginatedResponse } from '@/api/resource'
import type { DeliverableTrip, DocumentRow } from './types'

// Every page of a list (the API pages by 25): documents and pickers must
// not silently stop at the first page.
export async function listAll<T>(
  api: { list: (params?: Record<string, unknown>) => Promise<PaginatedResponse<T>> },
  params: Record<string, unknown> = {},
): Promise<T[]> {
  const results: T[] = []
  for (let page = 1; page <= 200; page++) {
    const data = await api.list(page === 1 ? params : { ...params, page })
    results.push(...data.results)
    if (!data.next) break
  }
  return results
}

export function documentApi<T = DocumentRow>(path: string) {
  return createResourceApi<T>(path)
}

async function fetchPdf(path: string, id: number, lang: string): Promise<Blob> {
  const response = await apiClient.get(`${path}${id}/pdf/`, {
    params: { lang },
    responseType: 'blob',
  })
  return new Blob([response.data], { type: 'application/pdf' })
}

export async function downloadDocumentPdf(
  path: string,
  id: number,
  filename: string,
  lang: string,
): Promise<void> {
  const url = window.URL.createObjectURL(await fetchPdf(path, id, lang))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

// Opens the PDF in a new tab and starts the browser's print dialog there.
export async function printDocumentPdf(path: string, id: number, lang: string): Promise<void> {
  const url = window.URL.createObjectURL(await fetchPdf(path, id, lang))
  const tab = window.open(url, '_blank')
  tab?.addEventListener('load', () => tab.print())
}

export function fetchDeliverableTrips(customerId: number): Promise<DeliverableTrip[]> {
  return apiClient
    .get<DeliverableTrip[]>('/delivery-notes/deliverable-trips/', {
      params: { customer: customerId },
    })
    .then((r) => r.data)
}

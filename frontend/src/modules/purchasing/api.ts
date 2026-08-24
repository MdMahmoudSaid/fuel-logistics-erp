import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type { CessionLetter, SupplierLedger, SupplierOrder } from './types'

export const supplierOrderResource = createResourceApi<SupplierOrder>('/supplier-orders/')
export const cessionLetterResource = createResourceApi<CessionLetter>('/cession-letters/')

export function fetchSupplierLedger(supplierId: number): Promise<SupplierLedger> {
  return apiClient.get<SupplierLedger>(`/suppliers/${supplierId}/ledger/`).then((r) => r.data)
}

export function fetchNextSupplierOrderReference(): Promise<string> {
  return apiClient
    .get<{ reference: string }>('/supplier-orders/next-reference/')
    .then((r) => r.data.reference)
}

// Generic attachment upload (backend/apps/documents). The target object must
// already exist — content_type/object_id are validated against an allowlist
// and existence-checked server-side (see apps.documents.views).
export function uploadDocument(params: {
  file: File
  documentType: string
  contentTypeName: 'supplierorder' | 'cessionletter'
  objectId: number
}): Promise<void> {
  const form = new FormData()
  form.append('file', params.file)
  form.append('document_type', params.documentType)
  form.append('content_type_name', params.contentTypeName)
  form.append('object_id', String(params.objectId))
  return apiClient
    .post('/documents/', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then(() => undefined)
}

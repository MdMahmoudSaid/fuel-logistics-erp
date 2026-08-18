import { apiClient } from './client'

export interface PaginatedResponse<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface ResourceApi<T> {
  list: (params?: Record<string, unknown>) => Promise<PaginatedResponse<T>>
  // Optional: existing hand-rolled test doubles (see MasterDataView specs)
  // predate this method and don't implement it. createResourceApi() always
  // provides it.
  get?: (id: number) => Promise<T>
  create: (payload: Partial<T>) => Promise<T>
  update: (id: number, payload: Partial<T>) => Promise<T>
  remove: (id: number) => Promise<void>
}

export function createResourceApi<T = Record<string, unknown>>(basePath: string): ResourceApi<T> {
  return {
    list: (params) => apiClient.get<PaginatedResponse<T>>(basePath, { params }).then((r) => r.data),
    get: (id) => apiClient.get<T>(`${basePath}${id}/`).then((r) => r.data),
    create: (payload) => apiClient.post<T>(basePath, payload).then((r) => r.data),
    update: (id, payload) => apiClient.patch<T>(`${basePath}${id}/`, payload).then((r) => r.data),
    remove: (id) => apiClient.delete(`${basePath}${id}/`).then(() => undefined),
  }
}

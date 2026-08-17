import { apiClient } from './client'

export interface PaginatedResponse<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface ResourceApi<T> {
  list: () => Promise<PaginatedResponse<T>>
  create: (payload: Partial<T>) => Promise<T>
  update: (id: number, payload: Partial<T>) => Promise<T>
  remove: (id: number) => Promise<void>
}

export function createResourceApi<T = Record<string, unknown>>(basePath: string): ResourceApi<T> {
  return {
    list: () => apiClient.get<PaginatedResponse<T>>(basePath).then((r) => r.data),
    create: (payload) => apiClient.post<T>(basePath, payload).then((r) => r.data),
    update: (id, payload) => apiClient.patch<T>(`${basePath}${id}/`, payload).then((r) => r.data),
    remove: (id) => apiClient.delete(`${basePath}${id}/`).then(() => undefined),
  }
}

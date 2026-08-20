import { apiClient } from '@/api/client'
import type { SearchResults } from './types'

export function searchGlobal(query: string): Promise<SearchResults> {
  return apiClient.get<SearchResults>('/search/', { params: { q: query } }).then((r) => r.data)
}

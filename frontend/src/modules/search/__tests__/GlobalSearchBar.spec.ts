import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import GlobalSearchBar from '../GlobalSearchBar.vue'
import type { SearchResults } from '../types'

const emptyResults: SearchResults = {
  trucks: [],
  customers: [],
  suppliers: [],
  transporters: [],
  trips: [],
  invoices: [],
  orders: [],
  cessions: [],
}

const searchGlobal = vi.fn(async (query: string): Promise<SearchResults> => {
  void query
  return emptyResults
})

vi.mock('../api', () => ({
  searchGlobal: (query: string) => searchGlobal(query),
}))

describe('GlobalSearchBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not search until the user types something', async () => {
    mount(GlobalSearchBar)
    await vi.advanceTimersByTimeAsync(500)

    expect(searchGlobal).not.toHaveBeenCalled()
  })

  it('debounces the search and shows a truck result enriched with its current trip', async () => {
    searchGlobal.mockResolvedValueOnce({
      ...emptyResults,
      trucks: [
        {
          id: 1,
          internal_id: 'TRK-1',
          tractor_registration: 'AA-111-BB',
          tanker_registration: 'CC-222-DD',
          current_trip: {
            reference: 'TRIP-1',
            status: 'IN_TRANSIT',
            product: 'Gasoil',
            quantity_loaded: '45000.00',
            client: 'Client X',
          },
        },
      ],
    })

    const wrapper = mount(GlobalSearchBar)
    await wrapper.find('input').setValue('AA-111')

    expect(searchGlobal).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(searchGlobal).toHaveBeenCalledWith('AA-111')
    expect(wrapper.text()).toContain('AA-111-BB')
    expect(wrapper.text()).toContain('En transit')
    expect(wrapper.text()).toContain('Client X')
  })

  it('clears results when the query is emptied', async () => {
    const wrapper = mount(GlobalSearchBar)
    await wrapper.find('input').setValue('truck')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    await wrapper.find('input').setValue('')

    expect(wrapper.find('.absolute').exists()).toBe(false)
  })
})

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import EntityAllocationPicker, { type AllocationDraft } from '../EntityAllocationPicker.vue'
import type { SearchResults } from '@/modules/search/types'

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

const searchGlobal = vi.fn(async (_query: string): Promise<SearchResults> => emptyResults)

vi.mock('@/modules/search/api', () => ({
  searchGlobal: (query: string) => searchGlobal(query),
}))

function emptyDraft(): AllocationDraft {
  return { kind: '', objectId: null, label: '', allocatedAmount: '' }
}

describe('EntityAllocationPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not search until a kind is picked and text is typed', async () => {
    mount(EntityAllocationPicker, { props: { modelValue: emptyDraft() } })
    await vi.advanceTimersByTimeAsync(500)

    expect(searchGlobal).not.toHaveBeenCalled()
  })

  it('picking a kind resets any previous selection and emits the new kind', async () => {
    const wrapper = mount(EntityAllocationPicker, {
      props: { modelValue: { kind: 'truck', objectId: 5, label: 'TRK-5', allocatedAmount: '' } },
    })

    await wrapper.find('select').setValue('trip')

    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toEqual({
      kind: 'trip',
      objectId: null,
      label: '',
      allocatedAmount: '',
    })
  })

  it('searches trips for the chosen kind and emits the selection on click', async () => {
    searchGlobal.mockResolvedValueOnce({
      ...emptyResults,
      trips: [{ id: 42, reference: 'TRIP-042', status: 'DELIVERED', product: 'Gasoil' }],
    })

    const wrapper = mount(EntityAllocationPicker, {
      props: { modelValue: { kind: 'trip', objectId: null, label: '', allocatedAmount: '' } },
    })

    await wrapper.find('input[type=text]').setValue('TRIP-04')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(searchGlobal).toHaveBeenCalledWith('TRIP-04')
    const option = wrapper.findAll('button').find((b) => b.text() === 'TRIP-042')
    expect(option).toBeDefined()

    await option!.trigger('click')

    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted![emitted!.length - 1][0]).toMatchObject({
      kind: 'trip',
      objectId: 42,
      label: 'TRIP-042',
    })
  })

  it('locked mode hides the change/search controls and disables the kind select', () => {
    const wrapper = mount(EntityAllocationPicker, {
      props: {
        modelValue: { kind: 'trip', objectId: 42, label: 'TRIP-042', allocatedAmount: '' },
        locked: true,
      },
    })

    expect((wrapper.find('select').element as HTMLSelectElement).disabled).toBe(true)
    expect(wrapper.findAll('button').find((b) => b.text().includes('Changer'))).toBeUndefined()
  })

  it('emits amount changes', async () => {
    const wrapper = mount(EntityAllocationPicker, {
      props: { modelValue: { kind: 'trip', objectId: 42, label: 'TRIP-042', allocatedAmount: '' } },
    })

    await wrapper.find('input[type=number]').setValue('50000')

    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted![emitted!.length - 1][0]).toMatchObject({ allocatedAmount: '50000' })
  })
})

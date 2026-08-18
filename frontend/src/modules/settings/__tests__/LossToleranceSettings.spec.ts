import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import LossToleranceSettings from '../LossToleranceSettings.vue'
import type { LossToleranceConfig } from '../types'

let configToReturn: LossToleranceConfig
const updateLossTolerance = vi.fn(async (toleranceLitres: string) => ({
  tolerance_litres: toleranceLitres,
  updated_by: 1,
  updated_by_detail: { id: 1, email: 'admin@example.com', full_name: 'Admin' },
  updated_at: '2026-08-18T10:00:00Z',
}))

vi.mock('../api', () => ({
  fetchLossTolerance: vi.fn(async () => configToReturn),
  updateLossTolerance: (toleranceLitres: string) => updateLossTolerance(toleranceLitres),
}))

describe('LossToleranceSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads and displays the current tolerance', async () => {
    configToReturn = {
      tolerance_litres: '100.00',
      updated_by: null,
      updated_by_detail: null,
      updated_at: null,
    }
    const wrapper = mount(LossToleranceSettings)
    await flushPromises()

    expect((wrapper.find('#tolerance_litres').element as HTMLInputElement).value).toBe('100.00')
    expect(wrapper.text()).toContain('Not yet configured')
  })

  it('saves the new tolerance and shows who last updated it', async () => {
    configToReturn = {
      tolerance_litres: '100.00',
      updated_by: null,
      updated_by_detail: null,
      updated_at: null,
    }
    const wrapper = mount(LossToleranceSettings)
    await flushPromises()

    await wrapper.find('#tolerance_litres').setValue('150.00')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(Number(updateLossTolerance.mock.calls[0]![0])).toBe(150)
    expect(wrapper.text()).toContain('admin@example.com')
  })
})

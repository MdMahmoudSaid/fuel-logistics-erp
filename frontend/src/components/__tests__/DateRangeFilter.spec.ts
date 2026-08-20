import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DateRangeFilter from '../DateRangeFilter.vue'

describe('DateRangeFilter', () => {
  it('emits the default preset range on mount', () => {
    const wrapper = mount(DateRangeFilter)

    const events = wrapper.emitted('change')
    expect(events).toBeTruthy()
    expect(events![0]).toEqual([{ range: 'month' }])
  })

  it('emits a preset range when the selector changes', async () => {
    const wrapper = mount(DateRangeFilter)

    await wrapper.find('select').setValue('today')

    const events = wrapper.emitted('change')!
    expect(events[events.length - 1]).toEqual([{ range: 'today' }])
  })

  it('emits from/to instead of range once "custom" is selected', async () => {
    const wrapper = mount(DateRangeFilter)

    await wrapper.find('select').setValue('custom')
    const inputs = wrapper.findAll('input[type="date"]')
    await inputs[0]!.setValue('2026-08-01')
    await inputs[1]!.setValue('2026-08-18')

    const events = wrapper.emitted('change')!
    expect(events[events.length - 1]).toEqual([{ from: '2026-08-01', to: '2026-08-18' }])
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AuditLogViewer from '../AuditLogViewer.vue'
import type { AuditLog } from '../types'

const logs: AuditLog[] = [
  {
    id: 1,
    user: 1,
    user_email: 'admin@example.com',
    timestamp: '2026-08-18T10:00:00Z',
    action: 'UPDATE',
    content_type: 5,
    content_type_label: 'purchasing.supplierorder',
    object_id: 42,
    previous_value: { unit_price: '600.0000', reference: 'SO-1' },
    new_value: { unit_price: '650.0000', reference: 'SO-1' },
    reason: null,
  },
]

const list = vi.fn(async (params?: Record<string, unknown>) => {
  void params
  return { count: 1, next: null, previous: null, results: logs }
})

vi.mock('../api', () => ({
  auditLogResource: { list: (params?: Record<string, unknown>) => list(params) },
}))

describe('AuditLogViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists audit entries', async () => {
    const wrapper = mount(AuditLogViewer)
    await flushPromises()

    expect(wrapper.text()).toContain('purchasing.supplierorder')
    expect(wrapper.text()).toContain('Modification')
    expect(wrapper.text()).toContain('admin@example.com')
  })

  it('expands a row to show only the fields that actually changed', async () => {
    const wrapper = mount(AuditLogViewer)
    await flushPromises()

    await wrapper.find('tbody tr').trigger('click')

    expect(wrapper.text()).toContain('unit_price')
    expect(wrapper.text()).toContain('600.0000')
    expect(wrapper.text()).toContain('650.0000')
    // `reference` is identical before/after - must not appear in the diff.
    expect(wrapper.text()).not.toContain('SO-1')
  })
})

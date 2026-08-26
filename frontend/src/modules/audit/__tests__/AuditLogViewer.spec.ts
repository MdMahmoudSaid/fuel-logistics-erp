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
    summary: {
      module_key: 'supplier_order',
      reference: 'SO-1',
      related_party: 'Supplier X',
      account_label: null,
      amount: null,
    },
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

    expect(wrapper.text()).toContain('Commande fournisseur')
    expect(wrapper.text()).toContain('SO-1 (Supplier X)')
    expect(wrapper.text()).toContain('Modification')
    expect(wrapper.text()).toContain('admin@example.com')
  })

  it('expands a row to show only the fields that actually changed', async () => {
    const wrapper = mount(AuditLogViewer)
    await flushPromises()

    await wrapper.find('tbody tr').trigger('click')

    const diffTable = wrapper.find('table.text-xs')
    expect(diffTable.text()).toContain('unit_price')
    expect(diffTable.text()).toContain('600.0000')
    expect(diffTable.text()).toContain('650.0000')
    // `reference` is identical before/after - must not appear in the diff
    // (it legitimately appears elsewhere, in the readable object column).
    expect(diffTable.text()).not.toContain('SO-1')
  })

  it('shows "Module - Party" for an entry with no natural reference, e.g. a supplier payment', async () => {
    list.mockResolvedValueOnce({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          ...logs[0],
          id: 2,
          content_type_label: 'finance.supplierpayment',
          summary: {
            module_key: 'supplier_payment',
            reference: null,
            related_party: 'Ahmed',
            account_label: 'Main Cash',
            amount: '500000.00',
          },
        },
      ],
    })
    const wrapper = mount(AuditLogViewer)
    await flushPromises()

    expect(wrapper.text()).toContain('Paiement fournisseur - Ahmed')
  })

  it('falls back to "Module amount" when there is neither a reference nor a related party, e.g. a treasury transfer', async () => {
    list.mockResolvedValueOnce({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          ...logs[0],
          id: 3,
          content_type_label: 'finance.treasurytransaction',
          summary: {
            module_key: 'treasury',
            reference: null,
            related_party: null,
            account_label: 'Main Bank',
            amount: '22500000.00',
          },
        },
      ],
    })
    const wrapper = mount(AuditLogViewer)
    await flushPromises()

    // Amounts are wrapped in bidi isolate marks (LRI/PDI) so they can't be
    // reordered in RTL locales; strip them before matching adjacent text.
    expect(wrapper.text().replace(/[⁦⁩]/g, '')).toContain('Trésorerie 22 500 000 XOF')
  })
})

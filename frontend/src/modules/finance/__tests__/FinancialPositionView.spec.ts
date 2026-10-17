import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import FinancialPositionView from '../FinancialPositionView.vue'

const position = {
  assets: {
    lines: [
      {
        key: 'banks',
        amount: '411738383.00',
        children: [{ label: 'BDM', amount: '22872781.00' }],
      },
      { key: 'cash', amount: '9600000.00', children: [] },
      {
        key: 'fuel_stock',
        amount: '5000000.00',
        children: [
          { key: 'company_stock', amount: '0.00' },
          { key: 'at_supplier', amount: '5000000.00' },
        ],
      },
    ],
    total: '426338383.00',
  },
  liabilities: {
    lines: [
      { key: 'supplier_debts', amount: '105000000.00', children: [] },
      {
        key: 'shareholder_dues',
        amount: '300000000.00',
        children: [{ label: 'Associé A', amount: '300000000.00' }],
      },
    ],
    total: '405000000.00',
  },
  net_result: '21338383.00',
  capital: '300000000.00',
}

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  fetchFinancialPosition: vi.fn(async () => position),
}))

describe('FinancialPositionView', () => {
  it('shows what the company owns, what it owes and the net result', async () => {
    const wrapper = mount(FinancialPositionView)
    await flushPromises()

    const assets = wrapper.find('[data-test="position-assets"]').text()
    expect(assets).toContain('Ce que possède l’entreprise'.replace('’', "'"))
    expect(assets).toContain('Banques')
    expect(assets).toContain('BDM') // per-account detail
    expect(assets).toContain('426 338 383')

    const liabilities = wrapper.find('[data-test="position-liabilities"]').text()
    expect(liabilities).toContain('Dettes fournisseurs')
    expect(liabilities).toContain('Associé A') // each associate listed
    expect(liabilities).toContain('405 000 000')

    expect(wrapper.find('[data-test="position-net-result"]').text()).toContain('21 338 383')
  })

  it('hides zero sub-lines but keeps every main line', async () => {
    const wrapper = mount(FinancialPositionView)
    await flushPromises()

    const assets = wrapper.find('[data-test="position-assets"]').text()
    expect(assets).toContain('Caisses') // main line at its own amount
    expect(assets).not.toContain('Stock entreprise') // zero child hidden
    expect(assets).toContain('Chez le fournisseur')
  })
})

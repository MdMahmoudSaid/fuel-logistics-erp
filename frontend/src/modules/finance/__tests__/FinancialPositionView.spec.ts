import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import FinancialPositionView from '../FinancialPositionView.vue'
import { exportFinancialPositionPdf } from '../api'

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
        key: 'unsold_fuel_paid',
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
  starting_funds: '0.00',
  distributable_result: '21338383.00',
  gap: '0.00',
  matched_unsold: '30000000.00',
  working_capital_total: '650000000.00',
  treasury_origins: [
    { key: 'shareholdercontribution', amount: '300000000.00' },
    { key: 'customerpayment', amount: '100000000.00' },
  ],
  capital: '300000000.00',
}

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  fetchFinancialPosition: vi.fn(async () => position),
  exportFinancialPositionPdf: vi.fn(async () => undefined),
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

  it('shows the control against the distributable profit and flags any gap', async () => {
    const wrapper = mount(FinancialPositionView)
    await flushPromises()

    const control = wrapper.find('[data-test="position-control"]').text()
    expect(control).toContain('21 338 383')
    expect(control).toContain('Identique au résultat net')
    expect(wrapper.text()).toContain('650 000 000') // the Fond de roulement, for the record
    expect(wrapper.find('[data-test="position-origins"]').text()).toContain('Apports en capital')
  })

  it('hides zero sub-lines but keeps every main line', async () => {
    const wrapper = mount(FinancialPositionView)
    await flushPromises()

    const assets = wrapper.find('[data-test="position-assets"]').text()
    expect(assets).toContain('Caisses') // main line at its own amount
    expect(assets).not.toContain('stock entreprise') // zero child hidden
    expect(assets).toContain('Payé : chez le fournisseur')
  })

  it('offers a PDF download and a print button, with a print-only logo header', async () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined)
    const wrapper = mount(FinancialPositionView, { attachTo: document.body })
    await flushPromises()

    expect(wrapper.find('[data-test="position-print-masthead"] img').exists()).toBe(true)

    await wrapper.find('[data-test="position-export-pdf"]').trigger('click')
    expect(exportFinancialPositionPdf).toHaveBeenCalled()

    await wrapper.find('[data-test="position-print"]').trigger('click')
    expect(print).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows no starting-funds line in the control nor the opening balances in the origins', async () => {
    const { fetchFinancialPosition } = await import('../api')
    vi.mocked(fetchFinancialPosition).mockResolvedValueOnce({
      ...position,
      starting_funds: '92358500.00',
      treasury_origins: [
        { key: 'opening_balances', amount: '92358500.00' },
        ...position.treasury_origins,
      ],
    })
    const wrapper = mount(FinancialPositionView)
    await flushPromises()

    expect(wrapper.find('[data-test="position-control"]').text()).not.toContain('92 358 500')
    expect(wrapper.find('[data-test="position-origins"]').text()).not.toContain('92 358 500')
    expect(wrapper.find('[data-test="position-origins"]').text()).toContain('Apports en capital')
  })

  it('turns the control red with the gap when the net result differs from the profit', async () => {
    const { fetchFinancialPosition } = await import('../api')
    vi.mocked(fetchFinancialPosition).mockResolvedValueOnce({ ...position, gap: '92358500.00' })
    const wrapper = mount(FinancialPositionView)
    await flushPromises()

    const control = wrapper.find('[data-test="position-control"]')
    expect(control.text()).toContain('Écart avec le résultat net')
    expect(control.text()).toContain('92 358 500')
    expect(control.text()).not.toContain('Identique au résultat net')
    expect(control.find('.text-critique').exists()).toBe(true)
    expect(control.find('.text-livre').exists()).toBe(false)
  })
})

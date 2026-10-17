import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ProfitView from '../ProfitView.vue'
import { i18n } from '@/i18n'

// Design doc 2026-08-26-benefices-associes-refinement-design.md: the
// Benefices page reuses GET /api/reports/margin-report/ (already tested
// end to end in apps/reports/test_queries.py) rather than a new backend
// endpoint - this test only covers the page's own logic: period-triggered
// fetch, per-trip table rendering, and the indicative preview banner.

const fetchReport = vi.fn()
const fetchShareholderProfitPreview = vi.fn()
const exportProfitReportPdf = vi.fn(async (..._args: unknown[]) => undefined)

vi.mock('@/modules/reports/api', () => ({
  fetchReport: (...args: unknown[]) => fetchReport(...args),
}))

vi.mock('../api', () => ({
  fetchShareholderProfitPreview: (...args: unknown[]) => fetchShareholderProfitPreview(...args),
  exportProfitReportPdf: (...args: unknown[]) => exportProfitReportPdf(...args),
}))

describe('ProfitView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    i18n.global.locale.value = 'fr'
    fetchShareholderProfitPreview.mockResolvedValue({
      period_start: '2026-08-01',
      period_end: null,
      current_profit: '900000.00',
      operational_profit: '900000.00',
      general_expenses_paid: '150000.00',
      net_profit: '750000.00',
      all_time_net_profit: '750000.00',
      total_company_absorbed_loss: '0.00',
      working_capital: {
        capital: '100000.00',
        treasury_available: '400000.00',
        customer_receivables: '350000.00',
        supplier_debt_total: '200000.00',
        transporter_debt_total: '100000.00',
        other_debts: '50000.00',
        supplier_reliquat_value: '0.00',
        supplier_in_transit_value: '0.00',
        supplier_company_stock_value: '0.00',
        // gross = 400000 + 350000 = 750000
        // total = gross + 200000 + 100000 + 50000 (debts ADDED) = 1100000
        gross: '750000.00',
        total: '1100000.00',
      },
      // No distributions committed in this fixture's scenario.
      already_distributed: '0.00',
      already_validated_total: '0.00',
      // distributable_result = total (1100000) - debts (350000) - capital (100000) = 650000
      result_after_debts_and_capital: '650000.00',
      distributable_result: '750000.00',
      shareholders: [],
    })
    fetchReport.mockResolvedValue({
      report_type: 'margin-report',
      fields: [
        'trip_reference',
        'client',
        'product',
        'quantity',
        'quantity_loaded',
        'quantity_invoiced',
        'transporter_loss_quantity',
        'transporter_loss_indemnity',
        'supplier_unit_price',
        'transport_cost',
        'customs_cost',
        'transit_cost',
        'road_transit_cost',
        'border_cost',
        'loading_cost',
        'additional_costs',
        'real_total_cost',
        'unit_cost',
        'unit_selling_price',
        'unit_profit',
        'current_margin',
      ],
      rows: [
        {
          trip_reference: 'TRIP-1',
          client: 'Client A',
          product: 'Gasoil',
          quantity: '45000.00',
          quantity_loaded: '45000.00',
          quantity_invoiced: '44900.00',
          transporter_loss_quantity: '100.00',
          transporter_loss_indemnity: '90000.00',
          supplier_unit_price: '500.0000',
          transport_cost: '2925000.00',
          customs_cost: '10125000.00',
          transit_cost: '450000.00',
          road_transit_cost: '50000.00',
          border_cost: '200000.00',
          loading_cost: '100000.00',
          additional_costs: '50000.00',
          real_total_cost: '36000000.00',
          unit_cost: '800.0000',
          unit_selling_price: '850.0000',
          unit_profit: '50.0000',
          current_margin: '2250000.00',
        },
      ],
    })
  })

  it('loads the profit-by-trip breakdown on period change and renders totals', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()

    // The period filter triggers the load - simulate the DateRangeFilter's
    // default emit (it auto-applies "period" onMounted).
    await flushPromises()

    expect(fetchShareholderProfitPreview).toHaveBeenCalled()
    expect(wrapper.text()).toContain('TRIP-1')
    expect(wrapper.text()).toContain('Client A')
    expect(wrapper.text()).toContain('90 000 XOF')
    // period profit = sum of current_margin across rows (one row here)
    expect(wrapper.text()).toContain('2 250 000 XOF')
  })

  // Client report (2026-10-04): the operational-profit card (fed by
  // fetchReport) used to render as soon as the trip rows arrived, while
  // the general-expenses/net-profit cards next to it (fed by
  // fetchShareholderProfitPreview, a separate slower call) stayed blank
  // for a few hundred milliseconds - a visible flash of broken-looking
  // cards in the same row. The whole Rentabilite section must wait for
  // both calls together.
  it('does not render the Rentabilite cards until both the trip rows and the profit preview have resolved', async () => {
    let resolvePreview!: (value: unknown) => void
    fetchShareholderProfitPreview.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePreview = resolve
        }),
    )

    const wrapper = mount(ProfitView)
    await flushPromises()
    await flushPromises()

    // fetchReport has already resolved (it would show "2 250 000 XOF" if
    // rendered), but the preview is still pending - the page must still be
    // showing its loading state, not a half-populated grid.
    expect(wrapper.find('[data-test="profit-operational-card"]').exists()).toBe(false)
    expect(wrapper.text()).toContain(i18n.global.t('common.loading'))

    resolvePreview({
      period_start: '2026-08-01',
      period_end: null,
      current_profit: '900000.00',
      operational_profit: '900000.00',
      general_expenses_paid: '150000.00',
      net_profit: '750000.00',
      all_time_net_profit: '750000.00',
      total_company_absorbed_loss: '0.00',
      working_capital: {
        capital: '100000.00',
        treasury_available: '400000.00',
        customer_receivables: '350000.00',
        supplier_debt_total: '200000.00',
        transporter_debt_total: '100000.00',
        other_debts: '50000.00',
        supplier_reliquat_value: '0.00',
        supplier_in_transit_value: '0.00',
        supplier_company_stock_value: '0.00',
        gross: '750000.00',
        total: '1100000.00',
      },
      already_distributed: '0.00',
      already_validated_total: '0.00',
      result_after_debts_and_capital: '650000.00',
      distributable_result: '750000.00',
      shareholders: [],
    })
    await flushPromises()

    expect(wrapper.find('[data-test="profit-operational-card"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('2 250 000 XOF')
  })

  // UI reorg (2026-09-04): Section "Distribution" shows brut, dettes
  // ouvertes, capital apporte (replacing the old "Fond de roulement
  // client" total card - still available on the Dashboard), and resultat
  // distribuable, in that order.
  it('shows fond de roulement brut, dettes ouvertes (added), capital apporte, and resultat distribuable, informational only', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()
    await flushPromises()

    const grossCard = wrapper.find('[data-test="profit-working-capital-gross-card"]')
    expect(grossCard.exists()).toBe(true)
    expect(grossCard.text()).toContain('Trésorerie + créances clients')
    expect(grossCard.text()).toContain('750 000 XOF')

    const debtsCard = wrapper.find('[data-test="profit-working-capital-debts-card"]')
    expect(debtsCard.exists()).toBe(true)
    // supplier 200000 + transporter 100000 + other 50000 = 350000
    expect(debtsCard.text()).toContain('350 000 XOF')

    const capitalCard = wrapper.find('[data-test="profit-capital-card"]')
    expect(capitalCard.exists()).toBe(true)
    expect(capitalCard.text()).toContain('Capital apporté')
    expect(capitalCard.text()).toContain('100 000 XOF')

    const distributableResultCard = wrapper.find('[data-test="profit-distributable-result-card"]')
    expect(distributableResultCard.exists()).toBe(true)
    // 2026-09-25: this card is the profit still left to distribute (net
    // profit minus validated distributions), not the debts/capital figure.
    expect(distributableResultCard.text()).toContain('Bénéfice à distribuer')
    expect(distributableResultCard.text()).toContain('750 000 XOF')
  })

  // Final whole-branch review (2026-09-08, Fix 2a): distributable_result
  // now silently nets out already_distributed (money already committed to
  // shareholders via non-cancelled distributions) - this card makes that
  // term visible so the brut -> dettes -> capital -> distribuable chain
  // still reconciles on screen.
  it('shows already_distributed as its own card between capital and distributable result', async () => {
    fetchShareholderProfitPreview.mockResolvedValue({
      period_start: '2026-08-01',
      period_end: null,
      current_profit: '900000.00',
      operational_profit: '900000.00',
      general_expenses_paid: '150000.00',
      net_profit: '750000.00',
      all_time_net_profit: '750000.00',
      total_company_absorbed_loss: '0.00',
      working_capital: {
        capital: '100000.00',
        treasury_available: '400000.00',
        customer_receivables: '350000.00',
        supplier_debt_total: '200000.00',
        transporter_debt_total: '100000.00',
        other_debts: '50000.00',
        supplier_reliquat_value: '0.00',
        supplier_in_transit_value: '0.00',
        supplier_company_stock_value: '0.00',
        gross: '750000.00',
        total: '1100000.00',
      },
      already_distributed: '75000.00',
      already_validated_total: '0.00',
      result_after_debts_and_capital: '575000.00',
      distributable_result: '750000.00',
      shareholders: [],
    })

    const wrapper = mount(ProfitView)
    await flushPromises()
    await flushPromises()

    const alreadyDistributedCard = wrapper.find('[data-test="profit-already-distributed-card"]')
    expect(alreadyDistributedCard.exists()).toBe(true)
    expect(alreadyDistributedCard.text()).toContain('Déjà réparti (non retiré)')
    expect(alreadyDistributedCard.text()).toContain('75 000 XOF')
  })

  // UI reorg (2026-09-04): the two placeholder "profit-summary-card" cards
  // (Benefice encaisse / Benefice distribuable, no real value ever shown)
  // were removed as dead weight - Section "Rentabilite" now shows the 3
  // real, data-backed profit blocks instead (covered by a separate test
  // below).
  it('shows the Rentabilite and Distribution section headers in order', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()
    await flushPromises()

    const text = wrapper.text()
    const profitabilityIndex = text.indexOf('Rentabilité')
    const distributionIndex = text.indexOf('Distribution')
    const costDetailIndex = text.indexOf('Détail des coûts trajets')
    expect(profitabilityIndex).toBeGreaterThanOrEqual(0)
    expect(distributionIndex).toBeGreaterThan(profitabilityIndex)
    expect(costDetailIndex).toBeGreaterThan(distributionIndex)
    expect(text).toContain("Est-ce que l'activité est rentable ?")
    expect(text).toContain('Combien peut-on distribuer aux associés ?')
  })

  it('refetches the trip table with ISO start_date and end_date when custom dates change', async () => {
    fetchReport.mockImplementation(async (_reportType, params) => ({
      report_type: 'margin-report',
      fields: [],
      rows:
        params?.start_date === '2026-09-01' && params?.end_date === '2026-09-01'
          ? [
              {
                trip_reference: 'TRIP-SEP',
                client: 'Client Septembre',
                product: 'Gasoil',
                quantity: '1000.00',
                quantity_loaded: '1000.00',
                quantity_invoiced: '1000.00',
                transporter_loss_quantity: '0.00',
                transporter_loss_indemnity: '0.00',
                supplier_unit_price: '500.0000',
                transport_cost: '0.00',
                customs_cost: '0.00',
                transit_cost: '0.00',
                road_transit_cost: '0.00',
                border_cost: '0.00',
                loading_cost: '0.00',
                additional_costs: '0.00',
                real_total_cost: '600000.00',
                unit_cost: '600.0000',
                unit_selling_price: '650.0000',
                unit_profit: '50.0000',
                current_margin: '50000.00',
              },
            ]
          : [
              {
                trip_reference: 'TRIP-JAN',
                client: 'Client Janvier',
                product: 'Gasoil',
                quantity: '1000.00',
                quantity_loaded: '1000.00',
                quantity_invoiced: '1000.00',
                transporter_loss_quantity: '0.00',
                transporter_loss_indemnity: '0.00',
                supplier_unit_price: '500.0000',
                transport_cost: '0.00',
                customs_cost: '0.00',
                transit_cost: '0.00',
                road_transit_cost: '0.00',
                border_cost: '0.00',
                loading_cost: '0.00',
                additional_costs: '0.00',
                real_total_cost: '620000.00',
                unit_cost: '620.0000',
                unit_selling_price: '650.0000',
                unit_profit: '30.0000',
                current_margin: '30000.00',
              },
            ],
    }))
    const wrapper = mount(ProfitView)
    await flushPromises()
    expect(wrapper.text()).toContain('TRIP-JAN')
    expect(wrapper.text()).toContain('30 000 XOF')

    await wrapper.find('select').setValue('custom')
    await flushPromises()
    const inputs = wrapper.findAll('input[type="date"]')
    await inputs[0]!.setValue('2026-09-01')
    await inputs[1]!.setValue('2026-09-01')
    await flushPromises()

    expect(fetchReport).toHaveBeenLastCalledWith(
      'margin-report',
      expect.objectContaining({
        preset: 'custom',
        start_date: '2026-09-01',
        end_date: '2026-09-01',
      }),
    )
    expect(fetchShareholderProfitPreview).toHaveBeenLastCalledWith(
      expect.objectContaining({
        preset: 'custom',
        start_date: '2026-09-01',
        end_date: '2026-09-01',
      }),
    )
    expect(wrapper.text()).toContain('TRIP-SEP')
    expect(wrapper.text()).toContain('50 000 XOF')
    expect(wrapper.text()).not.toContain('TRIP-JAN')
    expect(wrapper.text()).not.toContain('30 000 XOF')
  })

  it('shows operational profit, general expenses paid, and net profit from the preview', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()

    expect(wrapper.text()).toContain('Bénéfice opérationnel des trajets')
    expect(wrapper.text()).toContain('Dépenses générales payées')
    expect(wrapper.text()).toContain('Bénéfice net après dépenses générales')
    expect(wrapper.text()).toContain('150 000 XOF')
    expect(wrapper.text()).toContain('750 000 XOF')
  })

  it('renders dashboard-style cost cards with icons and tabular aligned amounts', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()

    const cards = wrapper.findAll('[data-test="profit-cost-card"]')
    expect(cards).toHaveLength(9)
    expect(cards[0]!.classes()).toEqual(
      expect.arrayContaining(['border-ligne', 'rounded-lg', 'border', 'bg-white', 'p-4']),
    )
    expect(cards[0]!.find('svg').exists()).toBe(true)
    expect(cards[0]!.find('.font-mono.tabular-nums').exists()).toBe(true)
  })

  // Bug fix (2026-09-03 recette manuelle): "Transit routiere" (road_transit_
  // cost) used to be silently folded into "Autres frais comptabilises" -
  // it must now have its own dedicated card, and "Autres frais" must not
  // include it anymore.
  it('shows a dedicated Transit routiere card, separate from Autres frais', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()

    expect(wrapper.text()).toContain('Frais transit routière des trajets comptabilisés')

    const cards = wrapper.findAll('[data-test="profit-cost-card"]')
    const roadTransitCard = cards.find((card) =>
      card.text().includes('Frais transit routière des trajets comptabilisés'),
    )
    expect(roadTransitCard).toBeDefined()
    expect(roadTransitCard!.text()).toContain('50 000 XOF')

    const otherCard = cards.find((card) =>
      card.text().includes('Autres frais des trajets comptabilisés'),
    )
    expect(otherCard).toBeDefined()
    expect(otherCard!.text()).toContain('50 000 XOF')
    expect(otherCard!.text()).not.toContain('100 000 XOF')
  })

  it('shows an empty state when the period has no trips', async () => {
    fetchReport.mockResolvedValue({ report_type: 'margin-report', fields: [], rows: [] })
    const wrapper = mount(ProfitView)
    await flushPromises()

    expect(wrapper.text()).toContain('Aucun')
  })

  it('colors per-trip unit and total profit by sign', async () => {
    fetchReport.mockResolvedValue({
      report_type: 'margin-report',
      fields: [],
      rows: [
        {
          trip_reference: 'TRIP-POS',
          client: 'Client A',
          product: 'Gasoil',
          quantity: '1000.00',
          quantity_loaded: '1000.00',
          quantity_invoiced: '1000.00',
          transporter_loss_quantity: '0.00',
          transporter_loss_indemnity: '0.00',
          supplier_unit_price: '500.0000',
          transport_cost: '0.00',
          customs_cost: '0.00',
          transit_cost: '0.00',
          road_transit_cost: '0.00',
          border_cost: '0.00',
          loading_cost: '0.00',
          additional_costs: '0.00',
          real_total_cost: '630000.00',
          unit_cost: '630.0000',
          unit_selling_price: '640.0000',
          unit_profit: '10.0000',
          current_margin: '10000.00',
        },
        {
          trip_reference: 'TRIP-NEG',
          client: 'Client B',
          product: 'Gasoil',
          quantity: '1000.00',
          quantity_loaded: '1000.00',
          quantity_invoiced: '1000.00',
          transporter_loss_quantity: '0.00',
          transporter_loss_indemnity: '0.00',
          supplier_unit_price: '500.0000',
          transport_cost: '0.00',
          customs_cost: '0.00',
          transit_cost: '0.00',
          road_transit_cost: '0.00',
          border_cost: '0.00',
          loading_cost: '0.00',
          additional_costs: '0.00',
          real_total_cost: '650000.00',
          unit_cost: '650.0000',
          unit_selling_price: '640.0000',
          unit_profit: '-10.0000',
          current_margin: '-10000.00',
        },
        {
          trip_reference: 'TRIP-ZERO',
          client: 'Client C',
          product: 'Gasoil',
          quantity: '1000.00',
          quantity_loaded: '1000.00',
          quantity_invoiced: '1000.00',
          transporter_loss_quantity: '0.00',
          transporter_loss_indemnity: '0.00',
          supplier_unit_price: '500.0000',
          transport_cost: '0.00',
          customs_cost: '0.00',
          transit_cost: '0.00',
          road_transit_cost: '0.00',
          border_cost: '0.00',
          loading_cost: '0.00',
          additional_costs: '0.00',
          real_total_cost: '640000.00',
          unit_cost: '640.0000',
          unit_selling_price: '640.0000',
          unit_profit: '0.0000',
          current_margin: '0.00',
        },
      ],
    })
    const wrapper = mount(ProfitView)
    await flushPromises()

    const bodyRows = wrapper.findAll('tbody tr')
    const [posRow, negRow, zeroRow] = bodyRows
    const profitCells = (row: (typeof bodyRows)[number]) =>
      row
        .findAll('td')
        .slice(-2)
        .map((td) => td.find('span'))

    const [posUnit, posTotal] = profitCells(posRow!)
    expect(posUnit!.classes()).toContain('text-livre')
    expect(posTotal!.classes()).toContain('text-livre')

    const [negUnit, negTotal] = profitCells(negRow!)
    expect(negUnit!.classes()).toContain('text-critique')
    expect(negTotal!.classes()).toContain('text-critique')

    const [zeroUnit, zeroTotal] = profitCells(zeroRow!)
    expect(zeroUnit!.classes()).not.toContain('text-livre')
    expect(zeroUnit!.classes()).not.toContain('text-critique')
    expect(zeroTotal!.classes()).not.toContain('text-livre')
    expect(zeroTotal!.classes()).not.toContain('text-critique')
  })

  // UI reorg (2026-09-04): the new section titles/labels exist and are
  // correctly localized in all 3 supported languages.
  it('localizes the section titles and capital-contributed label in French, English, and Arabic', async () => {
    const french = mount(ProfitView)
    await flushPromises()
    await flushPromises()
    expect(french.text()).toContain('Rentabilité')
    expect(french.text()).toContain('Distribution')
    expect(french.text()).toContain('Détail des coûts trajets')
    expect(french.text()).toContain('Capital apporté')
    french.unmount()

    i18n.global.locale.value = 'en'
    const english = mount(ProfitView)
    await flushPromises()
    await flushPromises()
    expect(english.text()).toContain('Profitability')
    expect(english.text()).toContain('Distribution')
    expect(english.text()).toContain('Trip cost detail')
    expect(english.text()).toContain('Capital contributed')
    expect(english.text()).not.toContain('Rentabilité')
    english.unmount()

    i18n.global.locale.value = 'ar'
    const arabic = mount(ProfitView)
    await flushPromises()
    await flushPromises()
    expect(arabic.text()).toContain('الربحية')
    expect(arabic.text()).toContain('التوزيع')
    expect(arabic.text()).toContain('تفاصيل تكاليف الرحلات')
    expect(arabic.text()).toContain('رأس المال المُقدَّم')
    expect(arabic.text()).not.toContain('Rentabilité')
  })

  // Client request (2026-09-06): "Exporter en PDF" button, respecting the
  // period currently selected on this page.
  it('exports a PDF respecting the currently selected period', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()
    await flushPromises()

    const button = wrapper.find('[data-test="profit-export-pdf"]')
    expect(button.exists()).toBe(true)
    await button.trigger('click')
    await flushPromises()

    expect(exportProfitReportPdf).toHaveBeenCalledWith(
      expect.objectContaining({ preset: 'period' }),
      'fr',
    )
  })

  it('shows an error message if the PDF export fails, without blocking the page', async () => {
    exportProfitReportPdf.mockRejectedValueOnce(new Error('network error'))
    const wrapper = mount(ProfitView)
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-test="profit-export-pdf"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain("Impossible d'exporter ce rapport.")
    expect(wrapper.text()).toContain('TRIP-1')
  })
  // Spec 2026-10-05-periodes-independantes: in "Periode en cours" an older
  // trip changed since the last closure comes back as an adjustment row
  // carrying only the difference - totals must sum each row's own revenue
  // and supplier cost (a quantity x price product is wrong on a delta row).
  it('sums revenue from rows and marks since-closure adjustment rows', async () => {
    fetchReport.mockResolvedValue({
      report_type: 'margin-report',
      fields: [],
      rows: [
        {
          trip_id: 1,
          is_adjustment: false,
          trip_reference: 'TRIP-NEW',
          client: 'Client A',
          product: 'Gasoil',
          quantity: '1000.00',
          quantity_loaded: '1000.00',
          quantity_invoiced: '1000.00',
          transporter_loss_quantity: '0.00',
          transporter_loss_indemnity: '0.00',
          supplier_unit_price: '600.0000',
          transport_cost: '0.00',
          customs_cost: '0.00',
          transit_cost: '0.00',
          road_transit_cost: '0.00',
          border_cost: '0.00',
          loading_cost: '0.00',
          additional_costs: '0.00',
          real_total_cost: '600000.00',
          unit_cost: '600.0000',
          unit_selling_price: '1000.0000',
          unit_profit: '400.0000',
          current_margin: '400000.00',
          revenue: '1000000.00',
          supplier_cost: '600000.00',
        },
        {
          trip_id: 2,
          is_adjustment: true,
          trip_reference: 'TRIP-OLD',
          client: 'Client B',
          product: 'Gasoil',
          quantity: '0.00',
          quantity_loaded: '0.00',
          quantity_invoiced: '0.00',
          transporter_loss_quantity: '0.00',
          transporter_loss_indemnity: '0.00',
          supplier_unit_price: '600.0000',
          transport_cost: '0.00',
          customs_cost: '90000.00',
          transit_cost: '0.00',
          road_transit_cost: '0.00',
          border_cost: '0.00',
          loading_cost: '0.00',
          additional_costs: '0.00',
          real_total_cost: '90000.00',
          unit_cost: '602.0000',
          unit_selling_price: '900.0000',
          unit_profit: '298.0000',
          current_margin: '-90000.00',
          revenue: '0.00',
          supplier_cost: '0.00',
        },
      ],
    })

    const wrapper = mount(ProfitView)
    await flushPromises()
    await flushPromises()

    const operational = wrapper.find('[data-test="profit-operational-card"]')
    expect(operational.text()).toContain('310 000 XOF')
    expect(operational.text()).toContain('1 000 000 XOF')
    const badges = wrapper.findAll('[data-test="profit-adjustment-badge"]')
    expect(badges).toHaveLength(1)
    expect(badges[0]!.text()).toBe('Ajustement')
    expect(wrapper.text()).not.toContain('298,0000')
  })

  it('explains a deficit carried over from the last closure under the net profit', async () => {
    fetchShareholderProfitPreview.mockResolvedValue({
      period_start: '2026-10-06',
      period_end: null,
      current_profit: '0.00',
      operational_profit: '0.00',
      revenue: '0.00',
      general_expenses_paid: '0.00',
      carried_over: '-500000.00',
      distributions_since_closure: '0.00',
      net_profit: '-500000.00',
      all_time_net_profit: '-500000.00',
      total_company_absorbed_loss: '0.00',
      working_capital: {
        capital: '0.00',
        treasury_available: '0.00',
        customer_receivables: '0.00',
        supplier_debt_total: '0.00',
        transporter_debt_total: '0.00',
        other_debts: '0.00',
        supplier_reliquat_value: '0.00',
        supplier_in_transit_value: '0.00',
        supplier_company_stock_value: '0.00',
        gross: '0.00',
        total: '0.00',
      },
      already_distributed: '0.00',
      already_validated_total: '0.00',
      result_after_debts_and_capital: '0.00',
      distributable_result: '-500000.00',
      shareholders: [],
    })

    const wrapper = mount(ProfitView)
    await flushPromises()
    await flushPromises()

    const carried = wrapper.find('[data-test="profit-carried-over"]')
    expect(carried.exists()).toBe(true)
    expect(carried.text()).toContain('Report période précédente')
    expect(carried.text()).toContain('500 000 XOF')
    expect(wrapper.find('[data-test="profit-distributions-since-closure"]').exists()).toBe(false)
  })

  it('explains the profit brought from the previous application under the net profit', async () => {
    const preview = await fetchShareholderProfitPreview()
    fetchShareholderProfitPreview.mockResolvedValue({
      ...preview,
      brought_forward_profit: '92358500.00',
      net_profit: '92358500.00',
      distributable_result: '92358500.00',
    })

    const wrapper = mount(ProfitView)
    await flushPromises()
    await flushPromises()

    const note = wrapper.find('[data-test="profit-brought-forward"]')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('92 358 500 XOF')
  })
})

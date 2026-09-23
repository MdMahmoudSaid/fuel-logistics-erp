import { describe, it, expect, vi, beforeEach } from 'vitest'

const get = vi.fn()
vi.mock('@/api/client', () => ({ apiClient: { get: (...args: unknown[]) => get(...args) } }))

import { fetchReport } from '../api'

// TripDetail (loss-report), DashboardView (loss-report) and ProfitView
// (margin-report) call fetchReport(type, params) and must keep receiving the
// legacy {report_type, fields, rows} payload (spec D3, compatibility contract).
describe('fetchReport', () => {
  beforeEach(() => {
    get.mockReset()
    get.mockResolvedValue({ data: { report_type: 'loss-report', fields: [], rows: [] } })
  })

  it('sends only the caller params when no options are given', async () => {
    const result = await fetchReport('loss-report', { from: '2026-01-01', to: '2026-12-31' })

    expect(get).toHaveBeenCalledWith('/reports/loss-report/', {
      params: { from: '2026-01-01', to: '2026-12-31' },
    })
    expect(Object.keys(get.mock.calls[0]![1].params)).not.toContain('document')
    expect(Object.keys(get.mock.calls[0]![1].params)).not.toContain('lang')
    expect(result).toEqual({ report_type: 'loss-report', fields: [], rows: [] })
    expect(result.document).toBeUndefined()
  })

  it('adds document=1 and lang only when asked', async () => {
    await fetchReport('customer-statement', { customer_id: '4' }, { document: true, lang: 'ar' })

    expect(get).toHaveBeenCalledWith('/reports/customer-statement/', {
      params: { customer_id: '4', document: '1', lang: 'ar' },
    })
  })
})

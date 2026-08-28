import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CessionLetterList from '../CessionLetterList.vue'
import type { CessionLetter } from '../types'

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

const push = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

const cessionWithProof: CessionLetter = {
  id: 1,
  reference: 'CES-001',
  supplier_order: 5,
  authorized_quantity: '45000.00',
  issue_date: '2026-08-20',
  status: 'ACTIVE',
  notes: '',
  created_by: 1,
  created_by_detail: null,
  loaded_quantity: '0.00',
  remaining_quantity: '45000.00',
  documents: [
    {
      id: 9,
      file: '/media/documents/cession.jpg',
      document_type: 'cession_proof',
      reference: '',
      uploaded_by: 1,
      uploaded_by_email: 'admin@example.com',
      created_at: '',
    },
  ],
  created_at: '',
  updated_at: '',
}

const list = vi.fn(async () => paginated([cessionWithProof, { ...cessionWithProof, id: 2, reference: 'CES-002', documents: [] }]))

vi.mock('../api', () => ({
  cessionLetterResource: {
    list: (...args: unknown[]) => list(...(args as [])),
  },
}))

describe('CessionLetterList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows cession proofs in an internal modal and leaves empty rows as dashes', async () => {
    const wrapper = mount(CessionLetterList)
    await flushPromises()

    expect(wrapper.text()).toContain('Justificatif')
    expect(wrapper.find('a[target="_blank"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('—')

    const proofButton = wrapper.findAll('button').find((button) => button.text() === 'Voir justificatif')
    expect(proofButton).toBeTruthy()
    await proofButton!.trigger('click')
    await flushPromises()

    expect(push).not.toHaveBeenCalled()
    expect(wrapper.find('img[src="/media/documents/cession.jpg"]').exists()).toBe(true)
  })
})

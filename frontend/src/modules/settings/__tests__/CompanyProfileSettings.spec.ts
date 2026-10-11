import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CompanyProfileSettings from '../CompanyProfileSettings.vue'
import type { CompanyProfile } from '../types'

const profile = (): CompanyProfile => ({
  name: 'AZUR',
  tagline: '',
  tax_id: '',
  trade_register: '',
  address: '',
  city: '',
  phone: '',
  email: '',
  website: '',
  bank_accounts: [],
})
const updateCompanyProfile = vi.fn(async (p: Partial<CompanyProfile>) => ({ ...profile(), ...p }))

vi.mock('../api', () => ({
  fetchCompanyProfile: vi.fn(async () => profile()),
  updateCompanyProfile: (p: Partial<CompanyProfile>) => updateCompanyProfile(p),
}))

describe('CompanyProfileSettings', () => {
  beforeEach(() => vi.clearAllMocks())

  it('edits the details, adds a bank account and saves everything', async () => {
    const wrapper = mount(CompanyProfileSettings)
    await flushPromises()
    expect((wrapper.find('#company-name').element as HTMLInputElement).value).toBe('AZUR')

    await wrapper.find('#company-name').setValue('Sahel Commerce')
    await wrapper.find('[data-test="add-bank"]').trigger('click')
    await wrapper.find('[data-test="bank-0-bank"]').setValue('ECOBANK')
    await wrapper.find('[data-test="bank-0-account"]').setValue('SN094 01001')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(updateCompanyProfile).toHaveBeenCalledTimes(1)
    const sent = updateCompanyProfile.mock.calls[0][0]
    expect(sent.name).toBe('Sahel Commerce')
    expect(sent.bank_accounts).toEqual([
      { bank: 'ECOBANK', swift: '', account_number: 'SN094 01001', is_active: true },
    ])
    expect(wrapper.text()).toContain('Informations enregistrées.')
  })
})

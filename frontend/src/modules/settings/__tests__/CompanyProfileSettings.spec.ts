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

  it('adds and removes several phone numbers and e-mails, sent one per line', async () => {
    const wrapper = mount(CompanyProfileSettings)
    await flushPromises()
    // one empty input each by default, no remove button on a lone input
    expect(wrapper.find('[data-test="company-phone-0"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="company-phone-remove-0"]').exists()).toBe(false)

    await wrapper.find('[data-test="company-phone-0"]').setValue('76680484')
    await wrapper.find('[data-test="company-phone-add"]').trigger('click')
    await wrapper.find('[data-test="company-phone-1"]').setValue('66112233')
    await wrapper.find('[data-test="company-phone-add"]').trigger('click')
    await wrapper.find('[data-test="company-phone-remove-2"]').trigger('click')

    await wrapper.find('[data-test="company-email-0"]').setValue('a@example.com')
    await wrapper.find('[data-test="company-email-add"]').trigger('click')
    await wrapper.find('[data-test="company-email-1"]').setValue('b@example.com')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const sent = updateCompanyProfile.mock.calls[0][0]
    expect(sent.phone).toBe('76680484\n66112233')
    expect(sent.email).toBe('a@example.com\nb@example.com')
  })

  it('shows each stored value in its own input', async () => {
    const api = await import('../api')
    vi.mocked(api.fetchCompanyProfile).mockResolvedValueOnce({
      ...profile(),
      phone: '76680484\n66112233',
      email: 'a@example.com\nb@example.com',
    })
    const wrapper = mount(CompanyProfileSettings)
    await flushPromises()
    expect((wrapper.find('[data-test="company-phone-1"]').element as HTMLInputElement).value).toBe(
      '66112233',
    )
    expect((wrapper.find('[data-test="company-email-1"]').element as HTMLInputElement).value).toBe(
      'b@example.com',
    )
  })
})

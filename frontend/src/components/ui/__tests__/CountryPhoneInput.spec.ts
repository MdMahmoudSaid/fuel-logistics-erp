import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import CountryPhoneInput from '@/components/ui/CountryPhoneInput.vue'
import { i18n } from '@/i18n'

describe('CountryPhoneInput', () => {
  it('defaults to Mauritania and emits the normalized number as digits are typed', async () => {
    const wrapper = mount(CountryPhoneInput, {
      props: { id: 'phone', modelValue: '' },
      global: { plugins: [i18n] },
    })

    await wrapper.find('input#phone').setValue('12345678')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['+22212345678'])
  })

  it('parses an existing normalized value back into country + national number', () => {
    const wrapper = mount(CountryPhoneInput, {
      props: { id: 'phone', modelValue: '+22112345678' },
      global: { plugins: [i18n] },
    })

    expect((wrapper.find('input#phone').element as HTMLInputElement).value).toBe('12345678')
  })

  it('filters the country dropdown by typed name', async () => {
    const wrapper = mount(CountryPhoneInput, {
      props: { id: 'phone', modelValue: '' },
      global: { plugins: [i18n] },
    })

    const dropdown = wrapper.findAll('input')[0]
    await dropdown.trigger('focus')
    await dropdown.setValue('Mauri')

    expect(wrapper.text()).toContain('+222')
  })

  it('enforces the Senegal 9-digit rule via the maxlength attribute', async () => {
    const wrapper = mount(CountryPhoneInput, {
      props: { id: 'phone', modelValue: '+221123456789' },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('input#phone').attributes('maxlength')).toBe('9')
  })
})

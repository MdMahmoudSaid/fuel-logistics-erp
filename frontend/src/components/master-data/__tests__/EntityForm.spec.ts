import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import EntityForm from '@/components/master-data/EntityForm.vue'
import type { FieldSchema } from '@/components/master-data/types'
import { i18n } from '@/i18n'

describe('EntityForm', () => {
  it('renders a password field as a masked input', () => {
    const fields: FieldSchema[] = [{ key: 'password', label: 'Password', type: 'password' }]
    const wrapper = mount(EntityForm, {
      props: { fields, modelValue: {} },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('input#password').attributes('type')).toBe('password')
  })

  it('renders a phone field with the CountryPhoneInput component', () => {
    const fields: FieldSchema[] = [{ key: 'phone', label: 'Phone', type: 'phone' }]
    const wrapper = mount(EntityForm, {
      props: { fields, modelValue: {} },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('input#phone').exists()).toBe(true)
  })

  it('renders a pin field as a 4-digit numeric input', () => {
    const fields: FieldSchema[] = [{ key: 'pin', label: 'PIN', type: 'pin' }]
    const wrapper = mount(EntityForm, {
      props: { fields, modelValue: {} },
      global: { plugins: [i18n] },
    })

    const input = wrapper.find('input#pin')
    expect(input.attributes('inputmode')).toBe('numeric')
    expect(input.attributes('maxlength')).toBe('4')
  })

  it('blocks a typed letter in the pin field before it is inserted', () => {
    const fields: FieldSchema[] = [{ key: 'pin', label: 'PIN', type: 'pin' }]
    const wrapper = mount(EntityForm, {
      props: { fields, modelValue: {} },
      global: { plugins: [i18n] },
    })

    const input = wrapper.find('input#pin').element
    const event = new InputEvent('beforeinput', {
      inputType: 'insertText',
      data: 'a',
      cancelable: true,
    })
    input.dispatchEvent(event)

    expect(event.defaultPrevented).toBe(true)
  })
})

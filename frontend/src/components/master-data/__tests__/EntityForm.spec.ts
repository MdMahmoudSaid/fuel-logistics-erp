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
})

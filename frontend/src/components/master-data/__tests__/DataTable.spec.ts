import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DataTable from '@/components/master-data/DataTable.vue'
import { i18n } from '@/i18n'

describe('DataTable', () => {
  it('formats a phone column with a space between the dial code and the number', () => {
    const wrapper = mount(DataTable, {
      props: {
        columns: [{ key: 'phone', label: 'Téléphone', type: 'phone' }],
        rows: [{ id: 1, phone: '+22212340000' }],
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.text()).toContain('+222 12340000')
    expect(wrapper.text()).not.toContain('+22212340000')
  })
})

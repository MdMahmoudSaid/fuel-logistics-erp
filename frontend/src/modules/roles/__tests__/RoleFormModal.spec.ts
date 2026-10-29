import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { MODULES } from '@/modules/roles/permissionSchema'
import RoleFormModal from '@/modules/roles/RoleFormModal.vue'

describe('RoleFormModal', () => {
  it('toggles a permission action on and off', async () => {
    const wrapper = mount(RoleFormModal, {
      props: { modelValue: { name: 'Custom', permissions: {} } },
    })

    const rows = wrapper.findAll('tbody tr')
    const operationsRow = rows[0]
    await operationsRow!.findAll('input[type="checkbox"]')[0]!.setValue(true)

    let emitted = wrapper.emitted('update:modelValue')!
    expect(
      (emitted[0]![0] as { permissions: Record<string, string[]> }).permissions.operations,
    ).toEqual(['view'])

    await wrapper.setProps({
      modelValue: emitted[0]![0] as { name: string; permissions: Record<string, string[]> },
    })
    await wrapper.findAll('tbody tr')[0]!.findAll('input[type="checkbox"]')[0]!.setValue(false)

    emitted = wrapper.emitted('update:modelValue')!
    expect(
      (emitted[emitted.length - 1]![0] as { permissions: Record<string, string[]> }).permissions
        .operations,
    ).toEqual([])
  })

  it('offers every module the backend gates on, including reports', () => {
    const wrapper = mount(RoleFormModal, {
      props: { modelValue: { name: 'Custom', permissions: {} } },
    })
    // Must stay in sync with Role.MODULES in backend/apps/accounts/models.py.
    expect(MODULES).toEqual([
      'operations',
      'finance',
      'sales',
      'purchasing',
      'admin',
      'reports',
      'shareholders',
    ])
    expect(wrapper.findAll('tbody tr')).toHaveLength(MODULES.length)
  })
})

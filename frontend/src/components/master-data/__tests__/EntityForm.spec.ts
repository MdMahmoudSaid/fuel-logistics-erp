import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
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

  // UI recette fix (2026-09-05): generic "+ Creer..." inline mini-form for
  // a select field with a quickCreate config - Truck's Chauffeur field is
  // the first consumer, tested generically here since EntityForm is where
  // the behaviour actually lives.
  describe('quick-create on a select field', () => {
    function makeFields(create: (payload: Record<string, unknown>) => Promise<{ id: number; label: string }>): FieldSchema[] {
      return [
        {
          key: 'default_driver',
          label: 'Chauffeur',
          type: 'select',
          options: [{ value: '', label: 'Aucun' }],
          quickCreate: {
            buttonLabel: '+ Créer un nouveau chauffeur',
            errorMessage: 'Impossible de créer le chauffeur.',
            fields: [{ key: 'name', label: 'Nom', type: 'text', required: true }],
            create,
          },
        },
      ]
    }

    it('shows the quick-create toggle button next to the select', () => {
      const wrapper = mount(EntityForm, {
        props: { fields: makeFields(vi.fn()), modelValue: {} },
        global: { plugins: [i18n] },
      })

      expect(wrapper.find('[data-test="quick-create-toggle-default_driver"]').text()).toBe(
        '+ Créer un nouveau chauffeur',
      )
    })

    it('creates the record, selects it, and never loses other form values already entered', async () => {
      const create = vi.fn(async () => ({ id: 7, label: 'Ibrahim Kone' }))
      const wrapper = mount(EntityForm, {
        props: {
          fields: [
            { key: 'tractor_registration', label: 'Tracteur', type: 'text' },
            ...makeFields(create),
          ],
          modelValue: { tractor_registration: 'AA-111-SN' },
        },
        global: { plugins: [i18n] },
      })

      await wrapper.find('[data-test="quick-create-toggle-default_driver"]').trigger('click')
      await wrapper.find('#default_driver_name').setValue('Ibrahim Kone')
      await wrapper.find('[data-test="quick-create-submit-default_driver"]').trigger('click')
      await flushPromises()

      expect(create).toHaveBeenCalledWith({ name: 'Ibrahim Kone' })
      const emitted = wrapper.emitted('update:modelValue')!
      const lastEmit = emitted[emitted.length - 1]![0] as Record<string, unknown>
      expect(lastEmit.default_driver).toBe('7')
      // The tractor_registration value entered before opening quick-create
      // must survive - setField() only patches the one key it's called
      // with onto the existing modelValue.
      expect(lastEmit.tractor_registration).toBe('AA-111-SN')
      // The mini-form closes back to the toggle button after a successful
      // create.
      expect(wrapper.find('[data-test="quick-create-toggle-default_driver"]').exists()).toBe(true)
    })

    it('shows the configured error message and keeps the mini-form open when create() rejects', async () => {
      const create = vi.fn(async () => {
        throw new Error('boom')
      })
      const wrapper = mount(EntityForm, {
        props: { fields: makeFields(create), modelValue: {} },
        global: { plugins: [i18n] },
      })

      await wrapper.find('[data-test="quick-create-toggle-default_driver"]').trigger('click')
      await wrapper.find('#default_driver_name').setValue('Ibrahim Kone')
      await wrapper.find('[data-test="quick-create-submit-default_driver"]').trigger('click')
      await flushPromises()

      expect(wrapper.text()).toContain('Impossible de créer le chauffeur.')
      expect(wrapper.find('[data-test="quick-create-toggle-default_driver"]').exists()).toBe(false)
    })
  })
})

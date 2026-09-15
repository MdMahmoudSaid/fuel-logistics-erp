import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import AppAlert from '../AppAlert.vue'
import AlertNotifications from '../AlertNotifications.vue'
import Modal from '../Modal.vue'
import { dismissAlertNotification } from '@/composables/useAlertNotification'

enableAutoUnmount(afterEach)
afterEach(() => {
  dismissAlertNotification()
  vi.restoreAllMocks()
})

function notification() {
  return document.querySelector<HTMLElement>('[data-test="alert-notification"]')
}

function mountForm(outsideForm = false) {
  const error = ref('')
  const wrapper = mount(
    defineComponent({
      components: { AppAlert, AlertNotifications, Modal },
      setup: () => ({ error }),
      template: `<div>
      <AlertNotifications />
      <Modal title="Paiement">
        ${outsideForm ? '<AppAlert v-if="error" :message="error" />' : ''}
        <form @submit.prevent="error = 'Solde insuffisant.'">
          ${outsideForm ? '' : '<AppAlert v-if="error" :message="error" />'}
          <button>Enregistrer</button>
        </form>
      </Modal>
    </div>`,
    }),
    { attachTo: document.body },
  )
  return { wrapper, error }
}

describe('application alerts', () => {
  it('opens one centered error dialog without an inline banner', async () => {
    const { wrapper } = mountForm()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(notification()?.textContent).toContain('Solde insuffisant.')
    expect(notification()?.tagName).toBe('DIALOG')
    expect(notification()?.getAttribute('role')).toBe('alertdialog')
    expect(wrapper.findComponent(AppAlert).attributes('hidden')).toBeDefined()
    expect(wrapper.findComponent(AppAlert).text()).toContain('Solde insuffisant.')
  })

  it.each([false, true])('reopens the same error on retry (outside form: %s)', async (outside) => {
    const { wrapper } = mountForm(outside)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    notification()!.querySelector<HTMLButtonElement>('button')!.click()
    await flushPromises()
    expect(notification()).toBeNull()
    expect(wrapper.findComponent(AppAlert).text()).toContain('Solde insuffisant.')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(notification()?.textContent).toContain('Solde insuffisant.')
  })

  it('removes the notification when its error is cleared or its form is closed', async () => {
    const { wrapper, error } = mountForm()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    error.value = ''
    await flushPromises()
    expect(notification()).toBeNull()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    wrapper.unmount()
    expect(notification()).toBeNull()
  })

  it('updates an existing error and renders server text without interpreting HTML', async () => {
    const { wrapper, error } = mountForm()
    await wrapper.find('form').trigger('submit')
    error.value = '<b>Connexion interrompue</b>'
    await flushPromises()
    expect(notification()?.textContent).toContain('<b>Connexion interrompue</b>')
    expect(notification()?.querySelector('b')).toBeNull()
  })

  it('focuses OK and returns focus to the submit button when dismissed', async () => {
    const { wrapper } = mountForm()
    const submit = wrapper.find('form button').element as HTMLButtonElement
    submit.focus()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const ok = notification()!.querySelector<HTMLButtonElement>('button')!
    expect(document.activeElement).toBe(ok)
    ok.click()
    await flushPromises()
    expect(document.activeElement).toBe(submit)
    expect(notification()).toBeNull()
  })

  it('dismisses the popup on Escape without closing the form', async () => {
    const { wrapper } = mountForm()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    notification()!.dispatchEvent(new Event('cancel', { cancelable: true }))
    await flushPromises()
    expect(notification()).toBeNull()
    expect(wrapper.find('form').exists()).toBe(true)
  })

  it('does not remove another form’s newer notification when an older form closes', async () => {
    mount(AlertNotifications)
    const first = mount(AppAlert, { props: { message: 'First error' } })
    mount(AppAlert, { props: { message: 'Second error' } })
    await flushPromises()
    first.unmount()
    await flushPromises()
    expect(notification()?.textContent).toContain('Second error')
  })
})

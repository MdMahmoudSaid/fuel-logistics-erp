import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '@/modules/auth/LoginView.vue'
import { i18n } from '@/i18n'

describe('LoginView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the sign-in form', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', name: 'home', component: { template: '<div />' } },
        { path: '/login', name: 'login', component: LoginView },
      ],
    })
    router.push('/login')
    await router.isReady()

    const wrapper = mount(LoginView, {
      global: { plugins: [router, i18n] },
    })

    expect(wrapper.find('input#phone').exists()).toBe(true)
    expect(wrapper.find('input#pin').exists()).toBe(true)
    expect(wrapper.find('button[type="submit"]').text()).toContain('Se connecter')
  })

  it('blocks a typed letter in the PIN field before it is inserted', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', name: 'home', component: { template: '<div />' } },
        { path: '/login', name: 'login', component: LoginView },
      ],
    })
    router.push('/login')
    await router.isReady()

    const wrapper = mount(LoginView, {
      global: { plugins: [router, i18n] },
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

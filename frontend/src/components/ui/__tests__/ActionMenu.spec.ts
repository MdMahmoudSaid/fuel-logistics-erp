import { describe, it, expect, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import ActionMenu from '../ActionMenu.vue'

const mounted: { unmount: () => void }[] = []

// jsdom has no layout: fake the trigger's box, the menu's size and the window.
function mountWith(trigger: { top: number; bottom: number }, menuHeight: number, viewport: number) {
  Object.defineProperty(window, 'innerHeight', { value: viewport, configurable: true })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get() {
      return (this as HTMLElement).getAttribute('role') === 'menu' ? menuHeight : 0
    },
  })
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
    configurable: true,
    get() {
      return (this as HTMLElement).getAttribute('role') === 'menu' ? 160 : 0
    },
  })
  const wrapper = mount(ActionMenu, {
    props: { label: 'More', items: [{ key: 'a', label: 'A' }] },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  const button = wrapper.find('button').element
  vi.spyOn(button, 'getBoundingClientRect').mockReturnValue({
    top: trigger.top,
    bottom: trigger.bottom,
    left: 900,
    right: 930,
    width: 30,
    height: trigger.bottom - trigger.top,
    x: 900,
    y: trigger.top,
    toJSON: () => ({}),
  })
  return wrapper
}

async function openMenu(wrapper: ReturnType<typeof mountWith>) {
  await wrapper.find('button').trigger('click')
  await nextTick()
  await nextTick()
  return document.body.querySelector('[role=menu]') as HTMLElement
}

describe('ActionMenu placement', () => {
  afterEach(() => {
    mounted.splice(0).forEach((w) => w.unmount())
  })

  it('opens below the button when there is room', async () => {
    const menu = await openMenu(mountWith({ top: 100, bottom: 130 }, 120, 800))
    expect(menu.style.top).toBe('134px') // bottom + gap
    expect(menu.style.visibility).toBe('visible')
  })

  it('opens above the button when the row is near the bottom of the screen', async () => {
    const menu = await openMenu(mountWith({ top: 740, bottom: 770 }, 120, 800))
    expect(menu.style.top).toBe('616px') // trigger top - gap - menu height
  })

  it('scrolls inside the larger side when neither side fits', async () => {
    const menu = await openMenu(mountWith({ top: 300, bottom: 330 }, 600, 700))
    expect(menu.style.maxHeight).not.toBe('')
  })
})

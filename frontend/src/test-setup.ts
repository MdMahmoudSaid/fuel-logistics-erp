// Node 22+ ships a stub global `localStorage` (see the "--localstorage-file"
// warning) that shadows jsdom's implementation, because vitest's jsdom
// environment only assigns `localStorage` when it's absent from globalThis.
// Replace it with a real, working jsdom-backed Storage instance.
import { JSDOM } from 'jsdom'

const dom = new JSDOM('', { url: 'http://localhost' })
Object.defineProperty(globalThis, 'localStorage', {
  value: dom.window.localStorage,
  configurable: true,
  writable: true,
})

// Every component may call useI18n(), so every @vue/test-utils mount needs
// the i18n plugin installed — register it once globally instead of passing
// `global: { plugins: [i18n] }` in each spec file. Imported dynamically
// (after the localStorage polyfill above runs) because src/i18n/index.ts
// reads localStorage at module load time, and static imports are hoisted
// above the polyfill regardless of source order.
const { config } = await import('@vue/test-utils')
const { i18n } = await import('@/i18n')

config.global.plugins.push(i18n)

// jsdom does not implement the native dialog lifecycle. Browser checks cover
// top-layer rendering and modal keyboard behaviour.
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute('open', '')
}
HTMLDialogElement.prototype.close = function () {
  this.removeAttribute('open')
}

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

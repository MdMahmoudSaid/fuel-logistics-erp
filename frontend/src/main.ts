import './style.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { i18n } from './i18n'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(i18n)

app.mount('#app')

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  navigator.serviceWorker.register('/sw.js')
}

// Bug fix (client feedback 2026-09-06): scrolling the mouse wheel over a
// focused <input type="number"> makes the browser itself step the value
// up/down (e.g. quantite/prix unitaire silently drifting by 0.01 while the
// user just scrolls the page past the field) - this is native browser
// behaviour, not something a single component can opt out of, so it's
// fixed once here for every numeric field in the app instead of touching
// each form. One delegated listener (not per-input) blurs whichever
// number input currently has focus the moment a wheel event reaches it -
// the field keeps its value exactly as typed, the page still scrolls
// normally, only the accidental focus-driven step is stopped. The visible
// spin-button arrows are removed separately in style.css.
window.addEventListener(
  'wheel',
  () => {
    const active = document.activeElement
    if (active instanceof HTMLInputElement && active.type === 'number') {
      active.blur()
    }
  },
  { passive: true },
)

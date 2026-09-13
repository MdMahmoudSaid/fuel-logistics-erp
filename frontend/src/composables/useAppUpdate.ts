import { ref } from 'vue'

// Bug fix (2026-09-13): the service worker had no update path at all - once
// a phone or a browser tab cached the app shell, it kept serving that exact
// build forever, even after a redeploy, until someone manually cleared site
// data. This registers the worker, detects when a *new* one has finished
// installing behind the current one, and exposes a flag so the UI can offer
// a one-tap refresh instead of silently reloading mid-task (a manager
// halfway through a payment form should never get yanked out from under
// them).
const updateAvailable = ref(false)
let waitingWorker: ServiceWorker | null = null

export function useAppUpdate() {
  function reload() {
    // Just hands control to the new worker - the controllerchange listener
    // below does the actual page reload once that handoff completes, so a
    // stale tab never reloads onto its own still-old cache.
    if (waitingWorker) waitingWorker.postMessage({ type: 'SKIP_WAITING' })
    else window.location.reload()
  }

  return { updateAvailable, reload }
}

export function initAppUpdate() {
  if (!('serviceWorker' in navigator) || !import.meta.env.PROD) return

  navigator.serviceWorker.register('/sw.js').then((registration) => {
    // A worker already sitting in "waiting" (installed while no tab was
    // open) counts as an update too.
    if (registration.waiting) {
      waitingWorker = registration.waiting
      updateAvailable.value = true
    }

    registration.addEventListener('updatefound', () => {
      const incoming = registration.installing
      if (!incoming) return
      incoming.addEventListener('statechange', () => {
        if (incoming.state === 'installed' && navigator.serviceWorker.controller) {
          waitingWorker = incoming
          updateAvailable.value = true
        }
      })
    })

    // Catch a version that was deployed while this tab was already open and
    // idle - a plain "did a new worker show up" poll, cheap enough to run
    // whenever the tab regains focus.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') registration.update()
    })
  })

  // The new worker calls skipWaiting via our postMessage above, which swaps
  // the controller - reload once that happens so the fresh assets actually
  // take effect instead of the old ones lingering in memory.
  let reloading = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading) return
    reloading = true
    window.location.reload()
  })
}

// Minimal app-shell cache for offline reload support.
// Full offline action queue is deferred to Phase 7 (see roadmap/phase_7_hardening_deployment.md).
const CACHE_NAME = 'fuel-erp-shell-v1'
const SHELL_ASSETS = ['/', '/index.html']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)))
})

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)))
})

// App-shell cache for offline reload support.
// Full offline action queue is deferred to Phase 7 (see roadmap/phase_7_hardening_deployment.md).
//
// Bug fix (2026-09-13): CACHE_NAME used to be a hardcoded string that never
// changed between deploys, and the fetch handler served every GET
// cache-first - including '/' and '/index.html' themselves. Once a phone or
// a browser tab cached the shell once, it kept getting that exact build back
// forever; a redeploy changed nothing until someone manually cleared site
// data. Two changes fix that without giving up offline support:
//   1. The shell (navigation requests, i.e. index.html) is now
//      network-first - a live deploy always wins when the network is up,
//      and the cached copy is only a fallback for offline/flaky connections.
//   2. CACHE_NAME is versioned and 'activate' deletes every older cache, so
//      nothing accumulates and nothing outlives the build that made it.
// Hashed static assets (/assets/*.js, /assets/*.css - Vite content-hashes
// every filename) are still safe to cache-first forever: a changed file is a
// changed URL, never a stale one under an old name.
//
// Bug fix (2026-09-14, recette): the fetch handler's fallback branch below
// applied cache-first to EVERY same-origin GET, not just static assets -
// including /api/* calls like GET /api/suppliers/. The first load cached
// that exact response, and every later GET to the same URL (e.g. the list
// reload right after creating a supplier) replayed that same stale response
// forever instead of hitting the network - a create would succeed on the
// server (confirmed: duplicate Supplier rows from repeated retries) while
// the screen kept showing the old, unchanged list. /api/ requests must
// never be cached - always network, matching how dynamic data already
// worked before this service worker existed at all.
const CACHE_VERSION = 'v4'
const CACHE_NAME = `fuel-erp-shell-${CACHE_VERSION}`
const SHELL_ASSETS = ['/', '/index.html']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)))
  // Finish installing immediately rather than waiting for every open tab to
  // close - useAppUpdate.ts gates the actual takeover behind an explicit
  // user tap (SKIP_WAITING message), so this alone doesn't disrupt anyone.
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    Promise.all([
      caches.keys().then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
      ),
      self.clients.claim(),
    ]),
  )
})

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting()
})

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone()
          caches.open(CACHE_NAME).then((cache) => cache.put('/index.html', copy))
          return response
        })
        .catch(() => caches.match('/index.html')),
    )
    return
  }

  if (new URL(event.request.url).pathname.startsWith('/api/')) {
    return
  }

  event.respondWith(
    caches.match(event.request).then(
      (cached) =>
        cached ||
        fetch(event.request).then((response) => {
          if (response.ok && new URL(event.request.url).origin === self.location.origin) {
            const copy = response.clone()
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy))
          }
          return response
        }),
    ),
  )
})

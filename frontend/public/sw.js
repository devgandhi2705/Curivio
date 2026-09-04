// Curivio service worker — app shell caching + offline data serving.

const SHELL_CACHE_PREFIX = 'curivio-shell-'
// v3: the colour-grading rebuild. Static assets are cache-first below, so a
// browser holding v2 would keep serving CSS compiled by the previous Tailwind
// config — variables defined, nothing consuming them, theme switch inert.
// Bumping the version makes `activate` drop the old cache.
const SHELL_CACHE = 'curivio-shell-v3'

const STATIC_ASSET_RE = /\.(?:js|css|woff2?|png|svg|ico)$/
const PROJECT_DETAIL_RE = /^\/api\/projects\/([^/]+)$/
const INSIGHTS_PATH_RE = /^\/api\/projects\/([^/]+)\/insights\/?$/
const CHAT_MESSAGES_RE = /^\/api\/chat\/history\/([^/]+)$/

function isStaticAsset(path) {
  return STATIC_ASSET_RE.test(path)
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(['/', '/index.html']))
      .catch(() => {})
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith(SHELL_CACHE_PREFIX) && key !== SHELL_CACHE)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  const path = url.pathname
  if (url.origin !== self.location.origin) return

  if (event.request.mode === 'navigate') {
    event.respondWith(navigationShellFallback(event.request))
    return
  }

  // Static assets: cache-first (unchanged)
  if (isStaticAsset(path)) {
    event.respondWith(cacheFirst(event.request))
    return
  }

  // API intercepts: network-first, fall back to IndexedDB when offline.
  // Only intercept GET — never intercept POST/PUT/DELETE.
  if (event.request.method !== 'GET') return

  // Projects list
  if (path === '/api/projects') {
    event.respondWith(idbFallback(event.request, async () => {
      const row = await idbGet('appData', 'projectsList')
      return row ? row.data : null
    }))
    return
  }

  // Package / article content for a project's days — kept as its own lookup
  // since it's a multi-record index scan, not a single-key get.
  const insightsMatch = path.match(INSIGHTS_PATH_RE)
  if (insightsMatch) {
    const projectId = decodeURIComponent(insightsMatch[1])
    event.respondWith(idbFallback(event.request, async () => {
      const packages = await getPackagesForProject(projectId)
      return packages.length ? packages : null
    }))
    return
  }

  // Single project detail
  const projectDetailMatch = path.match(PROJECT_DETAIL_RE)
  if (projectDetailMatch) {
    const id = decodeURIComponent(projectDetailMatch[1])
    event.respondWith(idbFallback(event.request, async () => {
      return idbGet('projects', id)
    }))
    return
  }

  // Dashboard stats
  if (path === '/api/stats/reading') {
    event.respondWith(idbFallback(event.request, async () => {
      const row = await idbGet('appData', 'dashboard')
      return row ? row.stats : null
    }))
    return
  }

  // Bookmarks
  if (path === '/api/bookmarks') {
    event.respondWith(idbFallback(event.request, async () => {
      const row = await idbGet('appData', 'bookmarks')
      return row ? row.data : null
    }))
    return
  }

  // Chat sessions list
  if (path === '/api/chat/sessions') {
    event.respondWith(idbFallback(event.request, async () => {
      const row = await idbGet('appData', 'chatSessionsList')
      return row ? row.data : null
    }))
    return
  }

  // Chat messages for a session
  const chatMessagesMatch = path.match(CHAT_MESSAGES_RE)
  if (chatMessagesMatch) {
    const sessionId = decodeURIComponent(chatMessagesMatch[1])
    event.respondWith(idbFallback(event.request, async () => {
      const row = await idbGet('chatMessages', sessionId)
      return row ? row.messages : null
    }))
    return
  }

  // Discussions ("Related Discussions" on an article) — keyed by project+article pair
  if (path === '/api/feed-chat-links') {
    const projectId = url.searchParams.get('project_id') || ''
    const articleKey = url.searchParams.get('article_key') || ''
    event.respondWith(idbFallback(event.request, async () => {
      const row = await idbGet('discussions', `${projectId}_${articleKey}`)
      return row ? row.discussions : null
    }))
    return
  }
  // Everything else (other API calls) passes through to network normally.
})

async function cacheFirst(request) {
  const cache = await caches.open(SHELL_CACHE)
  const cached = await cache.match(request)
  if (cached) return cached
  try {
    const response = await fetch(request)
    if (response && response.ok) cache.put(request, response.clone())
    return response
  } catch (err) {
    return cached || Response.error()
  }
}

// Navigation requests (HTML documents) aren't cache-first — always prefer a
// fresh page when online, but fall back to the cached shell when the network
// is unavailable so the app still loads offline.
async function navigationShellFallback(request) {
  try {
    return await fetch(request)
  } catch (err) {
    const cache = await caches.open(SHELL_CACHE)
    const cached = await cache.match('/index.html')
    return cached || Response.error()
  }
}

// Shared network-first / IndexedDB-fallback strategy for all data API routes.
async function idbFallback(request, idbLookup) {
  try {
    return await fetch(request)
  } catch (err) {
    const data = await idbLookup()
    if (data !== null && data !== undefined) {
      return new Response(JSON.stringify(data), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify({ offline: true, error: 'No cached data' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}

// ─── Minimal inline IndexedDB read (mirrors src/lib/offlineStorage.js) ─────────
// Service workers can't import ES modules from src/, so this duplicates just
// the read path needed to serve cached data while offline.

const DB_NAME = 'curivio-offline'

// General-purpose single-key lookup. Never rejects — a miss resolves null,
// not an error. The DB version is intentionally omitted from indexedDB.open()
// so the SW opens whatever version currently exists, rather than forcing an
// upgrade (schema upgrades belong to src/lib/offlineStorage.js only).
function idbGet(storeName, key) {
  return new Promise((resolve) => {
    const req = indexedDB.open(DB_NAME)
    req.onsuccess = (e) => {
      const db = e.target.result
      if (!db.objectStoreNames.contains(storeName)) {
        resolve(null)
        return
      }
      const tx = db.transaction(storeName, 'readonly')
      const store = tx.objectStore(storeName)
      const getReq = store.get(key)
      getReq.onsuccess = () => resolve(getReq.result ?? null)
      getReq.onerror = () => resolve(null)
    }
    req.onerror = () => resolve(null)
  })
}

// Multi-record index scan for a project's cached packages — not expressible
// as a single idbGet(store, key) lookup.
function getPackagesForProject(projectId) {
  return new Promise((resolve) => {
    const req = indexedDB.open(DB_NAME)
    req.onsuccess = (e) => {
      const db = e.target.result
      if (!db.objectStoreNames.contains('articles')) { resolve([]); return }
      const store = db.transaction('articles', 'readonly').objectStore('articles')
      const index = store.index('project_id')
      const getReq = index.getAll(projectId)
      getReq.onsuccess = () => {
        const packages = (getReq.result || [])
          .filter((r) => r.kind === 'package')
          .map((r) => r.payload)
          .sort((a, b) => (b.day_number || 0) - (a.day_number || 0))
        resolve(packages)
      }
      getReq.onerror = () => resolve([])
    }
    req.onerror = () => resolve([])
  })
}

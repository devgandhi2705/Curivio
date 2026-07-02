// Curivio service worker — app shell caching + offline article serving.

const SHELL_CACHE_PREFIX = 'curivio-shell-'
const SHELL_CACHE = 'curivio-shell-v1'

const STATIC_ASSET_RE = /\.(?:js|css|woff2?|png|svg|ico)$/
const INSIGHTS_PATH_RE = /^\/api\/projects\/([^/]+)\/insights\/?$/
const PROJECTS_LIST_ID = '__projects_list__'

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
  if (url.origin !== self.location.origin) return

  if (event.request.mode === 'navigate') {
    event.respondWith(navigationShellFallback(event.request))
    return
  }

  if (event.request.method === 'GET' && url.pathname === '/api/projects') {
    event.respondWith(handleProjectsListRequest(event.request))
    return
  }

  const insightsMatch = url.pathname.match(INSIGHTS_PATH_RE)
  if (event.request.method === 'GET' && insightsMatch) {
    event.respondWith(handleInsightsRequest(event.request, insightsMatch[1]))
    return
  }

  if (STATIC_ASSET_RE.test(url.pathname)) {
    event.respondWith(cacheFirst(event.request))
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

async function handleProjectsListRequest(request) {
  if (navigator.onLine !== false) {
    try {
      return await fetch(request)
    } catch (err) {
      // network failed — fall through to IndexedDB
    }
  }
  try {
    const list = await getSavedRecord(PROJECTS_LIST_ID)
    if (!list) return Response.error()
    return new Response(JSON.stringify(list), {
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (err) {
    return Response.error()
  }
}

async function handleInsightsRequest(request, projectId) {
  if (navigator.onLine !== false) {
    try {
      return await fetch(request)
    } catch (err) {
      // network failed — fall through to IndexedDB
    }
  }
  try {
    const packages = await getPackagesForProject(decodeURIComponent(projectId))
    if (!packages.length) return Response.error()
    return new Response(JSON.stringify(packages), {
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (err) {
    return Response.error()
  }
}

// ─── Minimal inline IndexedDB read (mirrors src/lib/offlineStorage.js) ─────────
// Service workers can't import ES modules from src/, so this duplicates just
// the read path needed to serve cached packages while offline.

const DB_NAME = 'curivio-offline'
const DB_VERSION = 1

function openOfflineDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function getSavedRecord(id) {
  return openOfflineDB().then((db) => new Promise((resolve, reject) => {
    if (!db.objectStoreNames.contains('articles')) { resolve(null); return }
    const req = db.transaction('articles', 'readonly').objectStore('articles').get(id)
    req.onsuccess = () => resolve(req.result ? req.result.payload : null)
    req.onerror = () => reject(req.error)
  }))
}

function getPackagesForProject(projectId) {
  return openOfflineDB().then((db) => new Promise((resolve, reject) => {
    if (!db.objectStoreNames.contains('articles')) { resolve([]); return }
    const store = db.transaction('articles', 'readonly').objectStore('articles')
    const index = store.index('project_id')
    const req = index.getAll(projectId)
    req.onsuccess = () => {
      const packages = (req.result || [])
        .filter((r) => r.kind === 'package')
        .map((r) => r.payload)
        .sort((a, b) => (b.day_number || 0) - (a.day_number || 0))
      resolve(packages)
    }
    req.onerror = () => reject(req.error)
  }))
}

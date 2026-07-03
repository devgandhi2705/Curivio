/**
 * Thin async wrapper around IndexedDB for offline article storage.
 *
 * `articles` holds two kinds of records, both keyed by a caller-supplied `id`:
 *   - kind "package": a full daily package (from listProjectInsights), id = package.id
 *   - kind "card":    a single Read-Later card, id = `${projectId}_${insightId}_${articleKey}`
 * Both are indexed by `project_id` so the service worker can reconstruct a
 * project's package list while offline.
 *
 * `metadata` holds one lightweight record per saved id — used to populate
 * offline badges without loading full article payloads.
 *
 * @typedef {{id: string, savedAt: string, title: string, projectName: string}} OfflineMetadata
 */

const DB_NAME = 'curivio-offline'
const DB_VERSION = 2

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains('articles')) {
        const store = db.createObjectStore('articles', { keyPath: 'id' })
        store.createIndex('project_id', 'project_id', { unique: false })
      }
      if (!db.objectStoreNames.contains('metadata')) {
        db.createObjectStore('metadata', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('projects')) {
        db.createObjectStore('projects', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('dashboard')) {
        db.createObjectStore('dashboard', { keyPath: 'userId' })
      }
      if (!db.objectStoreNames.contains('bookmarks')) {
        db.createObjectStore('bookmarks', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('readLater')) {
        db.createObjectStore('readLater', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('chatSessions')) {
        db.createObjectStore('chatSessions', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('chatMessages')) {
        db.createObjectStore('chatMessages', { keyPath: 'sessionId' })
      }
      if (!db.objectStoreNames.contains('discussions')) {
        db.createObjectStore('discussions', { keyPath: 'articleId' })
      }
      if (!db.objectStoreNames.contains('appData')) {
        db.createObjectStore('appData', { keyPath: 'key' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

/** Opens (or creates) the offline database. */
export function initDB() {
  return openDB()
}

function runRequest(store, method, ...args) {
  return new Promise((resolve, reject) => {
    const req = store[method](...args)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function notifySaved(id) {
  window.dispatchEvent(new CustomEvent('curivio:offline-saved', { detail: { id } }))
}

async function putRecord(storeName, record) {
  const db = await openDB()
  await runRequest(db.transaction(storeName, 'readwrite').objectStore(storeName), 'put', record)
}

async function getRecord(storeName, key) {
  const db = await openDB()
  return runRequest(db.transaction(storeName, 'readonly').objectStore(storeName), 'get', key)
}

/**
 * Upsert a full package or single card into offline storage, plus its
 * metadata record. Dispatches "curivio:offline-saved" on success so live UI
 * (offline badges) can update without a manual refetch.
 * @param {string} id
 * @param {object} packageData
 * @param {{projectId?: string, kind?: 'package'|'card', title?: string, projectName?: string}} [meta]
 */
export async function savePackage(id, packageData, meta = {}) {
  const db = await openDB()

  const articleRecord = {
    id,
    project_id: meta.projectId ?? packageData.project_id ?? null,
    kind: meta.kind ?? 'package',
    payload: packageData,
  }
  const metadataRecord = {
    id,
    savedAt: new Date().toISOString(),
    title: meta.title ?? packageData.package_headline ?? packageData.title ?? '',
    projectName: meta.projectName ?? packageData.project_name ?? '',
  }

  await Promise.all([
    runRequest(db.transaction('articles', 'readwrite').objectStore('articles'), 'put', articleRecord),
    runRequest(db.transaction('metadata', 'readwrite').objectStore('metadata'), 'put', metadataRecord),
  ])

  notifySaved(id)
}

/**
 * @param {string} id
 * @returns {Promise<object|null>} the original packageData, or null if not cached
 */
export async function getPackage(id) {
  const db = await openDB()
  const record = await runRequest(db.transaction('articles', 'readonly').objectStore('articles'), 'get', id)
  return record ? record.payload : null
}

/** @returns {Promise<OfflineMetadata[]>} */
export async function getAllMetadata() {
  const db = await openDB()
  return runRequest(db.transaction('metadata', 'readonly').objectStore('metadata'), 'getAll')
}

/** @param {string} id */
export async function deletePackage(id) {
  const db = await openDB()
  await Promise.all([
    runRequest(db.transaction('articles', 'readwrite').objectStore('articles'), 'delete', id),
    runRequest(db.transaction('metadata', 'readwrite').objectStore('metadata'), 'delete', id),
  ])
}

/** Wipes both stores. */
export async function clearAll() {
  const db = await openDB()
  await Promise.all([
    runRequest(db.transaction('articles', 'readwrite').objectStore('articles'), 'clear'),
    runRequest(db.transaction('metadata', 'readwrite').objectStore('metadata'), 'clear'),
  ])
}

// ─── Projects list + detail ─────────────────────────────────────────────────

/** @param {object[]} projects */
export async function saveProjectsList(projects) {
  await putRecord('appData', { key: 'projectsList', data: projects, savedAt: Date.now() })
  notifySaved('projectsList')
}

/** @returns {Promise<object[]|null>} */
export async function getProjectsList() {
  const row = await getRecord('appData', 'projectsList')
  return row ? row.data : null
}

/** @param {{project_id: string}} project */
export async function saveProject(project) {
  await putRecord('projects', { id: project.project_id, ...project })
  notifySaved(project.project_id)
}

/** @param {string} id @returns {Promise<object|null>} */
export async function getProject(id) {
  const row = await getRecord('projects', id)
  return row ?? null
}

// ─── Dashboard ──────────────────────────────────────────────────────────────

/** @param {string} userId @param {object} stats */
export async function saveDashboard(userId, stats) {
  await putRecord('dashboard', { userId, stats, savedAt: Date.now() })
  notifySaved(`dashboard:${userId}`)
}

/** @param {string} userId @returns {Promise<object|null>} */
export async function getDashboard(userId) {
  const row = await getRecord('dashboard', userId)
  return row ? row.stats : null
}

/**
 * Fixed-key variant for the service worker, which can't read the JWT to
 * know the current userId.
 * @param {object} stats
 */
export async function saveDashboardOffline(stats) {
  await putRecord('appData', { key: 'dashboard', stats, savedAt: Date.now() })
  notifySaved('dashboard')
}

// ─── Bookmarks ──────────────────────────────────────────────────────────────

/** @param {object[]} bookmarks */
export async function saveBookmarks(bookmarks) {
  await putRecord('appData', { key: 'bookmarks', data: bookmarks, savedAt: Date.now() })
  notifySaved('bookmarks')
}

/** @returns {Promise<object[]|null>} */
export async function getBookmarks() {
  const row = await getRecord('appData', 'bookmarks')
  return row ? row.data : null
}

// ─── Read Later ─────────────────────────────────────────────────────────────
// Read Later has no backend endpoint (api/queue.js is localStorage-only); this
// store just mirrors that local queue so it's servable via the same offline
// lookup path as everything else.

/** @param {object[]} items */
export async function saveReadLater(items) {
  await putRecord('appData', { key: 'readLater', data: items, savedAt: Date.now() })
  notifySaved('readLater')
}

/** @returns {Promise<object[]|null>} */
export async function getReadLater() {
  const row = await getRecord('appData', 'readLater')
  return row ? row.data : null
}

// ─── Chat sessions + messages ───────────────────────────────────────────────

/** @param {{id: string}} session */
export async function saveChatSession(session) {
  await putRecord('chatSessions', session)
  notifySaved(session.id)
}

/** @param {object[]} sessions */
export async function saveChatSessionsList(sessions) {
  await putRecord('appData', { key: 'chatSessionsList', data: sessions, savedAt: Date.now() })
  notifySaved('chatSessionsList')
}

/** @returns {Promise<object[]|null>} */
export async function getChatSessionsList() {
  const row = await getRecord('appData', 'chatSessionsList')
  return row ? row.data : null
}

/** @param {string} sessionId @param {object[]} messages */
export async function saveChatMessages(sessionId, messages) {
  await putRecord('chatMessages', { sessionId, messages, savedAt: Date.now() })
  notifySaved(sessionId)
}

/** @param {string} sessionId @returns {Promise<object[]|null>} */
export async function getChatMessages(sessionId) {
  const row = await getRecord('chatMessages', sessionId)
  return row ? row.messages : null
}

// ─── Discussions ─────────────────────────────────────────────────────────────
// Keyed by `${projectId}_${articleKey}` since the real endpoint
// (GET /feed-chat-links) takes that pair, not a single id.

/** @param {string} articleId @param {object[]} discussions */
export async function saveDiscussions(articleId, discussions) {
  await putRecord('discussions', { articleId, discussions, savedAt: Date.now() })
  notifySaved(articleId)
}

/** @param {string} articleId @returns {Promise<object[]|null>} */
export async function getDiscussions(articleId) {
  const row = await getRecord('discussions', articleId)
  return row ? row.discussions : null
}

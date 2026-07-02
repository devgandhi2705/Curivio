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
const DB_VERSION = 1

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

  window.dispatchEvent(new CustomEvent('curivio:offline-saved', { detail: { id } }))
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

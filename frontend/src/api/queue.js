/**
 * Read-Later queue backed by localStorage.
 *
 * All mutations dispatch a "queuechange" CustomEvent on window so that any
 * component (nav counter, card buttons) can react without prop-drilling.
 * Event detail: { count: number }
 */

let _userId = null

/** Call once after login / on user change so the queue is per-user. */
export function setQueueUser(userId) { _userId = userId || null }

function queueKey() {
  return _userId ? `ra_read_queue_${_userId}` : "ra_read_queue_anon"
}

function load() {
  try { return JSON.parse(localStorage.getItem(queueKey()) || "[]") }
  catch { return [] }
}

function save(items) {
  localStorage.setItem(queueKey(), JSON.stringify(items))
  window.dispatchEvent(new CustomEvent("queuechange", { detail: { count: items.length } }))
}

/** Full queue array, newest-first. */
export function getQueue() { return load() }

/** Number of queued items. */
export function getQueueCount() { return load().length }

/** True if the given articleKey is already queued. */
export function isInQueue(articleKey) { return load().some(i => i.articleKey === articleKey) }

/**
 * Add a card to the queue (no-op if already present).
 * @param {string} articleKey  — slug from articleKeyFromTitle()
 * @param {{ title, summary, category, content_type, projectId, projectName, insightId }} data
 */
export function addToQueue(articleKey, data) {
  const items = load().filter(i => i.articleKey !== articleKey)
  items.unshift({ articleKey, ...data, queuedAt: new Date().toISOString() })
  save(items)
}

/** Remove a single card from the queue by articleKey. */
export function removeFromQueue(articleKey) {
  save(load().filter(i => i.articleKey !== articleKey))
}

/** Remove all queued cards. */
export function clearQueue() {
  save([])
}

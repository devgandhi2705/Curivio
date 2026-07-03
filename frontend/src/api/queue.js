/**
 * Read-Later queue — server-backed per account, mirrored into localStorage
 * (per user id) so the UI reads instantly and stays usable offline.
 *
 * All mutations dispatch a "queuechange" CustomEvent on window so that any
 * component (nav counter, card buttons) can react without prop-drilling.
 * Event detail: { count: number }
 */
const API_URL = import.meta.env.VITE_API_URL ?? ""

import { getAuthHeaders } from './auth.js'

let _userId = null
let _cache = []

function queueKey() {
  return _userId ? `ra_read_queue_${_userId}` : "ra_read_queue_anon"
}

function loadLocal() {
  try { return JSON.parse(localStorage.getItem(queueKey()) || "[]") }
  catch { return [] }
}

function commit(items) {
  _cache = items
  localStorage.setItem(queueKey(), JSON.stringify(items))
  window.dispatchEvent(new CustomEvent("queuechange", { detail: { count: items.length } }))
}

_cache = loadLocal()

/** Call once after login / on user change so the queue is per-user and re-synced with the server. */
export function setQueueUser(userId) {
  _userId = userId || null
  commit(loadLocal())
  if (_userId) fetchQueueFromServer()
}

async function fetchQueueFromServer() {
  try {
    const res = await fetch(`${API_URL}/read-later`, { headers: { ...getAuthHeaders() } })
    if (!res.ok) return
    commit(await res.json())
  } catch {
    // offline or server unreachable — keep the local mirror
  }
}

/** Full queue array, newest-first. */
export function getQueue() { return _cache }

/** Number of queued items. */
export function getQueueCount() { return _cache.length }

/** True if the given articleKey is already queued. */
export function isInQueue(articleKey) { return _cache.some(i => i.articleKey === articleKey) }

/**
 * Add a card to the queue (no-op if already present).
 * @param {string} articleKey  — slug from articleKeyFromTitle()
 * @param {{ title, summary, category, content_type, projectId, projectName, insightId }} data
 */
export function addToQueue(articleKey, data) {
  const items = _cache.filter(i => i.articleKey !== articleKey)
  items.unshift({ articleKey, ...data, queuedAt: new Date().toISOString() })
  commit(items)
  if (_userId) {
    fetch(`${API_URL}/read-later`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ articleKey, ...data }),
    }).catch(() => {})
  }
}

/** Remove a single card from the queue by articleKey. */
export function removeFromQueue(articleKey) {
  commit(_cache.filter(i => i.articleKey !== articleKey))
  if (_userId) {
    fetch(`${API_URL}/read-later/${encodeURIComponent(articleKey)}`, {
      method: 'DELETE',
      headers: { ...getAuthHeaders() },
    }).catch(() => {})
  }
}

/** Remove all queued cards. */
export function clearQueue() {
  commit([])
  if (_userId) {
    fetch(`${API_URL}/read-later`, { method: 'DELETE', headers: { ...getAuthHeaders() } }).catch(() => {})
  }
}

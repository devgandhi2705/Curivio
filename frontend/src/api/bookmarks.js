const API_URL = import.meta.env.VITE_API_URL ?? ""
const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

import { MOCK_COLLECTIONS, MOCK_BOOKMARKS } from '../mocks/bookmarkMocks.js'
import { getAuthHeaders } from './auth.js'

let _mockCollections = [...MOCK_COLLECTIONS]
let _mockBookmarks   = [...MOCK_BOOKMARKS]

// ── Collections ───────────────────────────────────────────────────────────────

export async function fetchCollections() {
  if (USE_MOCK) {
    await delay(200)
    return _mockCollections.map(c => ({
      ...c,
      bookmark_count: _mockBookmarks.filter(b => b.collection_id === c.collection_id).length,
    }))
  }
  const res = await fetch(`${API_URL}/bookmarks/collections`, { headers: { ...getAuthHeaders() } })
  if (!res.ok) throw new Error('Failed to fetch collections')
  return res.json()
}

export async function createCollection({ name, description = '', color = 'blue' }) {
  if (USE_MOCK) {
    await delay(150)
    const col = {
      collection_id:  crypto.randomUUID(),
      name,
      description,
      color,
      created_at:     new Date().toISOString(),
      updated_at:     new Date().toISOString(),
      bookmark_count: 0,
    }
    _mockCollections = [col, ..._mockCollections]
    return col
  }
  const res = await fetch(`${API_URL}/bookmarks/collections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ name, description, color }),
  })
  if (!res.ok) throw new Error('Failed to create collection')
  return res.json()
}

export async function updateCollection(collection_id, patch) {
  if (USE_MOCK) {
    await delay(100)
    _mockCollections = _mockCollections.map(c =>
      c.collection_id === collection_id ? { ...c, ...patch } : c
    )
    return _mockCollections.find(c => c.collection_id === collection_id)
  }
  const res = await fetch(`${API_URL}/bookmarks/collections/${collection_id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error('Failed to update collection')
  return res.json()
}

export async function deleteCollection(collection_id) {
  if (USE_MOCK) {
    await delay(100)
    _mockCollections = _mockCollections.filter(c => c.collection_id !== collection_id)
    _mockBookmarks   = _mockBookmarks.filter(b => b.collection_id !== collection_id)
    return
  }
  const res = await fetch(`${API_URL}/bookmarks/collections/${collection_id}`, { method: 'DELETE', headers: { ...getAuthHeaders() } })
  if (!res.ok) throw new Error('Failed to delete collection')
}

// ── Bookmarks ─────────────────────────────────────────────────────────────────

export async function fetchBookmarks({ collection_id, content_type, source_type, project_id, search } = {}) {
  if (USE_MOCK) {
    await delay(200)
    let bms = [..._mockBookmarks]
    if (collection_id) bms = bms.filter(b => b.collection_id === collection_id)
    if (content_type)  bms = bms.filter(b => b.content_type  === content_type)
    if (source_type)   bms = bms.filter(b => b.source_type   === source_type)
    if (project_id)    bms = bms.filter(b => b.project_id    === project_id)
    if (search) {
      const q = search.toLowerCase()
      bms = bms.filter(b =>
        b.title.toLowerCase().includes(q) ||
        b.summary.toLowerCase().includes(q) ||
        b.tags.some(t => t.toLowerCase().includes(q))
      )
    }
    return bms
  }
  const params = new URLSearchParams()
  if (collection_id) params.set('collection_id', collection_id)
  if (content_type)  params.set('content_type',  content_type)
  if (source_type)   params.set('source_type',   source_type)
  if (project_id)    params.set('project_id',    project_id)
  if (search)        params.set('search',        search)
  const res = await fetch(`${API_URL}/bookmarks?${params}`, { headers: { ...getAuthHeaders() } })
  if (!res.ok) throw new Error('Failed to fetch bookmarks')
  return res.json()
}

export async function saveBookmark(data) {
  if (USE_MOCK) {
    await delay(150)
    // Deduplicate: return existing if same title already in this collection
    const existing = _mockBookmarks.find(
      b => b.collection_id === data.collection_id && b.title === data.title
    )
    if (existing) return existing
    const col = _mockCollections.find(c => c.collection_id === data.collection_id)
    const bm = {
      bookmark_id:             crypto.randomUUID(),
      collection_name:         col?.name  || '',
      collection_color:        col?.color || 'blue',
      tags:                    [],
      retrieval_metadata:      {},
      related_topics:          [],
      ...data,
      saved_at: new Date().toISOString(),
    }
    _mockBookmarks = [bm, ..._mockBookmarks]
    return bm
  }
  const res = await fetch(`${API_URL}/bookmarks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to save bookmark')
  return res.json()
}

export async function updateBookmark(bookmark_id, patch) {
  if (USE_MOCK) {
    await delay(100)
    _mockBookmarks = _mockBookmarks.map(b =>
      b.bookmark_id === bookmark_id ? { ...b, ...patch } : b
    )
    return _mockBookmarks.find(b => b.bookmark_id === bookmark_id)
  }
  const res = await fetch(`${API_URL}/bookmarks/${bookmark_id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error('Failed to update bookmark')
  return res.json()
}

export async function deleteBookmark(bookmark_id) {
  if (USE_MOCK) {
    await delay(100)
    _mockBookmarks = _mockBookmarks.filter(b => b.bookmark_id !== bookmark_id)
    return
  }
  const res = await fetch(`${API_URL}/bookmarks/${bookmark_id}`, { method: 'DELETE', headers: { ...getAuthHeaders() } })
  if (!res.ok) throw new Error('Failed to delete bookmark')
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)) }

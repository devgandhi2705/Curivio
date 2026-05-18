/**
 * Global search API client.
 * Searches across feed cards, bookmarks, and chat messages in one request.
 */

import { getAuthHeaders } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true"

const _empty = (q) => ({ query: q, total: 0, results: { cards: [], bookmarks: [], chats: [] } })

export async function globalSearch(query, limit = 5) {
  const q = (query || "").trim()
  if (q.length < 2) return _empty(q)

  if (USE_MOCK) {
    await new Promise(r => setTimeout(r, 150))
    return _empty(q)
  }

  const res = await fetch(
    `${API_URL}/search/global?q=${encodeURIComponent(q)}&limit=${limit}`,
    { headers: { ...getAuthHeaders() } }
  )
  if (!res.ok) throw new Error(`Search failed: ${res.status}`)
  return res.json()
}

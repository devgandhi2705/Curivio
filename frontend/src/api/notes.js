/**
 * API client for per-card notes (card_notes table).
 * card_id is the article_key slug derived from the card title.
 */

import { getAuthHeaders } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true"

// In-memory mock store: Map<`${projectId}:${insightId}:${cardId}`, string>
const _mockNotes = new Map()

function _mockKey(projectId, insightId, cardId) {
  return `${projectId}:${insightId}:${cardId}`
}

/**
 * Create or update a note for a specific card.
 */
export async function saveCardNote(projectId, insightId, cardId, content) {
  if (USE_MOCK) {
    _mockNotes.set(_mockKey(projectId, insightId, cardId), content)
    return { project_id: projectId, insight_id: insightId, card_id: cardId, content }
  }
  const res = await fetch(
    `${API_URL}/projects/${encodeURIComponent(projectId)}/insights/${insightId}/cards/${encodeURIComponent(cardId)}/note`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ content }),
    }
  )
  if (!res.ok) throw new Error(`Save note failed: ${res.status}`)
  return res.json()
}

/**
 * Delete a note for a specific card.
 */
export async function deleteCardNote(projectId, insightId, cardId) {
  if (USE_MOCK) {
    _mockNotes.delete(_mockKey(projectId, insightId, cardId))
    return { deleted: true }
  }
  const res = await fetch(
    `${API_URL}/projects/${encodeURIComponent(projectId)}/insights/${insightId}/cards/${encodeURIComponent(cardId)}/note`,
    { method: "DELETE", headers: { ...getAuthHeaders() } }
  )
  if (!res.ok) throw new Error(`Delete note failed: ${res.status}`)
  return res.json()
}

/**
 * Fetch all notes for a package as {card_id: content} object.
 */
export async function getInsightNotes(projectId, insightId) {
  if (USE_MOCK) {
    const prefix = `${projectId}:${insightId}:`
    const result = {}
    for (const [k, v] of _mockNotes) {
      if (k.startsWith(prefix)) {
        result[k.slice(prefix.length)] = v
      }
    }
    return result
  }
  try {
    const res = await fetch(
      `${API_URL}/projects/${encodeURIComponent(projectId)}/insights/${insightId}/notes`,
      { headers: { ...getAuthHeaders() } }
    )
    if (!res.ok) return {}
    return res.json()
  } catch {
    return {}
  }
}

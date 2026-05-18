/**
 * API client for feed read-tracking and feed→chat link persistence.
 *
 * articleKeyFromTitle() must match the backend's article_key_from_title().
 * Both produce the same slug: lowercase, non-alphanumeric runs → '-', max 60 chars.
 */

import { getAuthHeaders } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true"

// ─── Shared helper ────────────────────────────────────────────────────────────

export function articleKeyFromTitle(title) {
  return (title || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60)
}

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

// ─── Mock read state ──────────────────────────────────────────────────────────

// In-memory mock store: Map<`${projectId}:${insightId}`, Set<articleKey>>
const _mockReads = new Map()

function _mockKey(projectId, insightId) {
  return `${projectId}:${insightId}`
}

// ─── Read tracking ────────────────────────────────────────────────────────────

/**
 * Mark an article card as read.
 * Returns the read record.
 */
export async function markCardRead(projectId, insightId, articleKey, articleTitle = "") {
  if (USE_MOCK) {
    const k = _mockKey(projectId, insightId)
    const s = _mockReads.get(k) ?? new Set()
    s.add(articleKey)
    _mockReads.set(k, s)
    return { project_id: projectId, insight_id: insightId, article_key: articleKey, article_title: articleTitle }
  }
  return apiFetch(
    `/projects/${encodeURIComponent(projectId)}/insights/${insightId}/cards/${encodeURIComponent(articleKey)}/read`,
    {
      method: "POST",
      body: JSON.stringify({ article_title: articleTitle }),
    }
  )
}

/**
 * Mark an article card as unread.
 */
export async function markCardUnread(projectId, insightId, articleKey) {
  if (USE_MOCK) {
    const k = _mockKey(projectId, insightId)
    const s = _mockReads.get(k)
    if (s) s.delete(articleKey)
    return { deleted: true }
  }
  return apiFetch(
    `/projects/${encodeURIComponent(projectId)}/insights/${insightId}/cards/${encodeURIComponent(articleKey)}/read`,
    { method: "DELETE" }
  )
}

/**
 * Fetch the set of article keys that have been read for a given package.
 * Returns a Set<string> for O(1) lookup in the UI.
 */
export async function getInsightReadKeys(projectId, insightId) {
  if (USE_MOCK) {
    const k = _mockKey(projectId, insightId)
    return new Set(_mockReads.get(k) ?? [])
  }
  try {
    const data = await apiFetch(
      `/projects/${encodeURIComponent(projectId)}/insights/${insightId}/reads`
    )
    return new Set(data.read_keys ?? [])
  } catch {
    return new Set()
  }
}

// ─── Feed → Chat links ────────────────────────────────────────────────────────

// In-memory mock link store: Map<`${projectId}:${articleKey}`, link[]>
const _mockLinks = new Map()

/**
 * Persist the link between a chat session and the feed article that originated it.
 * Called once after the user's first message succeeds (inside onDone).
 */
export async function createFeedChatLink({
  sessionId,
  projectId,
  articleKey,
  articleTitle = "",
  interactionType = "ask_about",
  insightId = null,
}) {
  if (USE_MOCK) {
    const k = `${projectId}:${articleKey}`
    const existing = _mockLinks.get(k) ?? []
    const link = {
      id: Date.now(),
      session_id: sessionId,
      project_id: projectId,
      insight_id: insightId,
      article_key: articleKey,
      article_title: articleTitle,
      interaction_type: interactionType,
      session_title: null,
      created_at: new Date().toISOString(),
    }
    _mockLinks.set(k, [link, ...existing])
    return link
  }
  return apiFetch("/feed-chat-links", {
    method: "POST",
    body: JSON.stringify({
      session_id:       sessionId,
      project_id:       projectId,
      article_key:      articleKey,
      article_title:    articleTitle,
      interaction_type: interactionType,
      insight_id:       insightId,
    }),
  })
}

/**
 * Fetch aggregate reading stats: streak, total cards read, packages, projects.
 */
export async function getReadingStats() {
  if (USE_MOCK) {
    await new Promise(r => setTimeout(r, 100))
    return {
      total_cards_read:  0,
      today_cards_read:  0,
      current_streak:    0,
      longest_streak:    0,
      active_projects:   0,
      total_packages:    0,
      total_days_active: 0,
    }
  }
  try {
    return await apiFetch("/stats/reading")
  } catch {
    return null
  }
}

/**
 * Fetch all chat sessions linked to a specific feed article.
 * Used to render "Related Discussions" on an InsightCard.
 */
export async function getArticleChatLinks(projectId, articleKey) {
  if (USE_MOCK) {
    const k = `${projectId}:${articleKey}`
    return _mockLinks.get(k) ?? []
  }
  try {
    return await apiFetch(
      `/feed-chat-links?project_id=${encodeURIComponent(projectId)}&article_key=${encodeURIComponent(articleKey)}`
    )
  } catch {
    return []
  }
}

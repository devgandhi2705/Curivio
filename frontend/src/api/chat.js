/**
 * API service for conversational chat endpoints.
 *
 * Set VITE_USE_MOCK=true in .env to bypass live API calls.
 */

import {
  MOCK_CHAT_DEFAULT,
  MOCK_CHAT_ROADMAP,
  MOCK_CHAT_REPOS,
  MOCK_CHAT_COMPARE,
  selectMockResponse,
} from "../mocks/chat.js"
import { getAuthHeaders, signalUnauthorized } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true"

const mockDelay = (ms = 800) => new Promise((resolve) => setTimeout(resolve, ms))

async function post(path, body) {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

async function get(path) {
  const res = await fetch(`${API_URL}${path}`, { headers: { ...getAuthHeaders() } })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

async function del(path) {
  const res = await fetch(`${API_URL}${path}`, { method: "DELETE", headers: { ...getAuthHeaders() } })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export async function sendMessage(sessionId, message, topicHint = null) {
  if (USE_MOCK) {
    await mockDelay(900)
    return selectMockResponse(message, sessionId)
  }
  return post("/chat", { session_id: sessionId, message, topic_hint: topicHint })
}

// Per-session AbortControllers — auto-cancel previous stream when a new one starts
const _streamControllers = new Map()

export function cancelStream(sessionId) {
  const ctrl = _streamControllers.get(sessionId)
  if (ctrl) {
    ctrl.abort()
    _streamControllers.delete(sessionId)
  }
}

/**
 * Stream an AI response, calling callbacks as data arrives.
 * Returns an abort function; call it to cancel the stream early.
 *
 * @param {string}   sessionId
 * @param {string}   message
 * @param {object}   callbacks
 * @param {function} callbacks.onChunk   - called with each text string
 * @param {function} callbacks.onDone    - called with the final metadata object
 * @param {function} callbacks.onError   - called with an error string
 * @param {function} callbacks.onStatus  - called with status update strings
 * @param {function} callbacks.onTitle   - called with the auto-generated session title
 * @returns {function} abort
 */
export function sendMessageStream(sessionId, message, { onChunk, onDone, onError, onStatus, onTitle }, chatMode = "normal", feedContext = null) {
  if (USE_MOCK) {
    ;(async () => {
      const mock = selectMockResponse(message, sessionId)
      const tokens = mock.response.match(/\S+\s*/g) || [mock.response]
      for (const token of tokens) {
        await mockDelay(18)
        onChunk(token)
      }
      onDone({ ...mock, chat_mode: chatMode })
    })()
    return () => {}
  }

  // Cancel any existing stream for this session before starting a new one
  cancelStream(sessionId)

  const controller = new AbortController()
  _streamControllers.set(sessionId, controller)

  // Deep research can take up to ~2.5 min; normal/web-search times out at 90 s
  const TIMEOUT_MS = chatMode === "deep_research" ? 150_000 : 90_000
  const timeoutId = setTimeout(() => {
    controller.abort()
    _streamControllers.delete(sessionId)
  }, TIMEOUT_MS)

  // Stall detector: emit "still working" if no bytes arrive for 20 s straight
  let stallTimer = null
  const resetStall = () => {
    clearTimeout(stallTimer)
    stallTimer = setTimeout(() => {
      onStatus?.("Still working on it…")
      resetStall()
    }, 20_000)
  }

  ;(async () => {
    resetStall()

    let res
    try {
      res = await fetch(`${API_URL}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          topic_hint: null,
          chat_mode: chatMode,
          ...(feedContext ? { feed_context: feedContext } : {}),
        }),
        signal: controller.signal,
      })
    } catch (e) {
      clearTimeout(timeoutId)
      clearTimeout(stallTimer)
      _streamControllers.delete(sessionId)
      if (e.name !== "AbortError") {
        onError("Could not reach the backend. Make sure FastAPI is running on port 8000.")
      }
      return
    }

    if (!res.ok) {
      clearTimeout(timeoutId)
      clearTimeout(stallTimer)
      _streamControllers.delete(sessionId)
      const err = await res.json().catch(() => ({}))
      if (res.status === 401) signalUnauthorized()
      onError(err.detail || `Request failed: ${res.status}`)
      return
    }

    const reader  = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer    = ""

    try {
      while (true) {
        const { done, value } = await reader.read()
        resetStall() // any incoming byte resets the stall timer
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() // hold back the last (possibly incomplete) line

        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const obj = JSON.parse(line)
            if      (obj.t === "chunk")     onChunk(obj.v)
            else if (obj.t === "title")     onTitle?.(obj.v)
            else if (obj.t === "status")    onStatus?.(obj.v)
            else if (obj.t === "heartbeat") { /* keepalive — no-op */ }
            else if (obj.t === "done")      onDone(obj)
            else if (obj.t === "error")     onError(obj.message || "Stream error")
          } catch {
            // skip malformed line
          }
        }
      }

      // Flush remaining buffer
      if (buffer.trim()) {
        try {
          const obj = JSON.parse(buffer)
          if      (obj.t === "done")  onDone(obj)
          else if (obj.t === "error") onError(obj.message || "Stream error")
        } catch {}
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        onError(e.message || "Stream read error")
      }
    } finally {
      clearTimeout(timeoutId)
      clearTimeout(stallTimer)
      _streamControllers.delete(sessionId)
    }
  })()

  return () => {
    controller.abort()
    _streamControllers.delete(sessionId)
  }
}

export async function fetchHistory(sessionId, limit = 50) {
  if (USE_MOCK) {
    await mockDelay(200)
    return []
  }
  return get(`/chat/history/${encodeURIComponent(sessionId)}?limit=${limit}`)
}

export async function fetchSessions(limit = 20) {
  if (USE_MOCK) {
    await mockDelay(200)
    return []
  }
  return get(`/chat/sessions?limit=${limit}`)
}

export async function searchSessions(query, limit = 20) {
  if (USE_MOCK) {
    await mockDelay(150)
    return []
  }
  try {
    return await get(`/chat/sessions/search?q=${encodeURIComponent(query)}&limit=${limit}`)
  } catch {
    return []
  }
}

export async function clearHistory(sessionId) {
  if (USE_MOCK) {
    await mockDelay(200)
    return { deleted: 0 }
  }
  return del(`/chat/history/${encodeURIComponent(sessionId)}`)
}

export async function deleteSession(sessionId) {
  if (USE_MOCK) {
    await mockDelay(200)
    return { deleted: true }
  }
  return del(`/chat/sessions/${encodeURIComponent(sessionId)}`)
}

export async function deleteLastTurn(sessionId) {
  if (USE_MOCK) {
    await mockDelay(200)
    return { deleted: 2 }
  }
  return del(`/chat/sessions/${encodeURIComponent(sessionId)}/last_turn`)
}

export async function renameSession(sessionId, title) {
  if (USE_MOCK) {
    await mockDelay(200)
    return { session_id: sessionId, title }
  }
  const res = await fetch(`${API_URL}/chat/sessions/${encodeURIComponent(sessionId)}/title`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ title }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

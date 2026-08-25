/**
 * API service for conversational chat endpoints.
 *
 * Set VITE_USE_MOCK=true in .env to bypass live API calls.
 */

import { selectMockResponse } from "../mocks/chat.js"
import { getAuthHeaders, signalUnauthorized } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true"

const mockDelay = (ms = 800) => new Promise((resolve) => setTimeout(resolve, ms))

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

/**
 * Upload an attachment and get back a URI reference — upload once, then
 * attach that reference to sendMessageStream. Never re-uploads the bytes on
 * later turns; the backend persists only this metadata against the message,
 * not the file itself.
 *
 * Images go to Gemini's Files API. Documents (pdf/docx/csv/text/code,
 * Chat-R6a) are text-extracted server-side instead — the uri comes back as
 * "doc://<id>", never a Gemini file reference.
 */
export async function uploadAttachment(file) {
  if (USE_MOCK) {
    await mockDelay(400)
    return {
      uri: `mock://attachment/${file.name}`,
      mime_type: file.type,
      filename: file.name,
      size_bytes: file.size,
      expires_at: new Date(Date.now() + 48 * 3600 * 1000).toISOString(),
    }
  }
  const formData = new FormData()
  formData.append("file", file)
  const res = await fetch(`${API_URL}/chat/upload`, {
    method: "POST",
    headers: { ...getAuthHeaders() }, // no Content-Type — browser sets multipart boundary
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Upload failed: ${res.status}`)
  }
  // Chat-R19c: response is now NDJSON ({"t":"stage",...} progress lines,
  // then a final {"t":"done",...}/{"t":"error",...}) — only the last line
  // carries the real outcome. Stage lines are ignored here; R19c-frontend
  // will consume them for a progress UI.
  const text = await res.text()
  const lines = text.trim().split("\n")
  const { t, ...last } = JSON.parse(lines[lines.length - 1])
  if (t === "error") {
    throw new Error(last.message || "Upload failed")
  }
  return last
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

// Phase K — the browser's IANA timezone, the only locale signal this app has.
// Sent on every turn, never only on sensitive ones: a field that appeared just
// as someone said something alarming would itself be a tell, and the backend
// needs it already in hand by the time it matters. Purely passive — no
// geolocation prompt, no IP lookup, no third-party call — and the backend
// resolves it against tzdb's own zone table (see crisis_support_service.py),
// so an unrecognised value degrades to "we don't know", never to a guess.
// try/catch because a throw here would take the whole chat request down; an
// undefined result just means the backend treats the location as unknown.
function clientTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || ""
  } catch {
    return ""
  }
}

/**
 * Stream an AI response, calling callbacks as data arrives.
 * Returns an abort function; call it to cancel the stream early.
 *
 * @param {string}   sessionId
 * @param {string}   message
 * @param {object}   callbacks
 * @param {function} callbacks.onChunk       - called with (text, seq, blockId) for each text delta (Chat-R10d ordering)
 * @param {function} callbacks.onThinking    - called with (text, seq, blockId) for each reasoning delta (Chat-6; ordering Chat-R10d)
 * @param {function} callbacks.onThinkingGap - called once with an honest note when reasoning ran
 *                                              but can't stream on this turn's model (Chat-6 followup)
 * @param {function} callbacks.onCodeExecutionGap - called once when task_type=="coding" but the
 *                                              leg answering can't run code_execution (Chat-R5b)
 * @param {function} callbacks.onCode        - called with (source, language) when Gemini executes code (Chat-7)
 * @param {function} callbacks.onCodeOutput  - called with (output, success) for that code's result (Chat-7)
 * @param {function} callbacks.onDone        - called with the final metadata object
 * @param {function} callbacks.onError       - called with an error string
 * @param {function} callbacks.onStatus      - called with (text, seq, blockId, tool, query, sources) for status
 *                                              updates; tool/query/sources are only set on the two tool-derived
 *                                              lines (tool_start has query, tool_end has sources — Chat-R10e)
 * @param {function} callbacks.onTitle       - called with the auto-generated session title
 * @returns {function} abort
 */
export function sendMessageStream(sessionId, message, { onChunk, onThinking, onThinkingGap, onCodeExecutionGap, onCode, onCodeOutput, onDone, onError, onStatus, onTitle }, chatMode = "normal", feedContext = null, attachments = null) {
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

  const tz = clientTimezone()

  const TIMEOUT_MS = 90_000
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
          ...(tz ? { client_timezone: tz } : {}),
          ...(feedContext ? { feed_context: feedContext } : {}),
          ...(attachments?.length ? { attachments } : {}),
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
            if      (obj.t === "chunk")        onChunk(obj.v, obj.seq, obj.block_id)
            else if (obj.t === "thinking")     onThinking?.(obj.v, obj.seq, obj.block_id)
            else if (obj.t === "thinking_gap") onThinkingGap?.(obj.v)
            else if (obj.t === "code_execution_gap")    onCodeExecutionGap?.(obj.v)
            else if (obj.t === "code")         onCode?.(obj.v, obj.language)
            else if (obj.t === "code_output")  onCodeOutput?.(obj.v, obj.success)
            else if (obj.t === "title")        onTitle?.(obj.v)
            // Chat-R10e: tool/query (tool_start) or tool/sources (tool_end) are
            // present only on the two tool-derived status lines — see
            // chat_service.chat_stream's docstring. Plain status pings (the
            // initial "Generating response…", the stall-timer's "Still working
            // on it…") carry none of this, so `tool` stays undefined for those.
            else if (obj.t === "status")    onStatus?.(obj.v, obj.seq, obj.block_id, obj.tool, obj.query, obj.sources)
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

/**
 * Full extracted text for a document attachment (Chat-R10 preview/download).
 * Permanent — no expiry, unlike the original file (see ChatAttachment on the
 * backend, and fetchAttachmentBlob below for the original bytes).
 *
 * Chat-R15b: pass shareToken when previewing inside a share view (no JWT
 * exists there) — skips getAuthHeaders() entirely and hits the share-scoped
 * endpoint instead, mirroring share.js's { auth } flag pattern.
 */
export async function fetchDocumentText(attachmentId, shareToken = null) {
  if (USE_MOCK) {
    await mockDelay(200)
    return { text: "Mock document text." }
  }
  if (shareToken) {
    const res = await fetch(
      `${API_URL}/share/${encodeURIComponent(shareToken)}/attachment/document/${encodeURIComponent(attachmentId)}`,
    )
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Request failed: ${res.status}`)
    }
    return res.json()
  }
  return get(`/chat/attachment/document/${encodeURIComponent(attachmentId)}`)
}

/**
 * Chat-R14b: real original bytes for any R2-backed attachment, as a same-
 * origin blob: URL — usable directly as an <img>/<iframe> src, or with
 * downloadUrl() for a real (non-renamed) download. One helper for all three
 * types since GET /chat/attachment/file/{id}/{filename} needs auth via
 * getAuthHeaders() (Bearer token, not cookies) — a bare <iframe src=...>/
 * <img src=...> pointed straight at the endpoint can't attach that header,
 * so every native embed/download must go through this fetch-then-blob path
 * instead (same proven shape as fetchDocumentText above).
 *
 * Picks the right id per type: images use their R2 dual-write id
 * (r2_attachment_id, Chat-R14a — never Gemini's own uri, which isn't R2-
 * reachable at all); documents/"other" files use the id embedded in uri
 * (doc://<id> or file://<id>).
 *
 * Chat-R15b: pass shareToken when previewing inside a share view (no JWT
 * exists there) — skips getAuthHeaders() entirely and hits R15a's share-
 * scoped endpoint instead, mirroring share.js's { auth } flag pattern.
 */
export async function fetchAttachmentBlob(attachment, shareToken = null) {
  if (USE_MOCK) {
    await mockDelay(200)
    return attachment.previewUrl ?? `mock://attachment-blob/${attachment.filename}`
  }
  const isImage = attachment.mime_type?.startsWith("image/")
  const id = isImage ? attachment.r2_attachment_id : attachment.uri.replace(/^(doc|file):\/\//, "")
  const path = shareToken
    ? `/share/${encodeURIComponent(shareToken)}/attachment/${encodeURIComponent(id)}/${encodeURIComponent(attachment.filename)}`
    : `/chat/attachment/file/${encodeURIComponent(id)}/${encodeURIComponent(attachment.filename)}`
  const res = await fetch(`${API_URL}${path}`, { headers: { ...(shareToken ? {} : getAuthHeaders()) } })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

export async function fetchHistory(sessionId, limit = 50) {
  if (USE_MOCK) {
    await mockDelay(200)
    return []
  }
  return get(`/chat/history/${encodeURIComponent(sessionId)}?limit=${limit}`)
}

/**
 * Chat-R16 files panel: every attachment across the whole session, unbounded
 * — deliberately not fetchHistory, which caps at 50 messages (ChatWorkspace's
 * in-memory state) and would pull full content/thinking/blocks for nothing.
 */
export async function fetchSessionAttachments(sessionId) {
  if (USE_MOCK) {
    await mockDelay(200)
    return []
  }
  return get(`/chat/attachments/${encodeURIComponent(sessionId)}`)
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

/**
 * API client for the Unpack feature: "Explain" (NDJSON stream), "Translate"
 * (plain JSON, Google Translate), and "Read Aloud" (plain JSON, Google
 * Cloud TTS) — the latter two are single-shot, no streaming.
 */

import { getAuthHeaders, signalUnauthorized } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const EXPLAIN_TIMEOUT_MS = 10_000
const TRANSLATE_TIMEOUT_MS = 8_000
const READ_ALOUD_TIMEOUT_MS = 10_000

/**
 * Stream an Explain result, calling callbacks as data arrives.
 * Returns an abort function; call it to cancel the request early.
 *
 * @param {object}   params
 * @param {string}   params.term
 * @param {string}   params.sentence
 * @param {string}   params.prevSentence
 * @param {string}   params.nextSentence
 * @param {object}   callbacks
 * @param {function} callbacks.onChunk - called with each incremental text string
 * @param {function} callbacks.onDone  - called with the final result object
 * @param {function} callbacks.onError - called with an error string
 * @returns {function} abort
 */
export function explainStream(
  { term, sentence, prevSentence, nextSentence },
  { onChunk, onDone, onError }
) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), EXPLAIN_TIMEOUT_MS)

  ;(async () => {
    let res
    try {
      res = await fetch(`${API_URL}/unpack/explain`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({
          term,
          sentence: sentence || "",
          prev_sentence: prevSentence || "",
          next_sentence: nextSentence || "",
        }),
        signal: controller.signal,
      })
    } catch (e) {
      clearTimeout(timeoutId)
      if (e.name !== "AbortError") onError("Could not reach the backend.")
      return
    }

    if (!res.ok) {
      clearTimeout(timeoutId)
      const err = await res.json().catch(() => ({}))
      if (res.status === 401) signalUnauthorized()
      onError(err.detail || `Request failed: ${res.status}`)
      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const obj = JSON.parse(line)
            if (obj.t === "chunk") onChunk(obj.v)
            else if (obj.t === "done") onDone(obj)
            else if (obj.t === "error") onError(obj.message || "Explain failed")
          } catch {
            // skip malformed line
          }
        }
      }

      if (buffer.trim()) {
        try {
          const obj = JSON.parse(buffer)
          if (obj.t === "done") onDone(obj)
          else if (obj.t === "error") onError(obj.message || "Explain failed")
        } catch {}
      }
    } catch (e) {
      if (e.name !== "AbortError") onError(e.message || "Stream read error")
    } finally {
      clearTimeout(timeoutId)
    }
  })()

  return () => controller.abort()
}

/**
 * Translate a selected term. Returns { term, target_language, translation, source }.
 * Throws on failure — caller shows an inline error.
 */
export async function translateTerm(term, targetLanguage) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), TRANSLATE_TIMEOUT_MS)

  let res
  try {
    res = await fetch(`${API_URL}/unpack/translate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ term, target_language: targetLanguage }),
      signal: controller.signal,
    })
  } catch (e) {
    throw new Error(e.name === "AbortError" ? "Translation timed out." : "Could not reach the backend.")
  } finally {
    clearTimeout(timeoutId)
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    if (res.status === 401) signalUnauthorized()
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }

  return res.json()
}

/**
 * Synthesize speech for a selected term/phrase. Returns
 * { term, language, audio_base64, source }. Throws on failure.
 */
export async function readAloudTerm(term) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), READ_ALOUD_TIMEOUT_MS)

  let res
  try {
    res = await fetch(`${API_URL}/unpack/read-aloud`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ term }),
      signal: controller.signal,
    })
  } catch (e) {
    throw new Error(e.name === "AbortError" ? "Read aloud timed out." : "Could not reach the backend.")
  } finally {
    clearTimeout(timeoutId)
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    if (res.status === 401) signalUnauthorized()
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }

  return res.json()
}

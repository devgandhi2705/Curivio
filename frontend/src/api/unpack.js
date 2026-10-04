/**
 * API client for the Unpack feature: "Explain" (NDJSON stream), "Translate"
 * (plain JSON, DeepL, single-shot), and "Read Aloud" (an MP3 stream from
 * Deepgram, played while it downloads).
 */

import { getAuthHeaders, signalUnauthorized } from "./auth.js"

const API_URL = import.meta.env.VITE_API_URL ?? ""
const EXPLAIN_TIMEOUT_MS = 10_000
const TRANSLATE_TIMEOUT_MS = 8_000
// Only until audio starts: the backend decides Flux vs the Aura-2 backup
// before its first byte (6s per attempt + ~2.5s to first audio). After
// that the clip streams for as long as it takes — Deepgram produces it at
// roughly playback pace, ~20s for a long paragraph.
const READ_ALOUD_START_TIMEOUT_MS = 15_000

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

// Browsers with Media Source Extensions for MP3 (Chrome, Edge, Firefox,
// desktop Safari) play while downloading; others (iPhone Safari before
// 17.1) wait for the whole clip, as before.
function canStream(mime) {
  return typeof window !== "undefined" && !!window.MediaSource?.isTypeSupported?.(mime)
}

/** A playable URL that fills as `body` arrives. Ends the clip cleanly if the
 *  download is cancelled or drops, so whatever arrived still plays. */
function streamToMediaSource(body, mime) {
  const ms = new window.MediaSource()
  ms.addEventListener("sourceopen", async () => {
    const sb = ms.addSourceBuffer(mime)
    sb.mode = "sequence" // MP3 frames carry no timestamps; just play them in order
    const reader = body.getReader()
    const end = () => { if (ms.readyState === "open") try { ms.endOfStream() } catch { /* already ended */ } }
    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        sb.appendBuffer(value)
        await new Promise((resolve) => sb.addEventListener("updateend", resolve, { once: true }))
      }
    } catch {
      // cancelled (popover closed) or the network dropped
    }
    end()
  }, { once: true })
  return URL.createObjectURL(ms)
}

/**
 * Start reading a selected term/phrase aloud with the user's Deepgram voice
 * options (see components/unpack/voicePrefs.js). Resolves as soon as audio
 * starts arriving with { src, source, cancel }: `src` goes on an <audio>
 * and plays while the rest downloads; `source` is "deepgram_tts",
 * "deepgram_tts_fallback" (the Aura-2 backup) or "cache"; `cancel` stops the
 * download and frees the URL. Throws on failure — a 400 carries Deepgram's
 * reason.
 */
export async function readAloudStream(term, options) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), READ_ALOUD_START_TIMEOUT_MS)

  let res
  try {
    res = await fetch(`${API_URL}/unpack/read-aloud`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ term, options }),
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

  const mime = (res.headers.get("content-type") || "audio/mpeg").split(";")[0].trim()
  const source = res.headers.get("x-read-aloud-source") || ""
  let src
  if (canStream(mime)) {
    src = streamToMediaSource(res.body, mime)
  } else {
    try {
      src = URL.createObjectURL(await res.blob())
    } catch {
      throw new Error("Could not load audio.")
    }
  }
  return { src, source, cancel: () => { controller.abort(); URL.revokeObjectURL(src) } }
}

/** Every Deepgram TTS voice, for the voice picker. Returns { voices: [...] }. */
export async function listVoices() {
  const res = await fetch(`${API_URL}/unpack/voices`, { headers: getAuthHeaders() })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    if (res.status === 401) signalUnauthorized()
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

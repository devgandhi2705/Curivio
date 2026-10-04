/**
 * Read Aloud voice settings: which Flux voice speaks, how fast and how
 * expressive. Saved per browser in localStorage; an empty object means the
 * server default (Sienna). Audio format and the training opt-out are fixed
 * by the backend.
 *
 * Per Deepgram's Oct 2026 docs (it re-checks every request and its 400
 * message is shown if this goes stale): speed 0.5–1.5 in steps of 0.05,
 * expressivity whole numbers −2 (calm) … 2 (animated).
 */

const KEY = "curivio.read-aloud-voice.v1"
const FLUX = /^flux-[a-z]+-[a-z]{2}$/
export const SPEED_RANGE = [0.5, 1.5]

export function loadVoicePrefs() {
  try { return JSON.parse(localStorage.getItem(KEY)) || {} } catch { return {} }
}

export function saveVoicePrefs(prefs) {
  try { localStorage.setItem(KEY, JSON.stringify(prefs)) } catch { /* private mode: settings last this tab only */ }
}

/**
 * The `options` body for /unpack/read-aloud. A saved voice from another
 * Deepgram family (picked before voices were limited to Flux) falls back to
 * the default; speed snaps to Deepgram's 0.05 grid.
 */
export function toTtsOptions(prefs = loadVoicePrefs()) {
  const out = { model: FLUX.test(prefs.model || "") ? prefs.model : "flux-sienna-en" }
  if (prefs.speed != null && prefs.speed !== 1) {
    out.speed = Math.round(Math.min(SPEED_RANGE[1], Math.max(SPEED_RANGE[0], prefs.speed)) * 20) / 20
  }
  if (Number.isInteger(prefs.expressivity) && prefs.expressivity) {
    out.expressivity = Math.min(2, Math.max(-2, prefs.expressivity))
  }
  return out
}

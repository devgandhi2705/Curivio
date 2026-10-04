/** Pure helpers for the motion hooks — no React, no DOM, so node can test them. */

export function easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3)
}

/** "12d" → { prefix: '', n: 12, suffix: 'd', decimals: 0, grouped: false }; anything without a number → null.
 *  "12,345" (a toLocaleString() value) counts as 12345 and is shown grouped again. */
export function splitCount(value) {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? { prefix: '', n: value, suffix: '', decimals: 0, grouped: false } : null
  }
  const m = /^([^\d-]*)(-?\d{1,3}(?:,\d{2,3})+(?:\.(\d+))?|-?\d+(?:\.(\d+))?)(.*)$/.exec(String(value))
  if (!m) return null
  const grouped = m[2].includes(',')
  return { prefix: m[1], n: Number(m[2].replace(/,/g, '')), suffix: m[5], decimals: (m[3] || m[4] || '').length, grouped }
}

/** The number part of a count-up frame, formatted the way the original value was. */
export function formatCount(n, parts) {
  return parts.grouped
    ? n.toLocaleString(undefined, { minimumFractionDigits: parts.decimals, maximumFractionDigits: parts.decimals })
    : n.toFixed(parts.decimals)
}

/** Count of false→true transitions; staying true or turning false never counts. */
export function nextTurnedOn(prev, now, count) {
  return !prev && now ? count + 1 : count
}

/** Count of day completions: only the last card marked (n-1 → n) counts. A jump
 *  to complete is the read keys landing after the cards — a load, not an act. */
export function nextCompleted(prevRead, read, total, count) {
  return total > 0 && read >= total && read - prevRead === 1 ? count + 1 : count
}

/** Was this message created in the last 5s? The backend stores naive UTC
 *  ("2026-10-02 09:30:57"), which Date.parse would read as local time. */
export function isFreshMessage(createdAt, now = Date.now()) {
  if (!createdAt) return true
  const s = String(createdAt)
  const iso = /(?:[zZ]|[+-]\d\d:?\d\d)$/.test(s) ? s : s.replace(' ', 'T') + 'Z'
  return Math.abs(now - Date.parse(iso)) < 5000
}

export function shouldDismiss(offsetPx, velocityPxPerMs, sizePx) {
  return offsetPx > sizePx / 3 || velocityPxPerMs > 0.6
}

/** Decide, once the finger has moved 8px, whether this is our swipe or the page's scroll. */
export function classifyGesture(dx, dy, axis) {
  const along = Math.abs(axis === 'x' ? dx : dy)
  const across = Math.abs(axis === 'x' ? dy : dx)
  if (Math.max(along, across) < 8) return 'undecided'
  return along > across ? 'swipe' : 'scroll'
}

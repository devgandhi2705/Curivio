import { useRef } from 'react'
import { nextCompleted, nextTurnedOn } from '../lib/motionMath.js'

// Refs updated during render, the same idiom ChatMessage's StreamingDots uses
// for its crossfade — the count is derived from props, not state, so it never
// costs an extra render.

/** 0 on mount; +1 every time `value` changes. Key a one-shot animation on it. */
export function useChangeCount(value) {
  const prev = useRef(value)
  const count = useRef(0)
  if (!Object.is(prev.current, value)) {
    prev.current = value
    count.current += 1
  }
  return count.current
}

/** +1 each time `flag` goes false→true after mount — never on mount itself. */
export function useTurnedOnCount(flag) {
  const prev = useRef(flag)
  const count = useRef(0)
  if (prev.current !== flag) {
    count.current = nextTurnedOn(prev.current, flag, count.current)
    prev.current = flag
  }
  return count.current
}

/** +1 each time marking one more item completes the set (n-1 → n) — never on
 *  mount, and never when the read state lands after the items (0 → n). */
export function useCompletedCount(read, total) {
  const prev = useRef(read)
  const count = useRef(0)
  if (prev.current !== read) {
    count.current = nextCompleted(prev.current, read, total, count.current)
    prev.current = read
  }
  return count.current
}

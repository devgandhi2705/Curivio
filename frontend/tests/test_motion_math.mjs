/**
 * Pure helpers behind count-ups, confetti triggers and swipe-to-close.
 *
 * Run with:  node frontend/tests/test_motion_math.mjs
 */
// West of UTC on purpose: a naive-UTC timestamp read as local time lands in the future here.
process.env.TZ = 'America/New_York'
import assert from 'node:assert/strict'
import { easeOutCubic, splitCount, formatCount, nextTurnedOn, nextCompleted, isFreshMessage, shouldDismiss, classifyGesture } from '../src/lib/motionMath.js'

assert.equal(easeOutCubic(0), 0)
assert.equal(easeOutCubic(1), 1)
assert.ok(easeOutCubic(0.5) > 0.5)                       // fast start, slow finish

assert.deepEqual(splitCount(12),     { prefix: '', n: 12, suffix: '', decimals: 0, grouped: false })
assert.deepEqual(splitCount('12d'),  { prefix: '', n: 12, suffix: 'd', decimals: 0, grouped: false })
assert.deepEqual(splitCount('86%'),  { prefix: '', n: 86, suffix: '%', decimals: 0, grouped: false })
assert.deepEqual(splitCount('$3.40'), { prefix: '$', n: 3.4, suffix: '', decimals: 2, grouped: false })
assert.deepEqual(splitCount('2/6'),  { prefix: '', n: 2, suffix: '/6', decimals: 0, grouped: false })
// Admin tiles pass toLocaleString() values: the whole grouped number counts, not just "12"
assert.deepEqual(splitCount('12,345'), { prefix: '', n: 12345, suffix: '', decimals: 0, grouped: true })
assert.deepEqual(splitCount('$1,234.50'), { prefix: '$', n: 1234.5, suffix: '', decimals: 2, grouped: true })
assert.equal(formatCount(5000, splitCount('12,345')), (5000).toLocaleString())
assert.equal(formatCount(3.4, splitCount('$3.40')), '3.40')
assert.equal(splitCount('—'), null)
assert.equal(splitCount(NaN), null)

// Confetti/haptic trigger: only false→true counts (Review Focus 5)
assert.equal(nextTurnedOn(false, true, 0), 1)
assert.equal(nextTurnedOn(true, true, 1), 1)             // still complete: no new burst
assert.equal(nextTurnedOn(true, false, 1), 1)            // un-marking: no burst
assert.equal(nextTurnedOn(false, false, 0), 0)

// Day completion counts only the last card marked (n-1 -> n); read keys arriving
// after the cards (0 -> n) is a load, not a completion (Review Focus 5)
assert.equal(nextCompleted(5, 6, 6, 0), 1)
assert.equal(nextCompleted(0, 6, 6, 0), 0)               // keys landed late
assert.equal(nextCompleted(6, 5, 6, 1), 1)               // un-marking
assert.equal(nextCompleted(4, 5, 6, 0), 0)               // not done yet
assert.equal(nextCompleted(0, 1, 1, 0), 1)               // a one-card day
assert.equal(nextCompleted(0, 0, 0, 0), 0)

// Fresh messages animate in; loaded history never does, whatever the timezone.
// The backend stores naive UTC ("2026-10-02 09:30:57").
assert.ok(new Date(0).getTimezoneOffset() > 0, 'test must run west of UTC')
const now = Date.parse('2026-10-02T09:31:00Z')
assert.equal(isFreshMessage('2026-10-02 09:30:57', now), true)
assert.equal(isFreshMessage('2026-10-02 09:20:00', now), false)
assert.equal(isFreshMessage('2026-10-02T09:30:58.000Z', now), true)
assert.equal(isFreshMessage('2026-10-01T09:30:58.000Z', now), false)
assert.equal(isFreshMessage(null, now), true)            // optimistic message, no stamp yet
assert.equal(isFreshMessage('not a date', now), false)

// Swipe-to-close: a third of the size, or a flick
assert.equal(shouldDismiss(100, 0.1, 280), true)
assert.equal(shouldDismiss(40, 0.1, 280), false)
assert.equal(shouldDismiss(40, 0.8, 280), true)

// Gesture direction is decided once the finger has moved 8px (Review Focus 4)
assert.equal(classifyGesture(3, 4, 'x'), 'undecided')
assert.equal(classifyGesture(-20, 4, 'x'), 'swipe')
assert.equal(classifyGesture(-4, 30, 'x'), 'scroll')     // vertical scroll in the drawer
assert.equal(classifyGesture(2, 25, 'y'), 'swipe')
assert.equal(classifyGesture(25, 4, 'y'), 'scroll')

console.log('motion math: ok')

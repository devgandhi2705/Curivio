/**
 * Lite-device detection and haptic patterns. (There is no motion preference:
 * the app always animates.)
 *
 * Run with:  node frontend/tests/test_motion_prefs.mjs
 */
import assert from 'node:assert/strict'
import { isLiteDevice, HAPTIC_PATTERNS } from '../src/lib/motionPrefs.js'

// Lite = a touch device that is short on memory or cores
assert.equal(isLiteDevice({ coarse: true, memory: 4, cores: 8 }), true)
assert.equal(isLiteDevice({ coarse: true, memory: 8, cores: 4 }), true)
assert.equal(isLiteDevice({ coarse: true, memory: 8, cores: 8 }), false)
assert.equal(isLiteDevice({ coarse: false, memory: 2, cores: 2 }), false)   // laptops never
assert.equal(isLiteDevice({ coarse: true }), false)                          // unknown = not lite

assert.deepEqual(HAPTIC_PATTERNS, { tap: 10, success: [12, 40, 18] })

console.log('motion prefs: ok')

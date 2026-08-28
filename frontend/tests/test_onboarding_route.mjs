/**
 * Onboarding route helper tests.
 *
 * Run with:  node frontend/tests/test_onboarding_route.mjs
 *
 * Uses Node's built-in assert — no test framework required.
 */

import assert from 'node:assert/strict'
import {
  ONBOARDING_STEPS,
  onboardingStepIndex,
  onboardingStepPath,
  parseOnboardingStep,
} from '../src/utils/onboardingRoute.js'

let passed = 0
let failed = 0

function test(description, fn) {
  try {
    fn()
    console.log(`  ✓ ${description}`)
    passed++
  } catch (err) {
    console.error(`  ✗ ${description}`)
    console.error(`    ${err.message}`)
    failed++
  }
}

function suite(name) {
  console.log(`\n${name}`)
}

// ═══════════════════════════════════════════════════════════════════════════════
// onboardingStepIndex
// ═══════════════════════════════════════════════════════════════════════════════

suite('onboardingStepIndex')

test('maps each known slug to its position', () => {
  ONBOARDING_STEPS.forEach((slug, i) => assert.equal(onboardingStepIndex(slug), i))
})

test('unknown slug defaults to 0', () => {
  assert.equal(onboardingStepIndex('bogus'), 0)
  assert.equal(onboardingStepIndex(undefined), 0)
})

// ═══════════════════════════════════════════════════════════════════════════════
// onboardingStepPath
// ═══════════════════════════════════════════════════════════════════════════════

suite('onboardingStepPath')

test('builds a path from a slug', () => {
  assert.equal(onboardingStepPath('topics'), '/feed/onboarding/topics')
})

test('builds a path from an index', () => {
  assert.equal(onboardingStepPath(0), '/feed/onboarding/project')
  assert.equal(onboardingStepPath(2), '/feed/onboarding/launch')
})

// ═══════════════════════════════════════════════════════════════════════════════
// parseOnboardingStep
// ═══════════════════════════════════════════════════════════════════════════════

suite('parseOnboardingStep')

test('returns null for a plain /feed path', () => {
  assert.equal(parseOnboardingStep('/feed'), null)
})

test('returns null for a project deep-link, not "onboarding"', () => {
  assert.equal(parseOnboardingStep('/feed/proj-123'), null)
})

test('extracts a known step slug', () => {
  assert.equal(parseOnboardingStep('/feed/onboarding/topics'), 'topics')
  assert.equal(parseOnboardingStep('/feed/onboarding/launch'), 'launch')
})

test('defaults to "project" when the step segment is missing', () => {
  assert.equal(parseOnboardingStep('/feed/onboarding'), 'project')
  assert.equal(parseOnboardingStep('/feed/onboarding/'), 'project')
})

test('defaults to "project" for an unknown step segment', () => {
  assert.equal(parseOnboardingStep('/feed/onboarding/bogus'), 'project')
})

// ═══════════════════════════════════════════════════════════════════════════════
// Results
// ═══════════════════════════════════════════════════════════════════════════════

console.log(`\n${'─'.repeat(50)}`)
console.log(`  ${passed} passed  |  ${failed} failed`)
console.log(`${'─'.repeat(50)}\n`)

if (failed > 0) process.exit(1)

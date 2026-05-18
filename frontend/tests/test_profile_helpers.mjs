/**
 * Learning Profile helper tests.
 *
 * Run with:  node frontend/tests/test_profile_helpers.mjs
 *
 * Uses Node's built-in assert — no test framework required.
 * All tests use mocked profile data; no backend calls are made.
 */

import assert from 'node:assert/strict'
import {
  getEngagementLevel,
  deriveStrongAreas,
  deriveCurrentInterests,
  deriveFocusAreas,
  buildLearningProfile,
  LEARNING_STYLE_META,
  PROGRESSION_META,
  STRONG_SCORE,
  INTEREST_SCORE,
  FOCUS_MIN_RECS,
} from '../src/utils/profileHelpers.js'

// ── Shared mock data ───────────────────────────────────────────────────────────

const MOCK_INTERESTS = [
  { topic: 'Transformers',       preference_score: 2.1,  difficulty_preference: 'advanced',     times_recommended: 6 },
  { topic: 'LLMs',               preference_score: 1.8,  difficulty_preference: 'intermediate', times_recommended: 5 },
  { topic: 'RLHF',               preference_score: 1.2,  difficulty_preference: 'advanced',     times_recommended: 4 },
  { topic: 'RAG',                preference_score: 1.0,  difficulty_preference: 'intermediate', times_recommended: 5 },
  { topic: 'Finance',            preference_score: 0.8,  difficulty_preference: 'intermediate', times_recommended: 4 },
  { topic: 'Quant Research',     preference_score: 0.6,  difficulty_preference: 'advanced',     times_recommended: 3 },
  { topic: 'Supply Chain',       preference_score: 0.4,  difficulty_preference: 'intermediate', times_recommended: 2 },
  { topic: 'Prompt Engineering', preference_score: 0.3,  difficulty_preference: 'beginner',     times_recommended: 2 },
  { topic: 'Python Basics',      preference_score: 0.1,  difficulty_preference: 'beginner',     times_recommended: 1 },
]

const MOCK_DATA = {
  learning_stage:        'developing',
  difficulty_preference: 'intermediate',
  top_interests:         MOCK_INTERESTS,
  suppressed_topics:     ['Crypto'],
  stats:                 { topics_tracked: 9, total_liked: 15, total_disliked: 2 },
}

// ── Minimal test runner ───────────────────────────────────────────────────────

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
// getEngagementLevel
// ═══════════════════════════════════════════════════════════════════════════════

suite('getEngagementLevel')

test('score >= 1.5 returns "deep"', () => {
  assert.equal(getEngagementLevel(1.5), 'deep')
  assert.equal(getEngagementLevel(2.1), 'deep')
})

test('score >= 0.5 and < 1.5 returns "growing"', () => {
  assert.equal(getEngagementLevel(0.5), 'growing')
  assert.equal(getEngagementLevel(1.0), 'growing')
  assert.equal(getEngagementLevel(1.49), 'growing')
})

test('score < 0.5 returns "exploring"', () => {
  assert.equal(getEngagementLevel(0.0), 'exploring')
  assert.equal(getEngagementLevel(0.3), 'exploring')
  assert.equal(getEngagementLevel(0.49), 'exploring')
})

// ═══════════════════════════════════════════════════════════════════════════════
// deriveStrongAreas
// ═══════════════════════════════════════════════════════════════════════════════

suite('deriveStrongAreas')

test('returns only topics with score >= STRONG_SCORE (0.5)', () => {
  const strong = deriveStrongAreas(MOCK_INTERESTS)
  assert.ok(strong.every(t => t.preference_score >= STRONG_SCORE))
})

test('excludes topics below STRONG_SCORE', () => {
  const strong = deriveStrongAreas(MOCK_INTERESTS)
  assert.ok(!strong.some(t => t.topic === 'Supply Chain'))
  assert.ok(!strong.some(t => t.topic === 'Prompt Engineering'))
})

test('caps result at 6 topics', () => {
  const many = Array.from({ length: 20 }, (_, i) => ({
    topic: `Topic ${i}`, preference_score: 1.0, times_recommended: 1,
  }))
  assert.ok(deriveStrongAreas(many).length <= 6)
})

test('returns empty array when no topics qualify', () => {
  const lowScore = [{ topic: 'X', preference_score: 0.1, times_recommended: 1 }]
  assert.deepEqual(deriveStrongAreas(lowScore), [])
})

test('preserves order (highest score first from input)', () => {
  const strong = deriveStrongAreas(MOCK_INTERESTS)
  assert.equal(strong[0].topic, 'Transformers')
})

// ═══════════════════════════════════════════════════════════════════════════════
// deriveCurrentInterests
// ═══════════════════════════════════════════════════════════════════════════════

suite('deriveCurrentInterests')

test('includes topics with score >= INTEREST_SCORE (0)', () => {
  const interests = deriveCurrentInterests(MOCK_INTERESTS)
  assert.ok(interests.every(t => t.preference_score >= INTEREST_SCORE))
})

test('caps result at 8 topics', () => {
  const many = Array.from({ length: 20 }, (_, i) => ({
    topic: `Topic ${i}`, preference_score: 0.5, times_recommended: 1,
  }))
  assert.ok(deriveCurrentInterests(many).length <= 8)
})

test('returns empty array when all scores are negative', () => {
  const neg = [{ topic: 'Negative', preference_score: -0.5, times_recommended: 2 }]
  assert.deepEqual(deriveCurrentInterests(neg), [])
})

test('includes borderline zero-score topics', () => {
  const zero = [{ topic: 'Zero', preference_score: 0, times_recommended: 1 }]
  assert.equal(deriveCurrentInterests(zero).length, 1)
})

// ═══════════════════════════════════════════════════════════════════════════════
// deriveFocusAreas
// ═══════════════════════════════════════════════════════════════════════════════

suite('deriveFocusAreas')

test('returns only topics with times_recommended >= FOCUS_MIN_RECS (3)', () => {
  const focus = deriveFocusAreas(MOCK_INTERESTS)
  assert.ok(focus.every(t => t.times_recommended >= FOCUS_MIN_RECS))
})

test('excludes low-recommendation topics', () => {
  const focus = deriveFocusAreas(MOCK_INTERESTS)
  assert.ok(!focus.some(t => t.topic === 'Supply Chain'))    // 2 recs
  assert.ok(!focus.some(t => t.topic === 'Prompt Engineering')) // 2 recs
})

test('sorted by times_recommended descending', () => {
  const focus = deriveFocusAreas(MOCK_INTERESTS)
  for (let i = 0; i < focus.length - 1; i++) {
    assert.ok(focus[i].times_recommended >= focus[i + 1].times_recommended)
  }
})

test('caps result at 5 topics', () => {
  const many = Array.from({ length: 20 }, (_, i) => ({
    topic: `Topic ${i}`, preference_score: 1.0, times_recommended: 5,
  }))
  assert.ok(deriveFocusAreas(many).length <= 5)
})

test('returns empty array when no topics qualify', () => {
  const low = [{ topic: 'X', preference_score: 0.5, times_recommended: 1 }]
  assert.deepEqual(deriveFocusAreas(low), [])
})

// ═══════════════════════════════════════════════════════════════════════════════
// LEARNING_STYLE_META
// ═══════════════════════════════════════════════════════════════════════════════

suite('LEARNING_STYLE_META')

test('has entries for all three difficulty levels', () => {
  assert.ok(LEARNING_STYLE_META.beginner)
  assert.ok(LEARNING_STYLE_META.intermediate)
  assert.ok(LEARNING_STYLE_META.advanced)
})

test('each entry has required display fields', () => {
  for (const meta of Object.values(LEARNING_STYLE_META)) {
    assert.ok(typeof meta.label       === 'string', 'missing label')
    assert.ok(typeof meta.tagline     === 'string', 'missing tagline')
    assert.ok(typeof meta.description === 'string', 'missing description')
    assert.ok(typeof meta.accentClass === 'string', 'missing accentClass')
    assert.ok(typeof meta.bgClass     === 'string', 'missing bgClass')
  }
})

test('descriptions are non-trivially long', () => {
  for (const meta of Object.values(LEARNING_STYLE_META)) {
    assert.ok(meta.description.length > 30)
  }
})

// ═══════════════════════════════════════════════════════════════════════════════
// PROGRESSION_META
// ═══════════════════════════════════════════════════════════════════════════════

suite('PROGRESSION_META')

test('has entries for all three stages', () => {
  assert.ok(PROGRESSION_META.early)
  assert.ok(PROGRESSION_META.developing)
  assert.ok(PROGRESSION_META.proficient)
})

test('each entry has required display fields', () => {
  for (const meta of Object.values(PROGRESSION_META)) {
    assert.ok(typeof meta.label       === 'string', 'missing label')
    assert.ok(typeof meta.tagline     === 'string', 'missing tagline')
    assert.ok(typeof meta.progressPct === 'number', 'missing progressPct')
    assert.ok(typeof meta.accentClass === 'string', 'missing accentClass')
    assert.ok(typeof meta.barClass    === 'string', 'missing barClass')
  }
})

test('progressPct increases from early to developing to proficient', () => {
  assert.ok(PROGRESSION_META.early.progressPct < PROGRESSION_META.developing.progressPct)
  assert.ok(PROGRESSION_META.developing.progressPct < PROGRESSION_META.proficient.progressPct)
})

test('all progressPct values are between 0 and 100', () => {
  for (const meta of Object.values(PROGRESSION_META)) {
    assert.ok(meta.progressPct >= 0 && meta.progressPct <= 100)
  }
})

// ═══════════════════════════════════════════════════════════════════════════════
// buildLearningProfile
// ═══════════════════════════════════════════════════════════════════════════════

suite('buildLearningProfile')

test('returns all required profile keys', () => {
  const profile = buildLearningProfile(MOCK_DATA)
  const required = ['stage', 'progressionMeta', 'styleMeta', 'strongAreas', 'currentInterests', 'focusAreas', 'topicsExplored']
  for (const key of required) {
    assert.ok(key in profile, `missing key: ${key}`)
  }
})

test('stage matches input learning_stage', () => {
  const profile = buildLearningProfile(MOCK_DATA)
  assert.equal(profile.stage, 'developing')
})

test('progressionMeta matches the learning stage', () => {
  const profile = buildLearningProfile(MOCK_DATA)
  assert.deepEqual(profile.progressionMeta, PROGRESSION_META.developing)
})

test('styleMeta matches the difficulty preference', () => {
  const profile = buildLearningProfile(MOCK_DATA)
  assert.deepEqual(profile.styleMeta, LEARNING_STYLE_META.intermediate)
})

test('topicsExplored comes from stats.topics_tracked', () => {
  const profile = buildLearningProfile(MOCK_DATA)
  assert.equal(profile.topicsExplored, 9)
})

test('strongAreas are a subset of top_interests with high scores', () => {
  const profile = buildLearningProfile(MOCK_DATA)
  assert.ok(profile.strongAreas.every(t => t.preference_score >= STRONG_SCORE))
})

test('currentInterests are a subset of top_interests with positive scores', () => {
  const profile = buildLearningProfile(MOCK_DATA)
  assert.ok(profile.currentInterests.every(t => t.preference_score >= INTEREST_SCORE))
})

test('focusAreas are topics with enough recommendation count', () => {
  const profile = buildLearningProfile(MOCK_DATA)
  assert.ok(profile.focusAreas.every(t => t.times_recommended >= FOCUS_MIN_RECS))
})

test('handles missing stats gracefully', () => {
  const profile = buildLearningProfile({ ...MOCK_DATA, stats: undefined })
  assert.equal(profile.topicsExplored, 0)
})

test('handles empty top_interests gracefully', () => {
  const profile = buildLearningProfile({ ...MOCK_DATA, top_interests: [] })
  assert.deepEqual(profile.strongAreas,      [])
  assert.deepEqual(profile.currentInterests, [])
  assert.deepEqual(profile.focusAreas,       [])
})

test('defaults unknown stage to early meta', () => {
  const profile = buildLearningProfile({ ...MOCK_DATA, learning_stage: 'unknown' })
  assert.deepEqual(profile.progressionMeta, PROGRESSION_META.early)
})

test('defaults unknown difficulty to intermediate meta', () => {
  const profile = buildLearningProfile({ ...MOCK_DATA, difficulty_preference: 'unknown' })
  assert.deepEqual(profile.styleMeta, LEARNING_STYLE_META.intermediate)
})

test('proficient stage uses proficient meta', () => {
  const profile = buildLearningProfile({ ...MOCK_DATA, learning_stage: 'proficient' })
  assert.equal(profile.progressionMeta.label, 'Deep Explorer')
})

test('early stage uses early meta', () => {
  const profile = buildLearningProfile({ ...MOCK_DATA, learning_stage: 'early' })
  assert.equal(profile.progressionMeta.label, 'Just Getting Started')
})

test('beginner style uses beginner meta', () => {
  const profile = buildLearningProfile({ ...MOCK_DATA, difficulty_preference: 'beginner' })
  assert.equal(profile.styleMeta.label, 'Foundational Explorer')
})

test('advanced style uses advanced meta', () => {
  const profile = buildLearningProfile({ ...MOCK_DATA, difficulty_preference: 'advanced' })
  assert.equal(profile.styleMeta.label, 'Deep-Dive Enthusiast')
})

// ═══════════════════════════════════════════════════════════════════════════════
// Results
// ═══════════════════════════════════════════════════════════════════════════════

console.log(`\n${'─'.repeat(50)}`)
console.log(`  ${passed} passed  |  ${failed} failed`)
console.log(`${'─'.repeat(50)}\n`)

if (failed > 0) process.exit(1)

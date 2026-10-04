/**
 * motion.css must never carry its own colours — theme.css owns every colour,
 * which is what keeps Light, Dark and Legacy in step for free.
 *
 * Run with:  node frontend/tests/test_motion_css.mjs
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const css = readFileSync(new URL('../src/motion.css', import.meta.url), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '')                    // comments may name colours

assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b/i, 'hex colour in motion.css')
assert.doesNotMatch(css, /\b(rgba?|hsla?)\(\s*\d/i, 'literal rgb()/hsl() in motion.css')
// a bare keyword, not part of an identifier like --u-blue-500
assert.doesNotMatch(css, /(?<![-\w])(white|black|red|green|blue|gray|grey|yellow|orange|purple|pink)(?![-\w])/i,
  'named colour in motion.css')

for (const token of ['--m-spring', '--m-spring-soft', '--m-pop', '--m-out', '--m-exit', '--m-settle'])
  assert.match(css, new RegExp(`${token}:`), `${token} missing`)
assert.doesNotMatch(css, /\[data-motion="reduced"\]/, 'the app always animates — no reduced mode')
assert.match(css, /\[data-motion-lite\]/, 'lite mode missing')

// Legacy deliberately leaves most --u-<family>-<shade> channels unset (Tailwind
// falls back to stock colours there), so a bare var() makes the whole
// declaration invalid in Legacy — the progress fill and focus ring vanished.
const indexCss = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')
for (const [name, text] of [['motion.css', css], ['index.css', indexCss]]) {
  const bare = text.match(/var\(--u-[a-z]+-\d+\)/g) || []
  assert.deepEqual(bare, [], `${name}: palette var without a stock fallback: ${bare.join(', ')}`)
}

console.log('motion css: ok')

/**
 * LaTeX detection tests for MarkdownText.
 *
 * Run with:  node frontend/tests/test_math_text.mjs
 */
import assert from 'node:assert/strict'
import { matchInlineMath, matchMathBlock } from '../src/utils/mathText.js'

// Inline delimiters
assert.deepEqual(matchInlineMath('so \\(x^2\\) grows'), { before: 'so ', tex: 'x^2', display: false, after: ' grows' })
assert.deepEqual(matchInlineMath('area $\\pi r^2$.'), { before: 'area ', tex: '\\pi r^2', display: false, after: '.' })
assert.deepEqual(matchInlineMath('$x$'), { before: '', tex: 'x', display: false, after: '' })
assert.equal(matchInlineMath('\\[ HI = T + 4.0 \\]').display, true)
assert.equal(matchInlineMath('$$E = mc^2$$').tex, 'E = mc^2')
assert.equal(matchInlineMath('$$E = mc^2$$').display, true)

// Currency and prose stay prose
assert.equal(matchInlineMath('costs $5 and $10 today'), null)
assert.equal(matchInlineMath('between $5-$10'), null)
assert.equal(matchInlineMath('no math here'), null)

// Math inside inline code is left for the code branch
assert.equal(matchInlineMath('run `echo $HOME$` now'), null)
assert.equal(matchInlineMath('`$a$` then $b$').tex, 'b')
assert.equal(matchInlineMath('`$a$` then $b$').before, '`$a$` then ')
assert.equal(matchInlineMath('costs $10, see code `$x$`'), null)

// Multi-line blocks — the exact shape from the bug report
const report = ['\\[', 'HI = T + (0.33 \\times RH) - (0.70 \\times WS) + 4.0', '\\]', 'after']
assert.deepEqual(matchMathBlock(report, 0), { tex: 'HI = T + (0.33 \\times RH) - (0.70 \\times WS) + 4.0', nextIndex: 3 })
assert.deepEqual(matchMathBlock(['$$', 'a', 'b', '$$'], 0), { tex: 'a\nb', nextIndex: 4 })
assert.deepEqual(matchMathBlock(['  \\[ a = 1', 'b \\]'], 0), { tex: 'a = 1\nb', nextIndex: 2 })
// Unclosed (still streaming) and single-line blocks are not blocks
assert.equal(matchMathBlock(['\\[', 'x = 1'], 0), null)
assert.equal(matchMathBlock(['\\[ x = 1 \\]'], 0), null)
assert.equal(matchMathBlock(['plain'], 0), null)

console.log('math text: all passed')

// LaTeX detection for MarkdownText. Pure string logic, no React, so
// frontend/tests/test_math_text.mjs can run it under plain node.
//
// Delimiters models actually emit: \[ \] and $$ $$ (display), \( \) and $ $
// (inline). Single-$ follows Pandoc's rule — no space after the opening $,
// none before the closing $, no digit right after it — so "$5 and $10"
// stays prose. Single-$ content never holds a backtick, so a stray "$10"
// can't pair with a "$" inside a later code span.
//
// The prefix is backtick-aware: it only ever swallows whole `code` spans, so
// math-looking text inside inline code is never matched here and reaches the
// code branch intact. No lookbehind, for the same Safari reason as _ITALIC_RE.
const _INLINE_MATH_RE =
  /^((?:[^`]|`[^`\n]*`)*?)(?:\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$(?![\s$])([^$\n`]*?[^\s$\\`])\$(?!\d))(.*)$/s

// First math span in `text`, or null. { before, tex, display, after }
export function matchInlineMath(text) {
  const m = text.match(_INLINE_MATH_RE)
  if (!m) return null
  const display = m[2] !== undefined || m[3] !== undefined
  const tex = m[2] ?? m[3] ?? m[4] ?? m[5]
  return { before: m[1], tex: tex.trim(), display, after: m[6] }
}

const _BLOCK_OPENERS = [["$$", "$$"], ["\\[", "\\]"]]

// Multi-line display block starting at lines[start]:
//   \[            $$
//   x = 1    or   x = 1
//   \]            $$
// Returns { tex, nextIndex } or null. An unclosed block (mid-stream) returns
// null so the lines show as plain text until the closer arrives.
export function matchMathBlock(lines, start) {
  const first = lines[start].trim()
  for (const [open, close] of _BLOCK_OPENERS) {
    if (!first.startsWith(open)) continue
    const head = first.slice(open.length)
    // Closed on the same line: the inline matcher renders it.
    if (head.includes(close)) return null
    const body = [head]
    for (let i = start + 1; i < lines.length; i++) {
      const line = lines[i].trim()
      const end = line.indexOf(close)
      if (end !== -1) {
        body.push(line.slice(0, end))
        return { tex: body.join("\n").trim(), nextIndex: i + 1 }
      }
      body.push(lines[i])
    }
    return null
  }
  return null
}

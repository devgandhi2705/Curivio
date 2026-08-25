import { useState } from "react"

// Copy icon component
function CopyIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z" />
      <path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z" />
    </svg>
  )
}

// Code block copy button
function CodeBlockCopyButton({ code }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button
      onClick={handleCopy}
      title="Copy code"
      className="flex items-center gap-1 px-2 py-1 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors text-xs"
    >
      <CopyIcon />
      {copied && <span className="text-[10px]">Copied!</span>}
    </button>
  )
}

// Inline parser: bold (**text**), italic (*text*, Phase L), links
// ([text](url)), inline code (`text`), citation markers ([N], Phase E).
// `sources` is the turn's real, ordered {title,url} list (from the tool_call
// block(s) — see MarkdownText below); [N] resolves to sources[N-1], 1-indexed
// to match the numbering chat_tools.web_search/format_reasoning_search_note
// assign server-side.
//
// Branch ORDER below is load-bearing, not incidental:
//   link -> citation -> bold -> code -> italic
// Bold before italic so "**x**" is consumed as bold and never seen by the
// italic branch. Code before italic so a backticked "`a *b* c`" keeps its
// asterisks literal instead of emphasising inside code.
// The italic pattern is independently anchored too (see _ITALIC_RE) — it
// cannot mis-consume a "**" run even if it ran first — so this ordering is
// belt-and-braces rather than the only thing keeping bold intact.
// Italic (*text*) — Phase L. Deliberately written WITHOUT lookbehind:
// `(?<!\*)` would be the obvious way to say "this star isn't the second star
// of a **run", but lookbehind is ES2018 and Safari only shipped it in 16.4.
// An unparseable regex literal is a module-level SyntaxError, so on an older
// iOS the whole bundle would fail to load — a blank app, not just missing
// italics. `((?:.*?[^*])?)` says the same thing with plain groups: the prefix
// is either empty or ends in a non-star. Verified equivalent to the lookbehind
// version on all 18 collision probes, 0 differing cases.
const _ITALIC_RE = /^((?:.*?[^*])?)\*(?![\s*])([^*\n]*[^\s*])\*(?!\*)(.*)$/

export function renderInline(text, sources = []) {
  const parts = []
  let remaining = text
  let key = 0

  while (remaining.length > 0) {
    const linkMatch = remaining.match(/^(.*?)\[([^\]]+)\]\(([^)]+)\)(.*)$/)
    if (linkMatch) {
      if (linkMatch[1]) parts.push(<span key={key++}>{renderInline(linkMatch[1], sources)}</span>)
      parts.push(
        <a key={key++} href={linkMatch[3]} target="_blank" rel="noopener noreferrer"
          className="text-blue-400 hover:text-blue-300 underline underline-offset-[3px] decoration-blue-400/40 hover:decoration-blue-300/60 transition-colors">
          {linkMatch[2]}
        </a>
      )
      remaining = linkMatch[4]
      continue
    }

    // Citation marker [N] — checked after linkMatch above, so a real
    // "[1](https://...)" markdown link is already consumed as a link before
    // this branch ever sees it; a bare "[1]" with no following "(url)" never
    // matches linkMatch, so there's no ambiguity between the two.
    const citeMatch = remaining.match(/^(.*?)\[(\d+)\](.*)$/)
    if (citeMatch) {
      if (citeMatch[1]) parts.push(<span key={key++}>{renderInline(citeMatch[1], sources)}</span>)
      const n = parseInt(citeMatch[2], 10)
      const source = sources[n - 1]
      parts.push(
        source ? (
          <sup key={key++}>
            <a href={source.url} target="_blank" rel="noopener noreferrer" title={source.title || source.url}
              className="inline-flex items-center justify-center ml-0.5 px-1 min-w-[14px] h-[13px] rounded text-[9px] font-semibold bg-blue-500/15 text-blue-300 hover:bg-blue-500/25 hover:text-blue-200 no-underline align-super leading-none">
              {n}
            </a>
          </sup>
        ) : (
          // Invalid/out-of-range id (model over-cited, or no real sources
          // available for this render path — e.g. structured mode, out of
          // scope this phase) — never a dead link, never a crash: the
          // bracket renders as plain visible text instead.
          <span key={key++}>[{n}]</span>
        )
      )
      remaining = citeMatch[3]
      continue
    }

    const boldMatch = remaining.match(/^(.*?)\*\*(.+?)\*\*(.*)$/)
    if (boldMatch) {
      if (boldMatch[1]) parts.push(<span key={key++}>{renderInline(boldMatch[1], sources)}</span>)
      parts.push(<strong key={key++} className="font-semibold text-slate-100">{boldMatch[2]}</strong>)
      remaining = boldMatch[3]
      continue
    }

    const codeMatch = remaining.match(/^(.*?)`([^`]+)`(.*)$/)
    if (codeMatch) {
      if (codeMatch[1]) parts.push(<span key={key++}>{renderInline(codeMatch[1], sources)}</span>)
      parts.push(
        <code key={key++} className="bg-slate-800/80 border border-slate-700/50 rounded-md px-[5px] py-[1.5px] text-[12.5px] font-mono text-violet-300 leading-none">
          {codeMatch[2]}
        </code>
      )
      remaining = codeMatch[3]
      continue
    }

    // Italic (*text*) — Phase L. Every guard here is load-bearing:
    //   (?<!\*)   opening star is not the second star of a "**" run
    //   (?![\s*]) opening star is not followed by whitespace ("2 * 3 * 4" must
    //             stay literal arithmetic) or by another star
    //   [^*\n]*[^\s*]  content holds no star, is at least one char, and does
    //             not end in whitespace (CommonMark's right-flanking rule)
    //   (?!\*)    closing star is not the first star of a "**" run
    // Together these make "**bold**" unmatchable by this pattern at any offset,
    // which is what the precondition's collision probe demanded.
    const italicMatch = remaining.match(_ITALIC_RE)
    if (italicMatch) {
      if (italicMatch[1]) parts.push(<span key={key++}>{renderInline(italicMatch[1], sources)}</span>)
      parts.push(<em key={key++} className="italic">{renderInline(italicMatch[2], sources)}</em>)
      remaining = italicMatch[3]
      continue
    }

    parts.push(<span key={key++}>{remaining}</span>)
    break
  }

  return parts.length === 1 && typeof parts[0].props?.children === "string"
    ? parts[0].props.children
    : parts
}

// List line: optional leading whitespace (nesting depth), then a bullet
// (-, *, •) or numbered (N.) marker. Matches at any indent — the old code
// only ever checked column-0 markers, so an indented sub-item read as
// "not a list line" and fell straight to the plain-paragraph branch below,
// collapsing the nesting (and splitting one list into several, since the
// indented lines broke the contiguous-run scan too).
const _LIST_LINE_RE = /^( *)([-*•]|\d+\.)\s(.*)$/

// Heading line: 1-6 hashes, then a space, then real content. The required
// space is what keeps a bare "#hashtag" out, and the {1,6} cap is CommonMark's.
const _HEADING_RE = /^(#{1,6}) +(.*\S.*)$/

// Levels 2-6. Level 1 uses the component's own `headingClass` (unchanged).
//
// Level 4+ design call, made against real data rather than taste: #### appears
// 8 times across 3 real assistant messages in this DB, and ALL 3 of those also
// use ### — one sample has five #### siblings under a single ###. Collapsing
// #### into ###'s styling would therefore flatten a hierarchy real content
// actually relies on, so level 4 gets its own weight.
//
// It is subordinate to ### by CASE and DIMNESS, not by size: ### is already a
// small uppercase eyebrow (0.8rem via .reading-text h3 in index.css, which
// beats these utilities on specificity), and anything smaller stops being
// readable. Sentence-case + a dimmer slate reads as "below the eyebrow" while
// staying legible. ##### and ###### reuse it verbatim — they occur 0 times in
// real content, so they must WORK but do not warrant a bespoke step each.
function _headingClass(level, isThinking) {
  if (isThinking) return "text-slate-400 text-[13px] sm:text-[14px] leading-[1.6] sm:leading-[1.7] mt-3 sm:mt-4 mb-1 first:mt-0"
  if (level === 2) return "text-[14.5px] sm:text-[15.5px] font-semibold text-slate-100 mt-5 sm:mt-7 mb-2 sm:mb-2.5 first:mt-0 leading-snug tracking-tight"
  if (level === 3) return "text-[11px] sm:text-[11.5px] font-semibold text-slate-400 mt-5 sm:mt-6 mb-1.5 sm:mb-2 first:mt-0 uppercase tracking-widest"
  return "text-[12px] sm:text-[12.5px] font-semibold text-slate-400/85 mt-4 sm:mt-5 mb-1.5 first:mt-0 leading-snug"
}

// Collects a contiguous run of list lines (any indent) starting at `start`
// and builds a real parent/child tree via a depth stack — standard
// indent-stack parsing: an entry pops back to (and attaches under) the
// nearest ancestor with strictly shallower indent, or nests one level under
// the previous entry if it's deeper.
function _parseListRun(lines, start) {
  const entries = []
  let i = start
  while (i < lines.length) {
    const m = lines[i].match(_LIST_LINE_RE)
    if (!m) break
    entries.push({ indent: m[1].length, ordered: /^\d+\.$/.test(m[2]), text: m[3] })
    i++
  }
  const root = []
  const stack = [{ indent: -1, children: root }]
  for (const entry of entries) {
    while (stack.length > 1 && entry.indent <= stack[stack.length - 1].indent) stack.pop()
    const item = { text: entry.text, ordered: entry.ordered, children: [] }
    stack[stack.length - 1].children.push(item)
    stack.push({ indent: entry.indent, children: item.children })
  }
  return { items: root, nextIndex: i }
}

function _renderListTree(items, keyPrefix, sources) {
  const ordered = items[0]?.ordered
  const Tag = ordered ? "ol" : "ul"
  return (
    <Tag key={keyPrefix} className={`my-2.5 sm:my-3.5 space-y-2 sm:space-y-2.5 pl-0${ordered ? " list-none" : ""}`}>
      {items.map((item, idx) => (
        <li key={idx} className="flex flex-col gap-1.5 text-[14px] sm:text-[15px] text-slate-300 leading-[1.7] sm:leading-[1.75]">
          <div className="flex gap-2.5">
            {ordered ? (
              <span className="text-blue-400/60 flex-shrink-0 tabular-nums text-[13px] font-semibold mt-[2px] min-w-[1.4em] text-right">{idx + 1}.</span>
            ) : (
              <span className="text-blue-400/50 flex-shrink-0 mt-[3px] select-none text-[13px] sm:text-[14px]">•</span>
            )}
            <span>{renderInline(item.text, sources)}</span>
          </div>
          {item.children.length > 0 && (
            <div className="pl-5 sm:pl-6">{_renderListTree(item.children, `${keyPrefix}-${idx}`, sources)}</div>
          )}
        </li>
      ))}
    </Tag>
  )
}

// Line-by-line markdown renderer. `sources` (Phase E): the turn's real,
// ordered {title,url} list — resolves [N] citation markers in the text.
// Omitted/empty for any render path with nothing real to cite against
// (structured mode, thinking text, no tool call this turn) — renderInline's
// own invalid-id fallback already renders [N] as plain text in that case,
// so no separate empty-sources handling is needed here.
export default function MarkdownText({ text, variant = "default", className = "", sources = [] }) {
  const lines = text.split("\n")
  const isThinking = variant === "thinking"
  const headingClass = isThinking
    ? "text-slate-400 text-[13px] sm:text-[14px] leading-[1.6] sm:leading-[1.7]"
    : "text-[16px] sm:text-[18px] font-bold text-slate-50 mt-6 sm:mt-8 mb-2.5 sm:mb-3 first:mt-0 leading-tight tracking-tight"
  const subheadingClass = isThinking
    ? "font-medium text-slate-400 text-[13px] sm:text-[14px] leading-[1.6] sm:leading-[1.7]"
    : "font-semibold text-slate-100 text-[14px] sm:text-[15px] mt-5 sm:mt-6 mb-2 sm:mb-2.5 first:mt-0 leading-snug"
  const paragraphClass = isThinking
    ? "text-slate-400 text-[13px] sm:text-[14px] leading-[1.6] sm:leading-[1.7]"
    : "text-slate-300 leading-[1.72] sm:leading-[1.78] text-[14px] sm:text-[15px]"
  const elements = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Headings, levels 1-6 (Phase L). Was three hardcoded startsWith branches
    // that stopped at "### ", so "#### Quick Takeaways" fell through to the
    // plain-paragraph branch and rendered its hashes as literal text. The
    // level-1/2/3 class strings below are byte-identical to those branches —
    // this is an extension, not a restyle.
    const headingMatch = line.match(_HEADING_RE)
    if (headingMatch) {
      const level = headingMatch[1].length
      const Tag = `h${level}`
      elements.push(
        <Tag key={i} className={level === 1 ? headingClass : _headingClass(level, isThinking)}>
          {renderInline(headingMatch[2], sources)}
        </Tag>
      )
      i++
      continue
    }

    if (line.startsWith("```")) {
      const lang = line.slice(3).trim()
      const codeLines = []
      i++
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i])
        i++
      }
      const codeContent = codeLines.join("\n")
      elements.push(
        <div key={i} className="bg-slate-900 border border-slate-700/60 rounded-xl overflow-hidden my-4">
          {/* Phase L: the label div is now ALWAYS rendered, empty or not. It
              used to be `{lang && <div .../>}`, which left this
              justify-between row with a single child on any fence that carries
              no language — and a lone flex child under justify-between sits at
              flex-START, so the copy button silently jumped from the right edge
              to the left. Real and reproducible: same block, one with
              "```python" and one with "```", produced two different layouts. */}
          <div className="flex items-center justify-between px-4 pt-3">
            <div className="text-slate-500 text-[10.5px] font-medium uppercase tracking-widest">{lang}</div>
            <CodeBlockCopyButton code={codeContent} />
          </div>
          <pre className="px-4 pb-3 pt-1 overflow-x-scroll-touch">
            {/* leading-[1.68] -> 1.5. Not a defect fix, a judgement call stated
                as one: 13px x 1.68 = 21.8px per line, which is prose rhythm
                applied to code. Tightening to 19.5px keeps indentation runs
                reading as one visual block, which is what makes the pyramid
                sample legible as a shape. */}
            <code className="text-[13px] font-mono text-slate-200 leading-[1.5] block whitespace-pre">{codeContent}</code>
          </pre>
        </div>
      )
      i++
      continue
    }

    if (line.startsWith("**") && line.endsWith("**") && !line.slice(2, -2).includes("**")) {
      elements.push(
        <p key={i} className={subheadingClass}>
          {/* Phase L: was `{line.slice(2, -2)}` — raw text, the only branch in
              this renderer that skipped renderInline. That silently swallowed
              every inline feature inside a whole-line bold subheading: an
              *italic* stayed literal, and so did [1] citations and [text](url)
              links. Routed through renderInline like every sibling branch. */}
          {renderInline(line.slice(2, -2), sources)}
        </p>
      )
      i++
      continue
    }

    if (line.startsWith("|") && line.endsWith("|")) {
      const tableLines = []
      while (i < lines.length && lines[i].startsWith("|")) {
        tableLines.push(lines[i])
        i++
      }
      const headerCells = tableLines[0].split("|").filter(Boolean).map(c => c.trim())
      // A real GFM separator row is only "|", "-", ":", and whitespace, with
      // at least one "-" (e.g. "|---|:--:|"). Models frequently omit this row
      // entirely — treating tableLines[1] as the separator unconditionally
      // silently drops the first real data row in that case. Recover instead
      // of corrupting: if line 1 isn't actually a separator, every line after
      // the header is real data.
      const isSeparatorRow = line => /^\|?[\s|:-]+\|?$/.test(line) && line.includes("-")
      const hasSeparator = tableLines.length > 1 && isSeparatorRow(tableLines[1])
      const dataRows = (hasSeparator ? tableLines.slice(2) : tableLines.slice(1)).map(row =>
        row.split("|").filter(Boolean).map(c => c.trim())
      )
      elements.push(
        <div key={i} className="overflow-x-scroll-touch my-4 rounded-xl border border-slate-700/50">
          <table className="w-full text-[13.5px] border-collapse">
            <thead>
              <tr className="border-b border-slate-700/70">
                {headerCells.map((cell, ci) => (
                  <th key={ci} className="text-left px-3.5 py-2.5 bg-slate-800/60 text-slate-200 font-semibold text-[12px] uppercase tracking-wide">
                    {renderInline(cell, sources)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {dataRows.map((row, ri) => (
                <tr key={ri} className={ri % 2 === 0 ? "bg-transparent" : "bg-slate-800/20"}>
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-3.5 py-2.5 text-slate-300 border-b border-slate-800/60 leading-relaxed">
                      {renderInline(cell, sources)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
      continue
    }

    if (_LIST_LINE_RE.test(line)) {
      const { items, nextIndex } = _parseListRun(lines, i)
      elements.push(_renderListTree(items, `list-${i}`, sources))
      i = nextIndex
      continue
    }

    if (!line.trim()) {
      if (!isThinking) elements.push(<div key={i} className="h-1 sm:h-1.5" />)
      i++
      continue
    }

    elements.push(
      <p key={i} className={paragraphClass}>
        {renderInline(line, sources)}
      </p>
    )
    i++
  }

  return <div className={`reading-text prose-wrap ${className || "space-y-1.5"}`}>{elements}</div>
}

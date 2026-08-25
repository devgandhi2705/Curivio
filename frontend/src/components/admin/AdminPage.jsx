import { useState, useEffect, useMemo, useCallback, useRef } from "react"
import { listAdminProjects, listAdminCallsGrouped, getAdminSummary, getAdminOperationSummary, getAdminCallVolume, getAdminCallTree, exportAdminCallsGrouped } from "../../api/admin.js"

// Real confirmed default from the live /admin/calls/grouped route (Phase D
// precondition check) — B2's backend default, not assumed from memory.
const GROUP_PAGE_SIZE = 20

// ── Small building blocks ───────────────────────────────────────────────────

function Skeleton({ className }) {
  return <div className={`rounded-2xl bg-slate-900/60 border border-slate-800/50 animate-pulse ${className}`} />
}

function StatusBadge({ success }) {
  return success ? (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
      OK
    </span>
  ) : (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-rose-500/10 border border-rose-500/25 text-rose-400">
      ERROR
    </span>
  )
}

function formatTimestamp(ts) {
  if (!ts) return "—"
  const d = new Date(ts.includes("T") ? ts : ts.replace(" ", "T") + "Z")
  if (isNaN(d.getTime())) return ts
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

// model_used is only ever set on success (by design — it's not known until the
// call completes). For failed calls, model_requested is the real captured
// value; falling back to it here fixes a genuine display bug, not a data gap.
function formatModel(row) {
  const model = row.model_used || row.model_requested
  return model ? `${row.provider} / ${model}` : row.provider
}

// call_logger.py's on_llm_end used to fall back to Python's str(list) when an
// extended-thinking response's content was a list of blocks instead of a
// plain string (fixed server-side — see call_logger.py). Rows logged before
// that fix still have the raw repr stored (`[{'type': 'thinking', ...}, ...]`)
// — display-only recovery here, nothing is rewritten in the DB. Python repr
// is close to JSON (single quotes instead of double, True/False/None instead
// of true/false/null); this walks the string once, tracking whether it's
// inside a quoted literal, and rewrites quoting to valid JSON so it can
// actually be parsed — a regex over the raw text can't reliably tell a
// dict-key colon from text content, but a real (if minimal) parse can.
function pythonReprToJson(s) {
  let out = "", i = 0, inString = false, quoteChar = null
  while (i < s.length) {
    const c = s[i]
    if (inString) {
      if (c === "\\" && i + 1 < s.length) {
        const next = s[i + 1]
        if (next === quoteChar) { out += next; i += 2; continue }
        if (next === "\\") { out += "\\\\"; i += 2; continue }
        out += c + next; i += 2; continue
      }
      if (c === quoteChar) { out += '"'; inString = false; quoteChar = null; i++; continue }
      if (c === '"') { out += '\\"'; i++; continue }
      out += c; i++; continue
    }
    if (c === "'" || c === '"') { inString = true; quoteChar = c; out += '"'; i++; continue }
    out += c; i++
  }
  return out.replace(/\bTrue\b/g, "true").replace(/\bFalse\b/g, "false").replace(/\bNone\b/g, "null")
}

// Same "text blocks only, drop thinking" rule call_logger.py now applies at
// write time (extract_text), applied here to a parsed legacy blob instead.
function formatOutput(raw) {
  if (!raw || typeof raw !== "string" || !/^\[\{['"]type['"]\s*:/.test(raw.trim())) return raw
  try {
    const parsed = JSON.parse(pythonReprToJson(raw))
    if (!Array.isArray(parsed)) return raw
    const parts = parsed.map(item =>
      typeof item === "string" ? item : (item?.type === "text" ? (item.text || "") : "")
    )
    const cleaned = parts.join("")
    return cleaned || raw
  } catch {
    return raw
  }
}

// Phase O-Task2 — two distinct fallback labels, not one: "Shared" means this
// row structurally has no single owner by design (intelligence_feed's daily
// cross-user cache-fill, confirmed in this phase's precondition — threading
// a user_id there would misattribute shared content to whichever request
// happened to trigger the cache miss). "Unattributed" means the opposite —
// this row COULD have carried a real user but doesn't, whether a historical
// write-path gap since fixed (chat/feed_legacy pre-July, translate/explain/
// tts pre-N-fix) or a not-yet-launched surface (feed_v2, whose write path is
// already correctly wired for when it ships). Conflating the two would
// mislabel a structural non-gap as a bug.
function formatUsername(userEmail, surface) {
  if (userEmail) return userEmail
  return surface === "intelligence_feed" ? "Shared" : "Unattributed"
}

// Phase J — Task 4. Every latency/token display used bare .toLocaleString(),
// which groups by the VIEWER's browser locale (a de-DE viewer sees "1.234"
// not "1,234" — a different number to someone skimming for a typo). One
// helper, explicit 'en-US', is the single source every site below reuses —
// fixing it here fixes every call site that goes through fmtMs/fmtTokens.
function fmtNum(n) {
  return n.toLocaleString("en-US")
}

// Group sums are nullable by design (see admin_service._groups_cte) — a group
// whose rows all logged NULL total_tokens must read "—", never a fake 0.
function fmtMs(ms) {
  return ms != null ? `${fmtNum(ms)}ms` : "—"
}

function fmtTokens(t) {
  return t != null ? fmtNum(t) : "—"
}

// Recognized error patterns from real llm_call_log data (RESOURCE_EXHAUSTED,
// API-key auth, 503) plus json_response.py's malformed-JSON RuntimeError path
// (backend/llm/json_response.py:73) — not yet seen in real data but a real
// documented failure mode, not speculative. Returns null if nothing matches;
// callers must not fabricate a summary when one can't be cleanly extracted.
function summarizeError(errorType, errorMessage) {
  const msg = errorMessage || ""

  if (/resource_exhausted|429|quota/i.test(msg)) {
    const retry = msg.match(/retryDelay['"]?:\s*['"]?(\d+s)/)
    return retry ? `Rate limit / quota exceeded — retry in ${retry[1]}` : "Rate limit / quota exceeded"
  }
  if (errorType === "AuthenticationError" || /invalid api key|api_key_invalid|api key not valid/i.test(msg)) {
    return "Invalid or missing API key"
  }
  if (errorType === "RuntimeError" && /malformed json/i.test(msg)) {
    return "Model returned malformed JSON after retries"
  }
  if (errorType === "ServerError" || /\b503\b|unavailable/i.test(msg)) {
    return "Upstream provider unavailable (503)"
  }
  return null
}

// ── Copy / download formatting (Phase I) ────────────────────────────────────
// All output is built with plain string templating and handed to a Blob — no
// CSV/file-generation library was added, and none is needed.

// Exact template from the phase spec. The values go in verbatim, wrapped in
// literal double quotes — deliberately NOT JSON-escaped, since the point is
// pasting real prompt text into an issue or another prompt.
function buildCombinedCopy(row) {
  return `INPUT: "${row.input ?? ""}"\nOUTPUT: "${formatOutput(row.output) ?? ""}"`
}

// Timestamps in exported files use the raw stored ISO value, not
// formatTimestamp's localized rendering: a file that gets attached to a ticket
// should not read differently depending on who downloaded it.
function exportMeta(row) {
  const meta = [
    ["Timestamp", row.created_at],
    ["Action", row.call_type || "—"],
    ["Model", formatModel(row)],
    ["Latency", row.latency_ms != null ? `${row.latency_ms}ms` : "—"],
    ["Tokens", row.total_tokens != null ? String(row.total_tokens) : "—"],
    ["Status", row.success ? "OK" : "ERROR"],
  ]
  if (row.error_type) {
    meta.push(["Error", `${row.error_type}: ${row.error_message || ""}`.trim()])
  }
  return meta
}

// Real logged text contains ``` fences (23 inputs / 14 outputs today, longest
// backtick run = 3), so a 3-backtick fence would be broken out of by real
// data. CommonMark lets a longer fence contain shorter ones — 4 is enough for
// everything actually in the table, and is recomputed per block anyway so a
// future 4-backtick payload still can't escape.
function mdFence(...texts) {
  let longest = 0
  for (const t of texts) {
    for (const m of String(t ?? "").matchAll(/`+/g)) longest = Math.max(longest, m[0].length)
  }
  return "`".repeat(Math.max(longest + 1, 4))
}

// One row rendered as a metadata header + Input/Output sections. Shared by the
// row-level file and by every row inside a group file, so the two can't drift.
function rowBlock(row, fmt, headingLevel = 1) {
  const title = `${row.call_type || "call"} — ${row.created_at}`
  const meta = exportMeta(row)
  const output = formatOutput(row.output)

  if (fmt === "md") {
    const h = "#".repeat(headingLevel)
    const hh = "#".repeat(headingLevel + 1)
    const fence = mdFence(row.input, output)
    return [
      `${h} ${title}`,
      "",
      ...meta.map(([k, v]) => `- **${k}:** ${v}`),
      "",
      `${hh} Input`,
      "",
      fence,
      row.input ?? "",
      fence,
      "",
      `${hh} Output`,
      "",
      fence,
      output ?? "",
      fence,
      "",
    ].join("\n")
  }

  return [
    title,
    "-".repeat(title.length),
    ...meta.map(([k, v]) => `${k}: ${v}`),
    "",
    "INPUT:",
    row.input ?? "",
    "",
    "OUTPUT:",
    output ?? "",
    "",
  ].join("\n")
}

function groupHeaderBlock(group, fmt) {
  const meta = [
    ["Trace ID", group.trace_id ?? "(none — single ungrouped row)"],
    ["Action Type", group.action_type ?? "—"],
    ["Started At", group.started_at],
    ["Rows", String(group.row_count)],
    ["All Succeeded", group.all_succeeded ? "yes" : "no"],
  ]
  if (fmt === "md") {
    return [`# Operation ${group.trace_id ?? "(ungrouped)"}`, "",
      ...meta.map(([k, v]) => `- **${k}:** ${v}`), "", "---", ""].join("\n")
  }
  const bar = "=".repeat(70)
  return [bar, `OPERATION ${group.trace_id ?? "(ungrouped)"}`, bar,
    ...meta.map(([k, v]) => `${k}: ${v}`), "", ""].join("\n")
}

// group.rows arrives in execution order (timestamp_start ASC) from the
// backend and is written out in exactly that order — no client-side re-sort.
function buildGroupFile(group, fmt) {
  return groupHeaderBlock(group, fmt) +
    group.rows.map(r => rowBlock(r, fmt, 2)).join(fmt === "md" ? "\n" : "\n")
}

function buildBulkFile(groups, fmt) {
  const header = fmt === "md"
    ? [`# LLM call export`, "", `- **Generated:** ${new Date().toISOString()}`,
       `- **Operations:** ${groups.length}`,
       `- **Rows:** ${groups.reduce((n, g) => n + g.rows.length, 0)}`, "", "---", ""].join("\n")
    : [`LLM CALL EXPORT`, `Generated: ${new Date().toISOString()}`,
       `Operations: ${groups.length}`,
       `Rows: ${groups.reduce((n, g) => n + g.rows.length, 0)}`, "", ""].join("\n")
  return header + groups.map(g => buildGroupFile(g, fmt)).join("\n")
}

// ── CSV (RFC 4180, hand-escaped — no library) ───────────────────────────────
// This is not a theoretical hazard: of 6,065 real rows, 5,578 inputs contain a
// newline, 3,441 contain a comma and 1,299 contain a double quote. A field is
// quoted whenever it holds a quote, comma, CR or LF, and internal quotes are
// doubled. Records are CRLF-separated per the spec (real data contains LF only,
// never bare CR, but the check covers CR anyway).
function csvCell(value) {
  if (value == null) return ""
  const s = String(value)
  return /["\,\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

const CSV_COLUMNS = [
  ["trace_id",        (r, g) => g.trace_id],
  ["group_action_type", (r, g) => g.action_type],
  ["group_row_count", (r, g) => g.row_count],
  ["row_id",          r => r.id],
  ["run_id",          r => r.run_id],
  ["parent_run_id",   r => r.parent_run_id],
  ["created_at",      r => r.created_at],
  ["call_type",       r => r.call_type],
  ["provider",        r => r.provider],
  ["model_requested", r => r.model_requested],
  ["model_used",      r => r.model_used],
  ["latency_ms",      r => r.latency_ms],
  ["input_tokens",    r => r.input_tokens],
  ["output_tokens",   r => r.output_tokens],
  ["total_tokens",    r => r.total_tokens],
  ["success",         r => (r.success ? "true" : "false")],
  ["error_type",      r => r.error_type],
  ["error_message",   r => r.error_message],
  ["input",           r => r.input],
  ["output",          r => r.output],
]

// Row-level, one line per underlying llm_call_log row, carrying its group's
// trace_id so the result can be pivoted back up to the operation level.
// No UTF-8 BOM: it keeps the file clean RFC 4180 for scripted parsers. Excel
// may then need an explicit UTF-8 choice on import — prepend "﻿" here if
// Excel-by-doubleclick matters more than parser cleanliness.
function buildCsv(groups) {
  const lines = [CSV_COLUMNS.map(([name]) => csvCell(name)).join(",")]
  for (const g of groups) {
    for (const r of g.rows) {
      lines.push(CSV_COLUMNS.map(([, get]) => csvCell(get(r, g))).join(","))
    }
  }
  return lines.join("\r\n")
}

// ── Download plumbing ───────────────────────────────────────────────────────

const MIME = { md: "text/markdown", txt: "text/plain", csv: "text/csv" }

function safeSlug(s, max = 40) {
  return String(s || "").replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, max) || "export"
}

function downloadText(filename, text, ext) {
  const blob = new Blob([text], { type: `${MIME[ext] || "text/plain"};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Revoked on the next tick, not synchronously — revoking immediately can
  // cancel the download before the browser has read the blob.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

// ── Copy / download controls ────────────────────────────────────────────────

const ACTION_BTN =
  "flex items-center gap-1 px-2 py-1 rounded-md text-[11px] text-slate-400 " +
  "hover:text-slate-100 hover:bg-slate-800 border border-slate-700/60 transition-colors"

function DownloadIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 1a.75.75 0 0 1 .75.75v6.44l2.22-2.22a.75.75 0 1 1 1.06 1.06l-3.5 3.5a.75.75 0 0 1-1.06 0l-3.5-3.5a.75.75 0 0 1 1.06-1.06l2.22 2.22V1.75A.75.75 0 0 1 8 1Z" />
      <path d="M2.75 12a.75.75 0 0 0 0 1.5h10.5a.75.75 0 0 0 0-1.5H2.75Z" />
    </svg>
  )
}

// Same copy-then-flash behaviour as CopyButton, with a visible label. Kept
// separate rather than adding a `label` prop to CopyButton so the existing
// per-row Input/Output copy buttons are not touched at all.
function CopyTextButton({ getText, label = "Copy", title }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(getText()).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button onClick={handleCopy} title={title} className={ACTION_BTN}>
      <CopyIcon />
      {copied ? "Copied!" : label}
    </button>
  )
}

// ── Detail panel icons — reused verbatim from ChatMessage.jsx / InsightCard.jsx ──

function CopyIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z" />
      <path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z" />
    </svg>
  )
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button
      onClick={handleCopy}
      title="Copy"
      className="flex items-center gap-1 px-2 py-1 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors text-xs"
    >
      <CopyIcon />
      {copied && <span className="text-[10px]">Copied!</span>}
    </button>
  )
}

function ChevronIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
      <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
    </svg>
  )
}

function SearchIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="9" cy="9" r="6" />
      <path d="m17 17-4.35-4.35" strokeLinecap="round" />
    </svg>
  )
}

// Phase R — free-text search across every call's input/output, additive
// (ANDed) with every other active filter, narrowing the CURRENT filtered set
// rather than replacing it. Debounced 300ms, same pattern as
// GlobalSearch.jsx's search box — each query itself is cheap (~90-150ms on
// the live DB, see admin_service._build_where's Phase R comment) but firing
// one per keystroke while typing would still be wasteful.
function HeaderSearchBar({ value, onChange }) {
  const [draft, setDraft] = useState(value)
  const debounceRef = useRef(null)

  function handleChange(e) {
    const v = e.target.value
    setDraft(v)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => onChange(v), 300)
  }

  function handleClear() {
    clearTimeout(debounceRef.current)
    setDraft("")
    onChange("")
  }

  return (
    <div className="relative w-full sm:w-72">
      <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none">
        <SearchIcon />
      </span>
      <input
        type="text"
        value={draft}
        onChange={handleChange}
        placeholder="Search input & output…"
        className="w-full bg-slate-800/60 border border-slate-700/50 rounded-lg pl-8 pr-8 py-2 text-sm text-slate-300 outline-none focus:border-slate-600 transition-colors placeholder:text-slate-600"
      />
      {draft && (
        <button
          onClick={handleClear}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
          aria-label="Clear search"
        >
          <CloseIcon />
        </button>
      )}
    </div>
  )
}

// ── Detail panel — collapsible input/output block ───────────────────────────

const COLLAPSE_THRESHOLD = 500 // chars — see recon: input p90=30k, output p90=9.4k

function HighlightMatches({ text, query }) {
  if (!query || !text) return text
  const normalizedQuery = query.trim()
  if (!normalizedQuery) return text

  const escapedQuery = normalizedQuery.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  const parts = String(text).split(new RegExp(`(${escapedQuery})`, "gi"))
  return parts.map((part, index) =>
    part.toLowerCase() === normalizedQuery.toLowerCase()
      ? <mark key={index} className="bg-amber-300/80 text-slate-950 rounded-[2px] px-0.5">{part}</mark>
      : part
  )
}

function rowMatchesSearch(row, query) {
  const normalizedQuery = query?.trim().toLowerCase()
  if (!normalizedQuery) return false
  return [row.input, row.output].some(value =>
    String(value || "").toLowerCase().includes(normalizedQuery)
  )
}

function CollapsibleBlock({ label, text, query }) {
  const isLong = (text?.length || 0) > COLLAPSE_THRESHOLD
  const [expanded, setExpanded] = useState(!isLong)

  if (!text) {
    return (
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-1.5">{label}</p>
        <p className="text-xs text-slate-600 italic">empty</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <button
          onClick={() => setExpanded(e => !e)}
          className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-500 hover:text-slate-300 transition-colors"
        >
          <ChevronIcon className={`w-3 h-3 transition-transform ${expanded ? "rotate-180" : ""}`} />
          {label}
          <span className="text-slate-700 normal-case tracking-normal">({text.length.toLocaleString()} chars)</span>
        </button>
        <CopyButton text={text} />
      </div>
      {expanded && (
        <pre className="text-[11px] font-mono text-slate-300 whitespace-pre-wrap break-words bg-slate-950/60 border border-slate-800/60 rounded-lg p-3 max-h-96 overflow-y-auto">
          <HighlightMatches text={text} query={query} />
        </pre>
      )}
    </div>
  )
}

// ── Detail panel — sibling row ───────────────────────────────────────────────

function SiblingRow({ row, isActive, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left transition-colors border ${
        isActive ? "bg-blue-500/10 border-blue-500/30" : "border-transparent hover:bg-slate-800/50"
      }`}
    >
      <StatusBadge success={row.success} />
      <span className="flex-1 min-w-0 text-xs text-slate-300 truncate">{row.call_type || "—"}</span>
      <span className="text-[11px] text-slate-500 font-mono tabular-nums flex-shrink-0">{fmtMs(row.latency_ms)}</span>
    </button>
  )
}

// ── Detail panel — right-side slide-over ─────────────────────────────────────
// No slide-over precedent exists elsewhere in the app — matched the app's
// centered-modal conventions instead (click-outside via e.target check, X
// button style, border/rounded tokens), adapted for a right-edge panel that
// doesn't dim the filters/table behind it.

function DetailPanel({ row, surface, batch, batchLoading, search, onClose, onSelectSibling }) {
  useEffect(() => {
    function handleKey(e) { if (e.key === "Escape") onClose() }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [onClose])

  const siblings = batch ? [...(batch.root ? [batch.root] : []), ...batch.children] : []
  const showBatch = siblings.length > 1

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0" onClick={onClose} />
      <div
        onClick={e => e.stopPropagation()}
        className="absolute inset-y-0 right-0 w-full sm:w-[480px] bg-slate-900 border-l border-slate-700/60 shadow-2xl shadow-black/60 flex flex-col"
      >
        <div className="flex items-start justify-between px-5 py-4 border-b border-slate-800 flex-shrink-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <StatusBadge success={row.success} />
              <span className="text-sm font-semibold text-slate-100 truncate">{row.call_type || "—"}</span>
            </div>
            <p className="text-[11px] text-slate-500 font-mono tabular-nums">{formatTimestamp(row.created_at)}</p>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors flex-shrink-0">
            <CloseIcon />
          </button>
        </div>

        {/* Phase I — row-level copy/download. The two CollapsibleBlocks below
            keep their own separate Input / Output copy buttons unchanged. */}
        <div className="flex items-center gap-2 px-5 py-2.5 border-b border-slate-800/60 flex-shrink-0">
          <CopyTextButton
            getText={() => buildCombinedCopy(row)}
            label="Copy input + output"
            title={'Copies:\nINPUT: "..."\nOUTPUT: "..."'}
          />
          <button
            onClick={() => downloadText(
              `call-${row.id}-${safeSlug(row.call_type)}.md`,
              rowBlock(row, "md"),
              "md",
            )}
            title="Download this call as Markdown"
            className={ACTION_BTN}
          >
            <DownloadIcon />
            .md
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 px-5 py-3 border-b border-slate-800/60">
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-0.5">Provider / Model</p>
              <p className="text-xs text-slate-300 truncate">{formatModel(row)}</p>
            </div>
            {/* Phase O-Task2 */}
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-0.5">User</p>
              <p className={`text-xs truncate ${row.user_email ? "text-slate-300" : "text-slate-600 italic"}`}>
                {formatUsername(row.user_email, surface)}
              </p>
            </div>
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-0.5">Latency</p>
              <p className="text-xs text-slate-300 font-mono tabular-nums">{fmtMs(row.latency_ms)}</p>
            </div>
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-0.5">Tokens</p>
              <p className="text-xs text-slate-300 font-mono tabular-nums">{fmtTokens(row.total_tokens)}</p>
            </div>
          </div>

          {!row.success && (() => {
            const summary = summarizeError(row.error_type, row.error_message)
            return (
              <div className="mx-5 mt-4 bg-rose-500/[0.07] border border-rose-500/25 rounded-lg px-3 py-2.5">
                <p className="text-[9px] font-semibold uppercase tracking-widest text-rose-500/70 mb-1">
                  {row.error_type || "Error"}
                </p>
                {summary && (
                  <p className="text-sm font-semibold text-rose-200 mb-1.5">{summary}</p>
                )}
                <p className="text-xs text-rose-200/80 leading-relaxed whitespace-pre-wrap">
                  {row.error_message || "No error message recorded."}
                </p>
              </div>
            )
          })()}

          {batchLoading && <Skeleton className="h-16 mx-5 mt-4" />}
          {!batchLoading && showBatch && (
            <div className="px-5 pt-4">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
                Batch ({siblings.length} calls)
              </p>
              <div className="space-y-1">
                {siblings.map(s => (
                  <SiblingRow key={s.run_id} row={s} isActive={s.run_id === row.run_id} onClick={() => onSelectSibling(s)} />
                ))}
              </div>
            </div>
          )}

          <div className="px-5 py-4 space-y-4">
            <CollapsibleBlock label="Input" text={row.input} query={search} />
            <CollapsibleBlock label="Output" text={formatOutput(row.output)} query={search} />
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Sparkline (hand-rolled SVG — no chart library in this app) ─────────────
// Buckets come straight from GET /admin/calls/volume — a real SQL GROUP BY
// DATE() over the complete filtered set, no row cap. No accuracy caveat left.

// Phase H — Task 3 (fit): SPARK_W/SPARK_H used to be hardcoded 560x84 while
// the SVG rendered at `w-full h-[84px]` with preserveAspectRatio="none". Two
// real consequences: (a) the card is a grid item that stretches to match
// SurfaceBreakdown's height (~228px at 7 surfaces) while the chart stayed
// pinned at 84px, leaving the dead space below it; (b) any real width other
// than exactly 560px horizontally stretched the tick-label glyphs. Both are
// fixed by measuring the plot box and using its REAL pixel size as the
// viewBox, so the mapping is 1:1 and preserveAspectRatio is irrelevant.
const SPARK_PAD_X = 24, SPARK_PAD_TOP = 10, SPARK_PAD_BOTTOM = 22
const SPARK_MIN_H = 84

// Callback-ref based so it re-attaches when the measured node actually mounts
// — Sparkline returns a Skeleton while loading, so the plot div doesn't exist
// on the first render and a plain useRef would observe null forever.
function useElementSize(fallbackW, fallbackH) {
  const [node, setNode] = useState(null)
  const [size, setSize] = useState({ w: fallbackW, h: fallbackH })
  useEffect(() => {
    if (!node) return
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setSize({ w: Math.round(width), h: Math.round(height) })
    })
    ro.observe(node)
    return () => ro.disconnect()
  }, [node])
  return [setNode, size]
}

// Phase O — Task 1: granularity-aware. Hour buckets arrive as a full
// "YYYY-MM-DDTHH:00:00" the Date constructor parses natively; day/week/month
// buckets are a bare "YYYY-MM-DD" (week = that week's Monday, month = the
// 1st), same "T00:00:00" local-midnight anchor the day-only version used.
// `full` is for the hover tooltip, which always shows full real precision
// regardless of tick granularity (year always included; week/month spelled
// out unambiguously) — tick labels stay the compact, granularity-appropriate
// form the axis needs.
function formatTickDate(value, granularity, full = false) {
  const d = granularity === "hour" ? new Date(value) : new Date(`${value}T00:00:00`)
  if (isNaN(d.getTime())) return value

  if (granularity === "hour") {
    return d.toLocaleString("en-US", full
      ? { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }
      : { month: "short", day: "numeric", hour: "numeric" })
  }
  if (granularity === "month") {
    return d.toLocaleDateString("en-US", full ? { month: "long", year: "numeric" } : { month: "short", year: "numeric" })
  }
  const label = d.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(full ? { year: "numeric" } : {}) })
  return granularity === "week" && full ? `Week of ${label}` : label
}

// Always include first/last; add 1 intermediate tick at 5+ points, 2 at 8+.
function pickTickIndices(n) {
  if (n <= 2) return [...Array(n).keys()]
  if (n < 5) return [0, n - 1]
  if (n < 8) return [0, Math.round((n - 1) / 2), n - 1]
  return [0, Math.round((n - 1) / 3), Math.round(((n - 1) * 2) / 3), n - 1]
}

function clientToSvgPoint(svg, clientX, clientY) {
  const ctm = svg.getScreenCTM()
  if (!ctm) return null
  const pt = svg.createSVGPoint()
  pt.x = clientX
  pt.y = clientY
  return pt.matrixTransform(ctm.inverse())
}

function svgToWrapperPoint(svg, wrapperRect, x, y) {
  const ctm = svg.getScreenCTM()
  if (!ctm) return null
  const pt = svg.createSVGPoint()
  pt.x = x
  pt.y = y
  const screenPt = pt.matrixTransform(ctm)
  return { x: screenPt.x - wrapperRect.left, y: screenPt.y - wrapperRect.top }
}

function Sparkline({ byDay, granularity, loading }) {
  const svgRef = useRef(null)
  const wrapperRef = useRef(null)
  const [setPlotNode, { w: SPARK_W, h: SPARK_H }] = useElementSize(560, SPARK_MIN_H)
  const [hover, setHover] = useState(null) // { idx, x, y }

  const { points, days, coords, stepX } = useMemo(() => {
    const days = byDay.map(d => d.date)
    const points = byDay.map(d => d.count)
    if (!points.length) return { points, days, coords: [], stepX: 0 }

    const min = Math.min(...points)
    const max = Math.max(...points)
    const rawRange = max - min
    const pad = Math.max(rawRange * 0.15, 1)
    const domainMin = Math.max(0, min - pad)
    const domainMax = max + pad
    const range = domainMax - domainMin || 1

    const plotH = SPARK_H - SPARK_PAD_TOP - SPARK_PAD_BOTTOM
    const stepX = points.length > 1 ? (SPARK_W - SPARK_PAD_X * 2) / (points.length - 1) : 0
    const coords = points.map((v, i) => {
      const x = SPARK_PAD_X + i * stepX
      const y = SPARK_PAD_TOP + (1 - (v - domainMin) / range) * plotH
      return [x, y]
    })
    return { points, days, coords, stepX }
  }, [byDay, SPARK_W, SPARK_H])

  if (loading) return <Skeleton className="h-full min-h-[104px]" />

  if (!points.length) {
    return (
      <div className="h-full min-h-[104px] rounded-2xl bg-slate-900/60 border border-slate-800/50 flex items-center justify-center">
        <p className="text-xs text-slate-600">No calls in range</p>
      </div>
    )
  }

  function handleMouseMove(e) {
    const svg = svgRef.current, wrapper = wrapperRef.current
    if (!svg || !wrapper) return
    const svgPt = clientToSvgPoint(svg, e.clientX, e.clientY)
    if (!svgPt) return
    let idx = points.length > 1 ? Math.round((svgPt.x - SPARK_PAD_X) / stepX) : 0
    idx = Math.max(0, Math.min(points.length - 1, idx))
    const [dx, dy] = coords[idx]
    const rel = svgToWrapperPoint(svg, wrapper.getBoundingClientRect(), dx, dy)
    if (rel) setHover({ idx, ...rel })
  }

  const tickIndices = pickTickIndices(days.length)

  let linePath = "", areaPath = ""
  if (points.length > 1) {
    linePath = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ")
    areaPath = `${linePath} L${coords[coords.length - 1][0].toFixed(1)},${SPARK_H - SPARK_PAD_BOTTOM} L${SPARK_PAD_X},${SPARK_H - SPARK_PAD_BOTTOM} Z`
  }

  return (
    <div ref={wrapperRef} className="relative flex flex-col h-full rounded-2xl bg-slate-900/60 border border-slate-800/50 p-4">
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">Call Volume</p>
        <p className="text-[10px] text-slate-600 font-mono">{days[0]} → {days[days.length - 1]}</p>
      </div>
      {/* flex-1 makes this box absorb the card's real leftover height; the
          ResizeObserver above feeds that height straight back as the viewBox,
          so the plot fills the card at any size with no dead space. */}
      <div ref={setPlotNode} className="flex-1 min-h-[84px]">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
        width={SPARK_W}
        height={SPARK_H}
        className="block cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHover(null)}
      >
        {points.length > 1 ? (
          <>
            <path d={areaPath} fill="rgba(59,130,246,0.12)" />
            <path d={linePath} fill="none" stroke="#3b82f6" strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" />
          </>
        ) : (
          <circle cx={coords[0][0]} cy={coords[0][1]} r="2.5" fill="#3b82f6" />
        )}

        {hover && (
          <>
            <line
              x1={coords[hover.idx][0]} x2={coords[hover.idx][0]}
              y1={SPARK_PAD_TOP} y2={SPARK_H - SPARK_PAD_BOTTOM}
              stroke="rgba(255,255,255,0.18)" strokeWidth="1"
            />
            <circle cx={coords[hover.idx][0]} cy={coords[hover.idx][1]} r="3" fill="#3b82f6" stroke="#0f1117" strokeWidth="1.5" />
          </>
        )}

        {tickIndices.map(i => (
          <text
            key={i}
            x={coords[i][0]}
            y={SPARK_H - 6}
            textAnchor={i === 0 ? "start" : i === days.length - 1 ? "end" : "middle"}
            fill="#475569"
            fontSize="9"
            fontFamily="var(--font-mono)"
          >
            {formatTickDate(days[i], granularity)}
          </text>
        ))}
      </svg>
      </div>

      {hover && (
        <div
          className="pointer-events-none absolute z-10 bg-slate-800 border border-white/[0.08] text-slate-200 text-[11px] font-medium px-2.5 py-1.5 rounded-lg shadow-xl whitespace-nowrap"
          style={{ left: hover.x, top: hover.y, transform: "translate(-50%, -130%)" }}
        >
          <div className="font-mono">{formatTickDate(days[hover.idx], granularity, true)}</div>
          <div className="text-slate-400">{points[hover.idx]} call{points[hover.idx] !== 1 ? "s" : ""}</div>
        </div>
      )}
    </div>
  )
}

// ── Summary strip (Phase F) ─────────────────────────────────────────────────
// Replaces the old flat 6-tile row. Two real levels now exist and are kept
// visually distinct rather than conflated: OPERATION level (trace_id groups
// — "how many things happened", all_succeeded-based) from opSummary/
// get_operation_summary, and ROW level ("how many individual model calls" —
// includes retried/fallback legs) from summary/get_call_summary. Verified
// live these genuinely differ (2026-08-14, 30d window: operation success
// rate 39.9% vs row success rate 42.9% — not the same number renamed).

// Real CSS transition on value change, no animation library: flashes true
// for ~500ms right after `value` changes (by reference/primitive equality),
// caller applies a transition-driven highlight while it's true.
function useFlashOnChange(value) {
  const [flashing, setFlashing] = useState(false)
  const prev = useRef(value)
  useEffect(() => {
    if (prev.current === value) return
    prev.current = value
    setFlashing(true)
    const t = setTimeout(() => setFlashing(false), 500)
    return () => clearTimeout(t)
  }, [value])
  return flashing
}

function Tile({ value, label, sublabel, accent = "text-slate-200", loading }) {
  const flashing = useFlashOnChange(value)
  if (loading) return <Skeleton className="h-full min-h-[52px]" />
  return (
    <div className="px-3 sm:px-4 py-2.5 sm:py-3">
      <div
        className={`text-[17px] font-bold leading-none tabular-nums font-mono transition-colors duration-500 ${accent} ${flashing ? "text-white" : ""}`}
      >
        {value}
      </div>
      <div className="text-[10px] text-slate-600 mt-1 truncate">{label}</div>
      {sublabel && <div className="text-[10px] text-slate-700 mt-0.5 truncate">{sublabel}</div>}
    </div>
  )
}

// No historical SLO/baseline exists to calibrate against — these are
// deliberately conservative, round-number thresholds (my call, flagged as
// adjustable) rather than an unstated arbitrary color choice. Applied to
// OPERATION-level failure rate only, not row-level error count: row-level
// failures are expected to be noisy (see model_provider.py's retry/fallback
// legs — a healthy operation can still contain several failed rows before
// succeeding), so coloring the row-level number red would misrepresent
// healthy traffic as alarming.
function escalateColor(rate, { warn = 0.05, bad = 0.15 } = {}) {
  if (rate > bad) return "text-rose-400"
  if (rate > warn) return "text-amber-400"
  return "text-emerald-400"
}

function SummaryStrip({ summary, opSummary, loading, opLoading }) {
  const opFailRate = opSummary ? (opSummary.total_operations ? opSummary.failed_operations / opSummary.total_operations : 0) : 0

  const row1 = opSummary && [
    { value: opSummary.total_operations.toLocaleString(), label: "total operations", sublabel: "trace_id groups" },
    { value: (summary?.total_calls ?? 0).toLocaleString(), label: "total model calls", sublabel: "individual rows" },
    {
      value: `${Math.round(opSummary.operation_success_rate * 100)}%`, label: "success rate",
      sublabel: "per operation", accent: escalateColor(1 - opSummary.operation_success_rate),
    },
    {
      value: opSummary.failed_operations.toLocaleString(), label: "failed operations",
      sublabel: `${Math.round(opFailRate * 100)}% of ${opSummary.total_operations}`,
      accent: escalateColor(opFailRate),
    },
  ]

  const topErrors = summary?.by_error_type?.slice(0, 2) ?? []
  const row2 = summary && [
    { value: fmtNum(summary.total_tokens), label: "total tokens" },
    {
      // Phase J — Task 4: this site never called .toLocaleString() at all (no
      // grouping of any kind, not even locale-dependent) — a real gap beyond
      // the precondition's toLocaleString grep, fixed for the same reason.
      value: opSummary ? fmtMs(Math.round(opSummary.avg_latency_per_operation_ms)) : "—",
      label: "avg latency", sublabel: "per operation (sum of legs)",
    },
    {
      value: summary.error_count.toLocaleString(), label: "row-level errors",
      sublabel: topErrors.length ? topErrors.map(e => `${e.error_type} (${e.count})`).join(", ") : "none",
      accent: summary.error_count > 0 ? "text-slate-300" : "text-slate-500",
    },
  ]

  return (
    <div className="space-y-3">
      {/* Phase H — Task 2: the Today / 7 Days toggle that sat here is gone.
          FilterRail's Date Range dropdown is now the single source of truth
          for quick date selection, so this header is just a label again. */}
      <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">Overview</p>
      <div className="grid grid-cols-2 sm:grid-cols-4 rounded-2xl bg-slate-900/60 border border-slate-800/50 overflow-hidden divide-y sm:divide-y-0 sm:divide-x divide-slate-800/50">
        {(loading || opLoading || !row1) ? [0, 1, 2, 3].map(i => <Tile key={i} loading />) : row1.map((t, i) => <Tile key={i} {...t} />)}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 rounded-2xl bg-slate-900/60 border border-slate-800/50 overflow-hidden divide-y sm:divide-y-0 sm:divide-x divide-slate-800/50">
        {(loading || !row2) ? [0, 1, 2].map(i => <Tile key={i} loading />) : row2.map((t, i) => <Tile key={i} {...t} />)}
      </div>
    </div>
  )
}

// Row 3 — real breakdown by surface. Plain width-% bars, not the hand-rolled
// SVG Sparkline pattern: Sparkline's machinery (viewBox, coordinate mapping,
// hover-tracking) exists to plot a continuous line over time — a categorical
// breakdown (N discrete surfaces) doesn't need any of that, and a div-based
// bar list is the simpler "no new dependency" option for this shape of data.
function SurfaceBreakdown({ bySurface, loading }) {
  if (loading) return <Skeleton className="h-[120px]" />
  if (!bySurface || bySurface.length === 0) {
    return (
      <div className="h-[120px] rounded-2xl bg-slate-900/60 border border-slate-800/50 flex items-center justify-center">
        <p className="text-xs text-slate-600">No calls in range</p>
      </div>
    )
  }
  const max = Math.max(...bySurface.map(s => s.count))
  return (
    <div className="rounded-2xl bg-slate-900/60 border border-slate-800/50 p-4">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-500 mb-3">By Surface</p>
      <div className="space-y-2">
        {bySurface.map(s => (
          <div key={s.surface ?? "none"} className="flex items-center gap-3">
            <span className="w-20 sm:w-32 flex-shrink-0 text-[11px] text-slate-400 truncate">
              {ACTION_TYPE_LABELS[s.surface] || s.surface || "Unknown"}
            </span>
            <div className="flex-1 h-4 rounded bg-slate-800/60 overflow-hidden">
              <div
                className="h-full bg-blue-500/60 rounded transition-all duration-500"
                style={{ width: `${max ? (s.count / max) * 100 : 0}%` }}
              />
            </div>
            <span className="w-10 flex-shrink-0 text-right text-[11px] text-slate-400 font-mono tabular-nums">{s.count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Filter rail ───────────────────────────────────────────────────────────────
// Phase D: Action Type replaces Call Type as the main filter. feed_legacy and
// feed_v2 are kept as two SEPARATE options rather than merged into one "Daily
// Feed Generation" choice with a surface sub-toggle — the backend's action_type
// param is a single-valued exact match against `surface` (confirmed: B2's
// _build_group_where has no OR-across-surfaces path), so a merged option would
// need two separate /admin/calls/grouped requests interleaved client-side,
// which conflicts with "groups arrive pre-sorted/pre-paginated, no client-side
// re-merge." feed_v2 is also a genuinely distinct pipeline (real data: 15 rows
// today vs feed_legacy's 484) an admin would want to tell apart, not blend.
//
// D-recon-fix-2: 'intelligence_feed' (backend/services/intelligence_service.py
// + industry_intelligence_service.py — the older interests-based/industry-brief
// pipeline, no project_id, no day_ref) is its OWN option, not folded into
// "Daily Feed Generation (Legacy)" — same reasoning as feed_legacy/feed_v2
// above, plus it isn't even the same kind of "feed" (no project). Labeled
// "Intelligence Feed" (not "Recommendation Feed" or "Interest Feed") because
// it mirrors the surface value itself and covers BOTH real sub-pipelines
// tagged with it — the personalized /generate-feed AND the industry-brief
// path — where "Recommendation"/"Interest" only reads naturally for the former.
// Phase Q: 'chat_upload' (backend/services/document_extraction_service.py +
// main.py's /chat/upload, Phase P) placed next to 'chat' — same "chat
// surface family" grouping intelligence_feed/feed_legacy/feed_v2 already use
// for their own related pairs, and chat_upload is structurally closer to
// Chat than to the one-shot Explain/Translate/Read Aloud actions below it.
const ACTION_TYPE_OPTIONS = [
  { value: "",             label: "All Actions" },
  { value: "feed_legacy",  label: "Daily Feed Generation (Legacy)" },
  { value: "feed_v2",      label: "Daily Feed Generation (v2)" },
  { value: "intelligence_feed", label: "Intelligence Feed" },
  { value: "chat",         label: "Chat" },
  { value: "chat_upload",  label: "Chat Upload" },
  { value: "explain",      label: "Explain" },
  { value: "translate",    label: "Translate" },
  { value: "tts",          label: "Read Aloud" },
  { value: "web_search",   label: "Web Search" },
]

const FEED_ACTION_TYPES = new Set(["feed_legacy", "feed_v2"])

// ── Date range presets (Phase H — Task 2) ───────────────────────────────────
// Replaces SummaryStrip's Phase F Today / 7-Days toggle. Presets write into
// the SAME filters.dateFrom/dateTo the two date inputs already own — there is
// no parallel date state to reconcile, and both inputs stay freely editable
// after a preset is picked (editing one just makes the dropdown read "Custom
// range", since the active preset is DERIVED from the dates, never stored).

function toLocalDateStr(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

// Arithmetic on local calendar components rather than epoch-ms subtraction:
// DST-safe, so a 23h or 25h day still moves exactly one calendar day. (The
// old toggle used `Date.now() - 6*24*60*60*1000`, which drifts across a DST
// boundary.)
function addDays(d, n) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
}

function addMonths(d, n) {
  return new Date(d.getFullYear(), d.getMonth() + n, d.getDate())
}

// "Last Weekend" == the most recently COMPLETED Saturday–Sunday pair.
// Spelled out here so the definition can't be silently reinterpreted later:
// if today IS a Saturday or Sunday, that weekend is still in progress and
// does NOT count — the pair before it is returned.
//   getDay(): 0=Sun, 1=Mon, … 6=Sat
//   Mon–Fri (1–5): the last Sunday is `day` days back (Mon→1 … Fri→5), and
//                  that weekend is fully over.
//   Sat (6):       this weekend is in progress → last Sunday is 6 days back.
//   Sun (0):       this weekend is in progress → last Sunday is 7 days back.
// Saturday is always the day before that Sunday.
function lastCompletedWeekend(today) {
  const day = today.getDay()
  const backToSunday = day === 0 ? 7 : day === 6 ? 6 : day
  const sunday = addDays(today, -backToSunday)
  return { from: toLocalDateStr(addDays(sunday, -1)), to: toLocalDateStr(sunday) }
}

// Both ends inclusive. The N-day windows count today as day 1 (so "7 Days" is
// today plus the 6 days before it), matching the 7-Days toggle this replaces.
const DATE_PRESETS = [
  { value: "today",     label: "Today",        range: t => ({ from: toLocalDateStr(t), to: toLocalDateStr(t) }) },
  { value: "yesterday", label: "Yesterday",    range: t => { const y = addDays(t, -1); return { from: toLocalDateStr(y), to: toLocalDateStr(y) } } },
  { value: "lastwknd",  label: "Last Weekend", range: lastCompletedWeekend },
  { value: "7d",        label: "7 Days",       range: t => ({ from: toLocalDateStr(addDays(t, -6)),   to: toLocalDateStr(t) }) },
  { value: "30d",       label: "30 Days",      range: t => ({ from: toLocalDateStr(addDays(t, -29)),  to: toLocalDateStr(t) }) },
  { value: "90d",       label: "90 Days",      range: t => ({ from: toLocalDateStr(addDays(t, -89)),  to: toLocalDateStr(t) }) },
  { value: "6m",        label: "6 Months",     range: t => ({ from: toLocalDateStr(addMonths(t, -6)),  to: toLocalDateStr(t) }) },
  { value: "1y",        label: "1 Year",       range: t => ({ from: toLocalDateStr(addMonths(t, -12)), to: toLocalDateStr(t) }) },
]

// Phase H — Task 3 (default range): the page used to mount with no date
// filter at all, so every view defaulted to all-time (real result today:
// 2020-01-01 → 2026-08-14, a ~6.5-year window driven by seeded rows). That
// is not a useful default for an ops panel. The mount default is now a real
// preset, applied to filters.dateFrom/dateTo — NOT a chart-only default,
// which would desync the trend line from the tiles and the list beside it.
// 30 rather than the proposed 90: the sparkline plots one point per day into
// a ~560px-wide box, so 90 points lands at ~6px/point and reads as noise,
// while Phase F's own live verification window (see SummaryStrip's header
// comment) was 30d and had ample real volume. Change one constant to move it.
const DEFAULT_DATE_PRESET = "30d"

export function defaultDateRange(today = new Date()) {
  return DATE_PRESETS.find(p => p.value === DEFAULT_DATE_PRESET).range(today)
}

// Derived, never stored — so manually editing either date input correctly
// falls back to "Custom range" instead of leaving a stale preset selected.
function activePresetValue(filters, today) {
  const match = DATE_PRESETS.find(p => {
    const { from, to } = p.range(today)
    return filters.dateFrom === from && filters.dateTo === to
  })
  return match ? match.value : ""
}

// Mirrors backend/services/translate_service.py's ALLOWED_LANGUAGES — a fixed
// 4-value enum. NOT derived from real llm_call_log rows: only one real
// target_language value exists in the DB today (fr, from live testing), far
// short of the real set the backend actually accepts — a DB-derived dropdown
// would silently hide 3 valid languages nobody has translated into yet.
const TARGET_LANGUAGES = [
  { code: "hi", label: "Hindi" },
  { code: "gu", label: "Gujarati" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
]

// Phase G — Task 1: 8-9 stacked controls (Date From/To, Project, User,
// Status, Action Type, optional Day/Target Language sub-filter, Include
// test data) before a single result row is a real usability problem below
// lg, not just "technically doesn't overflow" — collapsed by default on
// phone/tablet, always fully visible at lg: (unchanged desktop behavior,
// the `lg:block` override ignores mobileOpen entirely at that breakpoint).
function FilterRail({ filters, onChange, projects, userOptions, includeTestData, onToggleTestData }) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const inputCls = "w-full bg-slate-800/60 border border-slate-700/50 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 outline-none focus:border-slate-600 transition-colors"
  const labelCls = "text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-1 block"

  const today = new Date()
  const activePreset = activePresetValue(filters, today)

  const activeCount = [
    filters.dateFrom, filters.dateTo, filters.projectId, filters.userId,
    filters.status, filters.actionType, filters.dayRef, filters.targetLanguage,
  ].filter(Boolean).length + (includeTestData ? 1 : 0)

  return (
    <div className="w-full lg:w-56 flex-shrink-0 lg:sticky lg:top-0">
      <button
        onClick={() => setMobileOpen(o => !o)}
        className="w-full lg:hidden flex items-center justify-between px-3 py-2 mb-3 rounded-lg bg-slate-900/60 border border-slate-800/50 text-xs font-medium text-slate-300"
      >
        <span className="flex items-center gap-2">
          Filters
          {activeCount > 0 && (
            <span className="inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-blue-500/20 text-blue-300 text-[10px] font-mono">
              {activeCount}
            </span>
          )}
        </span>
        <ChevronIcon className={`w-3.5 h-3.5 flex-shrink-0 text-slate-500 transition-transform ${mobileOpen ? "rotate-180" : ""}`} />
      </button>
      <div className={`${mobileOpen ? "block" : "hidden"} lg:block space-y-4`}>
      {/* Phase H — Task 2. Sits above the two date inputs it writes into.
          `today` is captured once per render so every preset in the list is
          evaluated against one consistent "now". */}
      <div>
        <label className={labelCls}>Date Range</label>
        <select
          value={activePreset}
          onChange={e => {
            const preset = DATE_PRESETS.find(p => p.value === e.target.value)
            if (!preset) return
            const { from, to } = preset.range(today)
            onChange({ ...filters, dateFrom: from, dateTo: to })
          }}
          className={inputCls}
        >
          {/* Phase J — Task 1: always present, not conditionally rendered —
              a dropdown option that only sometimes exists in its own list
              reads as broken, not as "hidden until relevant". Selecting it
              is already a no-op: value="" matches no DATE_PRESETS entry, so
              the onChange handler's `if (!preset) return` guard below already
              does nothing. It's a real, visible, permanently-listed item
              whose selected-state is a readout (see activePresetValue),
              never an instruction to change the dates. */}
          <option value="">Custom</option>
          {DATE_PRESETS.map(p => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>Date From</label>
        <input type="date" value={filters.dateFrom} onChange={e => onChange({ ...filters, dateFrom: e.target.value })} className={inputCls} />
      </div>
      <div>
        <label className={labelCls}>Date To</label>
        <input type="date" value={filters.dateTo} onChange={e => onChange({ ...filters, dateTo: e.target.value })} className={inputCls} />
      </div>
      <div>
        <label className={labelCls}>User</label>
        <select value={filters.userId} onChange={e => onChange({ ...filters, userId: e.target.value })} className={inputCls}>
          <option value="">All Users</option>
          {userOptions.map(u => (
            <option key={u.user_id} value={u.user_id}>{u.user_email || u.user_id}</option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>Project</label>
        <select value={filters.projectId} onChange={e => onChange({ ...filters, projectId: e.target.value })} className={inputCls}>
          <option value="">All Projects</option>
          {projects.map(p => (
            <option key={p.project_id} value={p.project_id}>{p.name}</option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>Action Type</label>
        <select
          value={filters.actionType}
          onChange={e => onChange({ ...filters, actionType: e.target.value, dayRef: "", targetLanguage: "" })}
          className={inputCls}
        >
          {ACTION_TYPE_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
      {/* Sub-filters, conditional on Action Type (design decision 4). Chat /
          Read Aloud / Web Search get none — no row rendered, not a disabled
          placeholder. Explain gets none either: it has no language concept
          at all (confirmed in backend/services/unpack_service.py — no param).
          Phase H — Task 1: these stay directly beneath Action Type, so Status
          moves BELOW them rather than between a parent and its own dependent
          controls. See report for this reading of the ordering spec. */}
      {FEED_ACTION_TYPES.has(filters.actionType) && (
        <div>
          <label className={labelCls}>Day</label>
          <input
            type="number" min="1" step="1" placeholder="Any day"
            value={filters.dayRef}
            onChange={e => onChange({ ...filters, dayRef: e.target.value })}
            className={inputCls}
          />
        </div>
      )}
      {filters.actionType === "translate" && (
        <div>
          <label className={labelCls}>Target Language</label>
          <select value={filters.targetLanguage} onChange={e => onChange({ ...filters, targetLanguage: e.target.value })} className={inputCls}>
            <option value="">All Languages</option>
            {TARGET_LANGUAGES.map(l => (
              <option key={l.code} value={l.code}>{l.label}</option>
            ))}
          </select>
        </div>
      )}
      <div>
        <label className={labelCls}>Status</label>
        <select value={filters.status} onChange={e => onChange({ ...filters, status: e.target.value })} className={inputCls}>
          <option value="">All</option>
          <option value="success">Success</option>
          <option value="failed">Failed</option>
        </select>
      </div>
      <label className="flex items-center gap-2 pt-1 cursor-pointer select-none">
        <input type="checkbox" checked={includeTestData} onChange={e => onToggleTestData(e.target.checked)}
          className="accent-blue-500 w-3.5 h-3.5" />
        <span className="text-xs text-slate-400">Include test data</span>
      </label>
      </div>
    </div>
  )
}

// ── Grouped calls list ──────────────────────────────────────────────────────
// Phase D: replaces the flat CallsTable. Groups are keyed by trace_id; a
// group with no trace_id (pre-Phase-3 historical row, or — per the Phase D
// precondition check — occasionally a fresh row too) is its own row_count=1
// singleton with no chevron (design decision 6). group.action_type mirrors
// group.surface (B2's response shape — 'web_search' is never a surface value,
// it only ever shows up as the has_web_search flag on whichever real surface
// the group belongs to).

const ACTION_TYPE_LABELS = {
  feed_legacy:       "Daily Feed (Legacy)",
  feed_v2:           "Daily Feed (v2)",
  intelligence_feed: "Intelligence Feed",
  chat:              "Chat",
  chat_upload:       "Chat Upload",
  explain:           "Explain",
  translate:         "Translate",
  tts:               "Read Aloud",
}

// Phase H — Task 4. An explicit CSS grid replaces the ad-hoc flex layout the
// three row shapes used. Adopted rather than a lighter fix because the
// requirement is a strict column ORDER held identical across three DIFFERENT
// row shapes (group header / singleton / nested), and Phase G's `flex-wrap`
// actively fights that: with wrapping, the same field lands in a different
// visual slot depending on how long its neighbours' text happened to be, so
// "Latency, Tokens, Status are always the last three" could not be guaranteed
// structurally — only coincidentally. Fixed tracks make the order a property
// of the layout instead of an emergent property of the content.
//
// Tracks: marker │ Timestamp │ User │ Action Type │ Detail │ Latency │ Tokens │ Status
// Phase J — Task 3: display (grid vs hidden) is now the CALLER's concern —
// every usage site pairs this with `hidden sm:grid` for the sm+ grid version,
// and a separate stacked-card renders `sm:hidden` beside it.
// Phase O-Task2 — 8th track (User) added between Timestamp and Action Type:
// paired with Timestamp as "who/when" context, distinct from Action/Detail's
// "what happened". Fixed 9rem width, truncated — same "full value one click
// away in DetailPanel" tradeoff every other track here already makes; emails
// in this DB run up to ~36 chars (real sample:
// onboard-test-1782991497@example.com), too wide to show in full without
// crowding Detail's flexible track.
const ROW_GRID =
  "grid-cols-[0.875rem_8.25rem_9rem_minmax(0,auto)_minmax(0,1fr)_4.25rem_3.25rem_3.25rem] items-center gap-2.5"

// Phase J — Task 3: below sm (640px), the 7-track grid abandoned entirely —
// horizontal scroll technically works but a phone user shouldn't have to
// swipe sideways to read one row. Three-line stacked card: (1) action
// identity + timestamp, (2) Detail content alone on its own line (room to
// NOT truncate the common case, unlike squeezed into a grid track), (3) a
// compact latency/tokens/status cluster. Same content as the grid row, same
// onClick — this is a layout fork, not a second data model.
function MobileRowCard({ marker, actionType, callType, hasWebSearch, timestamp, userEmail, surface, detail, latencyMs, tokens, success, onClick, indented, isSearchMatch }) {
  return (
    <button
      onClick={onClick}
      className={`sm:hidden w-full text-left px-3 py-3 transition-colors hover:bg-slate-800/40 ${
        isSearchMatch
          ? "bg-amber-400/[0.08] border-l-2 border-amber-300"
          : indented ? "bg-slate-950/40 border-t border-slate-800/20" : "border-b border-slate-800/40 last:border-0"
      }`}
    >
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <span className="flex items-center gap-1.5 min-w-0">
          {marker}
          {actionType
            ? <ActionTypeBadge actionType={actionType} />
            : <span className="text-[11px] text-slate-300 truncate">{callType || <span className="text-slate-600 italic">none</span>}</span>}
          {hasWebSearch && <WebSearchBadge />}
          {/* Phase L — Task 2: a singleton passes BOTH actionType (badge,
              above) and callType — restores the per-call label the badge
              alone doesn't carry, capped so it can't crowd out the badge on
              a narrow phone width. */}
          {actionType && callType && (
            <span className="text-[10px] text-slate-500 truncate max-w-[90px]">{callType}</span>
          )}
        </span>
        <span className="text-[10px] text-slate-500 font-mono tabular-nums flex-shrink-0">{formatTimestamp(timestamp)}</span>
      </div>
      {/* Phase O-Task2 — own line: emails are too wide to squeeze into the
          top row beside the action badge and timestamp without truncating
          both. */}
      <p className={`text-[10px] truncate mb-1 ${userEmail ? "text-slate-400" : "text-slate-600 italic"}`}>
        {formatUsername(userEmail, surface)}
      </p>
      <p className="text-[11px] text-slate-500 truncate mb-2">{detail}</p>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-slate-500 font-mono tabular-nums">{fmtMs(latencyMs)} · {fmtTokens(tokens)} tok</span>
        <StatusBadge success={success} />
      </div>
    </button>
  )
}

function ActionTypeBadge({ actionType }) {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-700/40 border border-slate-600/40 text-slate-300 whitespace-nowrap">
      {ACTION_TYPE_LABELS[actionType] || "Unknown"}
    </span>
  )
}

function WebSearchBadge() {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-sky-500/10 border border-sky-500/25 text-sky-400 whitespace-nowrap">
      Web Search
    </span>
  )
}

// A group's own rows (group.rows) are flat siblings sharing one trace_id —
// there is no deeper hierarchy inside a group. The parent_run_id-based
// "Batch" concept (SiblingRow/DetailPanel) is a different, narrower thing —
// retry-legs of ONE call — and still only surfaces inside a single row's own
// DetailPanel, unrelated to this outer grouping.
function GroupHeaderRow({ group, isExpanded, onToggle, onRowClick, search }) {
  const hasSearchMatch = group.rows.some(row => rowMatchesSearch(row, search))
  return (
    <div className="border-b border-slate-800/40 last:border-0">
      <button
        onClick={onToggle}
        className={`hidden sm:grid ${ROW_GRID} w-full px-3 py-2.5 text-left hover:bg-slate-800/40 transition-colors ${
          hasSearchMatch ? "bg-amber-400/[0.08] border-l-2 border-amber-300" : ""
        }`}
      >
        <ChevronIcon className={`w-3.5 h-3.5 text-slate-500 transition-transform ${isExpanded ? "rotate-180" : ""}`} />
        <span className="text-[11px] text-slate-400 font-mono tabular-nums truncate">{formatTimestamp(group.started_at)}</span>
        <span className={`text-[11px] truncate ${group.user_email ? "text-slate-300" : "text-slate-600 italic"}`}>
          {formatUsername(group.user_email, group.action_type)}
        </span>
        {/* Phase J — Task 2: has_web_search is a boolean flag, kept beside
            Action Type (its own track) rather than folded into Detail, which
            is for descriptive text now. */}
        <span className="flex items-center gap-1.5 min-w-0">
          <ActionTypeBadge actionType={group.action_type} />
          {group.has_web_search && <WebSearchBadge />}
        </span>
        {/* Detail for a group header: call count. A group can span several
            providers/models (Task 2's own reasoning) — "13 calls" is the
            meaningful summary, not any one leg's provider/model. */}
        <span className="text-[11px] text-slate-500 truncate">{group.row_count} calls</span>
        <span className="text-[11px] text-slate-400 font-mono tabular-nums text-right">{fmtMs(group.op_latency_ms)}</span>
        <span className="text-[11px] text-slate-400 font-mono tabular-nums text-right">{fmtTokens(group.op_tokens)}</span>
        <span className="justify-self-end"><StatusBadge success={group.all_succeeded} /></span>
      </button>
      {/* Phase J — Task 3: same data, stacked card, below sm only. Tapping
          the card toggles expand — same onClick as the grid header button. */}
      <MobileRowCard
        marker={<ChevronIcon className={`w-3.5 h-3.5 text-slate-500 transition-transform ${isExpanded ? "rotate-180" : ""}`} />}
        actionType={group.action_type}
        hasWebSearch={group.has_web_search}
        timestamp={group.started_at}
        userEmail={group.user_email}
        surface={group.action_type}
        detail={`${group.row_count} calls`}
        latencyMs={group.op_latency_ms}
        tokens={group.op_tokens}
        success={group.all_succeeded}
        onClick={onToggle}
        isSearchMatch={hasSearchMatch}
      />
      {isExpanded && (
        <div className="pb-1.5">
          {/* Phase I — group download lives INSIDE the expanded region, not in
              the header row: the header is itself a <button>, so a nested
              control would be invalid HTML and would fight the toggle click.
              This also leaves Phase H's 7-track column grid completely alone. */}
          <div className="flex items-center gap-2 px-3 py-2 bg-slate-950/60 border-t border-slate-800/40">
            <span className="text-[10px] uppercase tracking-widest text-slate-600">
              Download operation
            </span>
            {["md", "txt"].map(fmt => (
              <button
                key={fmt}
                onClick={() => downloadText(
                  `trace-${safeSlug(group.trace_id ?? `row-${group.rows[0]?.id}`, 20)}.${fmt}`,
                  buildGroupFile(group, fmt),
                  fmt,
                )}
                title={`Download all ${group.row_count} calls in this operation as .${fmt}`}
                className={ACTION_BTN}
              >
                <DownloadIcon />
                .{fmt}
              </button>
            ))}
          </div>
          {/* group.rows arrives in timestamp_start order straight from the
              backend — rendered as-is, no client-side re-sort.
              Nested rows reuse ROW_GRID unchanged rather than the old `pl-10`
              indent: indenting would push every field out of alignment with
              the header above it, which is the exact thing Task 4 asks for.
              Nesting is signalled by the tick in the marker track and the
              darker ground instead. */}
          {group.rows.map(row => (
            <div key={row.id}>
              {(() => {
                const isSearchMatch = rowMatchesSearch(row, search)
                return (
                  <>
                    <button
                onClick={() => onRowClick(row, group.action_type)}
                className={`hidden sm:grid ${ROW_GRID} w-full px-3 py-1.5 text-left hover:bg-slate-800/30 transition-colors border-t border-slate-800/20 first:border-0 ${
                  isSearchMatch ? "bg-amber-400/[0.08] border-l-2 border-amber-300" : "bg-slate-950/40"
                }`}
              >
                <span className="flex justify-center" aria-hidden="true">
                  <span className="w-1.5 h-px bg-slate-700" />
                </span>
                <span className="text-[11px] text-slate-500 font-mono tabular-nums truncate">{formatTimestamp(row.created_at)}</span>
                {/* Nested-row username: the row's own resolved email, but the
                    group's surface decides the fallback label — same reasoning
                    as call_type above not restating the group, applied in
                    reverse (surface classification IS shared across a group's
                    rows for this purpose). */}
                <span className={`text-[11px] truncate ${row.user_email ? "text-slate-400" : "text-slate-600 italic"}`}>
                  {formatUsername(row.user_email, group.action_type)}
                </span>
                {/* A nested row's own action is its call_type — repeating the
                    parent group's ActionTypeBadge on every child would just
                    restate the header. */}
                <span className="text-[11px] text-slate-300 truncate">
                  {row.call_type || <span className="text-slate-600 italic">none</span>}
                </span>
                <span className="text-[11px] text-slate-500 truncate">{formatModel(row)}</span>
                <span className="text-[11px] text-slate-500 font-mono tabular-nums text-right">{fmtMs(row.latency_ms)}</span>
                <span className="text-[11px] text-slate-500 font-mono tabular-nums text-right">{fmtTokens(row.total_tokens)}</span>
                <span className="justify-self-end"><StatusBadge success={row.success} /></span>
                  </button>
                  <MobileRowCard
                marker={<span className="w-1.5 h-px bg-slate-700" aria-hidden="true" />}
                callType={row.call_type}
                timestamp={row.created_at}
                userEmail={row.user_email}
                surface={group.action_type}
                detail={formatModel(row)}
                latencyMs={row.latency_ms}
                tokens={row.total_tokens}
                success={row.success}
                onClick={() => onRowClick(row, group.action_type)}
                indented
                isSearchMatch={isSearchMatch}
                    />
                  </>
                )
              })()}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// Singleton (row_count === 1): a plain row, no expand chevron — there's
// nothing to expand (design decision 6).
function SingletonRow({ group, onRowClick, search }) {
  const row = group.rows[0]
  return (
    <>
      <button
        onClick={() => onRowClick(row, group.action_type)}
        className={`hidden sm:grid ${ROW_GRID} w-full px-3 py-2.5 text-left hover:bg-slate-800/40 transition-colors border-b border-slate-800/40 last:border-0`}
      >
        <span aria-hidden="true" />
        <span className="text-[11px] text-slate-400 font-mono tabular-nums truncate">{formatTimestamp(group.started_at)}</span>
        <span className={`text-[11px] truncate ${row.user_email ? "text-slate-300" : "text-slate-600 italic"}`}>
          {formatUsername(row.user_email, group.action_type)}
        </span>
        <span className="flex items-center gap-1.5 min-w-0">
          <ActionTypeBadge actionType={group.action_type} />
          {group.has_web_search && <WebSearchBadge />}
          {/* Phase L — Task 2: call_type restored as a compact label beside
              Action Type, capped to max-w-[90px] so it can't grow the auto-
              sized Action Type track and squeeze Detail. Not a duplicate of
              Detail: this is WHICH call ("tinyfish_search"), Detail is WHAT
              answered it ("tinyfish" / "gemini / gemini-2.5-flash"). Full
              value was already one click away in DetailPanel regardless —
              this is a scan-speed restoration, not new information. */}
          <span className="text-[10px] text-slate-500 truncate max-w-[90px]">{row.call_type}</span>
        </span>
        {/* Phase J — Task 2: was call_type + formatModel crammed into one flex
            cell (the exact problem this task fixes). Detail here is purely
            "what actually answered this call": provider/model for an LLM row,
            the bare provider name for tool/service rows (formatModel already
            falls back to `row.provider` alone when there's no model_used/
            model_requested — confirmed real for tinyfish/deepl/deepgram rows). */}
        <span className="text-[11px] text-slate-500 truncate">{formatModel(row)}</span>
        {/* A singleton group is exactly one row, so the group's op_* sums and
            the row's own values are the same number — the row's own are used,
            being always present rather than nullable. */}
        <span className="text-[11px] text-slate-400 font-mono tabular-nums text-right">{fmtMs(row.latency_ms)}</span>
        <span className="text-[11px] text-slate-400 font-mono tabular-nums text-right">{fmtTokens(row.total_tokens)}</span>
        <span className="justify-self-end"><StatusBadge success={row.success} /></span>
      </button>
      <MobileRowCard
        marker={null}
        actionType={group.action_type}
        callType={row.call_type}
        hasWebSearch={group.has_web_search}
        timestamp={group.started_at}
        userEmail={row.user_email}
        surface={group.action_type}
        detail={formatModel(row)}
        latencyMs={row.latency_ms}
        tokens={row.total_tokens}
        success={row.success}
        onClick={() => onRowClick(row, group.action_type)}
      />
    </>
  )
}

// Phase Q — column keys below match admin_service.GROUP_SORT_COLUMNS's keys
// 1:1 so no frontend<->backend key translation table is needed. Detail has
// no backend column (it's a client-computed formatModel() string, not a
// group-level field) so it stays a plain, unsortable header.
function SortIcon({ direction }) {
  // Reuses ChevronIcon (already points down) rather than a new SVG —
  // rotate-180 for asc (points up), unrotated for desc (points down), same
  // rotate-on-state trick the expand chevron elsewhere on this page uses.
  return <ChevronIcon className={`w-2.5 h-2.5 transition-transform ${direction === "asc" ? "rotate-180" : ""}`} />
}

function SortableHeaderCell({ column, label, align, sortBy, sortOrder, onSort }) {
  const cell = "text-[9px] font-semibold uppercase tracking-widest text-slate-600"
  const isActive = sortBy === column
  return (
    <button
      onClick={() => onSort(column)}
      className={`${cell} flex items-center gap-0.5 hover:text-slate-300 transition-colors ${
        align === "right" ? "justify-end" : align === "end" ? "justify-self-end" : ""
      } ${isActive ? "text-slate-300" : ""}`}
    >
      {label}
      {isActive && <SortIcon direction={sortOrder} />}
    </button>
  )
}

// Column labels — with fixed tracks a header row is nearly free, and a bare
// "12,481" column with no heading isn't a Tokens column, it's a mystery number.
// Phase Q: Timestamp/User/Action/Latency/Tokens/Status are now real sort
// triggers (SortableHeaderCell), not static text — Detail stays static (see
// SORTABLE_COLUMNS's comment).
function ColumnHeader({ sortBy, sortOrder, onSort }) {
  const cell = "text-[9px] font-semibold uppercase tracking-widest text-slate-600"
  return (
    <div className={`hidden sm:grid ${ROW_GRID} px-3 py-2 border-b border-slate-800/60 bg-slate-950/40`}>
      <span aria-hidden="true" />
      <SortableHeaderCell column="timestamp" label="Timestamp" sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
      <SortableHeaderCell column="user" label="User" sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
      <SortableHeaderCell column="action" label="Action" sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
      <span className={cell}>Detail</span>
      <SortableHeaderCell column="latency" label="Latency" align="right" sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
      <SortableHeaderCell column="tokens" label="Tokens" align="right" sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
      <SortableHeaderCell column="status" label="Status" align="end" sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
    </div>
  )
}

function GroupedCallsList({ groups, loading, error, expandedKeys, onToggleGroup, onRowClick, search, sortBy, sortOrder, onSort }) {
  if (loading) return <Skeleton className="h-[420px]" />

  if (error) {
    return (
      <div className="h-[200px] rounded-2xl bg-slate-900/60 border border-slate-800/50 flex items-center justify-center">
        <p className="text-xs text-red-400">Couldn't load calls: {error}</p>
      </div>
    )
  }

  if (groups.length === 0) {
    return (
      <div className="h-[200px] rounded-2xl bg-slate-900/60 border border-slate-800/50 flex items-center justify-center">
        <p className="text-sm text-slate-500">No calls match these filters.</p>
      </div>
    )
  }

  // Phase Q: groups arrive pre-filtered, pre-sorted (by sortBy/sortOrder —
  // backend-parameterized now, previously a hardcoded started_at DESC),
  // pre-paginated by the backend — still no client-side re-sort/re-group here.
  return (
    <div className="rounded-2xl bg-slate-900/60 border border-slate-800/50 overflow-hidden">
      {/* Phase H — Task 4: seven real columns can't wrap and stay
          column-aligned, so the grid scrolls sideways as a unit instead of
          reflowing — the standard treatment for a dense admin table.
          Phase J — Task 3: that's now sm+ ONLY. Below sm, MobileRowCard
          (rendered inside each row component, `sm:hidden`) replaces the grid
          entirely — real stacked cards, not horizontal scroll on a phone.
          `sm:min-w-[700px]` (was an unconditional 680px) matches the grid's
          real content width post-Task-2 (Latency 4.5rem→4.25rem, Tokens
          4.5rem→3.25rem shrank it; Action Type can now also carry a
          WebSearchBadge, which grew it back some) and, critically, no longer
          forces ANY minimum width below sm — a bare `min-w-[680px]` here
          would silently force horizontal scroll under the cards too,
          undoing Task 3 for the exact width it targets. */}
      <div className="overflow-x-auto">
        <div className="sm:min-w-[700px]">
          <ColumnHeader sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
          {groups.map(g => {
            const key = g.trace_id ?? `row-${g.rows[0]?.id}`
            return g.row_count === 1
              ? <SingletonRow key={key} group={g} onRowClick={onRowClick} />
              : (
                <GroupHeaderRow
                  key={key}
                  group={g}
                  isExpanded={expandedKeys.has(key)}
                  onToggle={() => onToggleGroup(key)}
                  onRowClick={onRowClick}
                  search={search}
                />
              )
          })}
        </div>
      </div>
    </div>
  )
}

// Phase I — bulk export over the FULL filtered set, not the visible page.
// Fetches /admin/calls/export (unpaginated) at click time rather than reusing
// the already-loaded page: the loaded page is 20 groups, and an export capped
// at one page would defeat its own purpose. Fetching on click also keeps the
// ~16 MB worst-case payload out of memory until someone actually asks for it.
function BulkExport({ filters, dateToInclusive, includeTestData, total }) {
  const [fmt, setFmt] = useState("md")
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)

  async function handleExport() {
    setBusy(true)
    setNote(null)
    try {
      const data = await exportAdminCallsGrouped({
        dateFrom: filters.dateFrom, dateTo: dateToInclusive,
        projectId: filters.projectId, userId: filters.userId, includeTestData,
        status: filters.status, actionType: filters.actionType,
        dayRef: filters.dayRef || undefined,
        targetLanguage: filters.targetLanguage || undefined,
        search: filters.search || undefined,
      })
      const groups = data.groups
      const rowCount = groups.reduce((n, g) => n + g.rows.length, 0)
      const stamp = new Date().toISOString().slice(0, 10)
      downloadText(
        `llm-calls-${stamp}.${fmt}`,
        fmt === "csv" ? buildCsv(groups) : buildBulkFile(groups, fmt),
        fmt,
      )
      // Truncation is reported, never silent.
      setNote(data.truncated
        ? `⚠ Capped: exported ${data.returned.toLocaleString()} of ${data.total.toLocaleString()} operations. Narrow the filters to get the rest.`
        : `Exported ${groups.length.toLocaleString()} operations (${rowCount.toLocaleString()} rows).`)
    } catch (e) {
      setNote(`Export failed: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center flex-wrap gap-2">
      <span className="text-[10px] uppercase tracking-widest text-slate-600">
        Export all {total.toLocaleString()} filtered
      </span>
      <select
        value={fmt}
        onChange={e => setFmt(e.target.value)}
        className="bg-slate-800/60 border border-slate-700/50 rounded-lg px-2 py-1 text-[11px] text-slate-300 outline-none focus:border-slate-600"
      >
        <option value="md">Markdown (.md)</option>
        <option value="txt">Plain text (.txt)</option>
        <option value="csv">CSV (.csv)</option>
      </select>
      <button onClick={handleExport} disabled={busy || total === 0} className={`${ACTION_BTN} disabled:opacity-40 disabled:cursor-not-allowed`}>
        <DownloadIcon />
        {busy ? "Preparing…" : "Download"}
      </button>
      {note && <span className="text-[10px] text-slate-500">{note}</span>}
    </div>
  )
}

function Pagination({ offset, limit, total, onPageChange }) {
  if (total === 0) return null
  const from = offset + 1
  const to = Math.min(offset + limit, total)
  return (
    <div className="flex items-center justify-between mt-3">
      <p className="text-[11px] text-slate-600 font-mono">{from}–{to} of {total}</p>
      <div className="flex gap-2">
        <button
          disabled={offset === 0}
          onClick={() => onPageChange(Math.max(offset - limit, 0))}
          className="text-xs px-2.5 py-1 rounded-lg bg-slate-800/60 border border-slate-700/50 text-slate-400 disabled:opacity-40 disabled:cursor-not-allowed hover:text-slate-200 transition-colors"
        >
          Prev
        </button>
        <button
          disabled={offset + limit >= total}
          onClick={() => onPageChange(offset + limit)}
          className="text-xs px-2.5 py-1 rounded-lg bg-slate-800/60 border border-slate-700/50 text-slate-400 disabled:opacity-40 disabled:cursor-not-allowed hover:text-slate-200 transition-colors"
        >
          Next
        </button>
      </div>
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function AdminPage() {
  const [projects, setProjects] = useState([])
  const [projectsLoading, setProjectsLoading] = useState(true)

  // Phase H — Task 3: mounts on the real default preset window rather than
  // no date filter at all (which meant all-time). Lazy initializer so the
  // range is computed once, not on every render.
  const [filters, setFilters] = useState(() => {
    const { from, to } = defaultDateRange()
    return {
      dateFrom: from, dateTo: to, projectId: "", userId: "",
      status: "", actionType: "", dayRef: "", targetLanguage: "", search: "",
    }
  })
  const [includeTestData, setIncludeTestData] = useState(false)

  const [summary, setSummary] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(true)

  const [opSummary, setOpSummary] = useState(null)
  const [opSummaryLoading, setOpSummaryLoading] = useState(true)

  const [dailyVolume, setDailyVolume] = useState([])
  const [volumeGranularity, setVolumeGranularity] = useState("day")
  const [volumeLoading, setVolumeLoading] = useState(true)

  const [offset, setOffset] = useState(0)
  const [groups, setGroups] = useState([])
  const [groupsTotal, setGroupsTotal] = useState(0)
  const [groupsLoading, setGroupsLoading] = useState(true)
  const [groupsError, setGroupsError] = useState(null)
  const [expandedKeys, setExpandedKeys] = useState(() => new Set())

  // Phase Q — sortBy/sortOrder default to 'timestamp'/'desc': the OLD
  // hardcoded ORDER BY started_at DESC, so mounting with no interaction
  // renders identically to before this phase. Deliberately NOT reset by the
  // filter-change effect below (filters reset `offset`, not sort) — a user
  // who sorted by Tokens desc while scanning a wide date range, then narrows
  // to one project, almost certainly still wants Tokens desc on the
  // narrowed set, not to be silently dropped back to recency order.
  const [sortBy, setSortBy] = useState("timestamp")
  const [sortOrder, setSortOrder] = useState("desc")

  // Clicking the already-active column toggles direction; clicking a
  // different column starts it at 'desc' — one rule for all six columns
  // rather than a per-column "numeric defaults desc, text defaults asc"
  // table, which would be six special cases for one click behavior.
  // Changing sort re-pages to the top, same as a filter change, so the user
  // isn't looking at page 3 of a suddenly-different ordering.
  function handleSort(column) {
    if (sortBy === column) {
      setSortOrder(o => (o === "desc" ? "asc" : "desc"))
    } else {
      setSortBy(column)
      setSortOrder("desc")
    }
    setOffset(0)
  }

  const [selectedRow, setSelectedRow] = useState(null)
  // Phase O-Task2 — surface for the DetailPanel username's fallback label.
  // Not on the row object itself (_ROW_COLUMNS has no surface column, and
  // batch siblings from getAdminCallTree don't carry one either) — tracked
  // separately, set once when the panel opens and left alone by sibling
  // switches below, since retry-legs of one call always share one surface.
  const [selectedRowSurface, setSelectedRowSurface] = useState(null)
  const [batch, setBatch] = useState(null)
  const [batchLoading, setBatchLoading] = useState(false)

  function handleToggleGroup(key) {
    setExpandedKeys(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Opening a row (from a singleton, or from inside an expanded group):
  // fetch the batch (siblings share row.parent_run_id — real data confirms no
  // row is ever both a parent and a child, so a row's own run_id never has
  // children; the group is found via its parent_run_id instead). This is the
  // narrower parent_run_id "Batch" concept — unrelated to trace_id grouping.
  function handleOpenRow(row, surface) {
    setSelectedRow(row)
    setSelectedRowSurface(surface)
    if (!row.parent_run_id) { setBatch(null); return }
    setBatchLoading(true)
    getAdminCallTree(row.parent_run_id)
      .then(setBatch)
      .catch(() => setBatch(null))
      .finally(() => setBatchLoading(false))
  }

  // Switching to a sibling already-loaded in `batch` — no refetch needed.
  function handleSelectSibling(row) {
    setSelectedRow(row)
  }

  function handleClosePanel() {
    setSelectedRow(null)
    setSelectedRowSurface(null)
    setBatch(null)
  }

  const dateToInclusive = filters.dateTo ? `${filters.dateTo} 23:59:59` : undefined

  // Projects list — for filter dropdowns. Fetched once.
  useEffect(() => {
    listAdminProjects()
      .then(d => setProjects(d.projects))
      .catch(() => setProjects([]))
      .finally(() => setProjectsLoading(false))
  }, [])

  const userOptions = useMemo(() => {
    const seen = new Map()
    projects.forEach(p => { if (p.user_id && !seen.has(p.user_id)) seen.set(p.user_id, p) })
    return [...seen.values()]
  }, [projects])

  // Summary + operation summary + daily volume — refetch whenever filters
  // (not pagination) change.
  useEffect(() => {
    setSummaryLoading(true)
    getAdminSummary({
      dateFrom: filters.dateFrom, dateTo: dateToInclusive, includeTestData,
      projectId: filters.projectId, userId: filters.userId,
      status: filters.status, actionType: filters.actionType,
      dayRef: filters.dayRef || undefined, targetLanguage: filters.targetLanguage || undefined,
      search: filters.search || undefined,
    })
      .then(setSummary).catch(() => setSummary(null))
      .finally(() => setSummaryLoading(false))

    // Phase F — group-level (trace_id/operation) counterpart, same filters.
    setOpSummaryLoading(true)
    getAdminOperationSummary({
      dateFrom: filters.dateFrom, dateTo: dateToInclusive,
      projectId: filters.projectId, userId: filters.userId, includeTestData,
      status: filters.status, actionType: filters.actionType,
      dayRef: filters.dayRef || undefined, targetLanguage: filters.targetLanguage || undefined,
      search: filters.search || undefined,
    })
      .then(setOpSummary).catch(() => setOpSummary(null))
      .finally(() => setOpSummaryLoading(false))

    // Phase F: /admin/calls/volume now honors status/action_type/day_ref/
    // target_language too (previously only date/project/user/test-data) —
    // the trend line used to silently ignore the Action Type filter.
    setVolumeLoading(true)
    getAdminCallVolume({
      dateFrom: filters.dateFrom, dateTo: dateToInclusive,
      projectId: filters.projectId, userId: filters.userId, includeTestData,
      status: filters.status, actionType: filters.actionType,
      dayRef: filters.dayRef || undefined, targetLanguage: filters.targetLanguage || undefined,
      search: filters.search || undefined,
    })
      .then(d => { setDailyVolume(d.by_day); setVolumeGranularity(d.granularity) })
      .catch(() => { setDailyVolume([]); setVolumeGranularity("day") })
      .finally(() => setVolumeLoading(false))

    setOffset(0)
    setExpandedKeys(new Set())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    filters.dateFrom, filters.dateTo, filters.projectId, filters.userId,
    filters.status, filters.actionType, filters.dayRef, filters.targetLanguage,
    filters.search, includeTestData,
  ])

  // Grouped calls page — refetch on filters or pagination change. Groups, not
  // rows: `limit`/`offset` here page GROUPS (GROUP_PAGE_SIZE), matching what
  // /admin/calls/grouped itself paginates.
  useEffect(() => {
    setGroupsLoading(true)
    setGroupsError(null)
    listAdminCallsGrouped({
      dateFrom: filters.dateFrom, dateTo: dateToInclusive,
      projectId: filters.projectId, userId: filters.userId, includeTestData,
      status: filters.status, actionType: filters.actionType,
      dayRef: filters.dayRef || undefined, targetLanguage: filters.targetLanguage || undefined,
      search: filters.search || undefined,
      limit: GROUP_PAGE_SIZE, offset, sortBy, sortOrder,
    })
      .then(d => { setGroups(d.groups); setGroupsTotal(d.total) })
      .catch(e => { setGroups([]); setGroupsTotal(0); setGroupsError(e.message) })
      .finally(() => setGroupsLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    filters.dateFrom, filters.dateTo, filters.projectId, filters.userId,
    filters.status, filters.actionType, filters.dayRef, filters.targetLanguage,
    filters.search, includeTestData, offset, sortBy, sortOrder,
  ])

  return (
    <div>
      <div className="mb-6 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Admin</h1>
          <p className="text-sm text-slate-500 mt-1">Every LLM call across Feed & Chat</p>
        </div>
        <HeaderSearchBar
          value={filters.search}
          onChange={search => setFilters(f => ({ ...f, search }))}
        />
      </div>

      <div className="flex flex-col lg:flex-row gap-5 items-start">
        <FilterRail
          filters={filters}
          onChange={setFilters}
          projects={projectsLoading ? [] : projects}
          userOptions={userOptions}
          includeTestData={includeTestData}
          onToggleTestData={setIncludeTestData}
        />

        <div className="flex-1 min-w-0 space-y-5">
          <SummaryStrip
            summary={summary} opSummary={opSummary}
            loading={summaryLoading} opLoading={opSummaryLoading}
          />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Sparkline byDay={dailyVolume} granularity={volumeGranularity} loading={volumeLoading} />
            <SurfaceBreakdown bySurface={summary?.by_surface} loading={summaryLoading} />
          </div>
          <BulkExport
            filters={filters}
            dateToInclusive={dateToInclusive}
            includeTestData={includeTestData}
            total={groupsTotal}
          />
          <GroupedCallsList
            groups={groups}
            loading={groupsLoading}
            error={groupsError}
            expandedKeys={expandedKeys}
            onToggleGroup={handleToggleGroup}
            onRowClick={handleOpenRow}
            search={filters.search}
            sortBy={sortBy}
            sortOrder={sortOrder}
            onSort={handleSort}
          />
          <Pagination offset={offset} limit={GROUP_PAGE_SIZE} total={groupsTotal} onPageChange={setOffset} />
        </div>
      </div>

      {selectedRow && (
        <DetailPanel
          row={selectedRow}
          surface={selectedRowSurface}
          batch={batch}
          batchLoading={batchLoading}
          search={filters.search}
          onClose={handleClosePanel}
          onSelectSibling={handleSelectSibling}
        />
      )}
    </div>
  )
}

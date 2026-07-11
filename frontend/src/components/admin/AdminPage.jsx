import { useState, useEffect, useMemo, useCallback, useRef } from "react"
import { listAdminProjects, listAdminCalls, getAdminSummary, getAdminCallVolume, getAdminCallTree } from "../../api/admin.js"

const PAGE_SIZE = 20

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

// ── Detail panel — collapsible input/output block ───────────────────────────

const COLLAPSE_THRESHOLD = 500 // chars — see recon: input p90=30k, output p90=9.4k

function CollapsibleBlock({ label, text }) {
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
          {text}
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
      <span className="text-[11px] text-slate-500 font-mono tabular-nums flex-shrink-0">{row.latency_ms.toLocaleString()}ms</span>
    </button>
  )
}

// ── Detail panel — right-side slide-over ─────────────────────────────────────
// No slide-over precedent exists elsewhere in the app — matched the app's
// centered-modal conventions instead (click-outside via e.target check, X
// button style, border/rounded tokens), adapted for a right-edge panel that
// doesn't dim the filters/table behind it.

function DetailPanel({ row, batch, batchLoading, onClose, onSelectSibling }) {
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

        <div className="flex-1 overflow-y-auto">
          <div className="grid grid-cols-3 gap-3 px-5 py-3 border-b border-slate-800/60">
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-0.5">Provider / Model</p>
              <p className="text-xs text-slate-300 truncate">{formatModel(row)}</p>
            </div>
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-0.5">Latency</p>
              <p className="text-xs text-slate-300 font-mono tabular-nums">{row.latency_ms.toLocaleString()}ms</p>
            </div>
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-0.5">Tokens</p>
              <p className="text-xs text-slate-300 font-mono tabular-nums">{row.total_tokens != null ? row.total_tokens.toLocaleString() : "—"}</p>
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
            <CollapsibleBlock label="Input" text={row.input} />
            <CollapsibleBlock label="Output" text={row.output} />
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Sparkline (hand-rolled SVG — no chart library in this app) ─────────────
// Buckets come straight from GET /admin/calls/volume — a real SQL GROUP BY
// DATE() over the complete filtered set, no row cap. No accuracy caveat left.

const SPARK_W = 560, SPARK_H = 84
const SPARK_PAD_X = 24, SPARK_PAD_TOP = 10, SPARK_PAD_BOTTOM = 22
const SPARK_PLOT_H = SPARK_H - SPARK_PAD_TOP - SPARK_PAD_BOTTOM

function formatTickDate(iso) {
  const d = new Date(`${iso}T00:00:00`)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
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

function Sparkline({ byDay, loading }) {
  const svgRef = useRef(null)
  const wrapperRef = useRef(null)
  const [hover, setHover] = useState(null) // { idx, x, y }

  const { points, days, coords, stepX, domainMin, domainMax } = useMemo(() => {
    const days = byDay.map(d => d.date)
    const points = byDay.map(d => d.count)
    if (!points.length) return { points, days, coords: [], stepX: 0, domainMin: 0, domainMax: 1 }

    const min = Math.min(...points)
    const max = Math.max(...points)
    const rawRange = max - min
    const pad = Math.max(rawRange * 0.15, 1)
    const domainMin = Math.max(0, min - pad)
    const domainMax = max + pad
    const range = domainMax - domainMin || 1

    const stepX = points.length > 1 ? (SPARK_W - SPARK_PAD_X * 2) / (points.length - 1) : 0
    const coords = points.map((v, i) => {
      const x = SPARK_PAD_X + i * stepX
      const y = SPARK_PAD_TOP + (1 - (v - domainMin) / range) * SPARK_PLOT_H
      return [x, y]
    })
    return { points, days, coords, stepX, domainMin, domainMax }
  }, [byDay])

  if (loading) return <Skeleton className="h-[104px]" />

  if (!points.length) {
    return (
      <div className="h-[104px] rounded-2xl bg-slate-900/60 border border-slate-800/50 flex items-center justify-center">
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
    <div ref={wrapperRef} className="relative rounded-2xl bg-slate-900/60 border border-slate-800/50 p-4">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">Call Volume</p>
        <p className="text-[10px] text-slate-600 font-mono">{days[0]} → {days[days.length - 1]}</p>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
        className="w-full h-[84px] cursor-crosshair"
        preserveAspectRatio="none"
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
            {formatTickDate(days[i])}
          </text>
        ))}
      </svg>

      {hover && (
        <div
          className="pointer-events-none absolute z-10 bg-slate-800 border border-white/[0.08] text-slate-200 text-[11px] font-medium px-2.5 py-1.5 rounded-lg shadow-xl whitespace-nowrap"
          style={{ left: hover.x, top: hover.y, transform: "translate(-50%, -130%)" }}
        >
          <div className="font-mono">{formatTickDate(days[hover.idx])}</div>
          <div className="text-slate-400">{points[hover.idx]} call{points[hover.idx] !== 1 ? "s" : ""}</div>
        </div>
      )}
    </div>
  )
}

// ── Summary strip ────────────────────────────────────────────────────────────

function SummaryStrip({ summary, loading }) {
  if (loading) return <Skeleton className="h-[60px]" />
  if (!summary) return null

  const { total_calls, success_count, error_count, success_rate, total_tokens, avg_latency_ms } = summary
  const tiles = [
    { value: total_calls, label: "total calls", accent: "text-slate-200" },
    { value: success_count, label: "success", accent: "text-emerald-400" },
    { value: error_count, label: "errors", accent: error_count > 0 ? "text-rose-400" : "text-slate-500" },
    { value: `${Math.round(success_rate * 100)}%`, label: "success rate", accent: "text-slate-200" },
    { value: total_tokens.toLocaleString(), label: "total tokens", accent: "text-slate-200" },
    { value: `${Math.round(avg_latency_ms)}ms`, label: "avg latency", accent: "text-slate-200" },
  ]

  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 rounded-2xl bg-slate-900/60 border border-slate-800/50 overflow-hidden divide-y sm:divide-y-0 sm:divide-x divide-slate-800/50">
      {tiles.map((t, i) => (
        <div key={i} className="px-3 sm:px-4 py-2.5 sm:py-3">
          <div className={`text-[17px] font-bold leading-none tabular-nums font-mono ${t.accent}`}>{t.value}</div>
          <div className="text-[10px] text-slate-600 mt-1 whitespace-nowrap">{t.label}</div>
        </div>
      ))}
    </div>
  )
}

// ── Filter rail ───────────────────────────────────────────────────────────────

function FilterRail({ filters, onChange, projects, userOptions, callTypeOptions, includeTestData, onToggleTestData }) {
  const inputCls = "w-full bg-slate-800/60 border border-slate-700/50 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 outline-none focus:border-slate-600 transition-colors"
  const labelCls = "text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-1 block"

  return (
    <div className="w-full lg:w-56 flex-shrink-0 space-y-4 lg:sticky lg:top-0">
      <div>
        <label className={labelCls}>Date From</label>
        <input type="date" value={filters.dateFrom} onChange={e => onChange({ ...filters, dateFrom: e.target.value })} className={inputCls} />
      </div>
      <div>
        <label className={labelCls}>Date To</label>
        <input type="date" value={filters.dateTo} onChange={e => onChange({ ...filters, dateTo: e.target.value })} className={inputCls} />
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
        <label className={labelCls}>User</label>
        <select value={filters.userId} onChange={e => onChange({ ...filters, userId: e.target.value })} className={inputCls}>
          <option value="">All Users</option>
          {userOptions.map(u => (
            <option key={u.user_id} value={u.user_id}>{u.user_email || u.user_id}</option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>Call Type</label>
        <select value={filters.callType} onChange={e => onChange({ ...filters, callType: e.target.value })} className={inputCls}>
          <option value="">All Types</option>
          {callTypeOptions.map(ct => (
            <option key={ct} value={ct}>{ct}</option>
          ))}
        </select>
      </div>
      <label className="flex items-center gap-2 pt-1 cursor-pointer select-none">
        <input type="checkbox" checked={includeTestData} onChange={e => onToggleTestData(e.target.checked)}
          className="accent-blue-500 w-3.5 h-3.5" />
        <span className="text-xs text-slate-400">Include test data</span>
      </label>
    </div>
  )
}

// ── Calls table ───────────────────────────────────────────────────────────────

const COLUMNS = [
  { key: "created_at",    label: "Timestamp" },
  { key: "call_type",     label: "Call Type" },
  { key: "provider",      label: "Provider / Model" },
  { key: "latency_ms",    label: "Latency" },
  { key: "total_tokens",  label: "Tokens" },
  { key: "success",       label: "Status" },
]

function CallsTable({ rows, loading, error, sortKey, sortDir, onSort, onRowClick }) {
  if (loading) return <Skeleton className="h-[420px]" />

  if (error) {
    return (
      <div className="h-[200px] rounded-2xl bg-slate-900/60 border border-slate-800/50 flex items-center justify-center">
        <p className="text-xs text-red-400">Couldn't load calls: {error}</p>
      </div>
    )
  }

  if (rows.length === 0) {
    return (
      <div className="h-[200px] rounded-2xl bg-slate-900/60 border border-slate-800/50 flex items-center justify-center">
        <p className="text-sm text-slate-500">No calls match these filters.</p>
      </div>
    )
  }

  // rows arrive pre-sorted by the backend (real SQL ORDER BY over the full
  // filtered set, applied before pagination) — no client-side re-sort here.
  return (
    <div className="rounded-2xl bg-slate-900/60 border border-slate-800/50 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-800/60">
              {COLUMNS.map(col => (
                <th key={col.key}
                  onClick={() => onSort(col.key)}
                  className="px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-slate-500 cursor-pointer hover:text-slate-300 transition-colors select-none whitespace-nowrap"
                >
                  {col.label}{sortKey === col.key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} onClick={() => onRowClick(r)} className="border-b border-slate-800/40 last:border-0 hover:bg-slate-800/40 transition-colors cursor-pointer">
                <td className="px-3 py-2 text-[11px] text-slate-400 font-mono tabular-nums whitespace-nowrap">{formatTimestamp(r.created_at)}</td>
                <td className="px-3 py-2 text-[11px] text-slate-300 whitespace-nowrap">{r.call_type || <span className="text-slate-600 italic">none</span>}</td>
                <td className="px-3 py-2 text-[11px] text-slate-400 whitespace-nowrap">{formatModel(r)}</td>
                <td className="px-3 py-2 text-[11px] text-slate-400 font-mono tabular-nums whitespace-nowrap">{r.latency_ms.toLocaleString()}ms</td>
                <td className="px-3 py-2 text-[11px] text-slate-400 font-mono tabular-nums whitespace-nowrap">{r.total_tokens != null ? r.total_tokens.toLocaleString() : "—"}</td>
                <td className="px-3 py-2 whitespace-nowrap"><StatusBadge success={r.success} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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

  const [filters, setFilters] = useState({ dateFrom: "", dateTo: "", projectId: "", userId: "", callType: "" })
  const [includeTestData, setIncludeTestData] = useState(false)

  const [summary, setSummary] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(true)

  const [dailyVolume, setDailyVolume] = useState([])
  const [volumeLoading, setVolumeLoading] = useState(true)

  const [offset, setOffset] = useState(0)
  const [calls, setCalls] = useState([])
  const [callsTotal, setCallsTotal] = useState(0)
  const [callsLoading, setCallsLoading] = useState(true)
  const [callsError, setCallsError] = useState(null)

  const [sortKey, setSortKey] = useState("created_at")
  const [sortDir, setSortDir] = useState("desc")

  const [selectedRow, setSelectedRow] = useState(null)
  const [batch, setBatch] = useState(null)
  const [batchLoading, setBatchLoading] = useState(false)

  function handleSort(key) {
    if (key === sortKey) setSortDir(d => (d === "asc" ? "desc" : "asc"))
    else { setSortKey(key); setSortDir("desc") }
    setOffset(0)
  }

  // Opening from the table: fetch the batch (siblings share row.parent_run_id —
  // real data confirms no row is ever both a parent and a child, so a row's own
  // run_id never has children; the group is found via its parent_run_id instead).
  function handleOpenRow(row) {
    setSelectedRow(row)
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

  // Summary + daily volume — refetch whenever filters (not pagination/sort) change.
  useEffect(() => {
    setSummaryLoading(true)
    getAdminSummary({ dateFrom: filters.dateFrom, dateTo: dateToInclusive, includeTestData })
      .then(setSummary).catch(() => setSummary(null))
      .finally(() => setSummaryLoading(false))

    setVolumeLoading(true)
    getAdminCallVolume({
      dateFrom: filters.dateFrom, dateTo: dateToInclusive, callType: filters.callType,
      projectId: filters.projectId, userId: filters.userId, includeTestData,
    })
      .then(d => setDailyVolume(d.by_day))
      .catch(() => setDailyVolume([]))
      .finally(() => setVolumeLoading(false))

    setOffset(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.dateFrom, filters.dateTo, filters.projectId, filters.userId, filters.callType, includeTestData])

  // Calls page — refetch on filters, pagination, or sort change.
  useEffect(() => {
    setCallsLoading(true)
    setCallsError(null)
    listAdminCalls({
      dateFrom: filters.dateFrom, dateTo: dateToInclusive, callType: filters.callType,
      projectId: filters.projectId, userId: filters.userId, includeTestData,
      limit: PAGE_SIZE, offset,
      sortBy: sortKey, sortOrder: sortDir,
    })
      .then(d => { setCalls(d.rows); setCallsTotal(d.total) })
      .catch(e => { setCalls([]); setCallsTotal(0); setCallsError(e.message) })
      .finally(() => setCallsLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.dateFrom, filters.dateTo, filters.projectId, filters.userId, filters.callType, includeTestData, offset, sortKey, sortDir])

  const callTypeOptions = useMemo(
    () => (summary?.by_call_type ?? []).map(x => x.call_type).filter(Boolean),
    [summary]
  )

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Admin</h1>
        <p className="text-sm text-slate-500 mt-1">Every LLM call across Feed & Chat</p>
      </div>

      <div className="flex flex-col lg:flex-row gap-5 items-start">
        <FilterRail
          filters={filters}
          onChange={setFilters}
          projects={projectsLoading ? [] : projects}
          userOptions={userOptions}
          callTypeOptions={callTypeOptions}
          includeTestData={includeTestData}
          onToggleTestData={setIncludeTestData}
        />

        <div className="flex-1 min-w-0 space-y-5">
          <SummaryStrip summary={summary} loading={summaryLoading} />
          <Sparkline byDay={dailyVolume} loading={volumeLoading} />
          <CallsTable
            rows={calls}
            loading={callsLoading}
            error={callsError}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={handleSort}
            onRowClick={handleOpenRow}
          />
          <Pagination offset={offset} limit={PAGE_SIZE} total={callsTotal} onPageChange={setOffset} />
        </div>
      </div>

      {selectedRow && (
        <DetailPanel
          row={selectedRow}
          batch={batch}
          batchLoading={batchLoading}
          onClose={handleClosePanel}
          onSelectSibling={handleSelectSibling}
        />
      )}
    </div>
  )
}

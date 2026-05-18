/**
 * ResearchWorkspace — autonomous AI research workspace.
 *
 * On topic submit, fires three parallel requests:
 *   1. /topic-expansion  → TopicGraph
 *   2. /deep-research    → DeepDivePanel
 *   3. /learning-path    → LearningPathPanel + RepoGrid
 *
 * After /learning-path resolves, extracts all resource strings and calls
 *   4. /categorize       → ResourceCatalog
 *
 * Session memory context is also fetched to show exploration history.
 */

import { useCallback, useRef, useState } from "react"
import DeepDivePanel from "./DeepDivePanel.jsx"
import LearningPathPanel from "./LearningPathPanel.jsx"
import RepoGrid from "./RepoGrid.jsx"
import ResourceCatalog from "./ResourceCatalog.jsx"
import TopicGraph from "./TopicGraph.jsx"
import {
  fetchCategorize,
  fetchDeepResearch,
  fetchLearningPath,
  fetchSessionContext,
  fetchTopicExpansion,
} from "../api/research.js"

// ── helpers ───────────────────────────────────────────────────────────────────

function extractResources(pathData) {
  const seen = new Set()
  const all = []
  for (const tier of ["beginner", "intermediate", "advanced"]) {
    for (const step of pathData[tier] || []) {
      for (const r of step.resources || []) {
        if (!seen.has(r)) {
          seen.add(r)
          all.push(r)
        }
      }
    }
  }
  return all
}

function formatRelativeTime(isoOrSqlite) {
  if (!isoOrSqlite) return null
  const d = new Date(isoOrSqlite.replace(" ", "T") + (isoOrSqlite.includes("T") ? "" : "Z"))
  const diffMs = Date.now() - d.getTime()
  const diffDays = Math.floor(diffMs / 86400000)
  if (diffDays === 0) return "today"
  if (diffDays === 1) return "yesterday"
  if (diffDays < 7) return `${diffDays}d ago`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`
  return `${Math.floor(diffDays / 30)}mo ago`
}

// ── sub-components ────────────────────────────────────────────────────────────

function SearchBar({ value, onChange, onSubmit, busy }) {
  return (
    <form onSubmit={onSubmit} className="relative">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none">
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z" />
            </svg>
          </span>
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Enter a research topic — e.g. RAG Pipelines, LoRA Fine-tuning…"
            className="w-full bg-slate-900 border border-slate-700 text-slate-100 placeholder-slate-600
                       text-sm rounded-xl pl-10 pr-4 py-3 focus:outline-none focus:border-blue-500/60
                       focus:ring-1 focus:ring-blue-500/20 transition-colors"
          />
        </div>
        <button
          type="submit"
          disabled={busy || !value.trim()}
          className="px-5 py-3 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800
                     disabled:text-slate-600 text-white text-sm font-medium transition-colors
                     focus:outline-none focus:ring-2 focus:ring-blue-500/40 shrink-0"
        >
          {busy ? "…" : "Research"}
        </button>
      </div>
    </form>
  )
}

function SessionBadge({ context }) {
  if (!context || context.times_explored === 0) return null

  const done = [
    context.has_deep_research   && "deep dive",
    context.has_learning_path   && "learning path",
    context.has_topic_expansion && "topic graph",
    context.has_github_repos    && "repos",
  ].filter(Boolean)

  const lastSeen = formatRelativeTime(context.last_activity_at)

  return (
    <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
      <span>
        Previously explored {context.times_explored}×
        {lastSeen ? ` · last ${lastSeen}` : ""}
      </span>
      {done.length > 0 && (
        <span className="text-slate-700">·</span>
      )}
      <div className="flex gap-1">
        {done.map((d) => (
          <span
            key={d}
            className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-500 text-[10px]"
          >
            {d}
          </span>
        ))}
      </div>
    </div>
  )
}

function ErrorBanner({ message }) {
  if (!message) return null
  return (
    <div className="rounded-lg border border-red-500/20 bg-red-500/8 px-4 py-3 text-sm text-red-400">
      {message}
    </div>
  )
}

function EmptyState() {
  const suggestions = [
    "RAG Pipelines",
    "LoRA Fine-tuning",
    "Diffusion Models",
    "Vector Databases",
    "Model Context Protocol",
    "Reinforcement Learning from Human Feedback",
  ]
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="w-12 h-12 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center mb-4">
        <svg className="w-5 h-5 text-slate-600" viewBox="0 0 16 16" fill="currentColor">
          <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
        </svg>
      </div>
      <p className="text-slate-500 text-sm mb-5">
        Enter a topic to start your research session
      </p>
      <div className="flex flex-wrap justify-center gap-2 max-w-lg">
        {suggestions.map((s) => (
          <span
            key={s}
            className="px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 text-slate-500 text-xs cursor-default"
          >
            {s}
          </span>
        ))}
      </div>
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────

export default function ResearchWorkspace() {
  const [inputValue, setInputValue]     = useState("")
  const [activeQuery, setActiveQuery]   = useState("")

  const [expansion, setExpansion]       = useState(null)
  const [expansionLoading, setExpL]     = useState(false)
  const [expansionError, setExpErr]     = useState(null)

  const [deepDive, setDeepDive]         = useState(null)
  const [deepLoading, setDeepL]         = useState(false)
  const [deepError, setDeepErr]         = useState(null)

  const [learningPath, setLearningPath] = useState(null)
  const [pathLoading, setPathL]         = useState(false)
  const [pathError, setPathErr]         = useState(null)

  const [resources, setResources]       = useState(null)
  const [resLoading, setResL]           = useState(false)

  const [sessionCtx, setSessionCtx]     = useState(null)

  // Track the request generation so stale responses from a previous
  // query are silently ignored when the user fires a new search.
  const generationRef = useRef(0)

  const handleSubmit = useCallback(
    async (e) => {
      e.preventDefault()
      const topic = inputValue.trim()
      if (!topic) return

      const gen = ++generationRef.current
      setActiveQuery(topic)

      // Clear previous results
      setExpansion(null); setExpErr(null); setExpL(true)
      setDeepDive(null);  setDeepErr(null); setDeepL(true)
      setLearningPath(null); setPathErr(null); setPathL(true)
      setResources(null); setResL(false)
      setSessionCtx(null)

      // ── Session context (non-blocking, best-effort) ──
      fetchSessionContext(topic)
        .then((ctx) => { if (gen === generationRef.current) setSessionCtx(ctx) })
        .catch(() => {})

      // ── Topic expansion ──
      fetchTopicExpansion(topic)
        .then((data) => {
          if (gen !== generationRef.current) return
          setExpansion(data)
        })
        .catch((err) => {
          if (gen !== generationRef.current) return
          setExpErr(err.message || "Failed to load topic graph")
        })
        .finally(() => {
          if (gen === generationRef.current) setExpL(false)
        })

      // ── Deep research ──
      fetchDeepResearch(topic)
        .then((data) => {
          if (gen !== generationRef.current) return
          setDeepDive(data)
        })
        .catch((err) => {
          if (gen !== generationRef.current) return
          setDeepErr(err.message || "Failed to load deep research")
        })
        .finally(() => {
          if (gen === generationRef.current) setDeepL(false)
        })

      // ── Learning path → then categorize extracted resources ──
      fetchLearningPath(topic)
        .then(async (data) => {
          if (gen !== generationRef.current) return
          setLearningPath(data)
          setPathL(false)

          const resourceStrings = extractResources(data)
          if (resourceStrings.length === 0) return

          setResL(true)
          try {
            const cats = await fetchCategorize(resourceStrings)
            if (gen === generationRef.current) setResources(cats)
          } catch {
            // Resource categorization failure is non-fatal
          } finally {
            if (gen === generationRef.current) setResL(false)
          }
        })
        .catch((err) => {
          if (gen !== generationRef.current) return
          setPathErr(err.message || "Failed to load learning path")
          setPathL(false)
        })
    },
    [inputValue]
  )

  const isAnyLoading = expansionLoading || deepLoading || pathLoading
  const hasResults   = expansion || deepDive || learningPath

  return (
    <div className="space-y-5">
      {/* Search */}
      <SearchBar
        value={inputValue}
        onChange={setInputValue}
        onSubmit={handleSubmit}
        busy={isAnyLoading}
      />

      {/* Session badge */}
      {activeQuery && sessionCtx && (
        <SessionBadge context={sessionCtx} />
      )}

      {/* Empty state */}
      {!activeQuery && !isAnyLoading && <EmptyState />}

      {/* Errors */}
      {(expansionError || deepError || pathError) && (
        <div className="space-y-2">
          <ErrorBanner message={expansionError} />
          <ErrorBanner message={deepError} />
          <ErrorBanner message={pathError} />
        </div>
      )}

      {/* ── Row 1: Topic Graph + Deep Dive ─────────────────────────────── */}
      {(activeQuery || expansionLoading || deepLoading) && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
          <div className="lg:col-span-2">
            <TopicGraph data={expansion} loading={expansionLoading} />
          </div>
          <div className="lg:col-span-3">
            <DeepDivePanel data={deepDive} loading={deepLoading} />
          </div>
        </div>
      )}

      {/* ── Row 2: Learning Path ────────────────────────────────────────── */}
      {(activeQuery || pathLoading) && (
        <LearningPathPanel data={learningPath} loading={pathLoading} />
      )}

      {/* ── Row 3: Repos + Resources ─────────────────────────────────────── */}
      {(learningPath?.repositories?.length > 0 || resLoading || resources) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <RepoGrid
            repos={learningPath?.repositories}
            loading={pathLoading}
          />
          <ResourceCatalog data={resources} loading={resLoading} />
        </div>
      )}
    </div>
  )
}

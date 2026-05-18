/**
 * ProgressionPanel — per-project learning progression, always below project header.
 *
 * Collapsed (default): one-line pill row showing focus + concept count + topic count + next suggestion.
 * Expanded: three-column detail — level/focus | explored concepts | next suggestions + completed.
 *
 * Props:
 *   progression   object   — progression record
 *   onUpdate      fn       — (fields) => void
 *   loading       bool
 */
import { useState } from "react"

const LEVEL_CONFIG = {
  beginner:     { label: "Beginner",     badge: "text-emerald-400 bg-emerald-900/30 border-emerald-800/40", bar: "bg-emerald-500", dots: 1 },
  intermediate: { label: "Intermediate", badge: "text-blue-400 bg-blue-900/30 border-blue-800/40",          bar: "bg-blue-500",    dots: 2 },
  advanced:     { label: "Advanced",     badge: "text-violet-400 bg-violet-900/30 border-violet-800/40",    bar: "bg-violet-500",  dots: 3 },
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function CheckIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 6l3 3 5-5" />
    </svg>
  )
}

function ChevronIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
    </svg>
  )
}

function ArrowIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 8h10M9 4l4 4-4 4" />
    </svg>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function LevelDots({ dots }) {
  return (
    <span className="inline-flex items-center gap-[3px]">
      {[1, 2, 3].map(i => (
        <span key={i} className={`w-[5px] h-[5px] rounded-full bg-current ${i <= dots ? "opacity-90" : "opacity-20"}`} />
      ))}
    </span>
  )
}

function ConceptCloud({ concepts }) {
  const [showAll, setShowAll] = useState(false)
  const MAX = 10
  const visible  = showAll ? concepts : concepts.slice(0, MAX)
  const overflow = concepts.length - MAX

  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
        Explored <span className="font-normal normal-case tracking-normal text-slate-600">({concepts.length})</span>
      </p>
      <div className="flex flex-wrap gap-1.5">
        {visible.map((c, i) => (
          <span
            key={i}
            className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] bg-slate-800/80 border border-slate-700/50 text-slate-400"
          >
            {c}
          </span>
        ))}
        {!showAll && overflow > 0 && (
          <button
            onClick={() => setShowAll(true)}
            className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] border border-dashed border-slate-700/50 text-slate-600 hover:text-slate-400 transition-colors"
          >
            +{overflow} more
          </button>
        )}
      </div>
    </div>
  )
}

function CompletedList({ topics, onMarkComplete }) {
  const [input, setInput] = useState("")

  function handleAdd(e) {
    e.preventDefault()
    if (!input.trim()) return
    onMarkComplete?.(input.trim())
    setInput("")
  }

  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
        Completed <span className="font-normal normal-case tracking-normal text-slate-600">({topics.length})</span>
      </p>
      {topics.length > 0 && (
        <ul className="space-y-1.5 mb-2.5">
          {topics.map((t, i) => (
            <li key={i} className="flex items-center gap-2">
              <span className="flex-shrink-0 w-4 h-4 rounded-full bg-emerald-900/40 border border-emerald-800/50 flex items-center justify-center">
                <CheckIcon className="w-2.5 h-2.5 text-emerald-400" />
              </span>
              <span className="text-xs text-slate-400">{t}</span>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={handleAdd} className="flex items-center gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Mark a topic complete…"
          className="flex-1 min-w-0 px-2.5 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/50 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-500 transition-colors"
        />
        <button
          type="submit"
          disabled={!input.trim()}
          className="px-2.5 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 border border-slate-600/50 text-xs text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          Add
        </button>
      </form>
    </div>
  )
}

function NextTopics({ topics, onStart }) {
  if (!topics.length) return null
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
        Suggested Next
      </p>
      <ul className="space-y-2">
        {topics.map((t, i) => (
          <li key={i} className="group flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <ArrowIcon className="w-3 h-3 text-blue-500/60 flex-shrink-0" />
              <span className="text-xs text-slate-300 truncate">{t}</span>
            </div>
            <button
              onClick={() => onStart?.(t)}
              className="flex-shrink-0 opacity-0 group-hover:opacity-100 px-2 py-0.5 rounded-md text-[10px] font-medium text-blue-400 bg-blue-900/30 border border-blue-800/40 hover:bg-blue-800/40 transition-all"
            >
              Start
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function ProgressionPanel({ progression, onUpdate, loading }) {
  const [expanded, setExpanded] = useState(false)

  if (loading) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-900/40 px-4 py-3 mb-5 animate-pulse">
        <div className="flex items-center gap-3">
          <div className="h-5 w-20 rounded-lg bg-slate-800" />
          <div className="h-3.5 w-40 rounded bg-slate-800" />
          <div className="ml-auto h-3.5 w-24 rounded bg-slate-800" />
        </div>
      </div>
    )
  }

  if (!progression) return null

  const {
    current_level         = "beginner",
    current_focus,
    explored_concepts     = [],
    completed_topics      = [],
    suggested_next_topics = [],
    days_completed        = 0,
  } = progression

  const lvl    = LEVEL_CONFIG[current_level] || LEVEL_CONFIG.beginner
  const nextTip = suggested_next_topics[0]

  function handleMarkComplete(topic) {
    onUpdate?.({ completed_topics: [...completed_topics, topic] })
  }

  function handleStart(topic) {
    onUpdate?.({ current_focus: topic })
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden mb-5">

      {/* Collapsed bar */}
      <button
        onClick={() => setExpanded(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-800/30 transition-colors text-left"
      >
        {/* Level */}
        <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-lg border text-[11px] font-semibold flex-shrink-0 ${lvl.badge}`}>
          <LevelDots dots={lvl.dots} />
          {lvl.label}
        </span>

        {/* Focus */}
        <span className="flex-1 min-w-0 text-xs text-slate-500 truncate">
          {current_focus
            ? <><span className="text-slate-700 mr-1.5">Focus:</span>{current_focus}</>
            : <span className="italic text-slate-700">No focus set</span>
          }
        </span>

        {/* Right stats + next tip */}
        <div className="flex items-center gap-3 flex-shrink-0">
          {explored_concepts.length > 0 && (
            <span className="text-[10px] text-slate-600 whitespace-nowrap hidden sm:inline">
              {explored_concepts.length} explored
            </span>
          )}
          {completed_topics.length > 0 && (
            <span className="text-[10px] text-slate-600 whitespace-nowrap hidden sm:inline">
              {completed_topics.length} done
            </span>
          )}
          {nextTip && (
            <span className="hidden md:inline-flex items-center gap-1 text-[10px] text-blue-400/70 whitespace-nowrap max-w-[160px]">
              <ArrowIcon className="w-2.5 h-2.5 flex-shrink-0" />
              <span className="truncate">{nextTip}</span>
            </span>
          )}
          <ChevronIcon className={`w-4 h-4 text-slate-600 transition-transform ${expanded ? "rotate-180" : ""}`} />
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-slate-800 px-4 py-5 grid grid-cols-1 md:grid-cols-3 gap-6">

          {/* Column 1: Level + focus + progress bar */}
          <div className="space-y-4">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2.5">Level</p>
              <div className="flex items-center gap-2.5 mb-3">
                <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-lg border text-[11px] font-semibold ${lvl.badge}`}>
                  <LevelDots dots={lvl.dots} />
                  {lvl.label}
                </span>
                <div className="flex-1 flex gap-1">
                  {["beginner", "intermediate", "advanced"].map((l, i) => {
                    const levelOrder = ["beginner", "intermediate", "advanced"]
                    const active = levelOrder.indexOf(l) <= levelOrder.indexOf(current_level)
                    return (
                      <div key={l} className={`flex-1 h-1.5 rounded-full ${active ? lvl.bar : "bg-slate-800"}`} />
                    )
                  })}
                </div>
              </div>

              {days_completed > 0 && (
                <p className="text-[10px] text-slate-600">
                  Day {days_completed} of learning
                </p>
              )}
            </div>

            {current_focus && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">Current Focus</p>
                <p className="text-xs text-slate-300 leading-relaxed">{current_focus}</p>
              </div>
            )}
          </div>

          {/* Column 2: Explored concepts */}
          <div className="space-y-4">
            {explored_concepts.length > 0
              ? <ConceptCloud concepts={explored_concepts} />
              : <p className="text-xs text-slate-600 italic">No concepts explored yet — generate your first daily package.</p>
            }
          </div>

          {/* Column 3: Next topics + completed */}
          <div className="space-y-5">
            <NextTopics topics={suggested_next_topics} onStart={handleStart} />
            <CompletedList topics={completed_topics} onMarkComplete={handleMarkComplete} />
          </div>
        </div>
      )}
    </div>
  )
}

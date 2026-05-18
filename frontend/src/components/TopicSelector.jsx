import { useState } from 'react'

const DIFFICULTY = {
  beginner:     { label: 'Beginner',     cls: 'text-emerald-400 bg-emerald-950/60 border-emerald-900/60' },
  intermediate: { label: 'Intermediate', cls: 'text-amber-400   bg-amber-950/60   border-amber-900/60'   },
  advanced:     { label: 'Advanced',     cls: 'text-red-400     bg-red-950/60     border-red-900/60'     },
}

const MAX = 2

function SelectionDots({ count }) {
  return (
    <div className="flex items-center gap-1.5">
      {[...Array(MAX)].map((_, i) => (
        <span
          key={i}
          className={`w-2 h-2 rounded-full transition-all duration-200 ${
            i < count ? 'bg-blue-400 scale-110' : 'bg-slate-700'
          }`}
        />
      ))}
      <span className="text-xs text-slate-500 ml-1 tabular-nums">{count} / {MAX}</span>
    </div>
  )
}

export default function TopicSelector({ topics, onSubmit, loading, submitted, error }) {
  const [selected, setSelected] = useState([])

  function toggle(title) {
    setSelected(prev => {
      if (prev.includes(title)) return prev.filter(t => t !== title)
      if (prev.length >= MAX) return prev
      return [...prev, title]
    })
  }

  // ── Submitted confirmation ────────────────────────────────────────────────

  if (submitted) {
    return (
      <section>
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3 flex items-center gap-2">
          <span>🎯</span> Study Plan
        </p>
        <div className="bg-slate-900 border border-emerald-900/40 rounded-2xl p-4 flex items-start gap-3">
          <span className="text-emerald-400 text-base flex-shrink-0 mt-0.5">✓</span>
          <div>
            <p className="text-emerald-300 text-sm font-medium">Added to your learning plan</p>
            <p className="text-slate-500 text-xs mt-0.5">
              These topics will be prioritised in your next generated feed.
            </p>
          </div>
        </div>
      </section>
    )
  }

  // ── Selection UI ──────────────────────────────────────────────────────────

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 flex items-center gap-2">
          <span>🎯</span> Add to Study Plan
        </p>
        <SelectionDots count={selected.length} />
      </div>

      <p className="text-xs text-slate-500 mb-3">
        Pick up to {MAX} topics to study — they'll be prioritised in future feeds.
      </p>

      <div className="space-y-2 mb-4">
        {topics.map(topic => {
          const isSelected  = selected.includes(topic.title)
          const isDisabled  = !isSelected && selected.length >= MAX
          const diff        = DIFFICULTY[topic.difficulty] ?? DIFFICULTY.beginner

          return (
            <button
              key={topic.title}
              onClick={() => !isDisabled && toggle(topic.title)}
              disabled={isDisabled}
              className={`w-full text-left p-3.5 rounded-xl border transition-all duration-150 ${
                isSelected
                  ? 'bg-blue-950/50 border-blue-600/70 shadow-sm shadow-blue-950/40'
                  : isDisabled
                  ? 'bg-slate-900/50 border-slate-800 opacity-40 cursor-not-allowed'
                  : 'bg-slate-900 border-slate-800 hover:border-slate-700 cursor-pointer'
              }`}
            >
              <div className="flex items-center gap-3">
                {/* Checkbox dot */}
                <span className={`flex-shrink-0 w-4 h-4 rounded border flex items-center justify-center text-xs transition-all ${
                  isSelected
                    ? 'bg-blue-500 border-blue-500 text-white'
                    : 'border-slate-600'
                }`}>
                  {isSelected && '✓'}
                </span>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className={`text-sm font-medium leading-snug ${isSelected ? 'text-blue-100' : 'text-slate-200'}`}>
                      {topic.title}
                    </span>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border flex-shrink-0 ${diff.cls}`}>
                      {diff.label}
                    </span>
                  </div>
                  <p className="text-slate-500 text-xs mt-0.5 leading-relaxed">{topic.reason}</p>
                </div>
              </div>
            </button>
          )
        })}
      </div>

      {error && (
        <p className="text-red-400 text-xs mb-3 flex items-center gap-1.5">
          <span>⚠</span> {error}
        </p>
      )}

      <button
        onClick={() => selected.length > 0 && !loading && onSubmit(selected)}
        disabled={selected.length === 0 || loading}
        className="w-full py-2.5 rounded-xl border transition-all text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed enabled:bg-blue-600/20 enabled:border-blue-600/50 enabled:text-blue-300 enabled:hover:bg-blue-600/30 enabled:hover:border-blue-500"
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Saving…
          </span>
        ) : selected.length === 0
          ? 'Select topics above'
          : `Add ${selected.length} topic${selected.length > 1 ? 's' : ''} to study plan →`
        }
      </button>
    </section>
  )
}

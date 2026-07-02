/**
 * CreateProjectModal — AI-assisted project creation.
 *
 * Keyword flow:
 *   1. User fills Name, Description, Level
 *   2. User clicks "Generate Keywords" → POST /projects/suggest-keywords (name+description+level)
 *   3. Chips populate with {keyword, source:"generated"}
 *   4. User can add (source:"user"), delete, or drag-to-reorder any chip
 *   5. Re-clicking Generate merges: preserves user-added, replaces AI set
 *   6. Submit extracts plain strings — no metadata sent to API
 *
 * No automatic LLM calls from onChange/debounce — only explicit button click.
 */
import { useState, useRef } from "react"
import { suggestKeywords } from "../../api/projects.js"

const COLORS = [
  { id: "blue",    label: "Blue",    class: "bg-blue-500"    },
  { id: "emerald", label: "Green",   class: "bg-emerald-500" },
  { id: "violet",  label: "Violet",  class: "bg-violet-500"  },
  { id: "amber",   label: "Amber",   class: "bg-amber-500"   },
  { id: "rose",    label: "Rose",    class: "bg-rose-500"    },
]

const DIFFICULTY_OPTIONS = [
  { id: "beginner",     label: "Beginner",     desc: "New to this domain"        },
  { id: "intermediate", label: "Intermediate", desc: "Some background knowledge" },
  { id: "advanced",     label: "Advanced",     desc: "Deep domain expertise"     },
]

const INTENSITY_OPTIONS = [
  { count: 2, label: "Light",     desc: "2 articles · focused depth"    },
  { count: 4, label: "Standard",  desc: "4 articles · balanced breadth" },
  { count: 6, label: "Intensive", desc: "6 articles · wide coverage"    },
]

// Keep all user-added keywords; replace the full AI-generated set with the new suggestions.
function mergeKeywords(existing, suggested) {
  const userAdded = existing.filter(k => k.source === "user")
  const userWords = new Set(userAdded.map(k => k.keyword.toLowerCase()))
  const newAI = suggested
    .filter(s => !userWords.has(s.toLowerCase()))
    .map(s => ({ keyword: s, source: "generated" }))
  return [...userAdded, ...newAI]
}

// ── Keyword chip ──────────────────────────────────────────────────────────────

function KeywordChip({ kw, index, onRemove, dragRef }) {
  const isAI = kw.source === "generated"
  return (
    <span
      draggable
      onDragStart={() => { dragRef.current = index }}
      onDragOver={e => e.preventDefault()}
      onDrop={() => {
        const from = dragRef.current
        if (from === null || from === index) return
        onRemove(null, from, index)
        dragRef.current = null
      }}
      title={isAI ? "AI-suggested · drag to reorder" : "You added · drag to reorder"}
      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs border cursor-grab select-none
        ${isAI
          ? "bg-blue-900/40 text-blue-300 border-blue-800/40"
          : "bg-slate-800 text-slate-300 border-slate-600/60"
        }`}
    >
      {isAI && <span className="opacity-50 text-[9px] leading-none">✦</span>}
      {kw.keyword}
      <button
        type="button"
        onClick={() => onRemove(index, null, null)}
        className="ml-0.5 opacity-60 hover:opacity-100 transition-opacity leading-none"
        aria-label={`Remove ${kw.keyword}`}
      >
        ×
      </button>
    </span>
  )
}

// ── Modal ─────────────────────────────────────────────────────────────────────

export default function CreateProjectModal({ onClose, onCreate, loading }) {
  const [name,                  setName]                  = useState("")
  const [description,           setDescription]           = useState("")
  const [keywords,              setKeywords]              = useState([])
  const [kwInput,               setKwInput]               = useState("")
  const [difficulty,            setDifficulty]            = useState("intermediate")
  const [color,                 setColor]                 = useState("blue")
  const [dailyCoreArticleCount, setDailyCoreArticleCount] = useState(4)
  const [error,                 setError]                 = useState(null)
  const [suggestLoading,        setSuggestLoading]        = useState(false)
  const [suggestError,          setSuggestError]          = useState(null)

  const dragIdx = useRef(null)

  const canGenerate = name.trim().length > 0 && description.trim().length >= 10

  async function runSuggestions() {
    setSuggestLoading(true)
    setSuggestError(null)
    try {
      const result = await suggestKeywords(name.trim(), description.trim(), difficulty)
      const suggested = result?.keywords || []
      setKeywords(prev => mergeKeywords(prev, suggested))
    } catch {
      setSuggestError("AI keyword generation is unavailable right now (API connection issue). Type your own keywords in the field below and press Enter to add them.")
    } finally {
      setSuggestLoading(false)
    }
  }

  function addKeyword() {
    const trimmed = kwInput.trim()
    if (trimmed && !keywords.some(k => k.keyword.toLowerCase() === trimmed.toLowerCase())) {
      setKeywords(prev => [...prev, { keyword: trimmed, source: "user" }])
    }
    setKwInput("")
  }

  // Handles both remove (deleteIdx set) and reorder (from/to set)
  function handleChipAction(deleteIdx, from, to) {
    if (deleteIdx !== null) {
      setKeywords(prev => prev.filter((_, i) => i !== deleteIdx))
    } else {
      setKeywords(prev => {
        const arr = [...prev]
        const [moved] = arr.splice(from, 1)
        arr.splice(to, 0, moved)
        return arr
      })
    }
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) { setError("Project name is required."); return }
    if (!description.trim()) { setError("Description is required."); return }
    setError(null)
    await onCreate({
      name: name.trim(),
      description,
      keywords: keywords.map(k => k.keyword),
      difficulty,
      color,
      daily_core_article_count: dailyCoreArticleCount,
    })
  }

  function handleBackdrop(e) {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
      onClick={handleBackdrop}
    >
      <div className="w-full max-w-lg bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 className="font-semibold text-slate-100">New Learning Project</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="overflow-y-auto max-h-[80vh]">
          <div className="px-6 py-5 space-y-5">

            {/* 1 — Project Name */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Project Name *</label>
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="e.g. Globalization, Machine Learning, Indian Pharma"
                maxLength={80}
                className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
              />
            </div>

            {/* 2 — Description */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Description *</label>
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder="Who are you and what are you trying to learn? e.g. 'I'm an economics student studying trade policy' or 'I'm a software engineer exploring enterprise AI adoption'"
                rows={3}
                maxLength={300}
                className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 resize-none focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
              />
            </div>

            {/* 3 — Your Level */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Your Level</label>
              <div className="grid grid-cols-3 gap-2">
                {DIFFICULTY_OPTIONS.map(d => (
                  <button
                    key={d.id}
                    type="button"
                    onClick={() => setDifficulty(d.id)}
                    className={`px-3 py-2 rounded-xl text-left border transition-all ${
                      difficulty === d.id
                        ? "bg-slate-700 border-slate-500 text-slate-100"
                        : "bg-slate-800/60 border-slate-700/50 text-slate-400 hover:border-slate-600"
                    }`}
                  >
                    <div className="text-xs font-medium">{d.label}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">{d.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* 4 — Generate Keywords button */}
            <div>
              <button
                type="button"
                onClick={runSuggestions}
                disabled={suggestLoading || !canGenerate}
                className={`w-full px-4 py-2.5 rounded-xl text-sm font-medium border transition-all flex items-center justify-center gap-2 ${
                  suggestLoading || !canGenerate
                    ? "bg-slate-800/40 border-slate-700/40 text-slate-600 cursor-not-allowed"
                    : "bg-slate-800 border-slate-600/70 text-slate-200 hover:bg-slate-700 hover:border-slate-500"
                }`}
              >
                {suggestLoading ? (
                  <>
                    <svg className="w-3.5 h-3.5 animate-spin flex-shrink-0" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                      <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Generating keywords…
                  </>
                ) : (
                  <>
                    <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M7.657 6.247c.11-.33.576-.33.686 0l.645 1.937a2.89 2.89 0 0 0 1.829 1.828l1.936.645c.33.11.33.576 0 .686l-1.937.645a2.89 2.89 0 0 0-1.828 1.829l-.645 1.936a.361.361 0 0 1-.686 0l-.645-1.937a2.89 2.89 0 0 0-1.828-1.828l-1.937-.645a.361.361 0 0 1 0-.686l1.937-.645a2.89 2.89 0 0 0 1.828-1.828zM3.794 1.148a.217.217 0 0 1 .412 0l.387 1.162c.173.518.579.924 1.097 1.097l1.162.387a.217.217 0 0 1 0 .412l-1.162.387A1.734 1.734 0 0 0 4.593 5.69l-.387 1.162a.217.217 0 0 1-.412 0L3.407 5.69A1.734 1.734 0 0 0 2.31 4.593l-1.162-.387a.217.217 0 0 1 0-.412l1.162-.387A1.734 1.734 0 0 0 3.407 2.31zM10.863.099a.145.145 0 0 1 .274 0l.258.774c.115.346.386.617.732.732l.774.258a.145.145 0 0 1 0 .274l-.774.258a1.156 1.156 0 0 0-.732.732l-.258.774a.145.145 0 0 1-.274 0l-.258-.774a1.156 1.156 0 0 0-.732-.732L9.1 2.137a.145.145 0 0 1 0-.274l.774-.258c.346-.115.617-.386.732-.732z" />
                    </svg>
                    Generate Keywords
                  </>
                )}
              </button>
              {!canGenerate && (
                <p className="text-[10px] text-slate-600 mt-1.5 text-center">
                  Add a name and description first
                </p>
              )}
              {suggestError && (
                <p className="text-[10px] text-amber-400 mt-1.5">{suggestError}</p>
              )}
            </div>

            {/* 5 — Keywords */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-medium text-slate-400">Keywords</label>
                {keywords.some(k => k.source === "generated") && (
                  <span className="text-[10px] text-slate-500">
                    <span className="text-blue-400/70">✦</span> AI-suggested · drag to reorder
                  </span>
                )}
              </div>

              <div className="flex gap-2 mb-2">
                <input
                  value={kwInput}
                  onChange={e => setKwInput(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addKeyword() } }}
                  placeholder="Or add keywords manually, press Enter"
                  className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50"
                />
                <button
                  type="button"
                  onClick={addKeyword}
                  className="px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm transition-colors"
                >
                  Add
                </button>
              </div>

              {keywords.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {keywords.map((kw, i) => (
                    <KeywordChip
                      key={`${kw.keyword}-${i}`}
                      kw={kw}
                      index={i}
                      onRemove={handleChipAction}
                      dragRef={dragIdx}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* 6 — Daily Intensity */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Daily Learning Intensity</label>
              <div className="grid grid-cols-3 gap-2">
                {INTENSITY_OPTIONS.map(opt => (
                  <button
                    key={opt.count}
                    type="button"
                    onClick={() => setDailyCoreArticleCount(opt.count)}
                    className={`px-3 py-2 rounded-xl text-left border transition-all ${
                      dailyCoreArticleCount === opt.count
                        ? "bg-slate-700 border-slate-500 text-slate-100"
                        : "bg-slate-800/60 border-slate-700/50 text-slate-400 hover:border-slate-600"
                    }`}
                  >
                    <div className="text-xs font-medium">{opt.label}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">{opt.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* 7 — Accent Color */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Accent Color</label>
              <div className="flex gap-2">
                {COLORS.map(c => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setColor(c.id)}
                    className={`w-7 h-7 rounded-full ${c.class} transition-all ${
                      color === c.id ? "ring-2 ring-white/60 ring-offset-2 ring-offset-slate-900 scale-110" : "opacity-60 hover:opacity-100"
                    }`}
                    title={c.label}
                  />
                ))}
              </div>
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-950/30 border border-red-900/40 px-3 py-2 rounded-xl">
                {error}
              </p>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 pb-5 flex gap-3">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-700/50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || !name.trim() || !description.trim()}
              className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? "Creating…" : "Create Project"}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

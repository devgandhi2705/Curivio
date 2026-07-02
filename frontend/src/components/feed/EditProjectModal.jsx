/**
 * EditProjectModal — edit an existing learning project.
 *
 * Pre-populates all fields from the project prop.
 * Organized into 3 sections: Identity, Learning Setup, Appearance.
 * Does NOT wipe history, insights, or progression — only updates project config.
 *
 * Props:
 *   project  — existing project object
 *   onClose  — close without saving
 *   onSave(fields) → Promise — called with updated fields; throws on error
 */
import { useState } from "react"
import { suggestKeywords } from "../../api/projects.js"

// ── Constants (shared with CreateProjectModal) ────────────────────────────────

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

const INTENSITY_MIN = 3
const INTENSITY_MAX = 10

function intensityDesc(count) {
  if (count <= 4) return "Light · focused depth"
  if (count <= 6) return "Standard · balanced breadth"
  if (count <= 8) return "Broad · expanded coverage"
  return "Intensive · wide coverage"
}

// Auto-grow a textarea to fit its content, no fixed/scrollable box.
function autoResize(el) {
  if (!el) return
  el.style.height = "auto"
  el.style.height = `${el.scrollHeight}px`
}

// ── Section label ─────────────────────────────────────────────────────────────

function SectionLabel({ children }) {
  return (
    <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-3">
      {children}
    </p>
  )
}

// ── Tag chip ──────────────────────────────────────────────────────────────────

function Chip({ label, onRemove, variant = "default" }) {
  const styles = {
    default: "bg-slate-800 text-slate-300 border-slate-700/50 [--x:theme(colors.slate.500)] hover:[--x:theme(colors.slate.300)]",
    blue:    "bg-blue-900/40 text-blue-300 border-blue-800/40 [--x:theme(colors.blue.400)] hover:[--x:theme(colors.blue.200)]",
  }
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs border ${styles[variant]}`}>
      {label}
      <button
        type="button"
        onClick={onRemove}
        className="ml-0.5 leading-none opacity-70 hover:opacity-100 transition-opacity"
        aria-label={`Remove ${label}`}
      >
        ×
      </button>
    </span>
  )
}

// ── Tag input row ─────────────────────────────────────────────────────────────

function TagInput({ value, onChange, onAdd, placeholder }) {
  return (
    <div className="flex gap-2">
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); onAdd() } }}
        placeholder={placeholder}
        className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50"
      />
      <button
        type="button"
        onClick={onAdd}
        className="min-w-[64px] px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm transition-colors flex items-center justify-center"
      >
        Add
      </button>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function EditProjectModal({ project, onClose, onSave, onEditPersona }) {
  // ── State — pre-populated from project ─────────────────────────────────────
  const [name,                  setName]                  = useState(project.name || "")
  const [description,           setDescription]           = useState(project.description || "")
  const [keywords,              setKeywords]              = useState([...(project.keywords || [])])
  const [kwInput,               setKwInput]               = useState("")
  const [difficulty,            setDifficulty]            = useState(project.difficulty || "intermediate")
  const [color,                 setColor]                 = useState(project.color || "blue")
  const [dailyCoreArticleCount, setDailyCoreArticleCount] = useState(
    Math.min(INTENSITY_MAX, Math.max(INTENSITY_MIN, project.daily_core_article_count || 4))
  )
  const [saving,                setSaving]                = useState(false)
  const [error,                 setError]                 = useState(null)
  const [suggestLoading,        setSuggestLoading]        = useState(false)
  const [suggestError,          setSuggestError]          = useState(null)
  const [suggestions,           setSuggestions]           = useState(null)

  // ── Keyword suggestion ─────────────────────────────────────────────────────
  async function runSuggestions() {
    if (!name.trim() || description.trim().length < 10) return
    setSuggestLoading(true)
    setSuggestError(null)
    setSuggestions(null)
    try {
      const result = await suggestKeywords(name.trim(), description.trim(), difficulty)
      setSuggestions(result?.keywords || [])
    } catch {
      setSuggestError("AI keyword generation is unavailable right now (API connection issue). Type your own keywords in the field below and press Enter to add them.")
    } finally {
      setSuggestLoading(false)
    }
  }

  // ── Keyword handlers ───────────────────────────────────────────────────────
  function addKeyword() {
    const t = kwInput.trim()
    if (t && !keywords.includes(t)) setKeywords(prev => [...prev, t])
    setKwInput("")
  }

  // ── Submit ─────────────────────────────────────────────────────────────────
  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) { setError("Project name is required."); return }
    if (!description.trim()) { setError("Description is required."); return }
    setError(null)
    setSaving(true)
    try {
      await onSave({
        name:                     name.trim(),
        description,
        keywords,
        difficulty,
        color,
        daily_core_article_count: dailyCoreArticleCount,
      })
    } catch (err) {
      setError(err?.message || "Failed to save. Please try again.")
    } finally {
      setSaving(false)
    }
  }

  function handleBackdrop(e) {
    if (e.target === e.currentTarget && !saving) onClose()
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
      onClick={handleBackdrop}
    >
      <div className="w-full max-w-lg bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className={`w-7 h-7 rounded-lg bg-gradient-to-br ${COLOR_GRAD[color] || COLOR_GRAD.blue} flex items-center justify-center flex-shrink-0`}>
              <svg className="w-3.5 h-3.5 text-white" viewBox="0 0 16 16" fill="currentColor">
                <path d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61Zm.176 4.823L9.75 4.81l-6.286 6.287a.25.25 0 0 0-.064.108l-.558 1.953 1.953-.558a.249.249 0 0 0 .108-.064Zm1.238-3.763a.25.25 0 0 0-.354 0L10.811 3.75l1.439 1.44 1.263-1.263a.25.25 0 0 0 0-.354Z" />
              </svg>
            </div>
            <div>
              <h2 className="font-semibold text-slate-100 text-sm leading-tight">Edit Project</h2>
              <p className="text-[10px] text-slate-500">{project.name}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={saving}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors disabled:opacity-40"
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="overflow-y-auto max-h-[75vh]">
          <div className="px-6 py-5 space-y-6">

            {/* ── Section 1: Identity ───────────────────────────────────── */}
            <div>
              <SectionLabel>Project Identity</SectionLabel>
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">Name *</label>
                  <input
                    value={name}
                    onChange={e => setName(e.target.value)}
                    maxLength={80}
                    className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">Description *</label>
                  <textarea
                    ref={el => autoResize(el)}
                    value={description}
                    onChange={e => { setDescription(e.target.value); autoResize(e.target) }}
                    rows={2}
                    maxLength={300}
                    placeholder="What are you trying to learn or track?"
                    className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 resize-none overflow-hidden focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
                  />
                </div>
              </div>
            </div>

            <div className="border-t border-slate-800/80" />

            {/* ── Section 2: Learning Setup ─────────────────────────────── */}
            <div>
              <SectionLabel>Learning Setup</SectionLabel>
              <div className="space-y-4">

                {/* Difficulty */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">Your Level</label>
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

                {/* Daily Intensity */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs text-slate-400">Daily Learning Intensity</label>
                    <span className="text-xs font-medium text-slate-100">
                      {dailyCoreArticleCount} article{dailyCoreArticleCount === 1 ? "" : "s"}
                    </span>
                  </div>
                  <input
                    type="range"
                    min={INTENSITY_MIN}
                    max={INTENSITY_MAX}
                    step={1}
                    value={dailyCoreArticleCount}
                    onChange={e => setDailyCoreArticleCount(Number(e.target.value))}
                    className="w-full h-1.5 rounded-full appearance-none bg-slate-700 accent-blue-500 cursor-pointer"
                  />
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-[10px] text-slate-600">{INTENSITY_MIN}</span>
                    <span className="text-[10px] text-slate-500">{intensityDesc(dailyCoreArticleCount)}</span>
                    <span className="text-[10px] text-slate-600">{INTENSITY_MAX}</span>
                  </div>
                </div>

                {/* Keywords */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">Keywords</label>
                  <TagInput
                    value={kwInput}
                    onChange={setKwInput}
                    onAdd={addKeyword}
                    placeholder="Add keyword, press Enter"
                  />
                  {keywords.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {keywords.map(kw => (
                        <Chip
                          key={kw}
                          label={kw}
                          variant="blue"
                          onRemove={() => setKeywords(prev => prev.filter(k => k !== kw))}
                        />
                      ))}
                    </div>
                  )}

                  {/* Regenerate button */}
                  <button
                    type="button"
                    onClick={runSuggestions}
                    disabled={suggestLoading || !name.trim() || description.trim().length < 10}
                    className="mt-3 w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl text-xs font-medium text-slate-400 hover:text-slate-200 bg-slate-800/60 hover:bg-slate-800 border border-slate-700/50 hover:border-slate-600 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {suggestLoading ? (
                      <>
                        <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                          <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Generating keywords…
                      </>
                    ) : (
                      <>
                        <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
                          <path d="M1.705 8.005a.75.75 0 0 1 .834.656 5.5 5.5 0 0 0 9.592 2.97l-1.204-1.204a.25.25 0 0 1 .177-.427h3.646a.25.25 0 0 1 .25.25v3.646a.25.25 0 0 1-.427.177l-1.38-1.38A7.002 7.002 0 0 1 1.05 8.84a.75.75 0 0 1 .656-.834ZM8 2.5a5.487 5.487 0 0 0-4.131 1.869l1.204 1.204A.25.25 0 0 1 4.896 6H1.25A.25.25 0 0 1 1 5.75V2.104a.25.25 0 0 1 .427-.177l1.38 1.38A7.002 7.002 0 0 1 14.95 7.16a.75.75 0 0 1-1.49.178A5.5 5.5 0 0 0 8 2.5Z" />
                        </svg>
                        Regenerate Keywords
                      </>
                    )}
                  </button>

                  {/* Error */}
                  {suggestError && (
                    <p className="mt-2 text-[10px] text-amber-400">{suggestError}</p>
                  )}

                  {/* Diff UI — shown after suggestions are returned */}
                  {suggestions !== null && (
                    <div className="mt-3 rounded-xl border border-slate-700/60 overflow-hidden">
                      {/* Current */}
                      <div className="px-3 py-2.5 bg-slate-800/40 border-b border-slate-700/40">
                        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">Current</p>
                        {keywords.length > 0 ? (
                          <div className="flex flex-wrap gap-1.5">
                            {keywords.map(kw => (
                              <span key={kw} className="px-2 py-0.5 rounded-md text-[11px] bg-slate-700/60 text-slate-400 border border-slate-600/40">{kw}</span>
                            ))}
                          </div>
                        ) : (
                          <p className="text-[11px] text-slate-600 italic">No keywords set</p>
                        )}
                      </div>

                      {/* Arrow */}
                      <div className="flex items-center justify-center py-1.5 bg-slate-800/20 border-b border-slate-700/40">
                        <svg className="w-3 h-3 text-slate-600" viewBox="0 0 16 16" fill="currentColor">
                          <path d="M8 2a.75.75 0 0 1 .75.75v8.69l3.22-3.22a.75.75 0 1 1 1.06 1.06l-4.5 4.5a.75.75 0 0 1-1.06 0l-4.5-4.5a.75.75 0 0 1 1.06-1.06L7.25 11.44V2.75A.75.75 0 0 1 8 2Z" />
                        </svg>
                      </div>

                      {/* Suggested */}
                      <div className="px-3 py-2.5 bg-slate-800/40">
                        <p className="text-[10px] font-semibold uppercase tracking-widest text-blue-500/60 mb-2">Suggested</p>
                        {suggestions.length > 0 ? (
                          <div className="flex flex-wrap gap-1.5">
                            {suggestions.map(kw => (
                              <span key={kw} className="px-2 py-0.5 rounded-md text-[11px] bg-blue-900/30 text-blue-300 border border-blue-700/40">{kw}</span>
                            ))}
                          </div>
                        ) : (
                          <p className="text-[11px] text-slate-600 italic">No suggestions returned</p>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="flex gap-2 px-3 py-2.5 border-t border-slate-700/40 bg-slate-800/20">
                        <button
                          type="button"
                          onClick={() => { setKeywords(suggestions); setSuggestions(null); setSuggestError(null) }}
                          disabled={suggestions.length === 0}
                          className="flex-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          Accept All
                        </button>
                        <button
                          type="button"
                          onClick={() => { setSuggestions(null); setSuggestError(null) }}
                          className="flex-1 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200 bg-slate-700/60 hover:bg-slate-700 border border-slate-600/40 transition-colors"
                        >
                          Discard
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="border-t border-slate-800/80" />

            {/* ── Section 3: Appearance ─────────────────────────────────── */}
            <div>
              <SectionLabel>Appearance</SectionLabel>
              <div className="flex gap-2.5 items-center">
                {COLORS.map(c => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setColor(c.id)}
                    className={`w-7 h-7 rounded-full ${c.class} transition-all ${
                      color === c.id
                        ? "ring-2 ring-white/60 ring-offset-2 ring-offset-slate-900 scale-110"
                        : "opacity-50 hover:opacity-100"
                    }`}
                    title={c.label}
                  />
                ))}
                <span className="text-[11px] text-slate-500 ml-1">Accent color</span>
              </div>
            </div>

            {/* Error */}
            {error && (
              <p className="text-xs text-red-400 bg-red-950/30 border border-red-900/40 px-3 py-2 rounded-xl">
                {error}
              </p>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 pb-5 border-t border-slate-800/60 pt-4 space-y-2.5">
            {/* Edit Persona — secondary action */}
            {onEditPersona && (
              <button
                type="button"
                onClick={onEditPersona}
                disabled={saving}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-xs font-medium text-slate-400 hover:text-blue-300 bg-slate-800/40 hover:bg-blue-500/10 border border-slate-700/40 hover:border-blue-500/30 transition-all disabled:opacity-40"
              >
                <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Zm4.879-2.773 4.264 2.559a.25.25 0 0 1 0 .428l-4.264 2.559A.25.25 0 0 1 6 10.559V5.442a.25.25 0 0 1 .379-.215Z" />
                </svg>
                Edit Learning Persona
              </button>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={onClose}
                disabled={saving}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-700/50 transition-colors disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving || !name.trim() || !description.trim()}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
              >
                {saving ? (
                  <>
                    <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                      <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Saving…
                  </>
                ) : (
                  "Save Changes"
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

// Gradient map used for the header icon
const COLOR_GRAD = {
  blue:    "from-blue-500 to-blue-600",
  emerald: "from-emerald-500 to-emerald-600",
  violet:  "from-violet-500 to-violet-600",
  amber:   "from-amber-500 to-amber-600",
  rose:    "from-rose-500 to-rose-600",
}

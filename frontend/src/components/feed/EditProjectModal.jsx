/**
 * EditProjectModal — edit an existing learning project.
 *
 * Pre-populates all fields from the project prop.
 * Organized into 4 sections: Identity, Learning, Retrieval, Appearance.
 * Does NOT wipe history, insights, or progression — only updates project config.
 *
 * Props:
 *   project  — existing project object
 *   onClose  — close without saving
 *   onSave(fields) → Promise — called with updated fields; throws on error
 */
import { useState } from "react"
import { checkSourceRelevance } from "../../api/projects.js"

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

const INTENSITY_OPTIONS = [
  { count: 2, label: "Light",     desc: "2 articles · focused depth"    },
  { count: 4, label: "Standard",  desc: "4 articles · balanced breadth" },
  { count: 6, label: "Intensive", desc: "6 articles · wide coverage"    },
]

// ── Domain helpers ────────────────────────────────────────────────────────────

function normalizeDomain(raw) {
  let s = raw.trim().toLowerCase()
  s = s.replace(/^https?:\/\//, "")
  s = s.split("/")[0].split("?")[0].split("#")[0]
  s = s.replace(/^www\./, "").replace(/\.$/, "")
  return s
}

function isValidDomain(s) {
  return s.length > 0 && s.length <= 100 && /^[a-z0-9][a-z0-9\-]*(\.[a-z0-9\-]+)+$/.test(s)
}

async function checkDomainReachable(domain) {
  const controller = new AbortController()
  const tid = setTimeout(() => controller.abort(), 6000)
  try {
    await fetch(`https://${domain}`, { mode: "no-cors", signal: controller.signal })
    clearTimeout(tid)
    return true
  } catch {
    clearTimeout(tid)
    return false
  }
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
    violet:  "bg-violet-900/30 text-violet-300 border-violet-800/40 [--x:theme(colors.violet.400)] hover:[--x:theme(colors.violet.200)]",
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

function TagInput({ value, onChange, onAdd, placeholder, buttonLabel = "Add", disabled = false, loading = false }) {
  return (
    <div className="flex gap-2">
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); if (!disabled) onAdd() } }}
        placeholder={placeholder}
        disabled={disabled}
        className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50 disabled:opacity-50"
      />
      <button
        type="button"
        onClick={onAdd}
        disabled={disabled}
        className="min-w-[64px] px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
      >
        {loading ? (
          <>
            <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
              <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Checking
          </>
        ) : (buttonLabel)}
      </button>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function EditProjectModal({ project, onClose, onSave }) {
  // ── State — pre-populated from project ─────────────────────────────────────
  const [name,             setName]             = useState(project.name || "")
  const [description,      setDescription]      = useState(project.description || "")
  const [keywords,         setKeywords]         = useState([...(project.keywords || [])])
  const [kwInput,          setKwInput]          = useState("")
  const [difficulty,       setDifficulty]       = useState(project.difficulty || "intermediate")
  const [focusAreas,       setFocusAreas]       = useState([...(project.focus_areas || [])])
  const [faInput,          setFaInput]          = useState("")
  const [color,            setColor]            = useState(project.color || "blue")
  const [preferredSources,      setPreferredSources]      = useState([...(project.preferred_sources || [])])
  const [ignoredSources,        setIgnoredSources]        = useState([...(project.ignored_sources || [])])
  const [srcInput,              setSrcInput]              = useState("")
  const [srcError,              setSrcError]              = useState(null)
  const [srcChecking,           setSrcChecking]           = useState(false)
  const [srcCheckPhase,         setSrcCheckPhase]         = useState("")
  const [srcWarnOnly,           setSrcWarnOnly]           = useState(false)
  const [dailyCoreArticleCount, setDailyCoreArticleCount] = useState(project.daily_core_article_count || 4)
  const [saving,                setSaving]                = useState(false)
  const [error,                 setError]                 = useState(null)

  // ── Keyword handlers ───────────────────────────────────────────────────────
  function addKeyword() {
    const t = kwInput.trim()
    if (t && !keywords.includes(t)) setKeywords(prev => [...prev, t])
    setKwInput("")
  }

  // ── Focus area handlers ────────────────────────────────────────────────────
  function addFocusArea() {
    const t = faInput.trim()
    if (t && !focusAreas.includes(t)) setFocusAreas(prev => [...prev, t])
    setFaInput("")
  }

  // ── Source handlers ────────────────────────────────────────────────────────
  async function addSource() {
    if (srcChecking) return
    setSrcError(null)
    setSrcWarnOnly(false)
    const domain = normalizeDomain(srcInput)
    if (!domain) { setSrcInput(""); return }
    if (!isValidDomain(domain)) {
      setSrcError("Invalid URL — enter a domain like arxiv.org or https://sec.gov")
      return
    }
    if (preferredSources.includes(domain) || ignoredSources.includes(domain)) {
      setSrcError("Already added")
      setSrcInput("")
      return
    }

    // Phase 1 — reachability
    setSrcChecking(true)
    setSrcCheckPhase("reachability")
    const reachable = await checkDomainReachable(domain)
    if (!reachable) {
      setSrcChecking(false)
      setSrcCheckPhase("")
      setSrcError(`Could not reach ${domain} — double-check the URL`)
      setSrcWarnOnly(true)
      return
    }

    // Phase 2 — relevance
    setSrcCheckPhase("relevance")
    const result = await checkSourceRelevance(domain, project.name, project.keywords || [])
    setSrcChecking(false)
    setSrcCheckPhase("")

    if (!result.relevant) {
      setIgnoredSources(prev => [...prev, domain])
      setSrcInput("")
      return
    }
    setPreferredSources(prev => [...prev, domain])
    setSrcInput("")
  }

  function forceAddSource() {
    const domain = normalizeDomain(srcInput)
    if (domain && !preferredSources.includes(domain)) {
      setPreferredSources(prev => [...prev, domain])
      setIgnoredSources(prev => prev.filter(d => d !== domain))
    }
    setSrcInput("")
    setSrcError(null)
    setSrcWarnOnly(false)
  }

  function promoteIgnored(domain) {
    setIgnoredSources(prev => prev.filter(d => d !== domain))
    setPreferredSources(prev => [...prev, domain])
  }

  // ── Submit ─────────────────────────────────────────────────────────────────
  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) { setError("Project name is required."); return }
    setError(null)
    setSaving(true)
    try {
      await onSave({
        name:                     name.trim(),
        description,
        keywords,
        difficulty,
        focus_areas:              focusAreas,
        color,
        preferred_sources:        preferredSources,
        ignored_sources:          ignoredSources,
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
                  <label className="block text-xs text-slate-400 mb-1.5">Description</label>
                  <textarea
                    value={description}
                    onChange={e => setDescription(e.target.value)}
                    rows={2}
                    maxLength={300}
                    placeholder="What are you trying to learn or track?"
                    className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 resize-none focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
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
                  <label className="block text-xs text-slate-400 mb-1.5">Daily Learning Intensity</label>
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
                </div>

                {/* Focus Areas */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">
                    Focus Areas <span className="text-slate-600 font-normal">(optional)</span>
                  </label>
                  <TagInput
                    value={faInput}
                    onChange={setFaInput}
                    onAdd={addFocusArea}
                    placeholder="e.g. Predictive Maintenance"
                  />
                  {focusAreas.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {focusAreas.map(fa => (
                        <Chip
                          key={fa}
                          label={fa}
                          onRemove={() => setFocusAreas(prev => prev.filter(f => f !== fa))}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="border-t border-slate-800/80" />

            {/* ── Section 3: Retrieval ──────────────────────────────────── */}
            <div>
              <SectionLabel>Retrieval Anchors</SectionLabel>
              <p className="text-[10px] text-slate-600 mb-3 leading-relaxed">
                Web search will be biased toward these domains on the next generation.
                Broader web search is always preserved.
              </p>
              <TagInput
                value={srcInput}
                onChange={v => { setSrcInput(v); setSrcError(null); setSrcWarnOnly(false) }}
                onAdd={addSource}
                placeholder="e.g. arxiv.org or https://sec.gov"
                disabled={srcChecking}
                loading={srcChecking}
                buttonLabel={srcCheckPhase === "relevance" ? "Validating" : srcCheckPhase === "reachability" ? "Checking" : "Add"}
              />
              {srcError && (
                <div className="flex items-center gap-2 mt-1.5">
                  <p className="text-[11px] text-red-400">{srcError}</p>
                  {srcWarnOnly && (
                    <button
                      type="button"
                      onClick={forceAddSource}
                      className="text-[11px] text-slate-400 hover:text-slate-200 underline underline-offset-2 transition-colors flex-shrink-0"
                    >
                      Add anyway
                    </button>
                  )}
                </div>
              )}
              {preferredSources.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {preferredSources.map(domain => (
                    <Chip
                      key={domain}
                      label={domain}
                      variant="violet"
                      onRemove={() => setPreferredSources(prev => prev.filter(d => d !== domain))}
                    />
                  ))}
                </div>
              )}

              {ignoredSources.length > 0 && (
                <div className="mt-2.5">
                  <p className="text-[10px] text-slate-600 mb-1.5 flex items-center gap-1">
                    <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1ZM6.5 5.75a.75.75 0 0 0-1.5 0v.5c0 .414.336.75.75.75H6v3h-.25a.75.75 0 0 0 0 1.5h2.5a.75.75 0 0 0 0-1.5H8V5.75a.75.75 0 0 0-.75-.75H6.5ZM8 4a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" />
                    </svg>
                    Ignored — not relevant to this project
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {ignoredSources.map(domain => (
                      <span
                        key={domain}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-800/60 text-slate-500 text-xs border border-slate-700/40 line-through"
                      >
                        {domain}
                        <button
                          type="button"
                          onClick={() => promoteIgnored(domain)}
                          title="Add anyway"
                          className="text-slate-600 hover:text-slate-300 ml-0.5 no-underline leading-none transition-colors"
                          style={{ textDecoration: "none" }}
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          onClick={() => setIgnoredSources(prev => prev.filter(d => d !== domain))}
                          className="text-slate-600 hover:text-slate-400 ml-0.5 leading-none transition-colors"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="border-t border-slate-800/80" />

            {/* ── Section 4: Appearance ─────────────────────────────────── */}
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
          <div className="px-6 pb-5 flex gap-3 border-t border-slate-800/60 pt-4">
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
              disabled={saving || !name.trim()}
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

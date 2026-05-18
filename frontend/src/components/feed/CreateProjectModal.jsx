/**
 * CreateProjectModal — form for creating a new learning project.
 * Collects name, description, keywords, difficulty, focus areas, and color.
 */
import { useState } from "react"
import { checkSourceRelevance } from "../../api/projects.js"

const COLORS = [
  { id: "blue",    label: "Blue",    class: "bg-blue-500"    },
  { id: "emerald", label: "Green",   class: "bg-emerald-500" },
  { id: "violet",  label: "Violet",  class: "bg-violet-500"  },
  { id: "amber",   label: "Amber",   class: "bg-amber-500"   },
  { id: "rose",    label: "Rose",    class: "bg-rose-500"    },
]

const DIFFICULTY_OPTIONS = [
  { id: "beginner",     label: "Beginner",     desc: "New to this domain"           },
  { id: "intermediate", label: "Intermediate", desc: "Some background knowledge"    },
  { id: "advanced",     label: "Advanced",     desc: "Deep domain expertise"        },
]

const INTENSITY_OPTIONS = [
  { count: 2, label: "Light",     desc: "2 articles · focused depth"   },
  { count: 4, label: "Standard",  desc: "4 articles · balanced breadth" },
  { count: 6, label: "Intensive", desc: "6 articles · wide coverage"    },
]

const SUGGESTED_PROJECTS = [
  {
    name: "AI in Manufacturing",
    keywords: ["predictive maintenance", "industrial AI", "computer vision", "digital twin"],
    color: "blue",
    preferred_sources: ["huggingface.co", "arxiv.org", "github.com"],
  },
  {
    name: "Indian Pharma Exports",
    keywords: ["USFDA", "generics", "API manufacturing", "export regulations"],
    color: "emerald",
    preferred_sources: ["who.int", "fda.gov"],
  },
  {
    name: "Quantitative Finance",
    keywords: ["algorithmic trading", "risk modeling", "derivatives", "factor models"],
    color: "violet",
    preferred_sources: ["sec.gov", "federalreserve.gov"],
  },
  {
    name: "Supply Chain Intelligence",
    keywords: ["demand forecasting", "logistics AI", "nearshoring", "disruption risk"],
    color: "amber",
    preferred_sources: ["worldbank.org", "wto.org"],
  },
]

// ── Domain normalization helpers ───────────────────────────────────────────────

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

// ── Modal ─────────────────────────────────────────────────────────────────────

export default function CreateProjectModal({ onClose, onCreate, loading }) {
  const [name,             setName]             = useState("")
  const [description,      setDescription]      = useState("")
  const [keywords,         setKeywords]         = useState([])
  const [kwInput,          setKwInput]          = useState("")
  const [difficulty,       setDifficulty]       = useState("intermediate")
  const [focusAreas,       setFocusAreas]       = useState([])
  const [faInput,          setFaInput]          = useState("")
  const [color,            setColor]            = useState("blue")
  const [preferredSources,      setPreferredSources]      = useState([])
  const [ignoredSources,        setIgnoredSources]        = useState([])
  const [srcInput,              setSrcInput]              = useState("")
  const [srcError,              setSrcError]              = useState(null)
  const [srcChecking,           setSrcChecking]           = useState(false)
  const [srcCheckPhase,         setSrcCheckPhase]         = useState("")  // "reachability" | "relevance"
  const [srcWarnOnly,           setSrcWarnOnly]           = useState(false)
  const [dailyCoreArticleCount, setDailyCoreArticleCount] = useState(4)
  const [error,                 setError]                 = useState(null)

  function addKeyword() {
    const trimmed = kwInput.trim()
    if (trimmed && !keywords.includes(trimmed)) {
      setKeywords(prev => [...prev, trimmed])
    }
    setKwInput("")
  }

  function addFocusArea() {
    const trimmed = faInput.trim()
    if (trimmed && !focusAreas.includes(trimmed)) {
      setFocusAreas(prev => [...prev, trimmed])
    }
    setFaInput("")
  }

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
    const result = await checkSourceRelevance(domain, name.trim() || "this project", keywords)
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

  function removeKeyword(kw) { setKeywords(prev => prev.filter(k => k !== kw)) }
  function removeFocusArea(fa) { setFocusAreas(prev => prev.filter(f => f !== fa)) }
  function removeSource(s) { setPreferredSources(prev => prev.filter(d => d !== s)) }

  function applyTemplate(tmpl) {
    setName(tmpl.name)
    setKeywords(tmpl.keywords)
    setColor(tmpl.color)
    setKwInput("")
    if (tmpl.preferred_sources) setPreferredSources(tmpl.preferred_sources)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) { setError("Project name is required."); return }
    setError(null)
    await onCreate({
      name: name.trim(),
      description,
      keywords,
      difficulty,
      focus_areas: focusAreas,
      color,
      preferred_sources: preferredSources,
      ignored_sources: ignoredSources,
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

            {/* Quick templates */}
            <div>
              <p className="text-xs text-slate-500 mb-2">Start from a template</p>
              <div className="grid grid-cols-2 gap-2">
                {SUGGESTED_PROJECTS.map(t => (
                  <button
                    key={t.name}
                    type="button"
                    onClick={() => applyTemplate(t)}
                    className="text-left px-3 py-2 rounded-xl bg-slate-800/60 border border-slate-700/50 hover:border-slate-600 hover:bg-slate-800 transition-all"
                  >
                    <span className="text-xs text-slate-300 font-medium block">{t.name}</span>
                    <span className="text-[10px] text-slate-500">{t.keywords.slice(0, 2).join(", ")}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="border-t border-slate-800" />

            {/* Name */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Project Name *</label>
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="e.g. AI in Manufacturing"
                maxLength={80}
                className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
              />
            </div>

            {/* Description */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Description</label>
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder="What are you trying to learn or track?"
                rows={2}
                maxLength={300}
                className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 resize-none focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
              />
            </div>

            {/* Keywords */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Keywords</label>
              <div className="flex gap-2 mb-2">
                <input
                  value={kwInput}
                  onChange={e => setKwInput(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addKeyword() } }}
                  placeholder="Add keyword, press Enter"
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
                  {keywords.map(kw => (
                    <span key={kw} className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-blue-900/40 text-blue-300 text-xs border border-blue-800/40">
                      {kw}
                      <button type="button" onClick={() => removeKeyword(kw)} className="text-blue-400 hover:text-blue-200 ml-0.5">×</button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Difficulty */}
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

            {/* Daily Intensity */}
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

            {/* Focus areas */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Focus Areas <span className="text-slate-600 font-normal">(optional)</span></label>
              <div className="flex gap-2 mb-2">
                <input
                  value={faInput}
                  onChange={e => setFaInput(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addFocusArea() } }}
                  placeholder="e.g. Predictive Maintenance"
                  className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50"
                />
                <button
                  type="button"
                  onClick={addFocusArea}
                  className="px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm transition-colors"
                >
                  Add
                </button>
              </div>
              {focusAreas.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {focusAreas.map(fa => (
                    <span key={fa} className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-800 text-slate-300 text-xs border border-slate-700/50">
                      {fa}
                      <button type="button" onClick={() => removeFocusArea(fa)} className="text-slate-500 hover:text-slate-300 ml-0.5">×</button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Preferred Sources */}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-0.5">
                Preferred Sources
                <span className="text-slate-600 font-normal ml-1">(optional)</span>
              </label>
              <p className="text-[10px] text-slate-600 mb-2 leading-relaxed">
                Domains added here are treated as trusted retrieval anchors — web search will be
                biased toward them while still searching broadly.
              </p>
              <div className="flex gap-2 mb-1.5">
                <input
                  value={srcInput}
                  onChange={e => { setSrcInput(e.target.value); setSrcError(null); setSrcWarnOnly(false) }}
                  onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addSource() } }}
                  placeholder="e.g. arxiv.org or https://sec.gov"
                  disabled={srcChecking}
                  className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50 disabled:opacity-50"
                />
                <button
                  type="button"
                  onClick={addSource}
                  disabled={srcChecking}
                  className="min-w-[64px] px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
                >
                  {srcChecking ? (
                    <>
                      <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                        <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      {srcCheckPhase === "relevance" ? "Validating" : "Checking"}
                    </>
                  ) : "Add"}
                </button>
              </div>
              {srcError && (
                <div className="mb-1.5 flex items-center gap-2">
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
                <div className="flex flex-wrap gap-1.5">
                  {preferredSources.map(domain => (
                    <span
                      key={domain}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-violet-900/30 text-violet-300 text-xs border border-violet-800/40"
                    >
                      <svg className="w-2.5 h-2.5 text-violet-500 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Zm4-1.25a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM10.5 8a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM7.25 10.5a.75.75 0 1 1 1.5 0 .75.75 0 0 1-1.5 0Z" />
                      </svg>
                      {domain}
                      <button
                        type="button"
                        onClick={() => removeSource(domain)}
                        className="text-violet-400 hover:text-violet-200 ml-0.5 leading-none"
                        aria-label={`Remove ${domain}`}
                      >
                        ×
                      </button>
                    </span>
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
                          aria-label={`Remove ${domain}`}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Color */}
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
              disabled={loading || !name.trim()}
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

/**
 * OnboardingModal — 3-step first-run flow.
 *
 * Step 0 — Project:  title + description
 * Step 1 — Topics:   AI-suggested keywords (POST /projects/suggest-keywords) + custom
 * Step 2 — Launch:   level · project name · color → generate Day 1
 */
import { useState, useEffect } from "react"
import { suggestKeywords } from "../../api/projects.js"
import { ONBOARDING_STEPS, onboardingStepIndex } from "../../utils/onboardingRoute.js"

// ── localStorage helpers ──────────────────────────────────────────────────────

const ONBOARDING_KEY = (userId) => userId ? `ra_onboarding_done_${userId}` : "ra_onboarding_done"
export const hasCompletedOnboarding = (userId) => localStorage.getItem(ONBOARDING_KEY(userId)) === "1"
export const markOnboardingDone     = (userId) => localStorage.setItem(ONBOARDING_KEY(userId), "1")

// ── sessionStorage draft — survives a hard refresh mid-onboarding ─────────────

const DRAFT_KEY = (userId) => userId ? `ra_onboarding_draft_${userId}` : "ra_onboarding_draft"

function loadDraft(userId) {
  try { return JSON.parse(sessionStorage.getItem(DRAFT_KEY(userId)) || "null") } catch { return null }
}
function saveDraft(userId, draft) {
  try { sessionStorage.setItem(DRAFT_KEY(userId), JSON.stringify(draft)) } catch { /* storage unavailable */ }
}
function clearDraft(userId) {
  try { sessionStorage.removeItem(DRAFT_KEY(userId)) } catch { /* storage unavailable */ }
}

// ── Style maps ────────────────────────────────────────────────────────────────

const CHIP = {
  blue:  { sel: "bg-blue-500/15 border-blue-500/50 text-blue-300",  unsel: "hover:border-blue-700/50 hover:text-blue-400" },
  slate: { sel: "bg-slate-500/15 border-slate-500/50 text-slate-300", unsel: "hover:border-slate-600/50 hover:text-slate-300" },
}

const COLORS = [
  { id: "blue",    cls: "bg-blue-500"    },
  { id: "emerald", cls: "bg-emerald-500" },
  { id: "violet",  cls: "bg-violet-500"  },
  { id: "amber",   cls: "bg-amber-500"   },
  { id: "rose",    cls: "bg-rose-500"    },
]

const DIFFICULTY = [
  {
    id: "beginner", label: "Beginner", tag: "New to this domain",
    detail: "Foundational vocabulary and mental models — no assumed expertise.",
    icon: (
      <svg className="w-4 h-4 sm:w-5 sm:h-5" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M9.664 1.319a.75.75 0 0 1 .672 0 41.059 41.059 0 0 1 8.198 5.424.75.75 0 0 1-.254 1.285 31.372 31.372 0 0 0-7.86 3.83.75.75 0 0 1-.84 0 31.508 31.508 0 0 0-2.08-1.287V9.394c0-.244.116-.463.315-.6a32.442 32.442 0 0 1 3.08-1.9l-5.95 3.03-.034.018A4.152 4.152 0 0 0 2.003 14c0 .494.08.972.229 1.417a.75.75 0 0 1-1.428.462 5.648 5.648 0 0 1-.301-1.879c0-2.239 1.317-4.18 3.229-5.066L9.664 1.319Z" clipRule="evenodd" />
        <path d="M9.161 17.478a31.617 31.617 0 0 1-5.813-3.637A4.126 4.126 0 0 0 2 17.25c0 .828.252 1.599.685 2.236A17.585 17.585 0 0 0 9.25 21.5a17.585 17.585 0 0 0 6.565-2.014 4.126 4.126 0 0 0-1.348-3.41 31.503 31.503 0 0 1-5.306 3.442Z" />
      </svg>
    ),
  },
  {
    id: "intermediate", label: "Intermediate", tag: "Some background knowledge",
    detail: "Dives into mechanisms, tradeoffs, and real-world applications.",
    icon: (
      <svg className="w-4 h-4 sm:w-5 sm:h-5" viewBox="0 0 20 20" fill="currentColor">
        <path d="M15.98 1.804a1 1 0 0 0-1.96 0l-.24 1.192a1 1 0 0 1-.784.785l-1.192.238a1 1 0 0 0 0 1.962l1.192.238a1 1 0 0 1 .785.785l.238 1.192a1 1 0 0 0 1.962 0l.238-1.192a1 1 0 0 1 .785-.785l1.192-.238a1 1 0 0 0 0-1.962l-1.192-.238a1 1 0 0 1-.785-.785l-.238-1.192ZM6.949 5.684a1 1 0 0 0-1.898 0l-.683 2.051a1 1 0 0 1-.633.633l-2.051.683a1 1 0 0 0 0 1.898l2.051.684a1 1 0 0 1 .633.632l.683 2.051a1 1 0 0 0 1.898 0l.683-2.051a1 1 0 0 1 .633-.633l2.051-.683a1 1 0 0 0 0-1.898l-2.051-.683a1 1 0 0 1-.633-.633L6.95 5.684Z" />
        <path d="M13.949 13.684a1 1 0 0 0-1.898 0l-.184.551a1 1 0 0 1-.632.633l-.551.183a1 1 0 0 0 0 1.898l.551.183a1 1 0 0 1 .633.633l.183.551a1 1 0 0 0 1.898 0l.184-.551a1 1 0 0 1 .632-.633l.551-.183a1 1 0 0 0 0-1.898l-.551-.184a1 1 0 0 1-.633-.632l-.183-.551Z" />
      </svg>
    ),
  },
  {
    id: "advanced", label: "Advanced", tag: "Deep domain expertise",
    detail: "Latest research, nuanced analysis, practitioner-level context.",
    icon: (
      <svg className="w-4 h-4 sm:w-5 sm:h-5" viewBox="0 0 20 20" fill="currentColor">
        <path d="M10.75 2.75a.75.75 0 0 0-1.5 0v8.614L6.295 8.235a.75.75 0 1 0-1.09 1.03l4.25 4.5a.75.75 0 0 0 1.09 0l4.25-4.5a.75.75 0 0 0-1.09-1.03l-2.955 3.129V2.75Z" />
        <path d="M3.5 12.75a.75.75 0 0 0-1.5 0v2.5A2.75 2.75 0 0 0 4.75 18h10.5A2.75 2.75 0 0 0 18 15.25v-2.5a.75.75 0 0 0-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5Z" />
      </svg>
    ),
  },
]

// ── Step indicator — compact on mobile, full on desktop ───────────────────────

function StepDots({ step, onBack }) {
  const labels = ["Project", "Topics", "Launch"]
  return (
    <div className="flex items-center">
      {labels.map((label, i) => (
        <div key={i} className="flex items-center">
          <div
            className={`flex items-center gap-1 sm:gap-2 ${i < step ? "cursor-pointer" : ""}`}
            onClick={() => i < step && onBack(i)}
          >
            <div className={`w-5 h-5 sm:w-6 sm:h-6 rounded-full flex items-center justify-center text-[10px] sm:text-[11px] font-bold transition-all flex-shrink-0 ${
              i < step   ? "bg-blue-600 text-white" :
              i === step ? "bg-blue-500 text-white ring-2 ring-blue-400/25" :
                           "bg-slate-800 text-slate-600"
            }`}>
              {i < step ? (
                <svg className="w-2.5 h-2.5" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2 6l3 3 5-5" />
                </svg>
              ) : i + 1}
            </div>
            <span className={`text-[10px] sm:text-xs font-medium ${i === step ? "text-slate-300" : i < step ? "text-slate-500" : "text-slate-700"}`}>
              {label}
            </span>
          </div>
          {i < labels.length - 1 && (
            <div className={`w-2 sm:w-6 mx-1 sm:mx-2 h-px rounded-full ${i < step ? "bg-blue-600" : "bg-slate-800"}`} />
          )}
        </div>
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function OnboardingModal({ onCreate, creating, userId, step: stepSlug, onGoToStep, onBack }) {
  const step = onboardingStepIndex(stepSlug)
  const [draft] = useState(() => loadDraft(userId))

  // Step 0 — project title + description
  const [title,         setTitle]         = useState(draft?.title ?? "")
  const [description,   setDescription]   = useState(draft?.description ?? "")

  // Step 1 — suggested + custom keywords
  const [suggested,     setSuggested]     = useState(draft?.suggested ?? [])
  // title+description pair the current `suggested` list was generated for —
  // lets the fetch effect skip regenerating when neither has changed.
  const [suggestedFor,  setSuggestedFor]  = useState(draft?.suggestedFor ?? null)
  const [customKeywords, setCustomKeywords] = useState(draft?.customKeywords ?? [])
  const [selected,      setSelected]      = useState(new Set(draft?.selected ?? []))
  const [kwInput,       setKwInput]       = useState("")
  const [suggestLoading, setSuggestLoading] = useState(false)
  const [suggestError,  setSuggestError]  = useState(null)

  // Step 2 — level + name + color
  const [difficulty,    setDifficulty]    = useState(draft?.difficulty ?? "intermediate")
  const [articleCount,  setArticleCount]  = useState(draft?.articleCount ?? 4)
  const [name,          setName]          = useState(draft?.name ?? "")
  const [color,         setColor]         = useState(draft?.color ?? "blue")

  const canProceedFromIntro = title.trim().length > 0 && description.trim().length >= 10

  // Persist the draft as the user types, so a hard refresh mid-onboarding
  // doesn't lose it. Cleared on successful launch (see handleLaunch).
  useEffect(() => {
    saveDraft(userId, { title, description, suggested, suggestedFor, customKeywords, selected: [...selected], difficulty, articleCount, name, color })
  }, [userId, title, description, suggested, suggestedFor, customKeywords, selected, difficulty, articleCount, name, color])

  // Landed directly on a later step (stale link) with nothing filled in —
  // bounce to the start instead of showing an empty Topics/Launch step.
  useEffect(() => {
    if (step > 0 && !title.trim()) onGoToStep("project")
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Fetch suggested keywords on entering the Topics step — but only when
  // title/description actually changed since the last generation, so
  // revisiting this step unchanged (e.g. via Back) doesn't re-hit the LLM.
  useEffect(() => {
    if (step !== 1 || suggestLoading) return
    const forKey = `${title.trim()} ${description.trim()}`
    if (suggestedFor === forKey) return
    let cancelled = false
    setSuggestLoading(true)
    setSuggestError(null)
    suggestKeywords(title.trim(), description.trim(), "intermediate")
      .then(result => {
        if (cancelled) return
        const kws = result?.keywords || []
        setSuggested(kws)
        setSuggestedFor(forKey)
        // A restored draft already carries the user's chosen selection —
        // only default to "select everything" on a fresh onboarding start.
        if (!draft) setSelected(new Set(kws))
      })
      .catch(() => {
        if (cancelled) return
        setSuggestError("Topic suggestions didn't load — add your own keywords below.")
      })
      .finally(() => { if (!cancelled) setSuggestLoading(false) })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step])

  function goToStep(n) {
    if (n === 2 && !name.trim()) setName(title.trim())
    onGoToStep(ONBOARDING_STEPS[n])
  }

  function addCustomKeyword() {
    const label = kwInput.trim()
    if (!label) return
    const exists = [...suggested, ...customKeywords].some(k => k.toLowerCase() === label.toLowerCase())
    if (!exists) {
      setCustomKeywords(prev => [...prev, label])
      setSelected(prev => new Set(prev).add(label))
    }
    setKwInput("")
  }

  function toggleKeyword(kw) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(kw) ? next.delete(kw) : next.add(kw)
      return next
    })
  }

  async function handleLaunch() {
    const finalName = name.trim() || title.trim() || "My Learning Project"
    const finalKeywords = [...suggested, ...customKeywords].filter(k => selected.has(k))
    markOnboardingDone(userId)
    clearDraft(userId)
    await onCreate({
      name:                     finalName,
      description:              description.trim(),
      keywords:                 finalKeywords,
      difficulty,
      color,
      daily_core_article_count: articleCount,
    })
  }

  const canProceedFromTopics = selected.size > 0

  return (
    // Mobile: fullscreen. Desktop: centered dialog with backdrop.
    <div
      className="fixed inset-0 z-50 md:flex md:items-center md:justify-center md:px-4"
      style={{ background: "rgba(2,6,23,0.92)", backdropFilter: "blur(10px)" }}
    >
      <div className="
        w-full h-full flex flex-col
        md:h-auto md:max-h-[90vh] md:max-w-2xl
        bg-slate-900
        md:border md:border-slate-700/60 md:rounded-3xl md:shadow-2xl md:shadow-black/70
      ">

        {/* ── Header ── */}
        <div className="px-4 sm:px-8 pt-5 sm:pt-7 pb-4 sm:pb-5 flex-shrink-0">
          {/* Branding */}
          <div className="flex items-center gap-2 mb-4 sm:mb-6">
            <div className="w-6 h-6 sm:w-7 sm:h-7 rounded-xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center shadow-lg shadow-violet-900/40">
              <svg className="w-3 h-3 sm:w-3.5 sm:h-3.5 text-white" viewBox="0 0 16 16" fill="currentColor">
                <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
              </svg>
            </div>
            <span className="text-[12px] sm:text-[13px] font-semibold text-slate-400 tracking-tight">Curivio</span>
          </div>

          {/* Step heading */}
          <div className="mb-4 sm:mb-5">
            {step === 0 && (
              <>
                <h1 className="text-[16px] sm:text-[22px] font-bold text-slate-100 leading-tight mb-1">What do you want to learn?</h1>
                <p className="text-[13px] sm:text-sm text-slate-500 leading-snug">Give your project a title and tell us what you're after — we'll suggest topics from it.</p>
              </>
            )}
            {step === 1 && (
              <>
                <h1 className="text-[16px] sm:text-[22px] font-bold text-slate-100 leading-tight mb-1">Here are your suggested topics</h1>
                <p className="text-[13px] sm:text-sm text-slate-500 leading-snug">Deselect any you don't want, or add your own.</p>
              </>
            )}
            {step === 2 && (
              <>
                <h1 className="text-[16px] sm:text-[22px] font-bold text-slate-100 leading-tight mb-1">Almost there — set your level</h1>
                <p className="text-[13px] sm:text-sm text-slate-500 leading-snug">This shapes how deep and technical your daily cards get.</p>
              </>
            )}
          </div>

          <StepDots step={step} onBack={goToStep} />
        </div>

        {/* ── Scrollable body ── */}
        <div className="flex-1 overflow-y-auto px-4 sm:px-8 pb-2 min-h-0">

          {/* Step 0 — Project title + description */}
          {step === 0 && (
            <div className="space-y-4 pb-2">
              <div>
                <input
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  placeholder="e.g. AI in healthcare, Indian pharma, Chess strategy…"
                  maxLength={80}
                  className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
                />
              </div>
              <div>
                <label className="block text-[11px] sm:text-xs font-medium text-slate-400 mb-1.5">Describe what you want from this project.</label>
                <textarea
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  placeholder="e.g. &quot;Teach me the fundamentals of machine learning from scratch&quot; or &quot;Keep me updated on the latest developments in AI regulation.&quot;"
                  rows={4}
                  maxLength={300}
                  className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 resize-none focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
                />
              </div>
            </div>
          )}

          {/* Step 1 — Suggested + custom keywords */}
          {step === 1 && (
            <div className="space-y-4 pb-2">
              {suggestLoading && (
                <div className="flex items-center gap-2.5 text-[13px] text-slate-500 py-2">
                  <svg className="w-3.5 h-3.5 animate-spin flex-shrink-0" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                    <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Finding the right topics…
                </div>
              )}

              {suggestError && (
                <p className="text-[11px] text-amber-400">{suggestError}</p>
              )}

              {suggested.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {suggested.map(kw => {
                    const isOn = selected.has(kw)
                    return (
                      <button
                        key={kw}
                        type="button"
                        onClick={() => toggleKeyword(kw)}
                        className={`px-3.5 sm:px-4 py-2 rounded-xl text-[13px] font-medium border transition-all active:scale-95 ${
                          isOn ? CHIP.blue.sel : `bg-slate-800/50 border-slate-700/50 text-slate-400 ${CHIP.blue.unsel}`
                        }`}
                      >
                        {kw}
                      </button>
                    )
                  })}
                </div>
              )}

              {/* Custom keywords */}
              <div className={suggested.length > 0 ? "pt-3 border-t border-slate-800/60" : ""}>
                {suggested.length > 0 && (
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-2.5">Add your own keywords</p>
                )}
                <div className="flex flex-wrap gap-2">
                  {customKeywords.map(kw => {
                    const isOn = selected.has(kw)
                    return (
                      <button
                        key={kw}
                        type="button"
                        onClick={() => toggleKeyword(kw)}
                        className={`px-3.5 sm:px-4 py-2 rounded-xl text-[13px] font-medium border transition-all active:scale-95 ${
                          isOn ? CHIP.slate.sel : `bg-slate-800/50 border-slate-700/50 text-slate-400 ${CHIP.slate.unsel}`
                        }`}
                      >
                        {kw}
                      </button>
                    )
                  })}
                  <div className="flex items-center gap-2 w-full sm:w-auto">
                    <input
                      type="text"
                      value={kwInput}
                      onChange={e => setKwInput(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addCustomKeyword() } }}
                      placeholder="Type a topic or keyword…"
                      maxLength={40}
                      className="flex-1 sm:flex-none sm:w-44 px-3.5 py-2 rounded-xl text-[13px] bg-slate-800/50 border border-slate-700/50 text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-500 min-w-0"
                    />
                    {kwInput.trim() && (
                      <button
                        type="button"
                        onClick={addCustomKeyword}
                        className="px-3 py-2 rounded-xl text-[13px] font-semibold bg-slate-700 hover:bg-slate-600 text-slate-200 border border-slate-600 transition-colors flex-shrink-0"
                      >
                        +
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {selected.size === 0 && !suggestLoading && (
                <p className="text-xs text-slate-600 pt-1">Select at least one topic to continue</p>
              )}
            </div>
          )}

          {/* Step 2 — Level + Name + Color */}
          {step === 2 && (
            <div className="space-y-4 sm:space-y-5 pb-2">

              {/* Difficulty */}
              <div className="space-y-2">
                {DIFFICULTY.map(opt => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setDifficulty(opt.id)}
                    className={`w-full flex items-center gap-3 sm:gap-4 px-4 sm:px-5 py-3 sm:py-4 rounded-2xl border text-left transition-all active:scale-[0.99] ${
                      difficulty === opt.id
                        ? "bg-slate-800 border-slate-500/70 ring-1 ring-blue-500/25"
                        : "bg-slate-800/40 border-slate-700/50 hover:border-slate-600 hover:bg-slate-800/60"
                    }`}
                  >
                    <div className={`flex-shrink-0 w-8 h-8 sm:w-9 sm:h-9 rounded-xl flex items-center justify-center transition-all ${
                      difficulty === opt.id ? "bg-blue-500/20 text-blue-400" : "bg-slate-800 text-slate-500"
                    }`}>
                      {opt.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline gap-1.5 sm:gap-2 flex-wrap">
                        <span className="font-semibold text-slate-100 text-[13px] sm:text-sm">{opt.label}</span>
                        <span className="text-[11px] text-slate-500">{opt.tag}</span>
                      </div>
                      <p className="text-[11px] sm:text-[12px] text-slate-500 leading-relaxed mt-0.5 line-clamp-1 sm:line-clamp-none">{opt.detail}</p>
                    </div>
                    <div className={`flex-shrink-0 w-4 h-4 rounded-full border-2 flex items-center justify-center transition-all ${
                      difficulty === opt.id ? "border-blue-500 bg-blue-500" : "border-slate-600"
                    }`}>
                      {difficulty === opt.id && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                    </div>
                  </button>
                ))}
              </div>

              {/* Daily Learning Intensity */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-[11px] sm:text-xs font-medium text-slate-400">Daily Learning Intensity</label>
                  <span className="text-[11px] sm:text-xs font-semibold text-slate-200">{articleCount} article{articleCount !== 1 ? "s" : ""}/day</span>
                </div>
                <input
                  type="range"
                  min={3}
                  max={10}
                  step={1}
                  value={articleCount}
                  onChange={e => setArticleCount(Number(e.target.value))}
                  className="w-full accent-blue-500"
                />
                <div className="flex justify-between text-[10px] text-slate-600 mt-1">
                  <span>Light</span>
                  <span>Intensive</span>
                </div>
              </div>

              {/* Summary chip strip */}
              <div className="px-3.5 sm:px-4 py-3 rounded-2xl bg-slate-800/40 border border-slate-700/40">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-2">Your selections</p>
                <div className="flex flex-wrap gap-1.5">
                  {[...selected].map(kw => {
                    const isCustomKw = customKeywords.includes(kw) && !suggested.includes(kw)
                    const c = CHIP[isCustomKw ? "slate" : "blue"]
                    return (
                      <span key={kw} className={`px-2.5 py-1 rounded-lg text-[11px] font-medium border ${c.sel}`}>
                        {kw}
                      </span>
                    )
                  })}
                </div>
              </div>

              {/* Project name */}
              <div>
                <label className="block text-[11px] sm:text-xs font-medium text-slate-400 mb-1.5">Project name</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder={title || "My Learning Project"}
                  maxLength={80}
                  className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
                />
              </div>

              {/* Color */}
              <div>
                <label className="block text-[11px] sm:text-xs font-medium text-slate-400 mb-2">Accent color</label>
                <div className="flex gap-3">
                  {COLORS.map(c => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => setColor(c.id)}
                      className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full ${c.cls} transition-all ${
                        color === c.id
                          ? "ring-2 ring-white/60 ring-offset-2 ring-offset-slate-900 scale-110"
                          : "opacity-40 hover:opacity-70"
                      }`}
                    />
                  ))}
                </div>
              </div>

              {/* What happens next */}
              <div className="flex items-start gap-2.5 sm:gap-3 px-3.5 sm:px-4 py-3 rounded-2xl bg-blue-950/30 border border-blue-900/40">
                <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-blue-400 flex-shrink-0 mt-0.5" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM6.5 5.75a.75.75 0 0 0-1.5 0v.5c0 .414.336.75.75.75H6v3h-.25a.75.75 0 0 0 0 1.5h2.5a.75.75 0 0 0 0-1.5H8V5.75a.75.75 0 0 0-.75-.75H6.5ZM8 4a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" />
                </svg>
                <p className="text-[11px] sm:text-[12px] text-slate-400 leading-relaxed">
                  We'll plan a personalised learning path, then build your <span className="text-slate-200 font-medium">Day 1 brief</span> — news, deep-dives, and curiosity picks — in the background. It usually takes a minute or two; once it's ready, <span className="text-slate-200 font-medium">Your Path</span> will show what's coming next.
                </p>
              </div>
            </div>
          )}

        </div>

        {/* ── Footer — fixed at bottom, lightweight on mobile ── */}
        <div className="
          px-4 sm:px-8 py-3 sm:py-5
          border-t border-slate-800/70
          flex-shrink-0 flex items-center justify-between gap-3
          bg-slate-900/95 backdrop-blur-sm
        ">
          <button
            type="button"
            onClick={() => step > 0 && onBack()}
            className={`text-[13px] sm:text-sm text-slate-500 hover:text-slate-300 transition-colors ${step === 0 ? "invisible pointer-events-none" : ""}`}
          >
            ← Back
          </button>

          {step === 0 && (
            <div className="flex items-center gap-2.5">
              {!canProceedFromIntro && <span className="text-[11px] text-slate-600 hidden sm:block">Add a title and description to continue</span>}
              <button
                type="button"
                onClick={() => goToStep(1)}
                disabled={!canProceedFromIntro}
                className="px-5 sm:px-6 py-2 sm:py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-[13px] sm:text-sm font-medium transition-colors disabled:opacity-35 disabled:cursor-not-allowed"
              >
                Continue →
              </button>
            </div>
          )}

          {step === 1 && (
            <div className="flex items-center gap-2.5">
              {!canProceedFromTopics && <span className="text-[11px] text-slate-600 hidden sm:block">Select at least one topic</span>}
              <button
                type="button"
                onClick={() => goToStep(2)}
                disabled={!canProceedFromTopics}
                className="px-5 sm:px-6 py-2 sm:py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-[13px] sm:text-sm font-medium transition-colors disabled:opacity-35 disabled:cursor-not-allowed"
              >
                {canProceedFromTopics
                  ? `Continue (${selected.size}) →`
                  : "Continue →"}
              </button>
            </div>
          )}

          {step === 2 && (
            <button
              type="button"
              onClick={handleLaunch}
              disabled={creating || !(name.trim() || title.trim())}
              className="flex items-center gap-2 px-5 sm:px-6 py-2 sm:py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-[13px] sm:text-sm font-medium transition-colors disabled:opacity-35 disabled:cursor-not-allowed"
            >
              {creating ? (
                <>
                  <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                    <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Creating…
                </>
              ) : "Create & Generate Day 1 →"}
            </button>
          )}
        </div>

      </div>
    </div>
  )
}

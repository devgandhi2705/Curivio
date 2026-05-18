/**
 * OnboardingModal — redesigned 3-step first-run flow.
 *
 * Step 0 — Domain:  pick one domain to focus on
 * Step 1 — Topics:  pick topics within that domain + custom keywords
 * Step 2 — Launch:  level · project name · color → generate Day 1
 */
import { useState, useMemo } from "react"

// ── localStorage helpers ──────────────────────────────────────────────────────

const ONBOARDING_KEY = (userId) => userId ? `ra_onboarding_done_${userId}` : "ra_onboarding_done"
export const hasCompletedOnboarding = (userId) => localStorage.getItem(ONBOARDING_KEY(userId)) === "1"
export const markOnboardingDone     = (userId) => localStorage.setItem(ONBOARDING_KEY(userId), "1")

// ── Domain + topic catalogue ──────────────────────────────────────────────────

const TOPIC_GROUPS = [
  {
    id: "tech", label: "Technology", color: "blue",
    description: "AI, cybersecurity, robotics, space & chips",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
        <path fillRule="evenodd" d="M6.28 5.22a.75.75 0 0 1 0 1.06L2.56 10l3.72 3.72a.75.75 0 0 1-1.06 1.06L.97 10.53a.75.75 0 0 1 0-1.06l4.25-4.25a.75.75 0 0 1 1.06 0Zm7.44 0a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L17.44 10l-3.72-3.72a.75.75 0 0 1 0-1.06ZM11.377 2.011a.75.75 0 0 1 .612.867l-2.5 14.5a.75.75 0 0 1-1.478-.255l2.5-14.5a.75.75 0 0 1 .866-.612Z" clipRule="evenodd" />
      </svg>
    ),
    topics: [
      { id: "ai",       label: "Artificial Intelligence", keywords: ["machine learning", "large language models", "AI research", "deep learning", "generative AI"] },
      { id: "cyber",    label: "Cybersecurity",           keywords: ["threat intelligence", "data breaches", "zero-day vulnerabilities", "encryption", "ransomware"] },
      { id: "robotics", label: "Robotics & Automation",   keywords: ["industrial robots", "autonomous systems", "drone technology", "automation", "cobots"] },
      { id: "space",    label: "Space Technology",        keywords: ["satellite technology", "space exploration", "SpaceX", "rocket propulsion", "NASA"] },
      { id: "chips",    label: "Semiconductors",          keywords: ["chip design", "TSMC", "GPU", "photonics", "Moore's law", "EDA tools"] },
    ],
  },
  {
    id: "finance", label: "Finance", color: "emerald",
    description: "Quant trading, venture capital, crypto & markets",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
        <path fillRule="evenodd" d="M12 7a1 1 0 1 1 2 0v6a1 1 0 1 1-2 0V7Zm-4 4a1 1 0 1 1 2 0v2a1 1 0 1 1-2 0v-2ZM4 9a1 1 0 1 1 2 0v4a1 1 0 1 1-2 0V9Zm14 8H2a.75.75 0 0 0 0 1.5h16a.75.75 0 0 0 0-1.5Z" clipRule="evenodd" />
      </svg>
    ),
    topics: [
      { id: "quant",   label: "Quantitative Finance", keywords: ["algorithmic trading", "risk modeling", "derivatives", "factor models", "quant strategies"] },
      { id: "vc",      label: "Venture Capital",      keywords: ["startup funding", "unicorns", "term sheets", "exit strategies", "VC deals"] },
      { id: "crypto",  label: "Crypto & Web3",        keywords: ["blockchain", "DeFi", "Ethereum", "Bitcoin", "smart contracts", "stablecoins"] },
      { id: "markets", label: "Global Markets",       keywords: ["macroeconomics", "Fed policy", "forex", "equity markets", "interest rates"] },
    ],
  },
  {
    id: "science", label: "Science", color: "violet",
    description: "Biotech, climate, neuroscience & quantum",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
        <path fillRule="evenodd" d="M8.5 3.528v4.644c0 .729-.29 1.429-.805 1.944l-1.217 1.217a7.5 7.5 0 1 0 10.063 0l-1.217-1.217A2.75 2.75 0 0 1 14.5 8.172V3.528a.75.75 0 0 1 .75-.75h.25a.75.75 0 0 0 0-1.5h-6a.75.75 0 0 0 0 1.5h.25a.75.75 0 0 1 .75.75Z" clipRule="evenodd" />
      </svg>
    ),
    topics: [
      { id: "biotech",  label: "Biotech & Life Sciences", keywords: ["CRISPR", "gene therapy", "mRNA", "drug discovery", "clinical trials", "synthetic biology"] },
      { id: "climate",  label: "Climate & Energy",        keywords: ["climate change", "renewable energy", "carbon capture", "EV adoption", "grid storage"] },
      { id: "neuro",    label: "Neuroscience",            keywords: ["brain-computer interfaces", "cognitive science", "neurotechnology", "Neuralink"] },
      { id: "quantum",  label: "Quantum Computing",       keywords: ["quantum algorithms", "quantum hardware", "error correction", "qubits", "quantum supremacy"] },
    ],
  },
  {
    id: "business", label: "Business", color: "amber",
    description: "Supply chain, strategy, M&A & industrial AI",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
        <path d="M6 5a3 3 0 0 0-3 3v.75H1.75a.75.75 0 0 0 0 1.5H3V14a3 3 0 0 0 3 3h8a3 3 0 0 0 3-3v-3.75h1.25a.75.75 0 0 0 0-1.5H17V8a3 3 0 0 0-3-3H6Zm9.5 5.25V14a1.5 1.5 0 0 1-1.5 1.5H6A1.5 1.5 0 0 1 4.5 14v-3.75h11Z" />
      </svg>
    ),
    topics: [
      { id: "supply",      label: "Supply Chain",   keywords: ["demand forecasting", "logistics AI", "nearshoring", "disruption risk", "inventory management"] },
      { id: "india",       label: "Indian Economy", keywords: ["USFDA", "manufacturing India", "PLI scheme", "Indian startups", "RBI policy"] },
      { id: "strategy",    label: "Strategy & M&A", keywords: ["corporate strategy", "mergers acquisitions", "leadership", "organizational design"] },
      { id: "ai_industry", label: "AI in Industry", keywords: ["predictive maintenance", "industrial AI", "computer vision", "digital twin", "smart manufacturing"] },
    ],
  },
  {
    id: "policy", label: "Policy & Society", color: "rose",
    description: "Geopolitics, tech regulation & healthcare policy",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
        <path fillRule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-7-4a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM9 9a.75.75 0 0 0 0 1.5h.253a.25.25 0 0 1 .244.304l-.459 2.066A1.75 1.75 0 0 0 10.747 15H11a.75.75 0 0 0 0-1.5h-.253a.25.25 0 0 1-.244-.304l.459-2.066A1.75 1.75 0 0 0 9.253 9H9Z" clipRule="evenodd" />
      </svg>
    ),
    topics: [
      { id: "geopolitics", label: "Geopolitics",       keywords: ["US-China relations", "NATO", "trade wars", "sanctions", "emerging markets"] },
      { id: "tech_reg",    label: "Tech Regulation",   keywords: ["AI regulation", "antitrust", "data privacy", "GDPR", "digital markets act"] },
      { id: "healthcare",  label: "Healthcare Policy", keywords: ["drug pricing", "healthcare reform", "medical regulation", "FDA approvals"] },
    ],
  },
]

const CUSTOM_DOMAIN_ID = "custom"

// ── Style maps ────────────────────────────────────────────────────────────────

const CHIP = {
  blue:    { sel: "bg-blue-500/15 border-blue-500/50 text-blue-300",    unsel: "hover:border-blue-700/50 hover:text-blue-400",    dot: "bg-blue-500",    ring: "ring-blue-500/30",    card: "border-blue-500/50 bg-blue-500/8"  },
  emerald: { sel: "bg-emerald-500/15 border-emerald-500/50 text-emerald-300", unsel: "hover:border-emerald-700/50 hover:text-emerald-400", dot: "bg-emerald-500", ring: "ring-emerald-500/30", card: "border-emerald-500/50 bg-emerald-500/8" },
  violet:  { sel: "bg-violet-500/15 border-violet-500/50 text-violet-300",  unsel: "hover:border-violet-700/50 hover:text-violet-400",  dot: "bg-violet-500",  ring: "ring-violet-500/30",  card: "border-violet-500/50 bg-violet-500/8"  },
  amber:   { sel: "bg-amber-500/15 border-amber-500/50 text-amber-300",    unsel: "hover:border-amber-700/50 hover:text-amber-400",    dot: "bg-amber-500",   ring: "ring-amber-500/30",   card: "border-amber-500/50 bg-amber-500/8"   },
  rose:    { sel: "bg-rose-500/15 border-rose-500/50 text-rose-300",      unsel: "hover:border-rose-700/50 hover:text-rose-400",      dot: "bg-rose-500",    ring: "ring-rose-500/30",    card: "border-rose-500/50 bg-rose-500/8"     },
  slate:   { sel: "bg-slate-500/15 border-slate-500/50 text-slate-300",   unsel: "hover:border-slate-600/50 hover:text-slate-300",    dot: "bg-slate-400",   ring: "ring-slate-500/30",   card: "border-slate-600/50 bg-slate-800/40"  },
}

const ICON_BG = {
  blue:    "bg-blue-500/20 text-blue-400",
  emerald: "bg-emerald-500/20 text-emerald-400",
  violet:  "bg-violet-500/20 text-violet-400",
  amber:   "bg-amber-500/20 text-amber-400",
  rose:    "bg-rose-500/20 text-rose-400",
  slate:   "bg-slate-700/60 text-slate-400",
}

const COLORS = [
  { id: "blue",    cls: "bg-blue-500"    },
  { id: "emerald", cls: "bg-emerald-500" },
  { id: "violet",  cls: "bg-violet-500"  },
  { id: "amber",   cls: "bg-amber-500"   },
  { id: "rose",    cls: "bg-rose-500"    },
]

const INTENSITY = [
  { id: "light",     label: "Light",     sub: "2 articles · focused depth",    count: 2 },
  { id: "standard",  label: "Standard",  sub: "4 articles · balanced breadth", count: 4 },
  { id: "intensive", label: "Intensive", sub: "6 articles · wide coverage",    count: 6 },
]

const DIFFICULTY = [
  {
    id: "beginner", label: "Beginner", tag: "New to this domain",
    detail: "Foundational vocabulary and mental models — no assumed expertise.",
    icon: (
      <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M9.664 1.319a.75.75 0 0 1 .672 0 41.059 41.059 0 0 1 8.198 5.424.75.75 0 0 1-.254 1.285 31.372 31.372 0 0 0-7.86 3.83.75.75 0 0 1-.84 0 31.508 31.508 0 0 0-2.08-1.287V9.394c0-.244.116-.463.315-.6a32.442 32.442 0 0 1 3.08-1.9l-5.95 3.03-.034.018A4.152 4.152 0 0 0 2.003 14c0 .494.08.972.229 1.417a.75.75 0 0 1-1.428.462 5.648 5.648 0 0 1-.301-1.879c0-2.239 1.317-4.18 3.229-5.066L9.664 1.319Z" clipRule="evenodd" />
        <path d="M9.161 17.478a31.617 31.617 0 0 1-5.813-3.637A4.126 4.126 0 0 0 2 17.25c0 .828.252 1.599.685 2.236A17.585 17.585 0 0 0 9.25 21.5a17.585 17.585 0 0 0 6.565-2.014 4.126 4.126 0 0 0-1.348-3.41 31.503 31.503 0 0 1-5.306 3.442Z" />
      </svg>
    ),
  },
  {
    id: "intermediate", label: "Intermediate", tag: "Some background knowledge",
    detail: "Dives into mechanisms, tradeoffs, and real-world applications.",
    icon: (
      <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
        <path d="M15.98 1.804a1 1 0 0 0-1.96 0l-.24 1.192a1 1 0 0 1-.784.785l-1.192.238a1 1 0 0 0 0 1.962l1.192.238a1 1 0 0 1 .785.785l.238 1.192a1 1 0 0 0 1.962 0l.238-1.192a1 1 0 0 1 .785-.785l1.192-.238a1 1 0 0 0 0-1.962l-1.192-.238a1 1 0 0 1-.785-.785l-.238-1.192ZM6.949 5.684a1 1 0 0 0-1.898 0l-.683 2.051a1 1 0 0 1-.633.633l-2.051.683a1 1 0 0 0 0 1.898l2.051.684a1 1 0 0 1 .633.632l.683 2.051a1 1 0 0 0 1.898 0l.683-2.051a1 1 0 0 1 .633-.633l2.051-.683a1 1 0 0 0 0-1.898l-2.051-.683a1 1 0 0 1-.633-.633L6.95 5.684Z" />
        <path d="M13.949 13.684a1 1 0 0 0-1.898 0l-.184.551a1 1 0 0 1-.632.633l-.551.183a1 1 0 0 0 0 1.898l.551.183a1 1 0 0 1 .633.633l.183.551a1 1 0 0 0 1.898 0l.184-.551a1 1 0 0 1 .632-.633l.551-.183a1 1 0 0 0 0-1.898l-.551-.184a1 1 0 0 1-.633-.632l-.183-.551Z" />
      </svg>
    ),
  },
  {
    id: "advanced", label: "Advanced", tag: "Deep domain expertise",
    detail: "Latest research, nuanced analysis, practitioner-level context.",
    icon: (
      <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
        <path d="M10.75 2.75a.75.75 0 0 0-1.5 0v8.614L6.295 8.235a.75.75 0 1 0-1.09 1.03l4.25 4.5a.75.75 0 0 0 1.09 0l4.25-4.5a.75.75 0 0 0-1.09-1.03l-2.955 3.129V2.75Z" />
        <path d="M3.5 12.75a.75.75 0 0 0-1.5 0v2.5A2.75 2.75 0 0 0 4.75 18h10.5A2.75 2.75 0 0 0 18 15.25v-2.5a.75.75 0 0 0-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5Z" />
      </svg>
    ),
  },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function allTopics() {
  return TOPIC_GROUPS.flatMap(g => g.topics)
}

function buildProjectName(selectedIds, extra = []) {
  const sel = [...allTopics(), ...extra].filter(t => selectedIds.has(t.id))
  if (sel.length === 0) return ""
  if (sel.length === 1) return sel[0].label
  if (sel.length === 2) return `${sel[0].label} & ${sel[1].label}`
  return `${sel[0].label} & More`
}

function buildKeywords(selectedIds, extra = []) {
  const sel = [...allTopics(), ...extra].filter(t => selectedIds.has(t.id))
  const seen = new Set()
  return sel
    .flatMap(t => t.keywords)
    .filter(kw => { if (seen.has(kw)) return false; seen.add(kw); return true })
    .slice(0, 12)
}

function dominantColor(selectedIds, domainId) {
  const group = TOPIC_GROUPS.find(g => g.id === domainId)
  return group?.color || "blue"
}

// ── Step indicator ────────────────────────────────────────────────────────────

function StepDots({ step, onBack }) {
  const labels = ["Domain", "Topics", "Launch"]
  return (
    <div className="flex items-center gap-0">
      {labels.map((label, i) => (
        <div key={i} className="flex items-center">
          <div
            className={`flex items-center gap-2 ${i < step ? "cursor-pointer" : ""}`}
            onClick={() => i < step && onBack(i)}
          >
            <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold transition-all ${
              i < step   ? "bg-blue-600 text-white" :
              i === step ? "bg-blue-500 text-white ring-2 ring-blue-400/25" :
                           "bg-slate-800 text-slate-600"
            }`}>
              {i < step ? (
                <svg className="w-3 h-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2 6l3 3 5-5" />
                </svg>
              ) : i + 1}
            </div>
            <span className={`text-xs font-medium ${i === step ? "text-slate-300" : i < step ? "text-slate-500" : "text-slate-700"}`}>
              {label}
            </span>
          </div>
          {i < labels.length - 1 && (
            <div className={`w-3 sm:w-6 mx-1 sm:mx-2 h-px rounded-full ${i < step ? "bg-blue-600" : "bg-slate-800"}`} />
          )}
        </div>
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function OnboardingModal({ onCreate, creating, userId }) {
  const [step,            setStep]            = useState(0)
  const [domainId,        setDomainId]        = useState(null)      // selected domain id or "custom"
  const [customDomainName, setCustomDomainName] = useState("")
  const [selected,        setSelected]        = useState(new Set()) // topic IDs
  const [customTopics,    setCustomTopics]    = useState([])
  const [customInput,     setCustomInput]     = useState("")
  const [difficulty,      setDifficulty]      = useState("intermediate")
  const [intensity,       setIntensity]       = useState("standard")
  const [name,            setName]            = useState("")
  const [color,           setColor]           = useState("blue")

  const domainGroup  = TOPIC_GROUPS.find(g => g.id === domainId)
  const isCustom     = domainId === CUSTOM_DOMAIN_ID
  const domainColor  = domainGroup?.color || "slate"

  const suggestedName = useMemo(
    () => isCustom
      ? (customDomainName.trim() || (customTopics[0]?.label ?? ""))
      : buildProjectName(selected, customTopics),
    [selected, customTopics, isCustom, customDomainName]
  )

  function selectDomain(id) {
    setDomainId(id)
    setSelected(new Set())
    setCustomTopics([])
    setCustomInput("")
    setColor(TOPIC_GROUPS.find(g => g.id === id)?.color || "blue")
  }

  function goToStep(n) {
    if (n === 2) {
      const nm = isCustom
        ? (customDomainName.trim() || customTopics[0]?.label || "My Project")
        : buildProjectName(selected, customTopics)
      setName(nm)
      setColor(domainGroup?.color || "blue")
    }
    setStep(n)
  }

  function addCustomTopic() {
    const label = customInput.trim()
    if (!label) return
    const id = `custom_${label.toLowerCase().replace(/\s+/g, "_")}_${Date.now()}`
    const newTopic = { id, label, keywords: [label.toLowerCase()] }
    setCustomTopics(prev => [...prev, newTopic])
    setSelected(prev => { const next = new Set(prev); next.add(id); return next })
    setCustomInput("")
  }

  function toggleTopic(id) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function handleLaunch() {
    const finalName = name.trim() || suggestedName || "My Learning Project"
    markOnboardingDone(userId)
    await onCreate({
      name:                     finalName,
      description:              "",
      keywords:                 buildKeywords(selected, customTopics),
      difficulty,
      focus_areas:              [],
      color,
      preferred_sources:        [],
      ignored_sources:          [],
      daily_core_article_count: INTENSITY.find(i => i.id === intensity)?.count ?? 4,
    })
  }

  const canProceedFromTopics = selected.size > 0 || customTopics.length > 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(2,6,23,0.92)", backdropFilter: "blur(10px)" }}
    >
      <div className="w-full max-w-2xl bg-slate-900 border border-slate-700/60 rounded-3xl shadow-2xl shadow-black/70 flex flex-col" style={{ maxHeight: "90vh" }}>

        {/* ── Header ── */}
        <div className="px-5 sm:px-8 pt-6 sm:pt-7 pb-5 flex-shrink-0">
          <div className="flex items-center gap-2 mb-6">
            <div className="w-7 h-7 rounded-xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center shadow-lg shadow-violet-900/40">
              <svg className="w-3.5 h-3.5 text-white" viewBox="0 0 16 16" fill="currentColor">
                <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
              </svg>
            </div>
            <span className="text-[13px] font-semibold text-slate-400 tracking-tight">Curivio</span>
          </div>

          <div className="mb-5">
            {step === 0 && (
              <>
                <h1 className="text-[18px] sm:text-[22px] font-bold text-slate-100 leading-tight mb-1">Let's build your first project</h1>
                <p className="text-sm text-slate-500">Choose a domain to focus on. A single focused domain makes for the sharpest daily brief.</p>
              </>
            )}
            {step === 1 && (
              <>
                <h1 className="text-[18px] sm:text-[22px] font-bold text-slate-100 leading-tight mb-1">
                  {isCustom ? "What topics do you want to learn?" : `Which ${domainGroup?.label} topics interest you?`}
                </h1>
                <p className="text-sm text-slate-500">
                  {isCustom ? "Add your own keywords — we'll build your feed around them." : "Pick one or more — or add your own. We'll tailor your daily brief around them."}
                </p>
              </>
            )}
            {step === 2 && (
              <>
                <h1 className="text-[18px] sm:text-[22px] font-bold text-slate-100 leading-tight mb-1">Almost there — set your level</h1>
                <p className="text-sm text-slate-500">This shapes how deep and technical your daily cards get.</p>
              </>
            )}
          </div>

          <StepDots step={step} onBack={goToStep} />
        </div>

        {/* ── Body ── */}
        <div className="flex-1 overflow-y-auto px-5 sm:px-8 pb-2 min-h-0">

          {/* Step 0 — Domain */}
          {step === 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pb-2">
              {TOPIC_GROUPS.map(group => {
                const c       = CHIP[group.color]
                const iconBg  = ICON_BG[group.color]
                const isOn    = domainId === group.id
                return (
                  <button
                    key={group.id}
                    type="button"
                    onClick={() => selectDomain(group.id)}
                    className={`flex items-start gap-3 px-4 py-4 rounded-2xl border text-left transition-all ${
                      isOn
                        ? `${c.card} border-2 ${c.ring.replace("ring-", "border-").replace("/30", "/60")} ring-1 ${c.ring}`
                        : "bg-slate-800/40 border-slate-700/50 hover:border-slate-600 hover:bg-slate-800/60"
                    }`}
                  >
                    <div className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${isOn ? iconBg : "bg-slate-800 text-slate-500"}`}>
                      {group.icon}
                    </div>
                    <div className="min-w-0">
                      <p className={`text-sm font-semibold mb-0.5 ${isOn ? "text-slate-100" : "text-slate-300"}`}>{group.label}</p>
                      <p className="text-[11px] text-slate-500 leading-snug">{group.description}</p>
                    </div>
                    {isOn && (
                      <div className={`ml-auto flex-shrink-0 w-4 h-4 rounded-full flex items-center justify-center ${c.dot}`}>
                        <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M2 6l3 3 5-5" />
                        </svg>
                      </div>
                    )}
                  </button>
                )
              })}

              {/* Custom domain card */}
              {(() => {
                const isOn = domainId === CUSTOM_DOMAIN_ID
                return (
                  <button
                    type="button"
                    onClick={() => selectDomain(CUSTOM_DOMAIN_ID)}
                    className={`flex items-start gap-3 px-4 py-4 rounded-2xl border text-left transition-all col-span-2 ${
                      isOn
                        ? "bg-slate-700/30 border-slate-500/60 ring-1 ring-slate-500/30"
                        : "bg-slate-800/40 border-slate-700/50 hover:border-slate-600 hover:bg-slate-800/60"
                    }`}
                  >
                    <div className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${isOn ? "bg-slate-600/60 text-slate-300" : "bg-slate-800 text-slate-500"}`}>
                      <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
                        <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
                      </svg>
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className={`text-sm font-semibold mb-0.5 ${isOn ? "text-slate-100" : "text-slate-300"}`}>Your Own Domain</p>
                      <p className="text-[11px] text-slate-500 leading-snug">Define your own learning area with custom keywords and topics</p>
                      {isOn && (
                        <input
                          type="text"
                          value={customDomainName}
                          onChange={e => setCustomDomainName(e.target.value)}
                          onClick={e => e.stopPropagation()}
                          placeholder="e.g. Sports Analytics, Fashion Tech…"
                          maxLength={50}
                          className="mt-2 w-full px-3 py-1.5 rounded-lg text-xs bg-slate-800/70 border border-slate-600/60 text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
                        />
                      )}
                    </div>
                    {isOn && (
                      <div className="ml-auto flex-shrink-0 w-4 h-4 rounded-full flex items-center justify-center bg-slate-500 mt-0.5">
                        <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M2 6l3 3 5-5" />
                        </svg>
                      </div>
                    )}
                  </button>
                )
              })()}
            </div>
          )}

          {/* Step 1 — Topics */}
          {step === 1 && (
            <div className="space-y-4 pb-2">
              {/* Domain topics */}
              {!isCustom && domainGroup && (
                <div className="flex flex-wrap gap-2">
                  {domainGroup.topics.map(topic => {
                    const isOn = selected.has(topic.id)
                    const c    = CHIP[domainColor]
                    return (
                      <button
                        key={topic.id}
                        type="button"
                        onClick={() => toggleTopic(topic.id)}
                        className={`px-4 py-2 rounded-xl text-[13px] font-medium border transition-all ${
                          isOn ? c.sel : `bg-slate-800/50 border-slate-700/50 text-slate-400 ${c.unsel}`
                        }`}
                      >
                        {topic.label}
                      </button>
                    )
                  })}
                </div>
              )}

              {/* Custom keywords */}
              <div className={!isCustom ? "pt-2 border-t border-slate-800/60" : ""}>
                {!isCustom && (
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-2.5">Add your own keywords</p>
                )}
                <div className="flex flex-wrap gap-2">
                  {customTopics.map(topic => (
                    <button
                      key={topic.id}
                      type="button"
                      onClick={() => toggleTopic(topic.id)}
                      className={`px-4 py-2 rounded-xl text-[13px] font-medium border transition-all ${
                        selected.has(topic.id)
                          ? CHIP.slate.sel
                          : `bg-slate-800/50 border-slate-700/50 text-slate-400 ${CHIP.slate.unsel}`
                      }`}
                    >
                      {topic.label}
                    </button>
                  ))}
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={customInput}
                      onChange={e => setCustomInput(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addCustomTopic() } }}
                      placeholder={isCustom ? "Type a topic or keyword…" : "Add your own…"}
                      maxLength={40}
                      className="px-3.5 py-2 rounded-xl text-[13px] bg-slate-800/50 border border-slate-700/50 text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-500 w-48"
                    />
                    {customInput.trim() && (
                      <button
                        type="button"
                        onClick={addCustomTopic}
                        className="px-3 py-2 rounded-xl text-[13px] font-semibold bg-slate-700 hover:bg-slate-600 text-slate-200 border border-slate-600 transition-colors"
                      >
                        +
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {selected.size === 0 && customTopics.length === 0 && (
                <p className="text-xs text-slate-600 pt-1">Select at least one topic to continue</p>
              )}
            </div>
          )}

          {/* Step 2 — Level + Name + Color */}
          {step === 2 && (
            <div className="space-y-5 pb-2">
              {/* Difficulty */}
              <div className="space-y-2.5">
                {DIFFICULTY.map(opt => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setDifficulty(opt.id)}
                    className={`w-full flex items-start gap-4 px-5 py-4 rounded-2xl border text-left transition-all ${
                      difficulty === opt.id
                        ? "bg-slate-800 border-slate-500/70 ring-1 ring-blue-500/25"
                        : "bg-slate-800/40 border-slate-700/50 hover:border-slate-600 hover:bg-slate-800/60"
                    }`}
                  >
                    <div className={`flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center mt-0.5 transition-all ${
                      difficulty === opt.id ? "bg-blue-500/20 text-blue-400" : "bg-slate-800 text-slate-500"
                    }`}>
                      {opt.icon}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-baseline gap-2 mb-1">
                        <span className="font-semibold text-slate-100 text-sm">{opt.label}</span>
                        <span className="text-[11px] text-slate-500">{opt.tag}</span>
                      </div>
                      <p className="text-[12px] text-slate-500 leading-relaxed">{opt.detail}</p>
                    </div>
                    <div className={`flex-shrink-0 w-4 h-4 rounded-full border-2 mt-1 flex items-center justify-center transition-all ${
                      difficulty === opt.id ? "border-blue-500 bg-blue-500" : "border-slate-600"
                    }`}>
                      {difficulty === opt.id && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                    </div>
                  </button>
                ))}
              </div>

              {/* Daily Learning Intensity */}
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-2">Daily Learning Intensity</label>
                <div className="grid grid-cols-3 gap-2">
                  {INTENSITY.map(opt => (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => setIntensity(opt.id)}
                      className={`flex flex-col px-4 py-3 rounded-xl border text-left transition-all ${
                        intensity === opt.id
                          ? "bg-slate-800 border-slate-500/70 ring-1 ring-blue-500/25"
                          : "bg-slate-800/40 border-slate-700/50 hover:border-slate-600 hover:bg-slate-800/60"
                      }`}
                    >
                      <span className={`text-sm font-semibold mb-0.5 ${intensity === opt.id ? "text-slate-100" : "text-slate-400"}`}>{opt.label}</span>
                      <span className="text-[11px] text-slate-500 leading-snug">{opt.sub}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Summary chip strip */}
              <div className="px-4 py-3 rounded-2xl bg-slate-800/40 border border-slate-700/40">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-2">Your selections</p>
                <div className="flex flex-wrap gap-1.5">
                  {[...selected].map(id => {
                    const topic = allTopics().find(t => t.id === id) || customTopics.find(t => t.id === id)
                    const isCustomT = customTopics.some(t => t.id === id)
                    const c = CHIP[isCustomT ? "slate" : (domainGroup?.color || "slate")]
                    return topic ? (
                      <span key={id} className={`px-2.5 py-1 rounded-lg text-[11px] font-medium border ${c.sel}`}>
                        {topic.label}
                      </span>
                    ) : null
                  })}
                </div>
              </div>

              {/* Project name */}
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1.5">Project name</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder={suggestedName || "My Learning Project"}
                  maxLength={80}
                  className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/60 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
                />
              </div>

              {/* Color */}
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-2">Accent color</label>
                <div className="flex gap-3">
                  {COLORS.map(c => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => setColor(c.id)}
                      className={`w-8 h-8 rounded-full ${c.cls} transition-all ${
                        color === c.id
                          ? "ring-2 ring-white/60 ring-offset-2 ring-offset-slate-900 scale-110"
                          : "opacity-40 hover:opacity-70"
                      }`}
                    />
                  ))}
                </div>
              </div>

              {/* What happens next */}
              <div className="flex items-start gap-3 px-4 py-3.5 rounded-2xl bg-blue-950/30 border border-blue-900/40">
                <svg className="w-4 h-4 text-blue-400 flex-shrink-0 mt-0.5" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM6.5 5.75a.75.75 0 0 0-1.5 0v.5c0 .414.336.75.75.75H6v3h-.25a.75.75 0 0 0 0 1.5h2.5a.75.75 0 0 0 0-1.5H8V5.75a.75.75 0 0 0-.75-.75H6.5ZM8 4a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" />
                </svg>
                <p className="text-[12px] text-slate-400 leading-relaxed">
                  We'll immediately generate your <span className="text-slate-200 font-medium">Day 1 brief</span> — tailored news, deep-dives, and concepts for your chosen topics.
                </p>
              </div>
            </div>
          )}

        </div>

        {/* ── Footer ── */}
        <div className="px-5 sm:px-8 py-5 border-t border-slate-800/70 flex-shrink-0 flex items-center justify-between gap-4">
          <button
            type="button"
            onClick={() => step > 0 && setStep(step - 1)}
            className={`text-sm text-slate-500 hover:text-slate-300 transition-colors ${step === 0 ? "invisible pointer-events-none" : ""}`}
          >
            ← Back
          </button>

          {step === 0 && (
            <div className="flex items-center gap-3">
              {!domainId && <span className="text-[11px] text-slate-600">Pick a domain to continue</span>}
              <button
                type="button"
                onClick={() => setStep(1)}
                disabled={!domainId}
                className="px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-35 disabled:cursor-not-allowed"
              >
                Continue →
              </button>
            </div>
          )}

          {step === 1 && (
            <div className="flex items-center gap-3">
              {!canProceedFromTopics && <span className="text-[11px] text-slate-600">Select at least one topic</span>}
              <button
                type="button"
                onClick={() => goToStep(2)}
                disabled={!canProceedFromTopics}
                className="px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-35 disabled:cursor-not-allowed"
              >
                {canProceedFromTopics ? `Continue with ${selected.size + customTopics.filter(t => !selected.has(t.id) ? false : true).length} topic${selected.size !== 1 ? "s" : ""} →` : "Continue →"}
              </button>
            </div>
          )}

          {step === 2 && (
            <button
              type="button"
              onClick={handleLaunch}
              disabled={creating || !(name.trim() || suggestedName)}
              className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-35 disabled:cursor-not-allowed"
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

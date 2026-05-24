import { useRef } from "react"

// ─── Logo ─────────────────────────────────────────────────────────────────────

function LogoMark({ size = 8 }) {
  const px = size * 4
  return (
    <div className={`relative w-${size} h-${size} flex-shrink-0`}>
      <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-blue-500 via-indigo-500 to-violet-600 shadow-lg shadow-violet-950/50" />
      <div className="absolute inset-0 rounded-xl flex items-center justify-center">
        <svg style={{ width: px * 0.56 + 'px', height: px * 0.56 + 'px' }} viewBox="0 0 20 20" fill="none">
          <circle cx="10" cy="8" r="4" fill="white" fillOpacity="0.95" />
          <rect x="8.25" y="12" width="3.5" height="1.2" rx="0.6" fill="white" fillOpacity="0.8" />
          <rect x="8.75" y="13.6" width="2.5" height="1.1" rx="0.55" fill="white" fillOpacity="0.6" />
          <path d="M10 4 L10 2.5" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
          <path d="M13.5 5.5 L14.6 4.4" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
          <path d="M6.5 5.5 L5.4 4.4" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
          <path d="M14.5 8 L16 8" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
          <path d="M5.5 8 L4 8" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
        </svg>
      </div>
    </div>
  )
}

// ─── Icons ────────────────────────────────────────────────────────────────────

function ChevronRight({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path fillRule="evenodd" d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
    </svg>
  )
}

function FeatureFeedIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path d="M10 2a.75.75 0 0 1 .75.75v.258a33.186 33.186 0 0 1 6.668.83.75.75 0 0 1-.336 1.461 31.28 31.28 0 0 0-1.103-.232l1.702 7.545a.75.75 0 0 1-.387.832A4.981 4.981 0 0 1 15 14c-.825 0-1.606-.2-2.294-.556a.75.75 0 0 1-.387-.832l1.77-7.849a31.743 31.743 0 0 0-3.339-.254v11.505a20.01 20.01 0 0 1 3.78.501.75.75 0 1 1-.339 1.462A18.51 18.51 0 0 0 10 17.5a18.51 18.51 0 0 0-4.191.501.75.75 0 1 1-.339-1.462 20.01 20.01 0 0 1 3.78-.501V4.509a31.743 31.743 0 0 0-3.339.254l1.77 7.849a.75.75 0 0 1-.387.832A4.98 4.98 0 0 1 5 14a4.98 4.98 0 0 1-2.294-.556.75.75 0 0 1-.387-.832l1.702-7.545c-.372.071-.738.148-1.103.232a.75.75 0 0 1-.336-1.461 33.186 33.186 0 0 1 6.668-.83V2.75A.75.75 0 0 1 10 2Z" />
    </svg>
  )
}

function FeatureExplainIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path d="M10 1a6 6 0 0 1 3.479 10.907A1 1 0 0 1 13 13H7a1 1 0 0 1-.479-1.093A6 6 0 0 1 10 1ZM8.5 15.5a.5.5 0 0 0 0 1h3a.5.5 0 0 0 0-1h-3Zm.25 2a.25.25 0 0 0 0 .5h2.5a.25.25 0 0 0 0-.5h-2.5Z" />
    </svg>
  )
}

function FeatureResearchIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z" clipRule="evenodd" />
    </svg>
  )
}

function FeatureTrackIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M1 2.75A.75.75 0 0 1 1.75 2h16.5a.75.75 0 0 1 0 1.5H18v8.75A2.75 2.75 0 0 1 15.25 15h-1.072l.798 3.06a.75.75 0 0 1-1.452.38L13.41 18H6.59l-.114.44a.75.75 0 0 1-1.452-.38L5.823 15H4.75A2.75 2.75 0 0 1 2 12.25V3.5h-.25A.75.75 0 0 1 1 2.75ZM7.373 15l-.391 1.5h6.037l-.392-1.5H7.373ZM13 7.5a.75.75 0 0 0-1.5 0v4.25a.75.75 0 0 0 1.5 0V7.5ZM9.25 9a.75.75 0 0 1 .75.75v2a.75.75 0 0 1-1.5 0v-2A.75.75 0 0 1 9.25 9ZM7 10.75a.75.75 0 0 0-1.5 0v.5a.75.75 0 0 0 1.5 0v-.5Z" clipRule="evenodd" />
    </svg>
  )
}

// ─── Feature-specific visuals ─────────────────────────────────────────────────

function FeedVisual() {
  return (
    <div className="relative h-12 mb-4">
      <div className="absolute bottom-0 left-0 right-4 h-7 rounded-lg bg-slate-800/35 border border-slate-700/20" />
      <div className="absolute bottom-1.5 left-0 right-2 h-7 rounded-lg bg-slate-800/55 border border-slate-700/30" />
      <div className="absolute bottom-3 left-0 right-0 h-7 rounded-lg bg-slate-900 border border-blue-500/20 flex items-center px-2.5">
        <span className="w-1 h-1 rounded-full bg-blue-400 mr-1.5 animate-pulse flex-shrink-0" />
        <span className="text-[9px] text-slate-400">AI Agents · Day 8</span>
        <span className="ml-auto text-[9px] font-medium text-blue-400">New</span>
      </div>
    </div>
  )
}

function ExplainVisual() {
  return (
    <div className="mb-4 rounded-xl bg-amber-500/6 border border-amber-500/12 px-3 py-2.5">
      <div className="flex items-center gap-1.5 mb-1.5">
        <div className="w-3 h-3 rounded bg-gradient-to-br from-blue-500 to-violet-600 flex-shrink-0" />
        <span className="text-[9px] text-slate-500 font-medium">Curivio</span>
        <span className="ml-auto text-[8px] text-amber-400/80">Explain Simply</span>
      </div>
      <p className="text-[10px] text-slate-500 leading-relaxed line-clamp-2">
        "Think of it like giving a capable assistant a single goal — and walking away while it handles everything."
      </p>
    </div>
  )
}

function ResearchVisual() {
  return (
    <div className="relative h-12 mb-4 flex items-center justify-center">
      <div className="relative z-10 px-2.5 py-1 rounded-lg bg-violet-500/12 border border-violet-500/20">
        <span className="text-[9px] font-medium text-violet-400/80">AI Agents</span>
      </div>
      <span className="absolute top-0.5 left-2 text-[8px] text-slate-600 bg-slate-800/70 px-1.5 py-0.5 rounded border border-slate-700/30">Memory</span>
      <span className="absolute bottom-0.5 right-2 text-[8px] text-slate-600 bg-slate-800/70 px-1.5 py-0.5 rounded border border-slate-700/30">Tool Use</span>
      <span className="absolute top-0 right-10 text-[8px] text-slate-600 bg-slate-800/70 px-1.5 py-0.5 rounded border border-slate-700/30">LLMs</span>
    </div>
  )
}

function TrackVisual() {
  const activity = [1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
  return (
    <div className="mb-4 space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="text-sm leading-none">🔥</span>
        <span className="text-[11px] font-semibold text-slate-300">12 day streak</span>
        <span className="ml-auto text-[9px] text-slate-600">best 21d</span>
      </div>
      <div className="flex gap-0.5">
        {activity.map((v, i) => (
          <div key={i} className={`h-2 flex-1 rounded-sm ${v ? 'bg-emerald-500/55' : 'bg-slate-800'}`} />
        ))}
      </div>
    </div>
  )
}

// ─── Feature data ─────────────────────────────────────────────────────────────

const FEATURES = [
  {
    Icon: FeatureFeedIcon,
    Visual: FeedVisual,
    accent: "bg-blue-500/10 border border-blue-500/20",
    iconColor: "text-blue-400",
    title: "Curated daily, just for you",
    description: "Wake up to 3–5 fresh cards on topics you're learning — news, deep dives, and counterintuitive curiosity picks. Updated every day from the live web.",
  },
  {
    Icon: FeatureExplainIcon,
    Visual: ExplainVisual,
    accent: "bg-amber-500/10 border border-amber-500/20",
    iconColor: "text-amber-400",
    title: "Complexity, made approachable",
    description: "Tap any card and get a plain-English breakdown with analogies. You never have to feel lost — complex ideas become clear in seconds.",
  },
  {
    Icon: FeatureResearchIcon,
    Visual: ResearchVisual,
    accent: "bg-violet-500/10 border border-violet-500/20",
    iconColor: "text-violet-400",
    title: "Depth, when you want it",
    description: "When a headline isn't enough, research mode surfaces connected topics, multiple perspectives, and real sources — conversationally.",
  },
  {
    Icon: FeatureTrackIcon,
    Visual: TrackVisual,
    accent: "bg-emerald-500/10 border border-emerald-500/20",
    iconColor: "text-emerald-400",
    title: "Growth you can see",
    description: "Streaks keep you consistent. Bookmarks and notes turn daily sessions into a personal knowledge base that compounds week by week.",
  },
]

// ─── Journey steps ────────────────────────────────────────────────────────────

const JOURNEY = [
  {
    num: "01",
    title: "Pick what you're curious about",
    desc: "Add any topic — AI, finance, biology, history. Set your difficulty and preferred sources. Done in under a minute.",
    color: "text-blue-400",
    border: "border-blue-500/20",
    bg: "bg-blue-500/5",
  },
  {
    num: "02",
    title: "Receive your daily feed",
    desc: "Every day, 3–5 fresh cards arrive: news, educational deep dives, and curiosity picks from live web knowledge.",
    color: "text-indigo-400",
    border: "border-indigo-500/20",
    bg: "bg-indigo-500/5",
  },
  {
    num: "03",
    title: "Learn at your own depth",
    desc: "Skim summaries, ask anything, get plain-English explanations, or dive into deep research — all from the same card.",
    color: "text-violet-400",
    border: "border-violet-500/20",
    bg: "bg-violet-500/5",
  },
  {
    num: "04",
    title: "Knowledge compounds",
    desc: "Bookmarks, notes, and tracked reading history turn scattered sessions into a coherent, growing knowledge base.",
    color: "text-emerald-400",
    border: "border-emerald-500/20",
    bg: "bg-emerald-500/5",
  },
]

// ─── Hero showcase mocks ──────────────────────────────────────────────────────

function FeedCardMock() {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/90 overflow-hidden shadow-2xl shadow-black/40">
      <div className="h-[3px] bg-gradient-to-r from-blue-500 to-indigo-500" />
      <div className="px-4 pt-3.5 pb-3">
        <div className="flex items-center gap-2 mb-2.5">
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold text-blue-400 bg-blue-500/10 border border-blue-500/20">
            News
          </span>
          <span className="text-[10px] text-slate-600">AI Agents · 3 min read</span>
          <span className="ml-auto text-[10px] text-slate-700">Day 3</span>
        </div>
        <h4 className="text-[13px] font-semibold text-slate-100 leading-snug mb-2">
          AI Agents Are Reshaping Software Development in 2025
        </h4>
        <p className="text-[11px] text-slate-500 leading-relaxed line-clamp-2">
          Autonomous agents can now plan, write, and debug code end-to-end, cutting development cycles from weeks to hours without human hand-holding.
        </p>
      </div>
      <div className="border-t border-slate-800/80 px-4 py-2 flex items-center gap-1.5">
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] text-slate-400 bg-slate-800/50 border border-slate-700/40">
          <svg className="w-2.5 h-2.5" viewBox="0 0 16 16" fill="currentColor"><path d="M1 2.75C1 1.784 1.784 1 2.75 1h10.5c.966 0 1.75.784 1.75 1.75v7.5A1.75 1.75 0 0 1 13.25 12H9.06l-2.573 2.573A1.458 1.458 0 0 1 4 13.543V12H2.75A1.75 1.75 0 0 1 1 10.25Z" /></svg>
          Ask About
        </span>
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] text-amber-400 bg-amber-500/10 border border-amber-500/20">
          <svg className="w-2.5 h-2.5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 1a6 6 0 0 1 3.479 10.907A1 1 0 0 1 13 13H7a1 1 0 0 1-.479-1.093A6 6 0 0 1 10 1ZM8.5 15.5a.5.5 0 0 0 0 1h3a.5.5 0 0 0 0-1h-3Zm.25 2a.25.25 0 0 0 0 .5h2.5a.25.25 0 0 0 0-.5h-2.5Z" /></svg>
          Explain Simply
        </span>
      </div>
    </div>
  )
}

function ExplainMock() {
  return (
    <div className="rounded-2xl border border-amber-500/15 bg-slate-900/90 px-4 py-3.5 shadow-2xl shadow-black/40">
      <div className="flex items-center gap-2 mb-2.5">
        <div className="w-4 h-4 rounded-md bg-gradient-to-br from-blue-500 to-violet-600 flex-shrink-0" />
        <span className="text-[11px] font-semibold text-slate-300">Curivio</span>
        <span className="ml-auto text-[10px] text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded-full border border-amber-500/20">Explain Simply</span>
      </div>
      <p className="text-[11px] text-slate-300 leading-relaxed">
        Think of it like hiring a capable assistant who can use a computer on their own. You give them a goal — "build me a login page" — and they figure out every step, write the code, test it, and hand it back.
      </p>
    </div>
  )
}

function ProgressMock() {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/90 px-4 py-3 shadow-2xl shadow-black/40">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold text-slate-400">AI Agents · Week 1</span>
        <span className="text-[11px] text-emerald-400 font-medium">🔥 7 day streak</span>
      </div>
      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className="h-full w-4/5 bg-gradient-to-r from-blue-500 to-emerald-500 rounded-full" />
      </div>
      <div className="flex gap-1.5 mt-2.5 flex-wrap">
        {['OpenAI', 'AutoGPT', 'LangChain', 'Workflows'].map((t, i) => (
          <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800/80 text-slate-600 border border-slate-700/40">{t}</span>
        ))}
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">Day 8 →</span>
      </div>
    </div>
  )
}

function HeroShowcase() {
  return (
    <div className="relative">
      <div className="absolute -inset-8 bg-gradient-to-br from-blue-500/6 to-violet-500/6 rounded-3xl blur-2xl pointer-events-none" />
      <div className="relative space-y-3">
        <div className="hover:-translate-y-0.5 transition-transform duration-200">
          <FeedCardMock />
        </div>
        <div className="hover:-translate-y-0.5 transition-transform duration-200 ml-2">
          <ExplainMock />
        </div>
        <div className="hover:-translate-y-0.5 transition-transform duration-200">
          <ProgressMock />
        </div>
      </div>
    </div>
  )
}

// ─── Feature card ─────────────────────────────────────────────────────────────

function FeatureCard({ Icon, Visual, accent, iconColor, title, description }) {
  return (
    <div className="p-5 rounded-2xl bg-slate-900/50 border border-slate-800 hover:border-slate-700/60 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/25 transition-all duration-200">
      <Visual />
      <div className={`w-8 h-8 rounded-lg ${accent} flex items-center justify-center mb-3`}>
        <Icon className={`w-4 h-4 ${iconColor}`} />
      </div>
      <h3 className="text-sm font-semibold text-slate-100 mb-2">{title}</h3>
      <p className="text-[13px] text-slate-400 leading-relaxed">{description}</p>
    </div>
  )
}

// ─── Progression card ─────────────────────────────────────────────────────────

function ProgressionCard({ dayLabel, badge, badgeColor, title, summary, border, accentBar }) {
  return (
    <div className={`rounded-2xl border bg-slate-900/60 overflow-hidden hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/25 transition-all duration-200 ${border}`}>
      <div className={`h-[2px] ${accentBar}`} />
      <div className="px-4 py-4">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{dayLabel}</span>
          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold ${badgeColor}`}>
            {badge}
          </span>
        </div>
        <h4 className="text-[13px] font-semibold text-slate-200 leading-snug mb-2">{title}</h4>
        <p className="text-[11px] text-slate-500 leading-relaxed">{summary}</p>
      </div>
    </div>
  )
}

// ─── Landing page ─────────────────────────────────────────────────────────────

export default function LandingPage({ onShowAuth, isAuthenticated = false, onEnterApp }) {
  const howRef = useRef(null)

  function scrollToHow() {
    howRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const ctaLabel  = isAuthenticated ? "Signup" : "Start Learning Free"
  const ctaAction = isAuthenticated ? onEnterApp : onShowAuth

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 overflow-x-hidden">

      {/* Ambient glow */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden" aria-hidden>
        <div className="absolute -top-40 -left-40 w-[480px] h-[480px] bg-blue-600/6 rounded-full blur-3xl" />
        <div className="absolute top-1/3 -right-40 w-96 h-96 bg-violet-600/6 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 left-1/3 w-72 h-72 bg-indigo-600/5 rounded-full blur-3xl" />
      </div>

      {/* ── Nav ──────────────────────────────────────────────────────────────── */}
      <nav className="sticky top-0 z-50 border-b border-slate-800/60 bg-slate-950/95 backdrop-blur-sm">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <LogoMark size={8} />
            <span className="font-bold text-[15px] tracking-tight select-none bg-gradient-to-r from-slate-100 to-slate-300 bg-clip-text text-transparent">
              Curivio
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={scrollToHow}
              className="hidden sm:block text-[13px] text-slate-400 hover:text-slate-200 transition-colors"
            >
              How it works
            </button>
            <button
              onClick={ctaAction}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-xl text-[13px] font-medium text-white bg-blue-600 hover:bg-blue-500 active:bg-blue-700 transition-colors"
            >
              {ctaLabel}
              {isAuthenticated && <ChevronRight className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>
      </nav>

      {/* ── Hero ─────────────────────────────────────────────────────────────── */}
      <section className="relative max-w-6xl mx-auto px-4 sm:px-6 pt-12 pb-10 md:pt-20 md:pb-16">
        <div className="grid md:grid-cols-2 gap-10 md:gap-16 items-center">

          {/* Left: copy */}
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-500/10 border border-blue-500/20 mb-6">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
              <span className="text-[12px] font-medium text-blue-400">Daily learning for curious minds</span>
            </div>

            <h1 className="text-4xl sm:text-5xl md:text-[54px] font-bold text-slate-100 leading-[1.1] tracking-tight mb-5">
              Stay curious,{" "}
              <span className="bg-gradient-to-r from-blue-400 via-indigo-400 to-violet-400 bg-clip-text text-transparent">
                every day.
              </span>
            </h1>

            <p className="text-[15px] sm:text-base text-slate-400 leading-relaxed mb-8 max-w-md">
              Curivio builds your understanding of topics you care about through short daily reading sessions — powered by live web knowledge, personalized to how you learn.
            </p>

            <div className="flex flex-col sm:flex-row gap-3">
              <button
                onClick={ctaAction}
                className="flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold text-white bg-blue-600 hover:bg-blue-500 active:bg-blue-700 transition-colors shadow-lg shadow-blue-600/25 hover:shadow-blue-600/35"
              >
                {ctaLabel}
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                onClick={scrollToHow}
                className="flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-sm font-medium text-slate-300 bg-slate-800/60 hover:bg-slate-800 border border-slate-700/60 hover:border-slate-600/60 transition-colors"
              >
                See how it works
              </button>
            </div>

            {!isAuthenticated && (
              <p className="mt-4 text-[12px] text-slate-600">Free to use. No credit card required.</p>
            )}
          </div>

          {/* Right: showcase */}
          <div className="w-full max-w-sm mx-auto md:max-w-none">
            <HeroShowcase />
          </div>

        </div>
      </section>

      {/* ── Social proof strip ──────────────────────────────────────────────── */}
      <div className="border-y border-slate-800/60 bg-slate-900/20 py-4">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <div className="flex flex-wrap justify-center gap-x-8 gap-y-2">
            {[
              "Sourced from the live web, daily",
              "Works beautifully on mobile",
              "Private by design",
              "Evolves with your interests",
            ].map(item => (
              <span key={item} className="flex items-center gap-1.5 text-[12px] text-slate-500">
                <svg className="w-3 h-3 text-emerald-500 flex-shrink-0" viewBox="0 0 12 12" fill="currentColor">
                  <path fillRule="evenodd" d="M10.28 2.28a.75.75 0 0 0-1.06 0L4.5 6.99 2.78 5.27a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.06 0l5.25-5.25a.75.75 0 0 0 0-1.06Z" clipRule="evenodd" />
                </svg>
                {item}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* ── How It Works ─────────────────────────────────────────────────────── */}
      <section ref={howRef} id="how-it-works" className="relative py-16 md:py-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">

          <div className="text-center mb-12">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-blue-400 mb-3">How Curivio works</p>
            <h2 className="text-2xl sm:text-3xl font-bold text-slate-100 mb-4">Four things that make it different</h2>
            <p className="text-sm text-slate-400 max-w-lg mx-auto leading-relaxed">
              Not a course. Not a generic chatbot. A personal learning system that evolves with your curiosity and compounds your knowledge over time.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {FEATURES.map(f => <FeatureCard key={f.title} {...f} />)}
          </div>

        </div>
      </section>

      {/* ── Knowledge Progression ────────────────────────────────────────────── */}
      <section className="relative border-t border-slate-800/60 py-16 md:py-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">

          <div className="text-center mb-10">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-indigo-400 mb-3">Knowledge that compounds</p>
            <h2 className="text-2xl sm:text-3xl font-bold text-slate-100 mb-4">
              Watch understanding build over time
            </h2>
            <p className="text-sm text-slate-400 max-w-lg mx-auto leading-relaxed">
              Curivio doesn't dump everything at once. It layers your knowledge day by day — from foundational concepts to real-world nuance.
            </p>
          </div>

          <div className="flex items-center gap-3 mb-6">
            <span className="text-[11px] text-slate-600 uppercase tracking-widest font-semibold">Topic</span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
              <span className="text-[12px] font-medium text-blue-400">Quantum Computing</span>
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <ProgressionCard
              dayLabel="Day 1"
              badge="Foundations"
              badgeColor="text-slate-400 bg-slate-800/80 border border-slate-700/40"
              title="Qubits and Superposition: The Basics"
              summary="A qubit isn't just 0 or 1 — it can be both simultaneously until measured. This property is what makes quantum fundamentally different from classical computing."
              border="border-slate-800"
              accentBar="bg-slate-800"
            />
            <ProgressionCard
              dayLabel="Day 7"
              badge="Connections"
              badgeColor="text-blue-400 bg-blue-500/10 border border-blue-500/20"
              title="How Quantum Gates Actually Work"
              summary="Once you understand superposition, quantum gates reveal how computers manipulate probability before collapsing state. Entanglement lets you coordinate operations at a distance."
              border="border-blue-500/20"
              accentBar="bg-gradient-to-r from-blue-500 to-indigo-500"
            />
            <ProgressionCard
              dayLabel="Day 21"
              badge="Real-world lens"
              badgeColor="text-violet-400 bg-violet-500/10 border border-violet-500/20"
              title="Why Quantum Advantage Is Still Years Away"
              summary="Error correction remains the core unsolved challenge. Today's noisy qubits can't sustain computation long enough for practical problems — but the trajectory is becoming clear."
              border="border-violet-500/20"
              accentBar="bg-gradient-to-r from-violet-500 to-indigo-500"
            />
          </div>

          <p className="text-center text-[12px] text-slate-600 mt-6">
            One topic. Three weeks. Genuine understanding — not just familiarity.
          </p>

        </div>
      </section>

      {/* ── Learning Journey ─────────────────────────────────────────────────── */}
      <section className="relative border-t border-slate-800/60 py-16 md:py-24">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">

          <div className="text-center mb-12">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-violet-400 mb-3">The learning loop</p>
            <h2 className="text-2xl sm:text-3xl font-bold text-slate-100 mb-4">
              From curious to knowledgeable
            </h2>
            <p className="text-sm text-slate-400 max-w-md mx-auto leading-relaxed">
              Curivio turns a casual interest into genuine expertise — one short session at a time.
            </p>
          </div>

          <div className="relative grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {JOURNEY.map((step, i) => (
              <div
                key={step.num}
                className={`relative p-5 rounded-2xl border ${step.border} ${step.bg} hover:-translate-y-0.5 hover:shadow-md transition-all duration-200`}
              >
                {i < JOURNEY.length - 1 && (
                  <div className="hidden lg:block absolute top-8 -right-2 w-4 h-px bg-slate-800 z-10" />
                )}
                <span className={`text-[11px] font-bold uppercase tracking-widest ${step.color} mb-3 block`}>
                  {step.num}
                </span>
                <h3 className="text-sm font-semibold text-slate-100 mb-2">{step.title}</h3>
                <p className="text-[12px] text-slate-400 leading-relaxed">{step.desc}</p>
              </div>
            ))}
          </div>

          {/* Example flow */}
          <div className="mt-10 p-5 rounded-2xl border border-slate-800/80 bg-slate-900/30">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-600 mb-4">Example: learning AI Agents</p>
            <div className="flex flex-wrap items-center gap-2 text-[12px]">
              {[
                { label: "Topic added", val: "\"AI Agents\"",    color: "text-blue-400 bg-blue-500/10 border-blue-500/20" },
                { label: "Day 1 feed",  val: "5 curated cards", color: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20" },
                { label: "Asked",       val: "Explain Simply",  color: "text-amber-400 bg-amber-500/10 border-amber-500/20" },
                { label: "Saved",       val: "3 bookmarks",     color: "text-violet-400 bg-violet-500/10 border-violet-500/20" },
                { label: "Week 4",      val: "Fluent in topic", color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
              ].map((item, i, arr) => (
                <div key={item.label} className="flex items-center gap-2">
                  <div className={`flex flex-col items-start px-3 py-2 rounded-xl border ${item.color}`}>
                    <span className="text-[10px] text-slate-500 mb-0.5">{item.label}</span>
                    <span className="font-medium">{item.val}</span>
                  </div>
                  {i < arr.length - 1 && (
                    <ChevronRight className="w-3 h-3 text-slate-700 flex-shrink-0" />
                  )}
                </div>
              ))}
            </div>
          </div>

        </div>
      </section>

      {/* ── Final CTA ────────────────────────────────────────────────────────── */}
      <section className="relative border-t border-slate-800/60 py-20 md:py-28 overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-blue-600/3 to-transparent pointer-events-none" />
        <div className="relative max-w-2xl mx-auto px-4 sm:px-6 text-center">

          <h2 className="text-3xl sm:text-4xl font-bold text-slate-100 mb-4 leading-tight tracking-tight">
            Small consistent curiosity{" "}
            <span className="bg-gradient-to-r from-blue-400 to-violet-400 bg-clip-text text-transparent">
              becomes real expertise.
            </span>
          </h2>
          <p className="text-slate-400 text-[15px] mb-8 leading-relaxed max-w-md mx-auto">
            Fifteen minutes a day. That's all it takes for Curivio to compound your understanding of anything you care about — week after week.
          </p>

          <button
            onClick={ctaAction}
            className="inline-flex items-center gap-2 px-8 py-3.5 rounded-xl text-[15px] font-semibold text-white bg-blue-600 hover:bg-blue-500 active:bg-blue-700 transition-colors shadow-xl shadow-blue-600/25 hover:shadow-blue-600/40"
          >
            {ctaLabel}
            <ChevronRight className="w-4 h-4" />
          </button>

          {!isAuthenticated && (
            <p className="mt-4 text-[12px] text-slate-600">Free. No credit card. Start in 30 seconds.</p>
          )}

        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────────────────── */}
      <footer className="border-t border-slate-800/60 py-10">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <div className="flex flex-col sm:flex-row items-center sm:items-start justify-between gap-6">

            <div className="flex flex-col items-center sm:items-start gap-2">
              <div className="flex items-center gap-2">
                <LogoMark size={6} />
                <span className="text-sm font-semibold text-slate-300">Curivio</span>
              </div>
              <p className="text-[12px] text-slate-600 text-center sm:text-left max-w-[200px]">
                Built for people who never stop being curious.
              </p>
            </div>

            <div className="flex items-center gap-6 text-[12px]">
              <button onClick={scrollToHow} className="text-slate-600 hover:text-slate-400 transition-colors">
                How it works
              </button>
              <button onClick={ctaAction} className="text-slate-600 hover:text-slate-400 transition-colors">
                {isAuthenticated ? "Open app" : "Get started"}
              </button>
            </div>

          </div>
          <div className="mt-8 pt-6 border-t border-slate-800/40 text-center">
            <p className="text-[11px] text-slate-700">
              © {new Date().getFullYear()} Curivio. AI-curated learning for the curious mind.
            </p>
          </div>
        </div>
      </footer>

    </div>
  )
}

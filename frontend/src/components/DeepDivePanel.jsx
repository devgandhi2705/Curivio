/**
 * DeepDivePanel — displays deep research results for a topic.
 *
 * Sections:
 *   • Research summary (prose)
 *   • Related concepts
 *   • Implementation ideas
 *   • Practical applications
 *   • Advanced follow-ups
 *   • Sources
 */

function SectionList({ title, items, accent = "blue" }) {
  const accentMap = {
    blue:    "bg-blue-500/10 border-blue-500/20 text-blue-300",
    violet:  "bg-violet-500/10 border-violet-500/20 text-violet-300",
    emerald: "bg-emerald-500/10 border-emerald-500/20 text-emerald-300",
    amber:   "bg-amber-500/10 border-amber-500/20 text-amber-300",
  }
  const dotMap = {
    blue:    "bg-blue-400",
    violet:  "bg-violet-400",
    emerald: "bg-emerald-400",
    amber:   "bg-amber-400",
  }

  if (!items?.length) return null

  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-2">
        {title}
      </h3>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item, i) => (
          <span
            key={i}
            className={`px-2.5 py-1 rounded-md border text-xs font-medium ${accentMap[accent]}`}
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}

function IdeaList({ title, items, accent = "blue" }) {
  const dotMap = {
    blue:    "bg-blue-400",
    violet:  "bg-violet-400",
    emerald: "bg-emerald-400",
    amber:   "bg-amber-400",
  }

  if (!items?.length) return null

  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-2">
        {title}
      </h3>
      <ul className="space-y-1.5">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-2.5 text-sm text-slate-300">
            <span
              className={`mt-1.5 shrink-0 w-1.5 h-1.5 rounded-full ${dotMap[accent]}`}
            />
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

function SkeletonBlock({ lines = 3 }) {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-3 rounded bg-slate-800"
          style={{ width: `${70 + Math.random() * 25}%` }}
        />
      ))}
    </div>
  )
}

export default function DeepDivePanel({ data, loading }) {
  if (loading) {
    return (
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 space-y-5">
        <div className="h-4 w-32 rounded bg-slate-800 animate-pulse" />
        <SkeletonBlock lines={4} />
        <SkeletonBlock lines={3} />
        <SkeletonBlock lines={3} />
      </div>
    )
  }

  if (!data) return null

  const {
    research_summary,
    related_concepts = [],
    implementation_ideas = [],
    practical_applications = [],
    advanced_follow_ups = [],
    sources = [],
  } = data

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 space-y-5">
      <h2 className="text-sm font-semibold text-slate-300 tracking-wide uppercase">
        Deep Dive
      </h2>

      {/* Research summary */}
      {research_summary && (
        <div className="bg-slate-800/60 rounded-lg p-4 border border-slate-700/50">
          <p className="text-sm text-slate-300 leading-relaxed">{research_summary}</p>
        </div>
      )}

      {/* Related concepts */}
      <SectionList
        title="Key Concepts"
        items={related_concepts}
        accent="blue"
      />

      {/* Implementation ideas */}
      <IdeaList
        title="Implementation Ideas"
        items={implementation_ideas}
        accent="emerald"
      />

      {/* Practical applications */}
      <IdeaList
        title="Practical Applications"
        items={practical_applications}
        accent="violet"
      />

      {/* Advanced follow-ups */}
      <SectionList
        title="Advanced Follow-ups"
        items={advanced_follow_ups}
        accent="amber"
      />

      {/* Sources */}
      {sources.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-2">
            Sources
          </h3>
          <ul className="space-y-1">
            {sources.map((src, i) => (
              <li key={i}>
                <a
                  href={src}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-400/70 hover:text-blue-400 transition-colors truncate block"
                >
                  {src}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

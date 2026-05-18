const SECTION_CONFIG = {
  industry_news: {
    label: "Industry & Tech",
    accent: "border-blue-700/40 bg-blue-900/10",
    badge:  "bg-blue-900/50 border-blue-700/40 text-blue-300",
    dot:    "bg-blue-400",
  },
  market_trends: {
    label: "Market & Business",
    accent: "border-emerald-700/40 bg-emerald-900/10",
    badge:  "bg-emerald-900/50 border-emerald-700/40 text-emerald-300",
    dot:    "bg-emerald-400",
  },
  technical_discoveries: {
    label: "Research & Tech",
    accent: "border-violet-700/40 bg-violet-900/10",
    badge:  "bg-violet-900/50 border-violet-700/40 text-violet-300",
    dot:    "bg-violet-400",
  },
}

export default function SectionCard({ section }) {
  const config = SECTION_CONFIG[section.type] || SECTION_CONFIG.industry_news

  return (
    <div className={`bg-slate-900 border rounded-2xl overflow-hidden ${config.accent}`}>
      <div className="px-4 py-3 border-b border-slate-800/80 flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${config.dot}`} />
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          {section.title}
        </span>
      </div>

      <div className="divide-y divide-slate-800/60">
        {section.items?.map((item, i) => (
          <SectionItem key={i} item={item} config={config} />
        ))}
      </div>
    </div>
  )
}

function SectionItem({ item, config }) {
  return (
    <div className="px-4 py-3.5">
      <h3 className="text-sm font-semibold text-slate-100 leading-snug mb-1.5">
        {item.title}
      </h3>
      <p className="text-xs text-slate-400 leading-relaxed mb-1.5">
        {item.insight}
      </p>
      <p className="text-xs text-slate-500 leading-relaxed italic">
        {item.why_it_matters}
      </p>
      {item.sources?.filter(Boolean).length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {item.sources.filter(Boolean).map((url, i) => (
            <a
              key={i}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border ${config.badge} hover:opacity-80 transition-opacity`}
            >
              <svg className="w-2.5 h-2.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M4.25 5.5a.75.75 0 0 0-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 0 0 .75-.75v-4a.75.75 0 0 1 1.5 0v4A2.25 2.25 0 0 1 12.75 17h-8.5A2.25 2.25 0 0 1 2 14.75v-8.5A2.25 2.25 0 0 1 4.25 4h5a.75.75 0 0 1 0 1.5h-5Z" clipRule="evenodd" />
                <path fillRule="evenodd" d="M6.194 12.753a.75.75 0 0 0 1.06.053L16.5 4.44v2.81a.75.75 0 0 0 1.5 0v-4.5a.75.75 0 0 0-.75-.75h-4.5a.75.75 0 0 0 0 1.5h2.553l-9.056 8.194a.75.75 0 0 0-.053 1.06Z" clipRule="evenodd" />
              </svg>
              Source
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

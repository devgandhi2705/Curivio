const CATEGORY_CONFIG = {
  'AI/Technology': {
    badge:  'bg-blue-500/10 text-blue-400 border-blue-500/20',
    border: 'border-l-blue-500',
  },
  Finance: {
    badge:  'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    border: 'border-l-emerald-500',
  },
  Manufacturing: {
    badge:  'bg-amber-500/10 text-amber-400 border-amber-500/20',
    border: 'border-l-amber-500',
  },
  Pharma: {
    badge:  'bg-violet-500/10 text-violet-400 border-violet-500/20',
    border: 'border-l-violet-500',
  },
  'Export/Trade': {
    badge:  'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
    border: 'border-l-cyan-500',
  },
}

const TYPE_LABEL = {
  industry_news:       'Insight',
  market_trends:       'Trend',
  technical_discovery: 'Research',
  development:         'Regulatory',
}

const DEFAULT_CONFIG = {
  badge:  'bg-slate-700/50 text-slate-400 border-slate-700',
  border: 'border-l-slate-600',
}

export default function InsightCard({ item }) {
  const cfg   = CATEGORY_CONFIG[item.category] || DEFAULT_CONFIG
  const label = TYPE_LABEL[item.type] || item.type

  return (
    <article
      className={`
        relative bg-slate-900 border border-slate-800 border-l-2 ${cfg.border}
        rounded-r-xl rounded-bl-xl p-4 flex flex-col gap-2.5
        hover:border-slate-700 transition-colors duration-150
      `}
    >
      {/* Top row: category badge + type + urgency */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cfg.badge}`}>
          {item.category}
        </span>
        <span className="text-xs text-slate-600">{label}</span>
        {item.urgency === 'high' && (
          <span className="ml-auto flex items-center gap-1 text-xs text-red-400 font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block" />
            Priority
          </span>
        )}
      </div>

      {/* Title */}
      <h3 className="text-sm font-semibold text-slate-100 leading-snug line-clamp-2">
        {item.title}
      </h3>

      {/* Insight */}
      <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">
        {item.insight}
      </p>

      {/* Why it matters */}
      {item.why_it_matters && (
        <p className="text-xs text-slate-500 italic leading-relaxed line-clamp-2">
          {item.why_it_matters}
        </p>
      )}

      {/* Sources */}
      {item.sources?.filter(Boolean).length > 0 && (
        <div className="flex flex-wrap gap-1 pt-0.5">
          {item.sources.filter(Boolean).map((url, i) => (
            <a
              key={i}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs text-slate-500
                         border border-slate-700 hover:text-slate-300 hover:border-slate-600 transition-colors"
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
    </article>
  )
}

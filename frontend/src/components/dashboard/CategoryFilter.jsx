const CATEGORIES = [
  'All',
  'AI/Technology',
  'Finance',
  'Manufacturing',
  'Pharma',
  'Export/Trade',
]

const ACTIVE_STYLES = {
  All:            'bg-slate-700 text-slate-100 border-slate-600',
  'AI/Technology':'bg-blue-600/20 text-blue-300 border-blue-500/50',
  Finance:        'bg-emerald-600/20 text-emerald-300 border-emerald-500/50',
  Manufacturing:  'bg-amber-600/20 text-amber-300 border-amber-500/50',
  Pharma:         'bg-violet-600/20 text-violet-300 border-violet-500/50',
  'Export/Trade': 'bg-cyan-600/20 text-cyan-300 border-cyan-500/50',
}

const INACTIVE_STYLES = 'bg-transparent text-slate-500 border-slate-800 hover:text-slate-300 hover:border-slate-700'

export default function CategoryFilter({ insights = [], activeCategory, onChange }) {
  const counts = {}
  for (const item of insights) {
    counts[item.category] = (counts[item.category] || 0) + 1
  }
  counts['All'] = insights.length

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {CATEGORIES.map(cat => {
        const isActive = cat === activeCategory
        const count    = counts[cat] || 0
        return (
          <button
            key={cat}
            onClick={() => onChange(cat)}
            className={`
              inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium
              transition-all duration-100
              ${isActive ? ACTIVE_STYLES[cat] : INACTIVE_STYLES}
            `}
          >
            {cat}
            {count > 0 && (
              <span className={`
                inline-flex items-center justify-center min-w-[1.1rem] h-[1.1rem]
                rounded-full text-[10px] font-semibold px-1
                ${isActive ? 'bg-white/10' : 'bg-slate-800 text-slate-500'}
              `}>
                {count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

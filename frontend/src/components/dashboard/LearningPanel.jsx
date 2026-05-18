const DIFFICULTY_BADGE = {
  beginner:     'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  intermediate: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  advanced:     'bg-violet-500/10 text-violet-400 border-violet-500/20',
}

const CATEGORY_DOT = {
  'AI/Technology': 'bg-blue-400',
  Finance:         'bg-emerald-400',
  Manufacturing:   'bg-amber-400',
  Pharma:          'bg-violet-400',
  'Export/Trade':  'bg-cyan-400',
}

export default function LearningPanel({ items = [] }) {
  if (!items.length) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
        <PanelHeader />
        <p className="text-xs text-slate-600 mt-3">No learning items for this category.</p>
      </div>
    )
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <PanelHeader />
      </div>

      <div className="divide-y divide-slate-800/50">
        {items.map((item, i) => (
          <LearningItem key={item.id ?? i} item={item} />
        ))}
      </div>
    </div>
  )
}

function PanelHeader() {
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-200">Learning Track</h3>
      <p className="text-xs text-slate-500 mt-0.5">Calibrated to your profile and interests</p>
    </div>
  )
}

function LearningItem({ item }) {
  const diff    = DIFFICULTY_BADGE[item.difficulty] || DIFFICULTY_BADGE.intermediate
  const catDot  = CATEGORY_DOT[item.category] || 'bg-slate-500'

  return (
    <div className="px-4 py-3 space-y-1.5">
      <div className="flex items-start gap-2">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${catDot}`} />
        <div className="flex-1 min-w-0 space-y-1">
          <p className="text-xs font-medium text-slate-200 leading-snug">{item.title}</p>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className={`px-1.5 py-0.5 rounded text-[10px] border capitalize ${diff}`}>
              {item.difficulty}
            </span>
            {item.category && (
              <span className="text-[10px] text-slate-600">{item.category}</span>
            )}
            {item.estimated_time && (
              <span className="text-[10px] text-slate-600 ml-auto">{item.estimated_time}</span>
            )}
          </div>
          <p className="text-[11px] text-slate-500 leading-relaxed">{item.reason}</p>
          {item.chat_connection && (
            <div className="flex items-start gap-1.5 pt-0.5">
              <svg className="w-3 h-3 text-violet-400 flex-shrink-0 mt-px" viewBox="0 0 16 16" fill="currentColor">
                <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
              </svg>
              <p className="text-[11px] text-violet-300/70 italic leading-relaxed">{item.chat_connection}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

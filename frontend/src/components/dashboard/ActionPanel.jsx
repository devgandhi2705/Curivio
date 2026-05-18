export default function ActionPanel({ items = [] }) {
  if (!items.length) return null

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-200">Action Items</h3>
        <p className="text-xs text-slate-500 mt-0.5">Startable today</p>
      </div>
      <div className="p-4 space-y-3">
        {items.map((action, i) => (
          <div key={i} className="flex gap-3">
            <span className="flex-shrink-0 w-5 h-5 rounded-full bg-slate-800 border border-slate-700
                             flex items-center justify-center text-slate-400 text-[10px] font-bold mt-0.5">
              {i + 1}
            </span>
            <p className="text-xs text-slate-400 leading-relaxed">{action}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

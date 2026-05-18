export default function ActionItems({ items, nextStep }) {
  // Support both new action_items array and legacy next_step string
  const actions = items?.length
    ? items
    : nextStep
    ? [nextStep]
    : []

  if (!actions.length) return null

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-200">Action items</h3>
        <p className="text-xs text-slate-500 mt-0.5">Concrete, startable today</p>
      </div>
      <div className="p-4 space-y-3">
        {actions.map((action, i) => (
          <div key={i} className="flex gap-3">
            <span className="flex-shrink-0 w-5 h-5 rounded-full bg-gradient-to-br from-blue-600 to-violet-600 flex items-center justify-center text-white text-xs font-bold">
              {i + 1}
            </span>
            <p className="text-sm text-slate-300 leading-relaxed">{action}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

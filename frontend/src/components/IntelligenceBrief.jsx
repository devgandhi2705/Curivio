export default function IntelligenceBrief({ brief, industryContext }) {
  if (!brief) return null

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
      {industryContext && (
        <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-violet-900/40 border border-violet-700/40 text-violet-300 text-xs font-medium mb-3">
          <span className="w-1.5 h-1.5 rounded-full bg-violet-400" />
          {industryContext}
        </div>
      )}

      <h2 className="text-lg font-bold text-slate-100 leading-snug mb-3">
        {brief.headline}
      </h2>

      <p className="text-sm text-slate-300 leading-relaxed mb-4">
        {brief.executive_summary}
      </p>

      {brief.key_signals?.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">
            Key signals
          </div>
          {brief.key_signals.map((signal, i) => (
            <div key={i} className="flex gap-2.5">
              <span className="flex-shrink-0 w-4 h-4 rounded bg-blue-900/50 border border-blue-700/40 flex items-center justify-center text-blue-400 text-xs font-bold mt-0.5">
                {i + 1}
              </span>
              <p className="text-sm text-slate-300 leading-relaxed">{signal}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

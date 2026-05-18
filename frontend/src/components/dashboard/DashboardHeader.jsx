function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
    })
  } catch {
    return iso
  }
}

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
    })
  } catch {
    return ''
  }
}

export default function DashboardHeader({ brief, generatedAt, onRefresh }) {
  if (!brief) return null

  return (
    <div className="space-y-4">
      {/* Title row */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1 flex-1 min-w-0">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span>{formatDate(generatedAt)}</span>
            {generatedAt && (
              <>
                <span>·</span>
                <span>Generated {formatTime(generatedAt)}</span>
              </>
            )}
          </div>
          <h1 className="text-lg font-semibold text-slate-100 leading-snug">
            {brief.headline}
          </h1>
          <p className="text-sm text-slate-400 leading-relaxed max-w-3xl">
            {brief.executive_summary}
          </p>
        </div>

        {onRefresh && (
          <button
            onClick={onRefresh}
            className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                       border border-slate-700 text-xs text-slate-400
                       hover:text-slate-200 hover:border-slate-600 transition-colors"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clipRule="evenodd" />
            </svg>
            Refresh
          </button>
        )}
      </div>

      {/* Key signals strip */}
      {brief.key_signals?.length > 0 && (
        <div className="flex flex-col gap-1.5 pl-3 border-l-2 border-slate-700">
          <span className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-0.5">
            Key signals
          </span>
          {brief.key_signals.map((signal, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="w-1 h-1 rounded-full bg-slate-500 flex-shrink-0 mt-1.5" />
              <p className="text-xs text-slate-400 leading-relaxed">{signal}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

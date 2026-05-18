function getDomain(url) {
  try {
    return new URL(url).hostname.replace('www.', '')
  } catch {
    return url
  }
}

function domainInitial(domain) {
  return domain.charAt(0).toUpperCase()
}

function SourceCard({ url }) {
  const domain = getDomain(url)
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex items-center gap-2.5 px-3 py-2 bg-slate-800/70 hover:bg-slate-800 border border-slate-700/60 hover:border-slate-600 rounded-xl transition-all"
    >
      <span className="flex-shrink-0 w-6 h-6 rounded-md bg-gradient-to-br from-blue-600/40 to-violet-600/40 border border-blue-500/20 flex items-center justify-center text-xs font-bold text-blue-300">
        {domainInitial(domain)}
      </span>
      <span className="flex-1 text-xs text-slate-400 group-hover:text-slate-200 truncate transition-colors">
        {domain}
      </span>
      <span className="flex-shrink-0 text-slate-600 group-hover:text-slate-400 transition-colors text-xs">
        ↗
      </span>
    </a>
  )
}

export default function InsightCard({ insight }) {
  return (
    <section>
      <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3 flex items-center gap-2">
        <span>📰</span> Key Insight
      </p>
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="border-l-4 border-blue-500 p-5">

          <h2 className="text-base font-semibold text-slate-100 mb-3 leading-snug">
            {insight.title}
          </h2>

          <p className="text-slate-300 text-sm leading-relaxed mb-4">
            {insight.summary}
          </p>

          <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl px-4 py-3 mb-4">
            <p className="text-xs font-semibold text-blue-400 uppercase tracking-wide mb-1.5">
              Why it matters
            </p>
            <p className="text-slate-300 text-sm leading-relaxed">
              {insight.why_it_matters}
            </p>
          </div>

          {insight.sources?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Sources
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {insight.sources.map((url, i) => (
                  <SourceCard key={i} url={url} />
                ))}
              </div>
            </div>
          )}

        </div>
      </div>
    </section>
  )
}

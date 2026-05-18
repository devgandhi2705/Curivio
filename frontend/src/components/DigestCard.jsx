import { useState } from 'react'

const DIFFICULTY = {
  beginner:     { label: 'Beginner',     cls: 'text-emerald-400 bg-emerald-950/60 border-emerald-900/60' },
  intermediate: { label: 'Intermediate', cls: 'text-amber-400   bg-amber-950/60   border-amber-900/60'   },
  advanced:     { label: 'Advanced',     cls: 'text-red-400     bg-red-950/60     border-red-900/60'     },
}

const STEP_GRADIENT = [
  'from-blue-600 to-blue-700',
  'from-violet-600 to-violet-700',
  'from-purple-600 to-purple-700',
  'from-pink-600 to-pink-700',
]

function getDomain(url) {
  try { return new URL(url).hostname.replace('www.', '') }
  catch { return url }
}

function formatDate(isoString) {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}

function formatTime(isoString) {
  const d = new Date(isoString)
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}

// Compact read-only topic row used inside digest cards
function TopicRow({ topic, index }) {
  const diff = DIFFICULTY[topic.difficulty] ?? DIFFICULTY.beginner
  return (
    <div className="flex items-start gap-3">
      <div className={`flex-shrink-0 w-6 h-6 rounded-lg bg-gradient-to-br ${STEP_GRADIENT[index]} flex items-center justify-center text-white text-xs font-bold`}>
        {index + 1}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <span className="text-sm font-medium text-slate-200 leading-snug">{topic.title}</span>
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border flex-shrink-0 ${diff.cls}`}>
            {diff.label}
          </span>
        </div>
        <p className="text-slate-500 text-xs mt-0.5 leading-relaxed">{topic.reason}</p>
      </div>
    </div>
  )
}

export default function DigestCard({ digest, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)

  const sourceTag = digest.source === 'user'
    ? { label: 'On-demand', cls: 'text-blue-400 bg-blue-950/60 border-blue-900/60' }
    : { label: 'Scheduled', cls: 'text-violet-400 bg-violet-950/60 border-violet-900/60' }

  return (
    <div className={`bg-slate-900 border rounded-2xl overflow-hidden transition-colors ${open ? 'border-slate-700' : 'border-slate-800 hover:border-slate-700'}`}>

      {/* ── Header (always visible) ── */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full text-left p-4 flex items-start gap-3"
      >
        {/* Chevron */}
        <span className={`flex-shrink-0 mt-0.5 text-slate-500 transition-transform duration-200 ${open ? 'rotate-90' : ''}`}>
          ▶
        </span>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-xs text-slate-500">{formatDate(digest.generated_at)}</span>
            <span className="text-slate-700">·</span>
            <span className="text-xs text-slate-600">{formatTime(digest.generated_at)}</span>
            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ml-auto ${sourceTag.cls}`}>
              {sourceTag.label}
            </span>
          </div>
          <p className="text-sm font-semibold text-slate-100 leading-snug line-clamp-2">
            {digest.news_title}
          </p>
        </div>
      </button>

      {/* ── Expanded body ── */}
      {open && (
        <div className="px-4 pb-5 space-y-5 border-t border-slate-800 pt-4">

          {/* News insight */}
          <section>
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3 flex items-center gap-2">
              <span>📰</span> Key Insight
            </p>
            <div className="border-l-2 border-blue-500 pl-4 space-y-3">
              <p className="text-slate-300 text-sm leading-relaxed">
                {digest.news_summary}
              </p>
              <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl px-4 py-3">
                <p className="text-xs font-semibold text-blue-400 uppercase tracking-wide mb-1">
                  Why it matters
                </p>
                <p className="text-slate-300 text-sm leading-relaxed">
                  {digest.why_it_matters}
                </p>
              </div>
            </div>
          </section>

          {/* Learning topics */}
          <section>
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3 flex items-center gap-2">
              <span>📚</span> Learning Path
            </p>
            <div className="space-y-3">
              {digest.learning_topics.map((t, i) => (
                <TopicRow key={i} topic={t} index={i} />
              ))}
            </div>
          </section>

          {/* Source links */}
          {digest.source_links?.length > 0 && (
            <section>
              <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-2 flex items-center gap-2">
                <span>🔗</span> Sources
              </p>
              <div className="flex flex-wrap gap-2">
                {digest.source_links.map((url, i) => (
                  <a
                    key={i}
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 px-3 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-slate-600 rounded-full text-xs text-slate-300 hover:text-white transition-all"
                  >
                    <span className="text-slate-500">↗</span>
                    {getDomain(url)}
                  </a>
                ))}
              </div>
            </section>
          )}

          {/* Next step */}
          <section>
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-2 flex items-center gap-2">
              <span>🚀</span> Next Move
            </p>
            <div className="border-l-2 border-emerald-500 pl-4">
              <p className="text-slate-300 text-sm leading-relaxed">{digest.next_step}</p>
            </div>
          </section>

        </div>
      )}
    </div>
  )
}

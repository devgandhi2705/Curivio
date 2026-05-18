const DIFFICULTY = {
  beginner:     { label: 'Beginner',     cls: 'text-emerald-400 bg-emerald-950/60 border-emerald-900/60' },
  intermediate: { label: 'Intermediate', cls: 'text-amber-400   bg-amber-950/60   border-amber-900/60'   },
  advanced:     { label: 'Advanced',     cls: 'text-red-400     bg-red-950/60     border-red-900/60'     },
}

const CATEGORY_STYLE = {
  'LLM Infrastructure':    'text-sky-400    bg-sky-950/50    border-sky-900/50',
  'LLM Training':          'text-violet-400 bg-violet-950/50 border-violet-900/50',
  'AI Agents':             'text-purple-400 bg-purple-950/50 border-purple-900/50',
  'RAG & Retrieval':       'text-blue-400   bg-blue-950/50   border-blue-900/50',
  'Vector Databases':      'text-cyan-400   bg-cyan-950/50   border-cyan-900/50',
  'Reinforcement Learning':'text-orange-400 bg-orange-950/50 border-orange-900/50',
  'Multimodal AI':         'text-pink-400   bg-pink-950/50   border-pink-900/50',
  'Computer Vision':       'text-rose-400   bg-rose-950/50   border-rose-900/50',
  'NLP Foundations':       'text-teal-400   bg-teal-950/50   border-teal-900/50',
  'ML Engineering':        'text-zinc-400   bg-zinc-800/60   border-zinc-700/50',
  'AI Safety':             'text-red-400    bg-red-950/50    border-red-900/50',
  'Finance AI':            'text-green-400  bg-green-950/50  border-green-900/50',
  'General ML':            'text-slate-400  bg-slate-800/60  border-slate-700/50',
}

const STEP_GRADIENT = [
  'from-blue-600 to-blue-700',
  'from-violet-600 to-violet-700',
  'from-purple-600 to-purple-700',
  'from-pink-600 to-pink-700',
]

// Feedback button definitions — value matches the API's expected string
const FEEDBACK_BUTTONS = [
  {
    value: 'liked',
    icon: '👍',
    label: 'Helpful',
    activeClass: 'bg-emerald-900/60 border-emerald-700 text-emerald-300',
  },
  {
    value: 'disliked',
    icon: '👎',
    label: 'Not helpful',
    activeClass: 'bg-red-900/60 border-red-700 text-red-300',
  },
  {
    value: 'too_basic',
    icon: '⬆',
    label: 'Too easy',
    activeClass: 'bg-sky-900/60 border-sky-700 text-sky-300',
  },
  {
    value: 'too_advanced',
    icon: '⬇',
    label: 'Too hard',
    activeClass: 'bg-orange-900/60 border-orange-700 text-orange-300',
  },
]

function FeedbackBar({ topic, submitted, loading, onFeedback }) {
  if (submitted) {
    const btn = FEEDBACK_BUTTONS.find(b => b.value === submitted)
    return (
      <div className="mt-3 pt-3 border-t border-slate-800 flex items-center gap-2">
        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border ${btn.activeClass}`}>
          {btn.icon} {btn.label} — saved to memory
        </span>
        <span className="text-xs text-slate-600">✓</span>
      </div>
    )
  }

  return (
    <div className="mt-3 pt-3 border-t border-slate-800 flex items-center gap-1.5 flex-wrap">
      <span className="text-xs text-slate-600 mr-1">Rate:</span>
      {FEEDBACK_BUTTONS.map(btn => (
        <button
          key={btn.value}
          disabled={loading}
          onClick={() => onFeedback(topic, btn.value)}
          title={btn.label}
          className="inline-flex items-center gap-1 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-slate-600 rounded-lg text-xs text-slate-400 hover:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          {loading ? (
            <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : btn.icon} {btn.label}
        </button>
      ))}
    </div>
  )
}

export default function LearningPath({ topics, onFeedback, topicFeedback = {}, topicLoading = {} }) {
  return (
    <section>
      <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3 flex items-center gap-2">
        <span>📚</span> Progressive Learning Path
      </p>
      <div className="space-y-3">
        {topics.map((topic, i) => {
          const diff    = DIFFICULTY[topic.difficulty] ?? DIFFICULTY.beginner
          const catCls  = CATEGORY_STYLE[topic.category] ?? CATEGORY_STYLE['General ML']
          return (
            <div
              key={i}
              className="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-2xl p-4 flex items-start gap-4 transition-colors"
            >
              <div
                className={`flex-shrink-0 w-8 h-8 rounded-xl bg-gradient-to-br ${STEP_GRADIENT[i]} flex items-center justify-center text-white text-sm font-bold shadow-md`}
              >
                {i + 1}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <span className="font-semibold text-slate-100 text-sm leading-snug">
                    {topic.title}
                  </span>
                  <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap justify-end">
                    {topic.category && topic.category !== 'General ML' && (
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${catCls}`}>
                        {topic.category}
                      </span>
                    )}
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${diff.cls}`}>
                      {diff.label}
                    </span>
                  </div>
                </div>
                <p className="text-slate-400 text-xs mt-1.5 leading-relaxed">
                  {topic.reason}
                </p>
                <FeedbackBar
                  topic={topic.title}
                  submitted={topicFeedback[topic.title] ?? null}
                  loading={topicLoading[topic.title] ?? false}
                  onFeedback={onFeedback}
                />
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

const DIFFICULTY_CONFIG = {
  beginner:     { label: "Beginner",     color: "bg-emerald-900/50 border-emerald-700/40 text-emerald-300" },
  intermediate: { label: "Intermediate", color: "bg-blue-900/50 border-blue-700/40 text-blue-300" },
  advanced:     { label: "Advanced",     color: "bg-violet-900/50 border-violet-700/40 text-violet-300" },
}

export default function LearningTrack({ topics, onFeedback, topicFeedback, topicLoading }) {
  if (!topics?.length) return null

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
      <div className="px-5 py-3.5 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-200">Personalized learning track</h3>
        <p className="text-xs text-slate-500 mt-0.5">Calibrated to your profile and recent conversations</p>
      </div>

      <div className="divide-y divide-slate-800/60">
        {topics.map((topic, i) => (
          <TrackItem
            key={i}
            index={i}
            topic={topic}
            onFeedback={onFeedback}
            feedback={topicFeedback?.[topic.title]}
            loading={topicLoading?.[topic.title]}
          />
        ))}
      </div>

      {/* Learning arc indicator */}
      <div className="px-5 py-3 border-t border-slate-800/60 flex items-center gap-2">
        <div className="flex items-center gap-1">
          {["beginner", "intermediate", "intermediate", "advanced"].map((d, i) => {
            const cfg = DIFFICULTY_CONFIG[d]
            return (
              <span key={i} className={`px-1.5 py-0.5 rounded text-xs border ${cfg.color}`}>
                {cfg.label.slice(0, 3)}
              </span>
            )
          })}
        </div>
        <span className="text-xs text-slate-600">→ deliberate progression arc</span>
      </div>
    </div>
  )
}

function TrackItem({ index, topic, onFeedback, feedback, loading }) {
  const diff   = DIFFICULTY_CONFIG[topic.difficulty] || DIFFICULTY_CONFIG.intermediate
  const title  = topic.title || ""
  const number = index + 1

  return (
    <div className="px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex gap-3 flex-1 min-w-0">
          <span className="flex-shrink-0 w-5 h-5 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-slate-500 text-xs font-medium mt-0.5">
            {number}
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <span className="font-medium text-slate-100 text-sm">{title}</span>
              <span className={`px-2 py-0.5 rounded-full text-xs border ${diff.color}`}>
                {diff.label}
              </span>
              {topic.category && topic.category !== "General ML" && (
                <span className="px-2 py-0.5 rounded-full text-xs bg-slate-800 border border-slate-700 text-slate-400">
                  {topic.category}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">{topic.reason}</p>
            {topic.chat_connection && (
              <div className="flex items-start gap-1.5 mt-1.5">
                <svg className="w-3 h-3 text-violet-400 flex-shrink-0 mt-0.5" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
                </svg>
                <p className="text-xs text-violet-300/80 leading-relaxed">{topic.chat_connection}</p>
              </div>
            )}
          </div>
        </div>

        {onFeedback && (
          <FeedbackButtons
            topic={title}
            feedback={feedback}
            loading={loading}
            onFeedback={onFeedback}
          />
        )}
      </div>
    </div>
  )
}

function FeedbackButtons({ topic, feedback, loading, onFeedback }) {
  if (feedback) {
    return (
      <span className={`text-xs px-2 py-1 rounded-lg border flex-shrink-0 ${
        feedback === "liked"
          ? "bg-emerald-900/40 border-emerald-700/40 text-emerald-400"
          : "bg-red-900/40 border-red-700/40 text-red-400"
      }`}>
        {feedback === "liked" ? "✓ Liked" : "✗ Skipped"}
      </span>
    )
  }

  return (
    <div className="flex gap-1 flex-shrink-0">
      <button
        onClick={() => onFeedback(topic, "liked")}
        disabled={loading}
        className="p-1.5 rounded-lg text-slate-500 hover:text-emerald-400 hover:bg-emerald-900/30 disabled:opacity-40 transition-all"
        title="Like this topic"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
          <path d="M1 8.25a1.25 1.25 0 1 1 2.5 0v7.5a1.25 1.25 0 0 1-2.5 0v-7.5ZM11 3V1.7c0-.268.14-.526.395-.607A2 2 0 0 1 14 3c0 .995-.182 1.948-.514 2.826-.204.54.166 1.174.744 1.174h2.52c1.243 0 2.261 1.01 2.146 2.247a23.864 23.864 0 0 1-1.341 5.974C17.153 16.323 16.072 17 14.9 17h-3.192a3 3 0 0 1-1.341-.317l-2.734-1.381A3 3 0 0 0 6.292 15H5V8h.963c.685 0 1.258-.483 1.612-1.068a4.011 4.011 0 0 1 2.166-1.73c.432-.143.853-.386 1.011-.814.16-.432.248-.9.248-1.388Z" />
        </svg>
      </button>
      <button
        onClick={() => onFeedback(topic, "disliked")}
        disabled={loading}
        className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-900/30 disabled:opacity-40 transition-all"
        title="Skip this topic"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
          <path d="M18.905 12.75a1.25 1.25 0 0 1-2.5 0v-7.5a1.25 1.25 0 0 1 2.5 0v7.5ZM8.905 17v1.3c0 .268-.14.526-.395.607A2 2 0 0 1 5.905 17c0-.995.182-1.948.514-2.826.204-.54-.166-1.174-.744-1.174h-2.52c-1.243 0-2.261-1.01-2.146-2.247.193-2.08.651-4.082 1.341-5.974C2.752 3.678 3.833 3 5.005 3h3.192a3 3 0 0 1 1.341.317l2.734 1.381A3 3 0 0 0 13.613 5h1.292v7h-.963c-.685 0-1.258.483-1.612 1.068a4.011 4.011 0 0 1-2.166 1.73c-.432.143-.853.386-1.011.814-.16.432-.248.9-.248 1.388Z" />
        </svg>
      </button>
    </div>
  )
}

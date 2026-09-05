import { useState, useEffect, useRef, useMemo } from "react"
import LogoMark from "../components/shared/LogoMark.jsx"
import { Link, useParams, useNavigate } from "react-router-dom"
import { resolveShareLink, forkSharedChat } from "../api/share.js"
import { getToken } from "../api/auth.js"
import { articleKeyFromTitle } from "../api/feed.js"
import InsightCard from "../components/feed/InsightCard.jsx"
import ChatMessage from "../components/chat/ChatMessage.jsx"
import FilesPanel, { FilesIcon } from "../components/chat/FilesPanel.jsx"
import LoadingState from "../components/LoadingState.jsx"
import LearningCalendar from "../components/feed/LearningCalendar.jsx"
import {
  StatsStrip,
  WeekdayChart,
  WeeklyGoalCard,
  ConsistencyCard,
  getMondayOfThisWeek,
} from "../components/dashboard/DashboardPage.jsx"

function Wordmark() {
  return (
    <Link to="/" className="inline-flex items-center gap-2.5 hover:opacity-80 transition-opacity">
      <LogoMark size={28} className="flex-shrink-0" />
      <span className="font-bold text-[15px] tracking-tight select-none bg-gradient-to-r from-slate-100 to-slate-300 bg-clip-text text-transparent">
        Curivio
      </span>
    </Link>
  )
}

function FeedShare({ resourceId, pkg }) {
  const parts = resourceId.split("/")
  const targetArticleKey = parts[2] ? decodeURIComponent(parts[2]) : null
  const [highlightKey, setHighlightKey] = useState(null)

  useEffect(() => {
    if (!targetArticleKey) return
    const raf = requestAnimationFrame(() => {
      const el = document.getElementById(`share-card-${targetArticleKey}`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" })
        setHighlightKey(targetArticleKey)
        setTimeout(() => setHighlightKey(null), 1500)
      }
    })
    return () => cancelAnimationFrame(raf)
  }, [targetArticleKey])

  const projectId      = parts[0]
  const newsCards      = pkg.insights?.filter(c => c.content_type === "news") || []
  const eduCards       = pkg.insights?.filter(c => c.content_type === "educational") || []
  const allCoreCards   = pkg.insights || []
  const curiosityCards = pkg.curiosity_insights || []
  const openHref = getToken() ? `/feed/${resourceId}` : `/login?next=${encodeURIComponent(`/feed/${resourceId}`)}`

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 md:px-8 md:py-10">
      <div className="mb-6">
        <Wordmark />
      </div>

      <h1 className="text-[17px] md:text-[22px] font-bold text-slate-100 leading-snug tracking-tight mb-1.5 md:mb-4 break-words">
        {pkg.package_headline}
      </h1>
      {pkg.learning_thread && (
        <p className="text-[12px] text-slate-500 leading-relaxed mb-4">{pkg.learning_thread}</p>
      )}

      <div className="space-y-2 md:space-y-3">
        {(newsCards.length > 0 || eduCards.length > 0 ? [...newsCards, ...eduCards] : allCoreCards).map((card, i) => {
          const ak = articleKeyFromTitle(card.title || "")
          return (
            <div
              key={card.id || i}
              id={`share-card-${ak}`}
              className={`rounded-2xl transition-shadow duration-500 ${highlightKey === ak ? "ring-2 ring-blue-500/50" : ""}`}
            >
              <InsightCard card={card} readOnly day={pkg.id} articleKey={ak} projectId={projectId} />
            </div>
          )
        })}
        {curiosityCards.map((card, i) => {
          const ak = articleKeyFromTitle(card.title || "")
          return (
            <div key={card.id || `curiosity-${i}`} id={`share-card-${ak}`}>
              <InsightCard card={card} readOnly day={pkg.id} articleKey={ak} projectId={projectId} />
            </div>
          )
        })}
      </div>

      <div className="mt-6">
        <Link
          to={openHref}
          className="inline-flex items-center px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
        >
          Open in Curivio
        </Link>
      </div>
    </div>
  )
}

const DEFAULT_WEEKLY_GOAL = 15

function DashboardShare({ username, stats, activity }) {
  const thisWeekCards = useMemo(() => {
    const weekStart = getMondayOfThisWeek()
    return activity
      .filter(d => new Date(d.date + "T00:00:00") >= weekStart)
      .reduce((sum, d) => sum + d.cards_read, 0)
  }, [activity])

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 md:px-8 md:py-10">
      <div className="mb-6">
        <Wordmark />
      </div>

      <h1 className="text-2xl font-bold text-slate-100 tracking-tight mb-6">
        {username}'s Dashboard
      </h1>

      <StatsStrip stats={stats} loading={false} />

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-5 items-start">
        <div className="space-y-5 min-w-0">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">Learning Calendar</span>
            </div>
            <LearningCalendar data={activity} loading={false} projectName="All Projects" />
          </div>
          <WeekdayChart activityData={activity} />
        </div>

        <div className="space-y-4">
          <WeeklyGoalCard current={thisWeekCards} target={DEFAULT_WEEKLY_GOAL} onChangeTarget={() => {}} />
          <ConsistencyCard activityData={activity} />
        </div>
      </div>
    </div>
  )
}

function ChatShare({ token, messages }) {
  const navigate = useNavigate()
  const [forking, setForking] = useState(false)
  const [forkError, setForkError] = useState(false)
  const [filesPanelOpen, setFilesPanelOpen] = useState(false)
  const errorTimerRef = useRef(null)

  useEffect(() => () => clearTimeout(errorTimerRef.current), [])

  async function handleContinue() {
    if (!getToken()) {
      navigate(`/login?next=${encodeURIComponent(`/share/${token}`)}&intent=fork`)
      return
    }
    setForking(true)
    setForkError(false)
    try {
      const { new_chat_id } = await forkSharedChat(token)
      navigate(`/chat/${new_chat_id}`)
    } catch {
      setForking(false)
      setForkError(true)
      clearTimeout(errorTimerRef.current)
      errorTimerRef.current = setTimeout(() => setForkError(false), 3000)
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 md:px-8 md:py-10">
      <div className="mb-6">
        <Wordmark />
      </div>

      {/* Files panel toggle — same fixed top-right convention as ChatWorkspace's
          desktop icon; this page has no mobile overflow menu to fall back to,
          so it's always visible here rather than hidden md:block. */}
      {messages.length > 0 && (
        <div className="fixed top-3.5 right-3.5 z-50">
          <button
            onClick={() => setFilesPanelOpen(true)}
            title="Files"
            aria-label="Files"
            className="inline-flex items-center justify-center w-7 h-7 rounded-lg text-slate-400 hover:text-blue-300 bg-slate-800/40 hover:bg-blue-500/10 border border-slate-700/40 hover:border-blue-500/30 transition-all"
          >
            <FilesIcon />
          </button>
        </div>
      )}

      <div className="space-y-4">
        {messages.map((msg, i) => (
          <ChatMessage key={i} message={msg} msgIndex={i} shareToken={token} />
        ))}
      </div>

      <div className="mt-6">
        <button
          onClick={handleContinue}
          disabled={forking}
          className="inline-flex items-center px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
        >
          {forking ? "Forking…" : "Continue this conversation"}
        </button>
        {forkError && (
          <p className="mt-2 text-xs text-red-400">Something went wrong. Try again.</p>
        )}
      </div>

      {filesPanelOpen && (
        <FilesPanel messages={messages} shareToken={token} onClose={() => setFilesPanelOpen(false)} />
      )}
    </div>
  )
}

export default function SharePage() {
  const { token } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(false)
    resolveShareLink(token)
      .then(result => { if (!cancelled) setData(result) })
      .catch(() => { if (!cancelled) setError(true) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token])

  if (loading) {
    return (
      <div className="min-h-screen min-h-dvh bg-slate-950 text-slate-100 px-4 py-8 md:px-8 md:py-10">
        <div className="max-w-2xl mx-auto">
          <div className="mb-6"><Wordmark /></div>
          <LoadingState />
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="min-h-screen min-h-dvh bg-slate-950 text-slate-100 flex items-center justify-center px-4">
        <div className="text-center">
          <p className="text-sm text-slate-400 mb-3">This link is no longer available.</p>
          <Link to="/" className="text-sm text-blue-400 hover:text-blue-300 transition-colors">← Back to Curivio</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen min-h-dvh bg-slate-950 text-slate-100">
      {data.type === "feed" ? (
        <FeedShare resourceId={data.resource_id} pkg={data.package} />
      ) : data.type === "dashboard" ? (
        <DashboardShare username={data.username} stats={data.stats} activity={data.activity} />
      ) : (
        <ChatShare token={token} messages={data.messages} />
      )}
    </div>
  )
}

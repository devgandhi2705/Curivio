import { useState, useEffect, useMemo } from "react"
import { listProjects } from "../../api/projects.js"
import { getReadingStats } from "../../api/feed.js"
import { getProjectActivity, getAllProjectsActivity } from "../../api/activity.js"
import LearningCalendar from "../feed/LearningCalendar.jsx"

// ── Constants & helpers ───────────────────────────────────────────────────────

const WEEKDAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
const WEEKLY_GOAL_KEY = "learning_weekly_goal"

const COLOR_DOT = {
  blue:    "bg-blue-500",
  emerald: "bg-emerald-500",
  violet:  "bg-violet-500",
  amber:   "bg-amber-500",
  rose:    "bg-rose-500",
}

const COLOR_BAR = {
  blue:    "from-blue-500 to-blue-600",
  emerald: "from-emerald-500 to-emerald-600",
  violet:  "from-violet-500 to-violet-600",
  amber:   "from-amber-500 to-amber-600",
  rose:    "from-rose-500 to-rose-600",
}

function getStoredWeeklyGoal() {
  try { return parseInt(localStorage.getItem(WEEKLY_GOAL_KEY) || "15", 10) } catch { return 15 }
}
function setStoredWeeklyGoal(n) {
  try { localStorage.setItem(WEEKLY_GOAL_KEY, String(n)) } catch {}
}

function getMondayOfThisWeek() {
  const d = new Date()
  const dow = d.getDay()
  const monday = new Date(d)
  monday.setDate(d.getDate() - (dow === 0 ? 6 : dow - 1))
  monday.setHours(0, 0, 0, 0)
  return monday
}

function formatLastActive(ts) {
  if (!ts) return null
  const diff = Date.now() - new Date(ts).getTime()
  const days = Math.floor(diff / 86400000)
  if (days === 0) return "Today"
  if (days === 1) return "Yesterday"
  if (days < 7) return `${days}d ago`
  return `${Math.floor(days / 7)}w ago`
}

// ── Stats strip ───────────────────────────────────────────────────────────────

function StatsStrip({ stats, loading }) {
  if (loading) {
    return <div className="h-[60px] rounded-2xl bg-slate-900/60 border border-slate-800/50 animate-pulse mb-5" />
  }
  if (!stats) return null

  const {
    current_streak = 0, longest_streak = 0,
    total_cards_read = 0, today_cards_read = 0,
    total_packages = 0, active_projects = 0,
  } = stats
  const streakActive = current_streak > 0

  const tiles = [
    {
      icon: streakActive ? "🔥" : "💤",
      value: `${current_streak}d`,
      label: streakActive
        ? (longest_streak > current_streak && longest_streak > 1 ? `streak · best ${longest_streak}d` : "current streak")
        : "no streak",
      accent: streakActive ? "text-amber-400" : "text-slate-600",
      bg: streakActive ? "bg-amber-950/20" : "",
    },
    {
      icon: "📖",
      value: today_cards_read,
      label: "read today",
      accent: today_cards_read > 0 ? "text-emerald-400" : "text-slate-500",
      bg: "",
    },
    {
      icon: "📚",
      value: total_cards_read,
      label: "cards total",
      accent: "text-slate-200",
      bg: "",
    },
    {
      icon: "📦",
      value: total_packages,
      label: total_packages === 1 ? "package" : "packages",
      accent: "text-slate-200",
      bg: "",
    },
    {
      icon: "🗂️",
      value: active_projects,
      label: active_projects === 1 ? "project" : "projects",
      accent: "text-slate-200",
      bg: "",
    },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 mb-5 rounded-2xl bg-slate-900/60 border border-slate-800/50 overflow-hidden divide-y sm:divide-y-0 sm:divide-x divide-slate-800/50">
      {tiles.map((t, i) => (
        <div key={i} className={`flex items-center gap-2 sm:gap-2.5 px-3 sm:px-4 py-2.5 sm:py-3 ${t.bg} ${i === tiles.length - 1 ? "col-span-2 sm:col-span-1" : ""}`}>
          <span className="text-lg leading-none">{t.icon}</span>
          <div className="min-w-0">
            <div className={`text-[17px] font-bold leading-none tabular-nums ${t.accent}`}>{t.value}</div>
            <div className="text-[10px] text-slate-600 mt-0.5 whitespace-nowrap">{t.label}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Weekly goal ring ──────────────────────────────────────────────────────────

function GoalRing({ current, target }) {
  const pct = Math.min(current / Math.max(target, 1), 1)
  const R = 46
  const cx = 58
  const cy = 58
  const circumference = 2 * Math.PI * R
  const offset = circumference * (1 - pct)
  const done = current >= target

  return (
    <svg width={116} height={116} viewBox="0 0 116 116">
      <circle cx={cx} cy={cy} r={R} fill="none" strokeWidth="9" stroke="#1e293b" />
      <circle
        cx={cx} cy={cy} r={R} fill="none" strokeWidth="9"
        stroke={done ? "#10b981" : "#3b82f6"}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ transition: "stroke-dashoffset 0.6s ease, stroke 0.3s" }}
      />
      <text x={cx} y={cy - 6} textAnchor="middle"
        style={{ fontSize: 26, fontWeight: 700, fill: done ? "#10b981" : "#e2e8f0", fontFamily: "inherit" }}>
        {current}
      </text>
      <text x={cx} y={cy + 14} textAnchor="middle"
        style={{ fontSize: 11, fill: "#475569", fontFamily: "inherit" }}>
        of {target}
      </text>
    </svg>
  )
}

function WeeklyGoalCard({ current, target, onChangeTarget }) {
  const [editing, setEditing] = useState(false)
  const [draft,   setDraft]   = useState(String(target))
  const done = current >= target
  const remaining = target - current

  function commit() {
    const n = parseInt(draft, 10)
    if (n > 0 && n <= 500) onChangeTarget(n)
    setEditing(false)
  }

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-2xl p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">Weekly Goal</p>
          <p className={`text-xs mt-1 font-medium ${done ? "text-emerald-400" : "text-slate-500"}`}>
            {done ? "Goal reached this week!" : `${remaining} card${remaining !== 1 ? "s" : ""} to go`}
          </p>
        </div>
        {editing ? (
          <div className="flex items-center gap-1.5">
            <input
              autoFocus
              type="number"
              min={1} max={500}
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false) }}
              className="w-14 px-2 py-1 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-200 text-center outline-none focus:border-slate-600"
            />
            <button onClick={commit} className="text-[11px] text-blue-400 hover:text-blue-300 transition-colors">set</button>
          </div>
        ) : (
          <button
            onClick={() => { setDraft(String(target)); setEditing(true) }}
            className="text-[11px] text-slate-600 hover:text-slate-400 transition-colors"
          >
            Edit goal
          </button>
        )}
      </div>
      <div className="flex justify-center">
        <GoalRing current={current} target={target} />
      </div>
      <p className="text-center text-[11px] text-slate-600 mt-3">cards read this week</p>
    </div>
  )
}

// ── 30-day consistency card ───────────────────────────────────────────────────

function ConsistencyCard({ activityData }) {
  const { pct, activeDays, label, colorClass, cells } = useMemo(() => {
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - 29)
    cutoff.setHours(0, 0, 0, 0)

    const cells = []
    for (let i = 0; i < 30; i++) {
      const d = new Date(cutoff)
      d.setDate(cutoff.getDate() + i)
      const iso = d.toISOString().slice(0, 10)
      const entry = activityData.find(a => a.date === iso)
      cells.push(!!(entry && (entry.cards_read > 0 || entry.packages_generated > 0)))
    }

    const activeDays = cells.filter(Boolean).length
    const pct = Math.round((activeDays / 30) * 100)
    const label      = pct >= 70 ? "Excellent"     : pct >= 40 ? "Good"    : pct >= 15 ? "Building"      : "Just Starting"
    const colorClass = pct >= 70 ? "text-emerald-400" : pct >= 40 ? "text-amber-400" : "text-rose-400"
    return { pct, activeDays, label, colorClass, cells }
  }, [activityData])

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-2xl p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">30-Day Consistency</p>
          <p className={`text-xs font-semibold mt-1 ${colorClass}`}>{label}</p>
        </div>
        <div className="text-right">
          <span className={`text-2xl font-bold tabular-nums leading-none ${colorClass}`}>{pct}%</span>
          <p className="text-[10px] text-slate-600 mt-0.5">{activeDays} / 30 days</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-[3px]">
        {cells.map((active, i) => (
          <div
            key={i}
            className={`w-[13px] h-[13px] rounded-sm transition-colors ${active ? "bg-blue-600/80" : "bg-slate-800/60"}`}
          />
        ))}
      </div>
      <p className="text-[10px] text-slate-700 mt-2.5">last 30 days</p>
    </div>
  )
}

// ── Weekday activity chart ────────────────────────────────────────────────────

function WeekdayChart({ activityData }) {
  const bars = useMemo(() => {
    const totals = Array(7).fill(0)
    const counts = Array(7).fill(0)
    activityData.forEach(d => {
      if (d.cards_read === 0) return
      const dow = new Date(d.date + "T00:00:00").getDay()
      totals[dow] += d.cards_read
      counts[dow]++
    })
    return WEEKDAY_NAMES.map((name, i) => ({
      name,
      avg: counts[i] > 0 ? totals[i] / counts[i] : 0,
      total: totals[i],
    }))
  }, [activityData])

  const maxAvg  = Math.max(...bars.map(b => b.avg), 1)
  const hasData = bars.some(b => b.avg > 0)
  const bestIdx = hasData ? bars.reduce((bi, b, i) => (b.avg > bars[bi].avg ? i : bi), 0) : -1

  return (
    <div className="bg-slate-900/60 border border-slate-800/60 rounded-2xl px-5 py-5">
      <div className="flex items-center justify-between mb-5">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">Activity by Weekday</p>
        {hasData && bestIdx >= 0 && (
          <p className="text-[11px] text-slate-600">
            Most active: <span className="text-blue-400">{bars[bestIdx].name}</span>
          </p>
        )}
      </div>
      <div className="flex items-end gap-2 h-[80px]">
        {bars.map(({ name, avg, total }, i) => (
          <div
            key={name}
            className="flex-1 flex flex-col items-center gap-2 h-full"
            title={total > 0 ? `${name}: avg ${avg.toFixed(1)} cards/active day` : `${name}: no activity`}
          >
            <div className="w-full flex items-end flex-1">
              <div
                className={`w-full rounded-md transition-all duration-500 ${
                  avg === 0 ? "bg-slate-800/50" : i === bestIdx ? "bg-blue-500" : "bg-blue-700/50"
                }`}
                style={{ height: `${Math.max((avg / maxAvg) * 64, avg > 0 ? 6 : 3)}px` }}
              />
            </div>
            <span className="text-[10px] text-slate-600 leading-none">{name}</span>
          </div>
        ))}
      </div>
      {!hasData && (
        <p className="text-center text-[11px] text-slate-700 mt-2">No activity data yet</p>
      )}
    </div>
  )
}

// ── Project leaderboard ───────────────────────────────────────────────────────

function ProjectLeaderboard({ projects }) {
  const ranked = useMemo(() =>
    [...projects]
      .sort((a, b) => (b.insight_count || 0) - (a.insight_count || 0))
      .slice(0, 6),
    [projects]
  )
  const max = Math.max(...ranked.map(p => p.insight_count || 0), 1)

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-2xl p-5">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-500 mb-4">
        Project Activity
      </p>
      {ranked.length === 0 ? (
        <p className="text-xs text-slate-600 py-2">No projects yet.</p>
      ) : (
        <div className="space-y-3.5">
          {ranked.map((p, i) => {
            const lastActive = formatLastActive(p.last_insight_at)
            return (
              <div key={p.project_id} className="flex items-center gap-2.5">
                <span className="text-[10px] text-slate-700 w-3 text-right flex-shrink-0">{i + 1}</span>
                <div className={`w-2 h-2 rounded-full flex-shrink-0 ${COLOR_DOT[p.color] ?? "bg-blue-500"}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs text-slate-300 truncate leading-none">{p.name}</span>
                    <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                      {lastActive && (
                        <span className="text-[9px] text-slate-700">{lastActive}</span>
                      )}
                      <span className="text-[10px] text-slate-500 tabular-nums">
                        {p.insight_count || 0}d
                      </span>
                    </div>
                  </div>
                  <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full bg-gradient-to-r ${COLOR_BAR[p.color] ?? COLOR_BAR.blue} rounded-full`}
                      style={{
                        width: `${Math.max(((p.insight_count || 0) / max) * 100, p.insight_count ? 4 : 0)}%`,
                        transition: "width 0.5s ease",
                      }}
                    />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Project selector ──────────────────────────────────────────────────────────

function ProjectSelector({ projects, value, onChange }) {
  if (projects.length === 0) return null
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="text-xs bg-slate-800 border border-slate-700/60 text-slate-300 rounded-lg px-2.5 py-1 outline-none focus:border-slate-600 cursor-pointer"
    >
      <option value="all">All Projects</option>
      {projects.map(p => (
        <option key={p.project_id} value={p.project_id}>{p.name}</option>
      ))}
    </select>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function DashboardPage({ onGoToFeed, userName }) {
  const [stats,             setStats]             = useState(null)
  const [statsLoading,      setStatsLoading]      = useState(true)
  const [projects,          setProjects]          = useState([])
  const [projectsLoading,   setProjectsLoading]   = useState(true)
  const [selectedProjectId, setSelectedProjectId] = useState('all')
  const [activityData,      setActivityData]      = useState([])
  const [activityLoading,   setActivityLoading]   = useState(false)
  const [weeklyTarget,      setWeeklyTarget]      = useState(getStoredWeeklyGoal)

  useEffect(() => {
    getReadingStats()
      .then(setStats).catch(() => setStats(null))
      .finally(() => setStatsLoading(false))

    listProjects()
      .then(data => { setProjects(data) })
      .catch(() => {})
      .finally(() => setProjectsLoading(false))
  }, [])

  useEffect(() => {
    setActivityLoading(true)
    const fetchPromise = selectedProjectId === 'all'
      ? getAllProjectsActivity()
      : getProjectActivity(selectedProjectId)
    fetchPromise
      .then(setActivityData).catch(() => setActivityData([]))
      .finally(() => setActivityLoading(false))
  }, [selectedProjectId])

  const thisWeekCards = useMemo(() => {
    const weekStart = getMondayOfThisWeek()
    return activityData
      .filter(d => new Date(d.date + "T00:00:00") >= weekStart)
      .reduce((sum, d) => sum + d.cards_read, 0)
  }, [activityData])

  const selectedProject = projects.find(p => p.project_id === selectedProjectId) ?? null
  const calendarLabel = selectedProjectId === 'all' ? 'All Projects' : (selectedProject?.name ?? '')

  function handleChangeTarget(n) {
    setWeeklyTarget(n)
    setStoredWeeklyGoal(n)
  }

  const hour      = new Date().getHours()
  const firstName = (userName || "").split(" ")[0]
  const timeStr   = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : hour < 21 ? "Good evening" : "Burning the midnight oil"
  const greeting  = firstName ? `${timeStr}, ${firstName}` : timeStr
  const dateStr  = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })

  return (
    <div>
      {/* Greeting */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100 tracking-tight">{greeting}</h1>
        <p className="text-sm text-slate-500 mt-1">{dateStr}</p>
      </div>

      {/* Stats strip */}
      <StatsStrip stats={stats} loading={statsLoading} />

      {/* Main 2-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-5 items-start">

        {/* ── Left: calendar + weekday chart ── */}
        <div className="space-y-5 min-w-0">

          {/* Calendar */}
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">Learning Calendar</span>
              <ProjectSelector projects={projects} value={selectedProjectId} onChange={setSelectedProjectId} />
            </div>
            {projectsLoading ? (
              <div className="h-48 rounded-2xl bg-slate-900/40 border border-slate-800/50 animate-pulse" />
            ) : projects.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-14 rounded-2xl bg-slate-900/40 border border-slate-800/50">
                <p className="text-sm text-slate-500 mb-2">No projects yet.</p>
                <button onClick={onGoToFeed} className="text-xs text-blue-400 hover:text-blue-300 transition-colors">
                  Create your first project →
                </button>
              </div>
            ) : (
              <LearningCalendar
                data={activityData}
                loading={activityLoading}
                projectName={calendarLabel}
              />
            )}
          </div>

          {/* Weekday chart — always visible */}
          <WeekdayChart activityData={activityData} />
        </div>

        {/* ── Right: analytics cards ── */}
        <div className="space-y-4">
          <WeeklyGoalCard
            current={thisWeekCards}
            target={weeklyTarget}
            onChangeTarget={handleChangeTarget}
          />
          <ConsistencyCard activityData={activityData} />
        </div>

      </div>
    </div>
  )
}

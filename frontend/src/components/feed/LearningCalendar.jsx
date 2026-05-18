/**
 * LearningCalendar — GitHub-style contribution heatmap.
 *
 * Shows 52 weeks (365 days) of per-project learning activity:
 *   - Blue intensity  → total cards read
 *   - Emerald ring    → a package was generated that day
 *   - White dot ring  → today
 *
 * Props:
 *   data        — array of { date, packages_generated, cards_read }
 *   loading     — boolean skeleton placeholder
 *   projectName — shown in empty state
 */
import { useState, useMemo, useEffect, useRef } from "react"

// ─── Constants ────────────────────────────────────────────────────────────────

const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
const DAY_ABBR    = ["", "Mon", "", "Wed", "", "Fri", ""]  // Sunday = 0
const CELL        = 11   // px square
const GAP         = 2    // px gap
const STRIDE      = CELL + GAP  // 13px per cell+gap

// ─── Color scale ──────────────────────────────────────────────────────────────
// Score = cards_read + packages_generated × 4
// Levels mirror GitHub's 5-band approach.

function activityScore(cardsRead, packagesGenerated) {
  return cardsRead + packagesGenerated * 4
}

function scoreLevel(score) {
  if (score === 0) return 0
  if (score <= 3)  return 1
  if (score <= 7)  return 2
  if (score <= 13) return 3
  return 4
}

// Tailwind classes for each level
const LEVEL_BG = [
  "bg-slate-800/60",                                 // 0 — no activity
  "bg-blue-950  border border-blue-900/50",          // 1 — faint
  "bg-blue-800/90",                                  // 2 — light
  "bg-blue-600",                                     // 3 — medium
  "bg-blue-400",                                     // 4 — active
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function friendlyDate(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    weekday: "short", month: "short", day: "numeric",
  })
}

/**
 * Group flat data array into week columns (Sunday-first).
 * Returns Array<Array<day|null>> where null = blank padding cell.
 */
function buildWeekColumns(data) {
  if (!data.length) return []

  const firstDate = new Date(data[0].date + "T00:00:00")
  const leadingBlanks = firstDate.getDay()            // 0 = Sun … 6 = Sat

  const flat = [...Array(leadingBlanks).fill(null), ...data]
  const cols = []
  for (let i = 0; i < flat.length; i += 7) {
    const col = flat.slice(i, i + 7)
    while (col.length < 7) col.push(null)             // trailing blanks
    cols.push(col)
  }
  return cols
}

/**
 * Walk week columns and return [{wi, label}] for the first week of each month.
 */
function buildMonthPositions(weeks) {
  const positions = []
  let lastMonth = -1
  weeks.forEach((col, wi) => {
    const firstDay = col.find(d => d !== null)
    if (!firstDay) return
    const m = new Date(firstDay.date + "T00:00:00").getMonth()
    if (m !== lastMonth) {
      positions.push({ wi, label: MONTH_NAMES[m] })
      lastMonth = m
    }
  })
  return positions
}

// ─── Tooltip ──────────────────────────────────────────────────────────────────

function CalendarTooltip({ tooltip }) {
  if (!tooltip) return null
  const { day, x, y } = tooltip
  const score = activityScore(day.cards_read, day.packages_generated)

  return (
    <div
      className="fixed z-[200] pointer-events-none"
      style={{ left: x, top: y - 10, transform: "translate(-50%, -100%)" }}
    >
      <div className="bg-slate-800 border border-slate-700/60 rounded-xl px-3 py-2.5 shadow-2xl min-w-[130px]">
        <p className="text-[11px] font-semibold text-slate-200 mb-1.5">{friendlyDate(day.date)}</p>
        {score === 0 ? (
          <p className="text-[10px] text-slate-500">No activity</p>
        ) : (
          <>
            {day.cards_read > 0 && (
              <div className="flex items-center gap-1.5 text-[10px] text-blue-300">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" />
                {day.cards_read} card{day.cards_read !== 1 ? "s" : ""} read
              </div>
            )}
            {day.packages_generated > 0 && (
              <div className="flex items-center gap-1.5 text-[10px] text-emerald-300 mt-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
                {day.packages_generated} package{day.packages_generated !== 1 ? "s" : ""} generated
              </div>
            )}
          </>
        )}
      </div>
      {/* Down arrow */}
      <div className="flex justify-center -mt-px">
        <div
          className="border-l-4 border-r-4 border-t-4 border-l-transparent border-r-transparent border-t-slate-700/60"
          style={{ width: 0, height: 0 }}
        />
      </div>
    </div>
  )
}

// ─── Cell ─────────────────────────────────────────────────────────────────────

function CalendarCell({ day, isToday, onEnter, onLeave }) {
  if (!day) {
    return <div style={{ width: CELL, height: CELL }} className="rounded-sm" />
  }

  const score   = activityScore(day.cards_read, day.packages_generated)
  const level   = scoreLevel(score)
  const hasPkg  = day.packages_generated > 0

  return (
    <div
      style={{ width: CELL, height: CELL }}
      className={[
        "rounded-sm cursor-default relative transition-opacity hover:opacity-75",
        LEVEL_BG[level],
        isToday
          ? "ring-1 ring-white/40 ring-offset-1 ring-offset-slate-950"
          : "",
        hasPkg && level < 2
          ? "ring-1 ring-emerald-600/60"
          : "",
      ].join(" ")}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    />
  )
}

// ─── Main export ──────────────────────────────────────────────────────────────

export default function LearningCalendar({ data = [], loading = false, projectName = "" }) {
  const [tooltip, setTooltip]     = useState(null)
  const [collapsed, setCollapsed] = useState(false)
  const today = todayIso()

  const weeks          = useMemo(() => buildWeekColumns(data), [data])
  const monthPositions = useMemo(() => buildMonthPositions(weeks), [weeks])

  // Summary stats
  const totalRead     = data.reduce((s, d) => s + d.cards_read, 0)
  const totalPackages = data.reduce((s, d) => s + d.packages_generated, 0)
  const activeDays    = data.filter(d => d.cards_read > 0 || d.packages_generated > 0).length

  function handleEnter(day, e) {
    const rect = e.currentTarget.getBoundingClientRect()
    setTooltip({ day, x: rect.left + rect.width / 2, y: rect.top })
  }

  return (
    <div className="rounded-2xl border border-slate-800/60 bg-slate-900/30 mb-5">

      {/* Collapsible header */}
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-slate-800/20 transition-colors rounded-2xl text-left"
      >
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">
            Learning Calendar
          </span>
          {!loading && activeDays > 0 && (
            <span className="text-[11px] text-slate-600">
              {activeDays} active day{activeDays !== 1 ? "s" : ""}
              {totalRead > 0 && ` · ${totalRead} cards read`}
              {totalPackages > 0 && ` · ${totalPackages} package${totalPackages !== 1 ? "s" : ""}`}
            </span>
          )}
        </div>
        <svg
          className={`w-3 h-3 text-slate-700 transition-transform duration-200 ${collapsed ? "-rotate-90" : ""}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
        </svg>
      </button>

      {!collapsed && (
        <div className="px-5 pb-4">
          {loading ? (
            <div className="h-[90px] rounded-xl bg-slate-800/30 animate-pulse" />
          ) : weeks.length === 0 ? (
            <p className="text-xs text-slate-600 py-3 text-center">
              Generate your first package for <span className="text-slate-400">{projectName}</span> to start tracking your learning streak.
            </p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <div style={{ minWidth: "fit-content" }}>

                  {/* Month labels */}
                  <div
                    className="flex items-end mb-1"
                    style={{ paddingLeft: 28 }}  // align with grid (day-label column width)
                  >
                    {weeks.map((_, wi) => {
                      const pos = monthPositions.find(p => p.wi === wi)
                      return (
                        <div
                          key={wi}
                          style={{ width: STRIDE, flexShrink: 0 }}
                          className="text-[9px] text-slate-600 leading-none select-none"
                        >
                          {pos?.label ?? ""}
                        </div>
                      )
                    })}
                  </div>

                  {/* Day labels + grid */}
                  <div className="flex items-start" style={{ gap: GAP * 2 }}>

                    {/* Day-of-week labels */}
                    <div className="flex flex-col" style={{ gap: GAP, width: 24, flexShrink: 0 }}>
                      {DAY_ABBR.map((label, i) => (
                        <div
                          key={i}
                          style={{ height: CELL }}
                          className="text-[9px] text-slate-600 leading-none flex items-center justify-end select-none"
                        >
                          {label}
                        </div>
                      ))}
                    </div>

                    {/* Week columns */}
                    <div className="flex" style={{ gap: GAP }}>
                      {weeks.map((col, wi) => (
                        <div key={wi} className="flex flex-col" style={{ gap: GAP }}>
                          {col.map((day, di) => (
                            <CalendarCell
                              key={di}
                              day={day}
                              isToday={day?.date === today}
                              onEnter={day ? (e) => handleEnter(day, e) : undefined}
                              onLeave={() => setTooltip(null)}
                            />
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Footer: legend + key */}
              <div className="flex flex-wrap items-center gap-y-2 justify-between mt-3">
                <div className="flex items-center gap-3 text-[9px] text-slate-600">
                  <span className="flex items-center gap-1">
                    <span className="inline-block w-2 h-2 rounded-sm ring-1 ring-emerald-600/60 bg-slate-800/60" />
                    package generated
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block w-2 h-2 rounded-sm ring-1 ring-white/40 ring-offset-1 ring-offset-slate-950 bg-slate-800/60" />
                    today
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-[9px] text-slate-600 mr-0.5">Less</span>
                  {LEVEL_BG.map((cls, i) => (
                    <div
                      key={i}
                      style={{ width: CELL, height: CELL }}
                      className={`rounded-sm ${cls.split(" ")[0]}`}
                    />
                  ))}
                  <span className="text-[9px] text-slate-600 ml-0.5">More</span>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      <CalendarTooltip tooltip={tooltip} />
    </div>
  )
}

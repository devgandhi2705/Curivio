/**
 * DailyPackageView — renders a full daily intelligence package for a project.
 *
 * Layout:
 *   Left: package content (headline, thread, insight cards, action item)
 *   Right sidebar: package history list (when > 1 package exists)
 *
 * Props:
 *   project           — project object
 *   packages          — list of package objects, newest first
 *   onGenerate()      — trigger next-day generation
 *   generating        — boolean
 *   onOpenInChat(card, action, projectMeta) — open card in chat
 *   readKeys          — Set<articleKey> for the currently-viewed package
 *   onMarkRead(insightId, articleKey, articleTitle)
 *   onMarkUnread(insightId, articleKey)
 *   relatedChatsMap   — Map<articleKey, list|null> for loaded related chats
 *   onLoadRelatedChats(insightId, articleKey)
 *   onOpenChat(sessionId)
 */
import { useState, useEffect, useRef } from "react"
import { createPortal } from "react-dom"
import { useNavigate, useLocation } from "react-router-dom"
import { AnimatePresence } from "../../lib/motion.jsx"
import ReadingMode from "./reader/ReadingMode.jsx"
import PopMenu from "../shared/PopMenu.jsx"
import { useChangeCount, useCompletedCount } from "../../hooks/useChangeCount.js"
import Confetti from "../shared/Confetti.jsx"
import Plate from "../shared/Plate.jsx"
import WaveDots from "../shared/WaveDots.jsx"
import { haptic } from "../../lib/motionPrefs.js"
import InsightCard from "./InsightCard.jsx"
import { articleKeyFromTitle } from "../../api/feed.js"
import { getInsightNotes, saveCardNote, deleteCardNote } from "../../api/notes.js"
import { exportAsPdf, downloadMarkdown } from "../../utils/exportPackage.js"
import { getQueue, addToQueue, removeFromQueue, isInQueue } from "../../api/queue.js"
import { getJourneyPreview } from "../../api/projects.js"
import { savePackage, deletePackage } from "../../lib/offlineStorage.js"

function formatDate(ts) {
  if (!ts) return ""
  try {
    return new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
  } catch { return "" }
}

// Compute human-readable day labels for all packages.
// Multiple packages on the same calendar date are sub-numbered: Day 2, Day 2.1, Day 2.2 …
// Failed/empty packages are labelled "Day 0".
export function computeDisplayLabels(packages) {
  const sorted = [...packages].sort((a, b) => a.day_number - b.day_number)
  const labels = new Map()
  let calendarDay = 0
  let lastDate = null
  let subCount = 0

  for (const pkg of sorted) {
    if (isFailedPackage(pkg)) {
      labels.set(pkg.id, "Day 0")
      continue
    }
    const dateStr = pkg.generated_at
      ? new Date(pkg.generated_at).toLocaleDateString("en-CA")
      : null
    if (dateStr !== lastDate) {
      calendarDay++
      subCount = 0
      lastDate = dateStr
      labels.set(pkg.id, `Day ${calendarDay}`)
    } else {
      subCount++
      labels.set(pkg.id, `Day ${calendarDay}.${subCount}`)
    }
  }
  return labels
}

// Compute the label for the *next* package to be generated.
// - New calendar day  → "Day X+1"
// - Same calendar day → "Day X.N"  (N = how many packages already exist today)
export function computeNextLabel(packages, displayLabels, generatedTodayCount) {
  if (packages.length === 0) return "Day 1"
  const latestGood = packages.find(p => displayLabels.get(p.id) !== "Day 0")
  const latestLabel = latestGood ? displayLabels.get(latestGood.id) : null
  if (!latestLabel) return "Day 1"
  const baseNum = parseInt(latestLabel.match(/^Day (\d+)/)?.[1] ?? "1", 10)
  return generatedTodayCount === 0
    ? `Day ${baseNum + 1}`
    : `Day ${baseNum}.${generatedTodayCount}`
}

// ─── Icon helpers ─────────────────────────────────────────────────────────────

function SpinnerIcon() {
  return <WaveDots className="text-blue-400" />
}

function PlusIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
    </svg>
  )
}

function LockIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M4 4a4 4 0 0 1 8 0v2h.25c.966 0 1.75.784 1.75 1.75v5.5A1.75 1.75 0 0 1 12.25 15h-8.5A1.75 1.75 0 0 1 2 13.25v-5.5C2 6.784 2.784 6 3.75 6H4V4Zm8.25 3.5h-8.5a.25.25 0 0 0-.25.25v5.5c0 .138.112.25.25.25h8.5a.25.25 0 0 0 .25-.25v-5.5a.25.25 0 0 0-.25-.25ZM10.5 4a2.5 2.5 0 0 0-5 0v2h5V4Z" />
    </svg>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function buildContentMix(pkg) {
  const newsCount      = (pkg.insights ?? []).filter(c => c.content_type === "news").length
  const eduCount       = (pkg.insights ?? []).filter(c => c.content_type === "educational").length
  const curiosityCount = (pkg.curiosity_insights ?? []).length
  const parts = []
  if (newsCount)      parts.push(`${newsCount} news`)
  if (eduCount)       parts.push(`${eduCount} educational`)
  const core = parts.join(" · ")
  return curiosityCount ? `${core} + ${curiosityCount} curiosity pick${curiosityCount !== 1 ? "s" : ""}` : core
}

// ─── Day history dropdown ─────────────────────────────────────────────────────

// The trigger carries the next day's state: a dot once it can be generated, a
// pulsing one while it builds. `open` is owned by the page so the progress
// bar's "unlocked" nudge can open the menu too. Reading mode passes
// canGenerate={false}: there the menu only switches days.
function DayDropdown({ packages, displayLabels, selectedId, onSelect, open, setOpen, next, canGenerate = true }) {
  const ref = useRef(null)
  const currentLabel = displayLabels.get(selectedId) ?? `Day ?`
  const labelChanges = useChangeCount(currentLabel)

  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener("pointerdown", onDown)
    return () => document.removeEventListener("pointerdown", onDown)
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        data-next={next.state}
        className={[
          "relative inline-flex items-center gap-1.5 px-3 py-1 rounded-lg",
          "text-[11px] font-semibold uppercase tracking-wider transition-colors select-none",
          open
            ? "bg-white/[0.12] border border-white/[0.16] text-slate-100"
            : "bg-white/[0.07] border border-white/[0.11] text-slate-400 hover:text-slate-100 hover:bg-white/[0.10] hover:border-white/[0.15]",
        ].join(" ")}
      >
        <span key={currentLabel} className={labelChanges ? "u-roll" : ""}>{currentLabel}</span>
        <svg
          className={`w-3 h-3 transition-transform duration-300 ${open ? "rotate-180" : ""}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
        </svg>
        {canGenerate && next.state !== "locked" && (
          <span
            aria-hidden="true"
            className={`u-pop-num absolute -top-1 -right-1 h-2 w-2 rounded-full ${next.state === "building" ? "animate-pulse" : ""}`}
            style={{ background: "var(--u-accent, #3b82f6)" }}
          />
        )}
      </button>

      <AnimatePresence>
      {open && (
        <PopMenu key="menu" className="origin-top absolute left-1/2 -ml-[120px] top-full mt-1.5 z-30 w-[240px] bg-slate-900/95 backdrop-blur-sm border border-white/[0.07] rounded-xl shadow-2xl shadow-black/60 overflow-hidden py-1">
          {canGenerate && (
            <>
              <GenerateRow next={next} onDone={() => setOpen(false)} />
              <div className="my-1 h-px bg-white/[0.06]" />
            </>
          )}
          {packages.map(pkg => {
            const label  = displayLabels.get(pkg.id)
            const isSel  = pkg.id === selectedId
            const failed = label === "Day 0"
            return (
              <button
                key={pkg.id}
                onClick={() => { onSelect(pkg.id); setOpen(false) }}
                className={[
                  "w-full flex items-center justify-between gap-4 px-3 py-1.5 text-left transition-colors",
                  isSel
                    ? "bg-white/[0.07] text-slate-100"
                    : "text-slate-400 hover:bg-white/[0.04] hover:text-slate-200",
                ].join(" ")}
              >
                <span className={`text-[11px] font-semibold uppercase tracking-wide ${failed ? "text-rose-400/80" : ""}`}>
                  {label}
                </span>
                <span className="text-[10px] text-slate-600 tabular-nums flex-shrink-0">
                  {formatDate(pkg.generated_at)}
                </span>
              </button>
            )
          })}
        </PopMenu>
      )}
      </AnimatePresence>
    </div>
  )
}

function PackageHeader({ pkg, dayLabel, projectId }) {
  const contentMix = buildContentMix(pkg)
  return (
    <div className="mb-3 md:mb-7">
      {/* Headline */}
      <div className="flex items-start justify-between gap-2 mb-1.5 md:mb-4">
        <h2 className="u-read-display text-slate-100 break-words">
          {pkg.package_headline}
        </h2>
      </div>

      {/* Learning thread — left-accent style */}
      {pkg.learning_thread && (
        <div className="flex gap-3">
          <div className="flex-shrink-0 w-0.5 rounded-full bg-white/[0.08] self-stretch" />
          <p className="u-read-body text-slate-400">{pkg.learning_thread}</p>
        </div>
      )}
    </div>
  )
}

function SectionDivider({ label }) {
  return (
    <div className="flex items-center gap-3 my-3 md:my-5">
      <div className="flex-1 h-px bg-white/[0.06]" />
      <span className="text-[10px] font-medium uppercase tracking-widest text-slate-600">{label}</span>
      <div className="flex-1 h-px bg-white/[0.06]" />
    </div>
  )
}

function ActionItem({ text }) {
  return (
    <div className="mt-3 md:mt-6 flex gap-2.5 md:gap-3 px-3 md:px-4 py-2.5 md:py-4 bg-white/[0.04] rounded-xl md:rounded-2xl">
      <div className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-600/20 border border-blue-500/30 flex items-center justify-center mt-0.5">
        <svg className="w-3 h-3 text-blue-400" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M2 6l3 3 5-5" />
        </svg>
      </div>
      <div>
        <p className="u-read-label text-blue-400/80 mb-1">Today's Action</p>
        <p className="u-read-body text-slate-200">{text}</p>
      </div>
    </div>
  )
}

// ─── Day progress bar ─────────────────────────────────────────────────────────

// unlocked: the next day's label once it can be generated — "Complete" then
// points at the Day menu, where generating lives.
function DayProgressBar({ readCount, totalCount, unlocked, onOpenNext }) {
  const allDone = totalCount > 0 && readCount >= totalCount
  // Keyed on real changes: the sheen and count pop never play on load, and
  // confetti + the success buzz fire only when the last card is marked.
  const changes = useChangeCount(readCount)
  const completions = useCompletedCount(readCount, totalCount)
  useEffect(() => { if (completions) haptic("success") }, [completions])

  if (totalCount === 0) return null
  const pct = Math.round((readCount / totalCount) * 100)

  return (
    <div className="relative flex items-center gap-3 mb-2.5 md:mb-5 px-3 md:px-4 py-2.5 md:py-3 bg-white/[0.04] rounded-xl">
      <div className="flex-1">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] font-semibold text-slate-400">Day progress</span>
          <span key={readCount} className={`text-[11px] font-semibold ${changes ? "u-pop-num" : ""} ${allDone ? "text-emerald-400" : "text-slate-500"}`}>
            {readCount} / {totalCount} core read
          </span>
        </div>
        <div className="h-1.5 bg-slate-700/60 rounded-full">
          <div className="u-progress-fill" data-done={allDone ? "true" : "false"} style={{ width: `${pct}%` }}>
            {changes > 0 && <span key={changes} className="u-sheen" aria-hidden="true" />}
          </div>
        </div>
      </div>
      {allDone && (unlocked ? (
        <button
          type="button"
          onClick={onOpenNext}
          className="u-pop-num text-[10px] font-semibold text-emerald-400 hover:text-emerald-300 hover:underline underline-offset-2 flex-shrink-0 transition-colors"
        >
          Complete · {unlocked} unlocked ↑
        </button>
      ) : (
        <span className="u-pop-num text-[10px] font-semibold text-emerald-400 flex-shrink-0">Complete</span>
      ))}
      <Confetti key={completions} fire={completions > 0} className="right-10 top-4" />
    </div>
  )
}

// ─── Generate row (first item of the Day menu) ────────────────────────────────

// next: { label, state: "locked"|"ready"|"building", remaining, extraToday, stage, offline, onGenerate }
function GenerateRow({ next, onDone }) {
  const [confirming, setConfirming] = useState(false)
  const { label, state, remaining, extraToday, stage, offline, onGenerate } = next

  if (confirming) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5">
        <span className="flex-1 text-[12px] text-slate-200">Generate {label}?</span>
        <button
          onClick={() => { setConfirming(false); onDone(); onGenerate() }}
          className="px-2.5 py-0.5 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-[11px] font-medium transition-colors"
        >
          Yes
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="px-2.5 py-0.5 rounded-md bg-slate-700 hover:bg-slate-600 text-slate-300 text-[11px] font-medium transition-colors"
        >
          Cancel
        </button>
      </div>
    )
  }

  const building = state === "building"
  const locked = state === "locked"
  const note = building ? stageShortLabel(stage)
    : offline ? "Needs internet"
    : locked ? `Read ${remaining} more to unlock`
    : extraToday ? "Extra for today"
    : null
  return (
    <button
      onClick={() => setConfirming(true)}
      disabled={building || locked || offline}
      className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-slate-200 hover:text-slate-50 disabled:text-slate-500 disabled:cursor-not-allowed transition-colors"
    >
      {building ? <SpinnerIcon />
        : locked ? <LockIcon className="w-3 h-3 flex-shrink-0" />
        : <PlusIcon className="w-3.5 h-3.5 flex-shrink-0" />}
      <span className="flex flex-col">
        <span className="text-[11px] font-semibold uppercase tracking-wide">
          {building ? "Building" : "Generate"} {label}
        </span>
        {note && <span className="text-[10px] text-slate-500">{note}</span>}
      </span>
    </button>
  )
}

// ─── Package content ──────────────────────────────────────────────────────────

function CuriositySectionHeader() {
  return (
    <div className="flex items-center gap-3 my-3 md:my-6">
      <div className="flex-1 h-px bg-slate-800/60" />
      <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-950/40 border border-amber-500/20">
        <svg className="w-3 h-3 text-amber-400/80" viewBox="0 0 20 20" fill="currentColor">
          <path d="M10 1a6 6 0 0 1 3.479 10.907A1 1 0 0 1 13 13H7a1 1 0 0 1-.479-1.093A6 6 0 0 1 10 1ZM8.5 15.5a.5.5 0 0 0 0 1h3a.5.5 0 0 0 0-1h-3Zm.25 2a.25.25 0 0 0 0 .5h2.5a.25.25 0 0 0 0-.5h-2.5Z" />
        </svg>
        <span className="text-[10px] font-semibold uppercase tracking-widest text-amber-400/80">
          Curiosity Picks
        </span>
      </div>
      <div className="flex-1 h-px bg-slate-800/60" />
    </div>
  )
}

// InsightCard props for one card — shared by the feed and Reading mode.
function buildCardProps(card, {
  pkg, project, readKeys, onMarkRead, onMarkUnread, onOpenInChat, relatedChatsMap,
  onLoadRelatedChats, onOpenChat, notesMap, onSaveNote, onDeleteNote, queuedKeys,
  onToggleQueue, isOnline = true, offlineIds,
}) {
  const ak = articleKeyFromTitle(card.title || "")
  return {
    card,
    isRead:             readKeys?.has(ak) ?? false,
    onMarkRead:         onMarkRead   ? () => onMarkRead(pkg.id, ak, card.title || "") : undefined,
    onMarkUnread:       onMarkUnread ? () => onMarkUnread(pkg.id, ak)                 : undefined,
    onAskAbout:         onOpenInChat ? (c) => onOpenInChat(c, "ask_about")         : undefined,
    onExplainSimply:    onOpenInChat ? (c) => onOpenInChat(c, "explain_simply")    : undefined,
    relatedChats:       relatedChatsMap?.get(ak) ?? null,
    onLoadRelatedChats: onLoadRelatedChats ? () => onLoadRelatedChats(pkg.id, ak)    : undefined,
    onOpenChat,
    projectId:   project?.project_id || '',
    projectName: project?.name       || '',
    note:         notesMap?.get(ak) ?? null,
    onSaveNote:   onSaveNote   ? (content) => onSaveNote(ak, content)  : undefined,
    onDeleteNote: onDeleteNote ? ()        => onDeleteNote(ak)         : undefined,
    isQueued:      queuedKeys?.has(ak) ?? false,
    onToggleQueue: onToggleQueue ? (c) => onToggleQueue(ak, c) : undefined,
    isOfflineAvailable: offlineIds?.has(pkg.id) || offlineIds?.has(`${project?.project_id || ''}_${pkg.id}_${ak}`) || false,
    offlineDisabled: !isOnline,
    day:        pkg.id,
    articleKey: ak,
  }
}

function PackageContent({
  pkg,
  project,
  generating,
  onRegenerate,
  onOpenInChat,
  isLatestPackage,
  nextPackage,
  onSelectPackage,
  dayLabel,
  nextLabel,
  unlockedLabel,
  onOpenNext,
  readKeys,
  onMarkRead,
  onMarkUnread,
  relatedChatsMap,
  onLoadRelatedChats,
  onOpenChat,
  notesMap,
  onSaveNote,
  onDeleteNote,
  queuedKeys,
  onToggleQueue,
  isOnline = true,
  offlineIds,
}) {
  const failed = isFailedPackage(pkg)

  const newsCards      = pkg.insights?.filter(c => c.content_type === "news") || []
  const eduCards       = pkg.insights?.filter(c => c.content_type === "educational") || []
  const allCoreCards   = pkg.insights || []
  const curiosityCards = pkg.curiosity_insights || []
  const totalCoreCards = allCoreCards.length

  const readCount      = coreReadCount(allCoreCards, readKeys)

  const makeCardProps = (card) => buildCardProps(card, {
    pkg, project, readKeys, onMarkRead, onMarkUnread, onOpenInChat, relatedChatsMap,
    onLoadRelatedChats, onOpenChat, notesMap, onSaveNote, onDeleteNote, queuedKeys,
    onToggleQueue, isOnline, offlineIds,
  })

  if (failed) {
    return (
      <FailedPackageBanner pkg={pkg} nextLabel={nextLabel} generating={generating} onRegenerate={onRegenerate} />
    )
  }

  return (
    <div>
      <PackageHeader
        pkg={pkg}
        dayLabel={dayLabel}
        projectId={project?.project_id}
      />

      {/* Day progress bar — core cards only (curiosity is optional) */}
      {isLatestPackage && totalCoreCards > 0 && (
        <DayProgressBar readCount={readCount} totalCount={totalCoreCards} unlocked={unlockedLabel} onOpenNext={onOpenNext} />
      )}

      {/* News cards */}
      {newsCards.length > 0 && (
        <>
          <SectionDivider label="Current Events" />
          <div className="space-y-2 md:space-y-3">
            {newsCards.map((card, i) => {
              const ak = articleKeyFromTitle(card.title || "")
              return (
                <div key={card.id || i} id={`queue-card-${ak}`} className="scroll-mt-20">
                  <InsightCard {...makeCardProps(card)} />
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* Educational cards */}
      {eduCards.length > 0 && (
        <>
          <SectionDivider label="Deep Learning" />
          <div className="space-y-2 md:space-y-3">
            {eduCards.map((card, i) => {
              const ak = articleKeyFromTitle(card.title || "")
              return (
                <div key={card.id || i} id={`queue-card-${ak}`} className="scroll-mt-20">
                  <InsightCard {...makeCardProps(card)} />
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* Fallback: unsorted core cards */}
      {newsCards.length === 0 && eduCards.length === 0 && allCoreCards.length > 0 && (
        <div className="space-y-2 md:space-y-3 mt-4">
          {allCoreCards.map((card, i) => {
            const ak = articleKeyFromTitle(card.title || "")
            return (
              <div key={card.id || i} id={`queue-card-${ak}`} className="scroll-mt-20">
                <InsightCard {...makeCardProps(card)} />
              </div>
            )
          })}
        </div>
      )}

      {/* Action item */}
      {pkg.action_item && <ActionItem text={pkg.action_item} />}

      {/* ── Curiosity Picks section ──────────────────────────────────────── */}
      {curiosityCards.length > 0 && (
        <div className="mt-1.5 md:mt-2">
          <CuriositySectionHeader />
          <p className="text-[12.5px] text-slate-500 mb-2 md:mb-3 leading-relaxed">
            Optional side trails — intellectually stimulating, not on the critical path.
          </p>
          <div className="space-y-2 md:space-y-3">
            {curiosityCards.map((card, i) => {
              const ak = articleKeyFromTitle(card.title || "")
              return (
                <div key={card.id || `curiosity-${i}`} id={`queue-card-${ak}`} className="scroll-mt-20">
                  <InsightCard {...makeCardProps(card)} />
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Generating lives in the Day menu; older days offer the way forward. */}
      {nextPackage && (
        <div className="mt-3 md:mt-6 pt-3 md:pt-5 border-t border-slate-800">
          <button
            type="button"
            onClick={() => onSelectPackage?.(nextPackage.id)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/[0.05] hover:bg-white/[0.09] border border-white/[0.07] hover:border-white/[0.12] text-sm text-slate-400 hover:text-slate-100 transition-all"
          >
            Read {nextPackage.label}
          </button>
        </div>
      )}
    </div>
  )
}

// ─── Wide-screen rails ────────────────────────────────────────────────────────

// Background graph plates for the normal feed, alternating sides down the page.
const FEED_PLATES = [
  { seed: 3,  count: 11, top: "6%",  side: "left"  },
  { seed: 19, count: 9,  top: "17%", side: "right" },
  { seed: 27, count: 12, top: "29%", side: "left"  },
  { seed: 44, count: 10, top: "41%", side: "right" },
  { seed: 52, count: 11, top: "53%", side: "left"  },
  { seed: 63, count: 9,  top: "65%", side: "right" },
  { seed: 71, count: 12, top: "77%", side: "left"  },
  { seed: 88, count: 10, top: "88%", side: "right" },
]

// The article list needs 280px beside a reading column of at least 720px,
// inside the feed's 32px side padding: 720 + 280 + 64 (see .u-feed-col).
const RAILS_MIN_WIDTH = 1064

// Width of the page's <main> (it changes with the sidebar, not just the
// window), so the list appears exactly when it fits.
function useMainWidth(ref, mounted) {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const main = ref.current?.closest("main")
    if (!main) return
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width))
    ro.observe(main)
    return () => ro.disconnect()
  }, [ref, mounted])
  return width
}

// Page order: news, then educational (or unsorted core), then curiosity.
function cardsInPageOrder(pkg) {
  const all  = pkg.insights ?? []
  const news = all.filter(c => c.content_type === "news")
  const edu  = all.filter(c => c.content_type === "educational")
  const core = news.length || edu.length ? [...news, ...edu] : all
  return { core, cards: [...core, ...(pkg.curiosity_insights ?? [])] }
}

// Right rail: the day's cards in order. Jumps to a card; marks the one in view
// and the ones read (newest day only — older days carry no read state).
function DayOutline({ pkg, dayLabel, readKeys, showRead }) {
  const { core: coreInPageOrder, cards } = cardsInPageOrder(pkg)
  const keys  = cards.map(c => articleKeyFromTitle(c.title || ""))
  const core  = coreInPageOrder.length
  const read  = coreReadCount(coreInPageOrder, readKeys)
  const [active, setActive] = useState(keys[0])

  useEffect(() => {
    const els = keys.map(k => document.getElementById(`queue-card-${k}`)).filter(Boolean)
    // A thin band just above the middle of the screen: whichever card crosses it is the one being read.
    const io = new IntersectionObserver(entries => {
      const hit = entries.find(e => e.isIntersecting)
      if (hit) setActive(hit.target.id.replace("queue-card-", ""))
    }, { rootMargin: "-35% 0px -60% 0px" })
    els.forEach(el => io.observe(el))
    return () => io.disconnect()
  }, [pkg.id]) // eslint-disable-line react-hooks/exhaustive-deps

  function jump(k) {
    setActive(k)
    document.getElementById(`queue-card-${k}`)?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  return (
    <nav aria-label="Today's cards">
      <p className="u-read-label text-slate-500 mb-2 px-2">{dayLabel}</p>
      {showRead && core > 0 && (
        <div className="flex items-center gap-2 mb-3 px-2">
          <div className="flex-1 h-1 bg-slate-700/60 rounded-full">
            <div className="u-progress-fill" data-done={read >= core ? "true" : "false"} style={{ width: `${Math.round(read / core * 100)}%` }} />
          </div>
          <span className="text-[11px] text-slate-500 tabular-nums">{read}/{core}</span>
        </div>
      )}
      <ol className="space-y-0.5">
        {cards.map((c, i) => {
          const k = keys[i]
          const isRead = showRead && readKeys?.has(k)
          const curiosity = i >= core
          return (
            <li key={k}>
              <button
                type="button"
                onClick={() => jump(k)}
                aria-current={active === k ? "true" : undefined}
                className={[
                  "w-full flex items-start gap-2 px-2 py-1.5 rounded-lg text-left text-[12.5px] leading-snug transition-colors",
                  active === k ? "bg-white/[0.06] text-slate-100" : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.03]",
                ].join(" ")}
              >
                {isRead ? (
                  <svg className="w-3 h-3 mt-[3px] flex-shrink-0 text-emerald-400" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M2 6l3 3 5-5" /></svg>
                ) : (
                  <span className={`w-1.5 h-1.5 mt-[6px] mx-[3px] rounded-full flex-shrink-0 ${curiosity ? "bg-amber-400/60" : "bg-slate-500"}`} />
                )}
                <span className="line-clamp-2">{c.title}</span>
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

// ─── Main export ──────────────────────────────────────────────────────────────

// readKeys also holds curiosity cards, which never count towards the day.
function coreReadCount(coreCards, readKeys) {
  return coreCards.filter(c => readKeys?.has(articleKeyFromTitle(c.title || ""))).length
}

function isFailedPackage(pkg) {
  return (
    (!pkg.insights || pkg.insights.length === 0) &&
    (pkg.package_headline || '').includes('generation error')
  )
}

function FailedPackageBanner({ pkg, nextLabel, generating, onRegenerate }) {
  return (
    <div className="mb-7">
      <div className="flex items-center gap-2 mb-3">
        <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-rose-950/60 border border-rose-800/50 text-[10px] font-bold uppercase tracking-wider text-rose-400">
          Generation Failed
        </span>
        <span className="text-[11px] text-slate-600">{pkg.generated_at ? new Date(pkg.generated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : ''}</span>
      </div>
      <div className="flex flex-col gap-3 px-5 py-5 rounded-2xl border border-rose-900/40 bg-rose-950/20">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-rose-400 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
            <path d="M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0 1 14.082 15H1.918a1.75 1.75 0 0 1-1.543-2.575Zm1.763.707a.25.25 0 0 0-.44 0L1.698 13.132a.25.25 0 0 0 .22.368h12.164a.25.25 0 0 0 .22-.368Zm.53 3.996v2.5a.75.75 0 0 1-1.5 0v-2.5a.75.75 0 0 1 1.5 0ZM9 11a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z" />
          </svg>
          <p className="text-sm font-semibold text-rose-300">Generation failed</p>
        </div>
        <p className="text-xs text-slate-400 leading-relaxed">
          The AI could not produce structured content for this day. This can happen when the model returns malformed output. Click below to try again.
        </p>
        <button
          onClick={() => onRegenerate?.(pkg.id)}
          disabled={generating}
          className="self-start flex items-center gap-2 px-4 py-2 rounded-xl bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/40 text-sm text-rose-300 hover:text-rose-200 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          {generating ? (
            <>
              <WaveDots />
              Regenerating…
            </>
          ) : (
            <>
              <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                <path d="M1.705 8.005a.75.75 0 0 1 .834.656 5.5 5.5 0 0 0 9.592 2.97l-1.204-1.204a.25.25 0 0 1 .177-.427h3.646a.25.25 0 0 1 .25.25v3.646a.25.25 0 0 1-.427.177l-1.38-1.38A7.002 7.002 0 0 1 1.05 8.84a.75.75 0 0 1 .656-.834ZM8 2.5a5.487 5.487 0 0 0-4.131 1.869l1.204 1.204A.25.25 0 0 1 4.896 6H1.25A.25.25 0 0 1 1 5.75V2.104a.25.25 0 0 1 .427-.177l1.38 1.38A7.002 7.002 0 0 1 14.95 7.16a.75.75 0 0 1-1.49.178A5.5 5.5 0 0 0 8 2.5Z" />
              </svg>
              Retry {nextLabel}
            </>
          )}
        </button>
      </div>
    </div>
  )
}

export default function DailyPackageView({
  project,
  packages,
  onGenerate,
  onRegenerate,
  generating,
  genStage,
  genStageDetail,
  genDismissed,
  onDismissGenerating,
  onOpenInChat,
  readKeys,
  onMarkRead,
  onMarkUnread,
  relatedChatsMap,
  onLoadRelatedChats,
  onOpenChat,
  targetInsightId,
  targetArticleKey,
  onClearQueueTarget,
  onExportReady,
  isOnline = true,
  offlineIds,
}) {
  const [selectedId, setSelectedId] = useState(packages[0]?.id ?? null)
  const [dayMenuOpen, setDayMenuOpen] = useState(false)
  const frameRef = useRef(null)
  const wide = useMainWidth(frameRef, packages.length > 0) >= RAILS_MIN_WIDTH
  // Map<cardId, noteContent> for the currently-selected package
  const [notesMap, setNotesMap] = useState(new Map())
  // Set<articleKey> — synced from localStorage queue
  const [queuedKeys, setQueuedKeys] = useState(() => new Set(getQueue().map(i => i.articleKey)))
  const navigate = useNavigate()

  const selected = packages.find(p => p.id === selectedId) ?? packages[0] ?? null
  const latestId = packages[0]?.id ?? null
  const isLatest = selected?.id === latestId
  // packages run newest-first, so the day after the selected one sits before it.
  const nextPkg  = packages[packages.findIndex(p => p.id === selected?.id) - 1] ?? null

  const selectPackage = (id) => {
    setSelectedId(id)
    navigate(`/feed/${project?.project_id || ''}/${id}`)
  }

  // Keep queuedKeys in sync with localStorage changes from other components
  useEffect(() => {
    function onQueueChange() {
      setQueuedKeys(new Set(getQueue().map(i => i.articleKey)))
    }
    window.addEventListener("queuechange", onQueueChange)
    return () => window.removeEventListener("queuechange", onQueueChange)
  }, [])

  // Auto-select the newest package whenever packages[0] changes (new generation).
  // This keeps the view, greeting, and sidebar all on the same day label.
  useEffect(() => {
    const newest = packages[0]?.id
    if (!newest) return
    setSelectedId(newest)
    // A day picked from the dropdown is pinned in the URL, and the deep-link
    // effect below re-applies that pin on every packages change — so the pin has
    // to move too, or a finished generation snaps straight back to the old day.
    const pid = project?.project_id
    if (pid && targetInsightId && targetInsightId !== newest) {
      navigate(`/feed/${encodeURIComponent(pid)}/${newest}`, { replace: true })
    }
  }, [packages[0]?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // When navigating from queue: select the target package
  useEffect(() => {
    if (!targetInsightId || !packages.length) return
    const pkg = packages.find(p => p.id === targetInsightId)
    if (pkg) setSelectedId(pkg.id)
  }, [targetInsightId, packages])

  // After selected package changes: scroll to the target card
  useEffect(() => {
    if (!targetArticleKey) return
    const raf = requestAnimationFrame(() => {
      const el = document.getElementById(`queue-card-${targetArticleKey}`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" })
        onClearQueueTarget?.()
      }
    })
    return () => cancelAnimationFrame(raf)
  }, [selectedId, targetArticleKey]) // eslint-disable-line react-hooks/exhaustive-deps

  function handleToggleQueue(articleKey, card) {
    const offlineId = `${project?.project_id || ""}_${selected?.id ?? ""}_${articleKey}`
    if (isInQueue(articleKey)) {
      removeFromQueue(articleKey)
      deletePackage(offlineId).catch(() => {})
    } else {
      addToQueue(articleKey, {
        title:        card.title        || "",
        summary:      card.summary      || "",
        category:     card.category     || null,
        content_type: card.content_type || "news",
        projectId:    project?.project_id || "",
        projectName:  project?.name       || "",
        insightId:    selected?.id        ?? null,
      })
      savePackage(offlineId, card, {
        projectId:   project?.project_id || "",
        kind:        "card",
        title:       card.title || "",
        projectName: project?.name || "",
      }).catch(() => {})
    }
  }

  // Load notes whenever the selected package changes
  useEffect(() => {
    if (!selected || !project?.project_id) return
    getInsightNotes(project.project_id, selected.id)
      .then(obj => setNotesMap(new Map(Object.entries(obj))))
      .catch(() => setNotesMap(new Map()))
  }, [selected?.id, project?.project_id]) // eslint-disable-line react-hooks/exhaustive-deps

  function handleSaveNote(cardId, content) {
    if (!selected || !project?.project_id) return
    setNotesMap(prev => new Map(prev).set(cardId, content))
    saveCardNote(project.project_id, selected.id, cardId, content).catch(() => {})
  }

  function handleDeleteNote(cardId) {
    if (!selected || !project?.project_id) return
    setNotesMap(prev => { const m = new Map(prev); m.delete(cardId); return m })
    deleteCardNote(project.project_id, selected.id, cardId).catch(() => {})
  }

  // Compute human-readable labels, same-day count, and next button label
  const displayLabels = computeDisplayLabels(packages)
  const todayStr = new Date().toLocaleDateString("en-CA")
  const generatedTodayCount = packages.filter(p =>
    p.generated_at && new Date(p.generated_at).toLocaleDateString("en-CA") === todayStr
  ).length
  const nextLabel = computeNextLabel(packages, displayLabels, generatedTodayCount)

  // The next day unlocks once the newest day's CORE cards are all read (curiosity
  // is optional; a failed day or one with no core cards never locks). readKeys is
  // always the newest day's, so this holds whichever day is being viewed.
  const latestCore = packages[0]?.insights ?? []
  const remaining  = latestCore.length - coreReadCount(latestCore, readKeys)
  const next = {
    label:      nextLabel,
    state:      generating ? "building" : remaining > 0 ? "locked" : "ready",
    remaining,
    extraToday: generatedTodayCount > 0,
    stage:      genStage,
    offline:    !isOnline,
    onGenerate,
  }

  // Expose export functions to parent whenever selection changes
  useEffect(() => {
    if (!onExportReady || !selected) return
    const dayLabelForExport = displayLabels.get(selected.id) ?? ""
    const pid = project?.project_id
    let cancelled = false

    async function setup() {
      let nextDayTitle = ""
      if (pid) {
        try {
          const preview = await getJourneyPreview(pid)
          nextDayTitle = preview?.today?.display_title || ""
        } catch (_) {}
      }
      if (cancelled) return
      const opts = {
        projectName: project?.name || "",
        dayLabel: dayLabelForExport,
        ...(nextDayTitle ? { nextDayTitle } : {}),
      }
      onExportReady(
        () => exportAsPdf(selected, opts),
        () => downloadMarkdown(selected, opts),
        {
          type: "feed",
          resourceId: `${pid}/${selected.id}`,
          shareTitle: selected.package_headline || "Daily package",
        }
      )
    }
    setup()
    return () => { cancelled = true }
  }, [selected?.id, project?.project_id]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Reading mode ──────────────────────────────────────────────────────────
  // { start, origin } while open. It opens on the card in view and, on exit,
  // the feed scrolls to the card that was last on screen.
  const [reading, setReading] = useState(null)
  const [readerDayOpen, setReaderDayOpen] = useState(false)
  const readerCards = selected ? cardsInPageOrder(selected) : { core: [], cards: [] }

  function openReading(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const line = window.innerHeight * 0.35
    let start = 0
    readerCards.cards.forEach((c, i) => {
      const el = document.getElementById(`queue-card-${articleKeyFromTitle(c.title || "")}`)
      if (el && el.getBoundingClientRect().top <= line) start = i
    })
    setDayMenuOpen(false)
    setReading({ start, origin: { x: r.left + r.width / 2, y: r.top + r.height / 2 } })
  }

  function exitReading(articleKey) {
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
    setReading(null)
    setReaderDayOpen(false)
    // Behind the closing reveal, so the feed is already in place when it clears.
    if (articleKey) document.getElementById(`queue-card-${articleKey}`)?.scrollIntoView({ block: "start" })
  }

  // Leaving the feed (Ask About opens chat, the back button, another project)
  // closes Reading mode — it belongs to this project's days only.
  const { pathname } = useLocation()
  const onFeed = pathname.startsWith("/feed")
  useEffect(() => {
    if (!onFeed && reading) exitReading(null)
  }, [onFeed]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setReading(null) }, [project?.project_id])

  const readerCardProps = (card) => buildCardProps(card, {
    pkg: selected, project,
    readKeys:     isLatest ? readKeys : undefined,
    onMarkRead:   isLatest ? onMarkRead : undefined,
    onMarkUnread: isLatest ? onMarkUnread : undefined,
    onOpenInChat, relatedChatsMap, onLoadRelatedChats, onOpenChat,
    notesMap, onSaveNote: handleSaveNote, onDeleteNote: handleDeleteNote,
    queuedKeys, onToggleQueue: handleToggleQueue, isOnline, offlineIds,
  })

  if (packages.length === 0) {
    // Dismissed with nothing to read yet: the progress strip carries the run,
    // so give the page the planned path to read instead of an empty column.
    if (generating && genDismissed) return <JourneyPreviewPanel projectId={project?.project_id} nextLabel={nextLabel} />
    if (generating) {
      return (
        <GeneratingPackageState
          project={project}
          nextLabel={nextLabel}
          stage={genStage}
          stageDetail={genStageDetail}
          onDismiss={onDismissGenerating}
        />
      )
    }
    return <EmptyPackageState project={project} onGenerate={onGenerate} isOnline={isOnline} />
  }

  return selected ? (
    <>
      <div className="fixed top-3.5 left-1/2 -translate-x-1/2 z-50 flex items-center gap-1.5">
        <DayDropdown
          packages={packages}
          displayLabels={displayLabels}
          selectedId={selectedId}
          onSelect={selectPackage}
          open={dayMenuOpen}
          setOpen={setDayMenuOpen}
          next={next}
        />
        {!isFailedPackage(selected) && (
          <button
            type="button"
            onClick={openReading}
            aria-label="Reading mode"
            title="Reading mode"
            className="inline-flex items-center justify-center gap-1.5 px-2 h-[26px] rounded-lg bg-white/[0.07] border border-white/[0.11] text-slate-400 hover:text-slate-100 hover:bg-white/[0.10] hover:border-white/[0.15] active:scale-95 transition-[color,background-color,border-color,transform] whitespace-nowrap"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
              <path d="M8 4.2C6.6 3.2 4.6 2.8 2 3v9.3c2.6-.2 4.6.2 6 1.2 1.4-1 3.4-1.4 6-1.2V3c-2.6-.2-4.6.2-6 1.2ZM8 4.2v9.3" />
            </svg>
            <span className="text-[11px] font-medium">Reading mode</span>
          </button>
        )}
      </div>
      <div ref={frameRef} className="relative isolate">
      {/* Graph plates down the page, behind the cards (the frame is isolated, so
          z -1 sits under its content): right ones fill the article list's column,
          left ones the margin, each just tucked under the column's edge. */}
      <div aria-hidden="true" className="u-feed-plates">
        {FEED_PLATES.map(p => (
          <div key={p.seed} className="absolute w-[260px] h-[195px] md:w-[360px] md:h-[270px]" style={{ top: p.top, ...(p.side === "left" ? { right: "calc(100% - 80px)" } : { left: "calc(100% - 40px)" }) }}>
            <Plate seed={p.seed} count={p.count} className="u-plate u-plate-feed" />
          </div>
        ))}
      </div>
      {/* Wide screens: the day's articles, sticky to the right of the reading column. */}
      {wide && (
        <div className="u-day-rail absolute inset-y-0 left-full ml-10 w-[240px]">
          <div className="sticky top-20">
            <DayOutline pkg={selected} dayLabel={displayLabels.get(selected.id)} readKeys={readKeys} showRead={isLatest} />
          </div>
        </div>
      )}
      <PackageContent
        pkg={selected}
        project={project}
        generating={generating}
        onRegenerate={onRegenerate}
        onOpenInChat={onOpenInChat}
        isLatestPackage={isLatest}
        nextPackage={nextPkg ? { id: nextPkg.id, label: displayLabels.get(nextPkg.id) ?? `Day ${nextPkg.day_number}` } : null}
        onSelectPackage={selectPackage}
        dayLabel={displayLabels.get(selected.id)}
        nextLabel={isLatest ? nextLabel : undefined}
        unlockedLabel={next.state === "ready" && isOnline ? nextLabel : null}
        onOpenNext={() => setDayMenuOpen(true)}
        readKeys={isLatest ? readKeys : undefined}
        onMarkRead={isLatest ? onMarkRead : undefined}
        onMarkUnread={isLatest ? onMarkUnread : undefined}
        relatedChatsMap={relatedChatsMap}
        onLoadRelatedChats={onLoadRelatedChats}
        onOpenChat={onOpenChat}
        notesMap={notesMap}
        onSaveNote={handleSaveNote}
        onDeleteNote={handleDeleteNote}
        queuedKeys={queuedKeys}
        onToggleQueue={handleToggleQueue}
        isOnline={isOnline}
        offlineIds={offlineIds}
      />
      </div>
      {createPortal(
        <AnimatePresence>
          {reading && (
            <ReadingMode
              key="reader"
              pkg={selected}
              cards={readerCards.cards}
              coreCount={readerCards.core.length}
              startIndex={reading.start}
              origin={reading.origin}
              dayLabel={displayLabels.get(selected.id)}
              readKeys={isLatest ? readKeys : undefined}
              cardProps={readerCardProps}
              onExit={exitReading}
              daySwitcher={
                <DayDropdown
                  packages={packages}
                  displayLabels={displayLabels}
                  selectedId={selectedId}
                  onSelect={selectPackage}
                  open={readerDayOpen}
                  setOpen={setReaderDayOpen}
                  next={next}
                  canGenerate={false}
                />
              }
            />
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  ) : null
}

// Keys match the stage values project_service writes to project_insights.stage.
const GENERATION_STAGES = [
  { key: "planning",  label: "Planning today's focus",             short: "planning"          },
  { key: "searching", label: "Scanning today's news & research",   short: "scanning sources"  },
  { key: "selecting", label: "Selecting the most relevant articles", short: "selecting articles" },
  { key: "writing",   label: "Writing and personalising your lesson", short: "writing"         },
]

function stageIndex(stage) {
  const i = GENERATION_STAGES.findIndex(s => s.key === stage)
  return i === -1 ? 0 : i   // stage not reported yet — the run always starts in planning
}

export function stageShortLabel(stage) {
  return GENERATION_STAGES[stageIndex(stage)].short
}

function formatElapsed(seconds) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`
}

function GeneratingPackageState({ project, nextLabel = "Day 1", stage, stageDetail, onDismiss }) {
  const [elapsed, setElapsed] = useState(0)
  const [preview, setPreview] = useState(null)

  useEffect(() => {
    const id = setInterval(() => setElapsed(s => s + 1), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!project?.project_id) return
    getJourneyPreview(project.project_id).then(setPreview).catch(() => {})
  }, [project?.project_id])

  const current    = stageIndex(stage)
  const focusTitle = preview?.today?.display_title
  const upcoming   = preview?.upcoming?.slice(0, 4) || []

  return (
    <div data-no-unpack className="relative isolate max-w-xl mx-auto py-10 md:py-16">
      <Plate seed={23} count={9} className="u-plate u-plate-gen" />
      <p className="text-[12px] text-slate-500 mb-2.5">{nextLabel} of {project.name}</p>
      <h2 className="text-[22px] md:text-[27px] font-semibold leading-[1.22] tracking-[-0.01em] text-slate-100 max-w-[24ch]">
        {focusTitle || `Building your ${nextLabel} lesson`}
      </h2>
      <p className="mt-2.5 mb-9 text-[13px] leading-relaxed text-slate-500 max-w-[52ch]">
        Reading today's web, grading each source it finds, then writing the lesson from the ones that hold up.
      </p>

      <ol className="ml-[3px]">
        {GENERATION_STAGES.map((step, i) => {
          const done   = i < current
          const active = i === current
          const isLast = i === GENERATION_STAGES.length - 1
          return (
            <li
              key={step.key}
              className={`relative pl-7 ${isLast ? "" : "pb-7"}`}
              style={{ borderLeft: `1px solid ${
                isLast ? "transparent"
                       : done ? "var(--u-accent)"
                              : "color-mix(in srgb, var(--u-axis) 32%, transparent)"
              }` }}
            >
              {active && (
                <span
                  aria-hidden
                  className="absolute -left-[9px] top-[1px] h-[19px] w-[19px] rounded-full animate-ping"
                  style={{ background: "var(--u-accent)", opacity: 0.18, animationDuration: "2.4s" }}
                />
              )}
              <span
                key={done ? "done" : "todo"}
                aria-hidden
                className={`absolute -left-[5px] top-[6px] h-[9px] w-[9px] rounded-full transition-colors duration-500 ${done ? "u-pop-num" : ""}`}
                style={{ background: done || active ? "var(--u-accent)" : "color-mix(in srgb, var(--u-axis) 38%, transparent)" }}
              />
              <p className={`text-[14px] leading-snug transition-colors duration-500 ${
                active ? "text-slate-100 font-medium" : done ? "text-slate-500" : "text-slate-600"
              }`}>
                {step.label}
              </p>
              {active && stageDetail && (
                <p className="mt-1 text-[12.5px] text-slate-500 leading-snug">{stageDetail}</p>
              )}
            </li>
          )
        })}
      </ol>

      {/* Never wraps: a row that flips between one and two lines as the timer ticks
          grows and shrinks the page, which flickers the scrollbar on narrow screens. */}
      <div className="mt-9 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:gap-4">
        <button
          type="button"
          onClick={onDismiss}
          className="px-4 py-2 rounded-xl text-[13px] font-medium text-slate-300 hover:text-slate-100 bg-white/[0.05] hover:bg-white/[0.09] border border-white/[0.08] hover:border-white/[0.14] transition-colors"
        >
          Continue in background
        </button>
        <span className="text-[12px] text-slate-500 tabular-nums">
          {formatElapsed(elapsed)} elapsed, usually a minute or two
        </span>
      </div>

      {upcoming.length > 0 && (
        <div className="mt-11 pt-6 border-t border-slate-800/70">
          <p className="text-[12px] text-slate-500 mb-3">Coming up after today</p>
          <ul className="space-y-2.5">
            {upcoming.map(day => (
              <li key={day.day_number} className="flex gap-4 text-[13px]">
                <span className="text-slate-600 w-11 flex-shrink-0">Day {day.day_number}</span>
                <span className="text-slate-400 leading-snug">{day.display_title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ─── Journey preview ──────────────────────────────────────────────────────────

// The server's "today" is the NEXT lesson to generate, and its day_numbers count
// lessons, not the calendar Day labels the feed shows (Day 2, Day 2.1 …). So the
// first entry takes the Day menu's own next label, and the rest stay unnumbered:
// their labels depend on the dates they'll be generated.
function JourneyPreviewPanel({ projectId, nextLabel = "Day 1", className = "mt-4 md:mt-6" }) {
  const [preview, setPreview] = useState(null)

  useEffect(() => {
    if (!projectId) return
    getJourneyPreview(projectId).then(setPreview).catch(() => {})
  }, [projectId])

  if (!preview) return null

  if (!preview.planned) {
    return (
      <div className={`${className} px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06]`}>
        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-600 mb-1">Your path</p>
        <p className="text-[12px] text-slate-600">Not yet planned — your path will appear here once your first package is generated.</p>
      </div>
    )
  }

  if (preview.shape === "rotating_theme") {
    return (
      <div className={`${className} px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06]`}>
        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-600 mb-1.5">Your path</p>
        <p className="text-[12px] text-slate-400 leading-relaxed">{preview.display_summary}</p>
      </div>
    )
  }

  // fixed_sequence
  return (
    <div className={`${className} px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06]`}>
      <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-600 mb-2">Your path</p>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-blue-400/80">Up next · {nextLabel}</p>
      <p className="mt-0.5 text-[12.5px] text-slate-200 leading-snug">{preview.today.display_title}</p>
      {preview.upcoming.length > 0 && (
        <ol className="mt-3 space-y-1.5 border-l border-white/[0.08] pl-3">
          {preview.upcoming.map(day => (
            <li key={day.day_number} className="text-[12px] text-slate-500 leading-snug">{day.display_title}</li>
          ))}
        </ol>
      )}
      {preview.remaining_count > 0 && (
        <p className="mt-2 text-[11px] text-slate-600">+{preview.remaining_count} more planned</p>
      )}
    </div>
  )
}

function EmptyPackageState({ project, onGenerate, isOnline = true }) {
  return (
    <div className="relative isolate flex flex-col items-center justify-center py-16 text-center">
      <Plate seed={5} count={9} className="u-plate u-plate-empty" />
      <div className="u-bob w-12 h-12 rounded-2xl bg-slate-800 border border-slate-700 flex items-center justify-center mb-4">
        <svg className="w-5 h-5 text-slate-500" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M4 3a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H4Zm12 12H4l4-8 3 6 2-4 3 6Z" clipRule="evenodd" />
        </svg>
      </div>
      <h3 className="font-semibold text-slate-300 mb-1">No packages yet</h3>
      <p className="text-sm text-slate-500 mb-6 max-w-xs leading-relaxed">
        Generate your first Day 1 package for{" "}
        <span className="text-slate-400">{project.name}</span>. Each package
        contains 3 current-events cards and 2 educational deep-dives tailored
        to your keywords and difficulty level.
      </p>
      <button
        onClick={onGenerate}
        disabled={!isOnline}
        title={!isOnline ? "Generating requires an internet connection" : undefined}
        className="u-ping-once flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Generate Day 1
      </button>
      <JourneyPreviewPanel projectId={project.project_id} />
    </div>
  )
}

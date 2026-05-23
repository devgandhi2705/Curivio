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
import InsightCard from "./InsightCard.jsx"
import { articleKeyFromTitle } from "../../api/feed.js"
import { getInsightNotes, saveCardNote, deleteCardNote } from "../../api/notes.js"
import { exportAsPdf, downloadMarkdown } from "../../utils/exportPackage.js"
import { getQueue, addToQueue, removeFromQueue, isInQueue } from "../../api/queue.js"

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

function SpinnerIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
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

// ─── Export button (PDF + Markdown dropdown) ──────────────────────────────────

function ExportButton({ pkg, project, dayLabel }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    function onDown(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [open])

  const opts = { projectName: project?.name || "", dayLabel: dayLabel || "" }

  return (
    <div ref={ref} className="relative ml-auto flex-shrink-0">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium text-slate-500 hover:text-slate-300 bg-slate-900/60 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 transition-all select-none"
      >
        <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
          <path d="M2.75 14A1.75 1.75 0 0 1 1 12.25v-2.5a.75.75 0 0 1 1.5 0v2.5c0 .138.112.25.25.25h10.5a.25.25 0 0 0 .25-.25v-2.5a.75.75 0 0 1 1.5 0v2.5A1.75 1.75 0 0 1 13.25 14Z" />
          <path d="M7.25 7.689V2a.75.75 0 0 1 1.5 0v5.689l1.97-1.97a.749.749 0 1 1 1.06 1.06l-3.25 3.25a.749.749 0 0 1-1.06 0L4.22 6.779a.749.749 0 1 1 1.06-1.06l1.97 1.97Z" />
        </svg>
        Export
        <svg className={`w-2.5 h-2.5 transition-transform duration-150 ${open ? "rotate-180" : ""}`} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 w-44 bg-slate-900 border border-slate-700/60 rounded-xl shadow-2xl overflow-hidden">
          <button
            onClick={() => { exportAsPdf(pkg, opts); setOpen(false) }}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 text-[11px] text-slate-300 hover:text-slate-100 hover:bg-slate-800/70 transition-colors text-left"
          >
            <svg className="w-3.5 h-3.5 text-rose-400/80 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
              <path d="M3.75 0h8.5C13.216 0 14 .784 14 1.75v12.5A1.75 1.75 0 0 1 12.25 16h-8.5A1.75 1.75 0 0 1 2 14.25V1.75C2 .784 2.784 0 3.75 0Zm0 1.5a.25.25 0 0 0-.25.25v12.5c0 .138.112.25.25.25h8.5a.25.25 0 0 0 .25-.25V1.75a.25.25 0 0 0-.25-.25Zm.5 3h7a.75.75 0 0 1 0 1.5h-7a.75.75 0 0 1 0-1.5Zm0 3h7a.75.75 0 0 1 0 1.5h-7a.75.75 0 0 1 0-1.5Zm0 3h4a.75.75 0 0 1 0 1.5h-4a.75.75 0 0 1 0-1.5Z" />
            </svg>
            Save as PDF
          </button>
          <div className="h-px bg-slate-800/80 mx-2" />
          <button
            onClick={() => { downloadMarkdown(pkg, opts); setOpen(false) }}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 text-[11px] text-slate-300 hover:text-slate-100 hover:bg-slate-800/70 transition-colors text-left"
          >
            <svg className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
              <path d="M14.85 3H1.15C.52 3 0 3.52 0 4.15v7.69C0 12.48.52 13 1.15 13h13.69c.64 0 1.15-.52 1.15-1.15v-7.7C16 3.52 15.48 3 14.85 3Zm-3.1 8L9.9 8.35 8 10.5V6h1.5v2.15l1.65-1.85L12 8.15 10.5 11H11.75ZM6 6H4.5v3.5H3V6H1.5V4.5H6Z" />
            </svg>
            Download Markdown
          </button>
        </div>
      )}
    </div>
  )
}

function PackageHeader({ pkg, dayLabel, actions }) {
  const contentMix = buildContentMix(pkg)
  return (
    <div className="mb-3 md:mb-7">
      {/* Meta row */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-2 md:mb-3">
        <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-slate-800 border border-slate-700/60 text-[10px] font-bold uppercase tracking-wider text-slate-400">
          {dayLabel ?? `Day ${pkg.day_number}`}
        </span>
        <span className="text-[11px] text-slate-600">{formatDate(pkg.generated_at)}</span>
        {contentMix && (
          <span className="text-[11px] text-slate-700 hidden sm:inline">{contentMix}</span>
        )}
        {actions && <div className="ml-auto">{actions}</div>}
      </div>

      {/* Headline */}
      <h2 className="text-[17px] md:text-[22px] font-bold text-slate-100 leading-snug tracking-tight mb-1.5 md:mb-4 break-words">
        {pkg.package_headline}
      </h2>

      {/* Learning thread — left-accent style */}
      {pkg.learning_thread && (
        <div className="flex gap-3">
          <div className="flex-shrink-0 w-0.5 rounded-full bg-slate-600/60 self-stretch" />
          <p className="text-[12px] text-slate-500 leading-relaxed">{pkg.learning_thread}</p>
        </div>
      )}
    </div>
  )
}

function SectionDivider({ label }) {
  return (
    <div className="flex items-center gap-3 my-2 md:my-5">
      <div className="flex-1 h-px bg-slate-800" />
      <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-600">{label}</span>
      <div className="flex-1 h-px bg-slate-800" />
    </div>
  )
}

function ActionItem({ text }) {
  return (
    <div className="mt-3 md:mt-6 flex gap-2.5 md:gap-3 px-3 md:px-4 py-2.5 md:py-4 bg-slate-800/40 border border-slate-700/40 rounded-xl md:rounded-2xl">
      <div className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-600/20 border border-blue-500/30 flex items-center justify-center mt-0.5">
        <svg className="w-3 h-3 text-blue-400" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M2 6l3 3 5-5" />
        </svg>
      </div>
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wide text-blue-400/80 mb-1">Today's Action</p>
        <p className="text-sm text-slate-300 leading-relaxed">{text}</p>
      </div>
    </div>
  )
}

// ─── Day progress bar ─────────────────────────────────────────────────────────

function DayProgressBar({ readCount, totalCount }) {
  if (totalCount === 0) return null
  const pct = Math.round((readCount / totalCount) * 100)
  const allDone = readCount >= totalCount

  return (
    <div className="flex items-center gap-3 mb-2.5 md:mb-5 px-3 md:px-4 py-2.5 md:py-3 bg-slate-800/30 rounded-xl border border-slate-700/40">
      <div className="flex-1">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] font-semibold text-slate-400">Day progress</span>
          <span className={`text-[11px] font-semibold ${allDone ? "text-emerald-400" : "text-slate-500"}`}>
            {readCount} / {totalCount} core read
          </span>
        </div>
        <div className="h-1.5 bg-slate-700/60 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              allDone ? "bg-emerald-500" : "bg-blue-500"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      {allDone && (
        <span className="text-[10px] font-semibold text-emerald-400 flex-shrink-0">Complete</span>
      )}
    </div>
  )
}

// ─── Generate button ──────────────────────────────────────────────────────────

function GenerateButton({ generating, onGenerate, locked, nextLabel = "Next Day", generatedTodayCount }) {
  const [confirming, setConfirming] = useState(false)
  const isExtraToday = generatedTodayCount > 0

  function handleClick() {
    if (locked || generating) return
    setConfirming(true)
  }

  function handleConfirm() {
    setConfirming(false)
    onGenerate()
  }

  function handleCancel() {
    setConfirming(false)
  }

  return (
    <div className="flex flex-col gap-2">
      {confirming ? (
        <div className="flex flex-col gap-2 px-4 py-2.5 rounded-xl bg-slate-800 border border-slate-700/60">
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-300 flex-1">
              Generate {nextLabel}
              {isExtraToday && <span className="text-slate-500 text-xs ml-1">(extra for today)</span>}
              ?
            </span>
            <button
              onClick={handleConfirm}
              className="px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors"
            >
              Yes
            </button>
            <button
              onClick={handleCancel}
              className="px-3 py-1 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs font-medium transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={handleClick}
          disabled={generating || locked}
          title={locked ? "Mark all articles as read to unlock the next package" : undefined}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700/60 hover:border-slate-600 text-sm text-slate-300 hover:text-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          {generating ? (
            <>
              <SpinnerIcon className="w-3.5 h-3.5 animate-spin text-blue-400" />
              Generating {nextLabel}…
            </>
          ) : locked ? (
            <>
              <LockIcon className="w-3.5 h-3.5 text-slate-500" />
              Generate {nextLabel}
            </>
          ) : (
            <>
              <PlusIcon className="w-3.5 h-3.5" />
              Generate {nextLabel}
            </>
          )}
        </button>
      )}
      {locked && !generating && (
        <p className="text-[11px] text-slate-600 ml-1">
          Mark all articles as read to unlock.
        </p>
      )}
    </div>
  )
}

// ─── History sidebar item ─────────────────────────────────────────────────────

function HistoryItem({ pkg, dayLabel, isSelected, onClick }) {
  const isEmpty = dayLabel === "Day 0"
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2.5 rounded-xl transition-colors ${
        isSelected
          ? "bg-slate-700/60 border border-slate-600/60"
          : "hover:bg-slate-800/60 border border-transparent"
      }`}
    >
      <div className="flex items-center justify-between mb-0.5">
        <span className={`text-[10px] font-semibold uppercase tracking-wide ${isEmpty ? "text-rose-500" : "text-slate-500"}`}>
          {dayLabel ?? `Day ${pkg.day_number}`}
        </span>
        <span className="text-[10px] text-slate-600">{formatDate(pkg.generated_at)}</span>
      </div>
      {isEmpty ? (
        <p className="text-xs text-rose-500/60 leading-snug italic">Generation failed — no content</p>
      ) : (
        <p className="text-xs text-slate-300 leading-snug line-clamp-2">{pkg.package_headline}</p>
      )}
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

function PackageContent({
  pkg,
  project,
  generating,
  onGenerate,
  onRegenerate,
  onOpenInChat,
  isLatestPackage,
  dayLabel,
  generatedTodayCount,
  nextLabel,
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
}) {
  const failed = isFailedPackage(pkg)

  const newsCards      = pkg.insights?.filter(c => c.content_type === "news") || []
  const eduCards       = pkg.insights?.filter(c => c.content_type === "educational") || []
  const allCoreCards   = pkg.insights || []
  const curiosityCards = pkg.curiosity_insights || []
  const totalCoreCards = allCoreCards.length

  // Generation lock is based on CORE cards only — curiosity is optional
  const readCount        = readKeys?.size ?? 0
  const generationLocked = isLatestPackage && totalCoreCards > 0 && readCount < totalCoreCards

  const makeCardProps = (card) => {
    const ak = articleKeyFromTitle(card.title || "")
    return {
      card,
      isRead:             readKeys?.has(ak) ?? false,
      onMarkRead:         onMarkRead   ? () => onMarkRead(pkg.id, ak, card.title || "") : undefined,
      onMarkUnread:       onMarkUnread ? () => onMarkUnread(pkg.id, ak)                 : undefined,
      onAskAbout:         onOpenInChat ? (c) => onOpenInChat(c, "ask_about")         : undefined,
      onDeepResearch:     onOpenInChat ? (c) => onOpenInChat(c, "deep_research")     : undefined,
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
    }
  }

  if (failed) {
    return (
      <div>
        <FailedPackageBanner pkg={pkg} nextLabel={nextLabel} generating={generating} onRegenerate={onRegenerate} />
        <div className="mt-4 pt-4 border-t border-slate-800">
          <GenerateButton generating={generating} onGenerate={onGenerate} locked={false} nextLabel={nextLabel} generatedTodayCount={generatedTodayCount} />
        </div>
      </div>
    )
  }

  return (
    <div>
      <PackageHeader
        pkg={pkg}
        dayLabel={dayLabel}
        actions={<ExportButton pkg={pkg} project={project} dayLabel={dayLabel} />}
      />

      {/* Day progress bar — core cards only (curiosity is optional) */}
      {isLatestPackage && totalCoreCards > 0 && (
        <DayProgressBar readCount={readCount} totalCount={totalCoreCards} />
      )}

      {/* News cards */}
      {newsCards.length > 0 && (
        <>
          <SectionDivider label="Current Events" />
          <div className="space-y-1.5 md:space-y-3">
            {newsCards.map((card, i) => {
              const ak = articleKeyFromTitle(card.title || "")
              return (
                <div key={card.id || i} id={`queue-card-${ak}`}>
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
          <div className="space-y-1.5 md:space-y-3">
            {eduCards.map((card, i) => {
              const ak = articleKeyFromTitle(card.title || "")
              return (
                <div key={card.id || i} id={`queue-card-${ak}`}>
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
              <div key={card.id || i} id={`queue-card-${ak}`}>
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
          <p className="text-[11px] text-slate-600 mb-2 md:mb-3 leading-relaxed">
            Optional side trails — intellectually stimulating, not on the critical path.
          </p>
          <div className="space-y-1.5 md:space-y-3">
            {curiosityCards.map((card, i) => {
              const ak = articleKeyFromTitle(card.title || "")
              return (
                <div key={card.id || `curiosity-${i}`} id={`queue-card-${ak}`}>
                  <InsightCard {...makeCardProps(card)} />
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Generate next package */}
      <div className="mt-3 md:mt-6 pt-3 md:pt-5 border-t border-slate-800">
        <GenerateButton
          generating={generating}
          onGenerate={onGenerate}
          locked={generationLocked}
          nextLabel={nextLabel}
          generatedTodayCount={generatedTodayCount}
        />
      </div>
    </div>
  )
}

// ─── Main export ──────────────────────────────────────────────────────────────

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
              <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
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
}) {
  const [selectedId, setSelectedId] = useState(packages[0]?.id ?? null)
  // Map<cardId, noteContent> for the currently-selected package
  const [notesMap, setNotesMap] = useState(new Map())
  // Set<articleKey> — synced from localStorage queue
  const [queuedKeys, setQueuedKeys] = useState(() => new Set(getQueue().map(i => i.articleKey)))

  // Keep a ref so popstate handler always sees the latest packages without re-registering
  const packagesRef = useRef(packages)
  useEffect(() => { packagesRef.current = packages }, [packages])

  // Restore selected day from browser history once packages are available (handles view-switch back)
  const historyRestoredRef = useRef(false)
  useEffect(() => {
    if (historyRestoredRef.current || !packages.length) return
    historyRestoredRef.current = true
    const day = window.history.state?.feedDay
    if (!day) return
    const pkg = packages.find(p => p.id === day)
    if (pkg) setSelectedId(pkg.id)
  }, [packages])

  // Within-feed: restore correct day when browser back/forward fires while already on feed
  useEffect(() => {
    function onPopState(e) {
      const day = e.state?.feedDay
      if (!day) return
      const pkg = packagesRef.current.find(p => p.id === day)
      if (pkg) setSelectedId(pkg.id)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const selected = packages.find(p => p.id === selectedId) ?? packages[0] ?? null
  const latestId = packages[0]?.id ?? null
  const isLatest = selected?.id === latestId

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
    if (packages[0]?.id) setSelectedId(packages[0].id)
  }, [packages[0]?.id])

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
    if (isInQueue(articleKey)) {
      removeFromQueue(articleKey)
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

  // Show the animated generation state any time a fetch is in progress,
  // regardless of whether prior packages exist. Keep the history sidebar
  // visible on desktop so the user can see how many days they already have.
  if (generating) {
    return (
      <div className="flex gap-6 min-h-0">
        <div className="flex-1 min-w-0">
          <GeneratingPackageState project={project} nextLabel={nextLabel} />
        </div>
        {packages.length > 1 && (
          <aside className="hidden md:block w-56 flex-shrink-0">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-3 px-1">
              History
            </p>
            <div className="space-y-1">
              {packages.map(pkg => (
                <HistoryItem
                  key={pkg.id}
                  pkg={pkg}
                  dayLabel={displayLabels.get(pkg.id)}
                  isSelected={false}
                  onClick={() => {}}
                />
              ))}
            </div>
          </aside>
        )}
      </div>
    )
  }

  if (packages.length === 0) {
    return <EmptyPackageState project={project} onGenerate={onGenerate} />
  }

  return (
    <div className="flex gap-6 min-h-0">

      {/* Left: main package content */}
      <div className="flex-1 min-w-0">

        {/* Mobile package timeline — scrollable snap strip, desktop hidden */}
        {packages.length > 1 && (
          <div className="relative flex md:hidden mb-3 -mx-3">
            <div className="absolute left-0 top-0 bottom-0 w-6 bg-gradient-to-r from-slate-950 to-transparent z-10 pointer-events-none" />
            <div className="absolute right-0 top-0 bottom-0 w-6 bg-gradient-to-l from-slate-950 to-transparent z-10 pointer-events-none" />
            <div className="flex overflow-x-auto scrollbar-none snap-x snap-mandatory px-4 w-full">
              {[...packages].reverse().map(pkg => {
                const label = displayLabels.get(pkg.id)
                const isSel = pkg.id === selected?.id
                return (
                  <button
                    key={pkg.id}
                    onClick={() => { setSelectedId(pkg.id); window.history.pushState({ view: 'feed', feedDay: pkg.id }, '') }}
                    className={`flex-shrink-0 snap-start flex flex-col items-center px-3 py-2 gap-1.5 border-b-2 transition-all duration-150 group ${
                      isSel ? 'border-blue-500' : 'border-slate-800/60 hover:border-slate-700'
                    }`}
                  >
                    <span className={`text-[11px] font-medium whitespace-nowrap leading-none transition-colors ${
                      isSel ? 'text-slate-100' : 'text-slate-600 group-hover:text-slate-400'
                    }`}>
                      {label}
                    </span>
                    <span className={`w-1.5 h-1.5 rounded-full transition-all ${
                      isSel ? 'bg-blue-400' : 'bg-slate-700'
                    }`} />
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {selected ? (
          <PackageContent
            pkg={selected}
            project={project}
            generating={generating}
            onGenerate={onGenerate}
            onRegenerate={onRegenerate}
            onOpenInChat={onOpenInChat}
            isLatestPackage={isLatest}
            dayLabel={displayLabels.get(selected.id)}
            generatedTodayCount={isLatest ? generatedTodayCount : 0}
            nextLabel={isLatest ? nextLabel : undefined}
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
          />
        ) : null}
      </div>

      {/* Right: history sidebar (only if > 1 package) — desktop only */}
      {packages.length > 1 && (
        <aside className="hidden md:block w-56 flex-shrink-0">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-3 px-1">
            History
          </p>
          <div className="space-y-1">
            {packages.map(pkg => (
              <HistoryItem
                key={pkg.id}
                pkg={pkg}
                dayLabel={displayLabels.get(pkg.id)}
                isSelected={pkg.id === selected?.id}
                onClick={() => { setSelectedId(pkg.id); window.history.pushState({ view: 'feed', feedDay: pkg.id }, '') }}
              />
            ))}
          </div>
        </aside>
      )}
    </div>
  )
}

const GENERATION_STEPS = [
  { label: "Scanning today's news & research",  doneAfter: 4  },
  { label: "Selecting the most relevant articles", doneAfter: 10 },
  { label: "Generating educational insights",   doneAfter: 18 },
  { label: "Personalising to your level",        doneAfter: 26 },
]

function GeneratingPackageState({ project, nextLabel = "Day 1" }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setElapsed(s => s + 1), 1000)
    return () => clearInterval(id)
  }, [])

  // Progress 0→100 over ~32s, then stays at 95 until done
  const progress = Math.min(95, Math.round((elapsed / 32) * 100))

  return (
    <div className="flex flex-col items-center justify-center py-14 text-center max-w-sm mx-auto">
      {/* Animated logo ring */}
      <div className="relative w-16 h-16 mb-6">
        <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-blue-500 via-indigo-500 to-violet-600 animate-pulse shadow-lg shadow-violet-950/60" />
        <div className="absolute inset-0 rounded-2xl flex items-center justify-center">
          <svg style={{ width: '26px', height: '26px' }} viewBox="0 0 20 20" fill="none">
            <circle cx="10" cy="8" r="4" fill="white" fillOpacity="0.95" />
            <rect x="8.25" y="12" width="3.5" height="1.2" rx="0.6" fill="white" fillOpacity="0.8" />
            <rect x="8.75" y="13.6" width="2.5" height="1.1" rx="0.55" fill="white" fillOpacity="0.6" />
          </svg>
        </div>
        {/* Spinning ring */}
        <svg className="absolute inset-0 w-16 h-16 -rotate-90 animate-[spin_2s_linear_infinite]" viewBox="0 0 64 64">
          <circle cx="32" cy="32" r="28" fill="none" stroke="white" strokeOpacity="0.08" strokeWidth="3" />
          <circle cx="32" cy="32" r="28" fill="none" stroke="url(#gen-ring)" strokeWidth="3"
            strokeDasharray="60 116" strokeLinecap="round" />
          <defs>
            <linearGradient id="gen-ring" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#60a5fa" />
              <stop offset="100%" stopColor="#a78bfa" />
            </linearGradient>
          </defs>
        </svg>
      </div>

      <h3 className="text-base font-semibold text-slate-100 mb-1">
        Building your {nextLabel} package
      </h3>
      <p className="text-[13px] text-slate-500 mb-6">
        Curating <span className="text-slate-400">{project.name}</span> insights from today's web
      </p>

      {/* Step list */}
      <div className="w-full space-y-2.5 mb-6 text-left">
        {GENERATION_STEPS.map((step, i) => {
          const done    = elapsed >= step.doneAfter
          const active  = !done && elapsed >= (GENERATION_STEPS[i - 1]?.doneAfter ?? 0)
          return (
            <div key={i} className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-500 ${
              done   ? "bg-emerald-950/30 border border-emerald-900/30" :
              active ? "bg-blue-950/40 border border-blue-900/30" :
                       "bg-slate-900/40 border border-slate-800/30"
            }`}>
              <div className={`w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center transition-all duration-300 ${
                done ? "bg-emerald-500/20" : active ? "bg-blue-500/20" : "bg-slate-800"
              }`}>
                {done ? (
                  <svg className="w-3 h-3 text-emerald-400" viewBox="0 0 12 12" fill="currentColor">
                    <path d="M10.28 2.28a.75.75 0 0 0-1.06 0L4.5 6.99 2.78 5.27a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.06 0l5.25-5.25a.75.75 0 0 0 0-1.05Z" />
                  </svg>
                ) : active ? (
                  <SpinnerIcon className="w-3 h-3 text-blue-400 animate-spin" />
                ) : (
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-700" />
                )}
              </div>
              <span className={`text-[13px] transition-colors duration-300 ${
                done ? "text-emerald-400" : active ? "text-slate-200" : "text-slate-600"
              }`}>{step.label}</span>
            </div>
          )
        })}
      </div>

      {/* Progress bar */}
      <div className="w-full h-1 bg-slate-800 rounded-full overflow-hidden mb-3">
        <div
          className="h-full rounded-full bg-gradient-to-r from-blue-500 to-violet-500 transition-all duration-1000 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
      <p className="text-[11px] text-slate-600">Usually takes 15–30 seconds</p>
    </div>
  )
}

function EmptyPackageState({ project, onGenerate }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-12 h-12 rounded-2xl bg-slate-800 border border-slate-700 flex items-center justify-center mb-4">
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
        className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
      >
        Generate Day 1
      </button>
    </div>
  )
}

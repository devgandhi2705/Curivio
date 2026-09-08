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
import { useNavigate } from "react-router-dom"
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

// ─── Day history dropdown ─────────────────────────────────────────────────────

function DayDropdown({ packages, displayLabels, selectedId, onSelect }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const currentLabel = displayLabels.get(selectedId) ?? `Day ?`

  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className={[
          "inline-flex items-center gap-1.5 px-3 py-1 rounded-lg",
          "text-[11px] font-semibold uppercase tracking-wider transition-colors select-none",
          open
            ? "bg-white/[0.12] border border-white/[0.16] text-slate-100"
            : "bg-white/[0.07] border border-white/[0.11] text-slate-400 hover:text-slate-100 hover:bg-white/[0.10] hover:border-white/[0.15]",
        ].join(" ")}
      >
        {currentLabel}
        <svg
          className={`w-3 h-3 transition-transform duration-150 ${open ? "rotate-180" : ""}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1.5 z-30 min-w-[172px] bg-slate-900/95 backdrop-blur-sm border border-white/[0.07] rounded-xl shadow-2xl shadow-black/60 overflow-hidden py-1">
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
        </div>
      )}
    </div>
  )
}

function PackageHeader({ pkg, dayLabel, projectId }) {
  const contentMix = buildContentMix(pkg)
  return (
    <div className="mb-3 md:mb-7">
      {/* Headline */}
      <div className="flex items-start justify-between gap-2 mb-1.5 md:mb-4">
        <h2 className="text-[17px] md:text-[22px] font-bold text-slate-100 leading-snug tracking-tight break-words">
          {pkg.package_headline}
        </h2>
      </div>

      {/* Learning thread — left-accent style */}
      {pkg.learning_thread && (
        <div className="flex gap-3">
          <div className="flex-shrink-0 w-0.5 rounded-full bg-white/[0.08] self-stretch" />
          <p className="text-[12px] text-slate-500 leading-relaxed">{pkg.learning_thread}</p>
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
    <div className="flex items-center gap-3 mb-2.5 md:mb-5 px-3 md:px-4 py-2.5 md:py-3 bg-white/[0.04] rounded-xl">
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

function GenerateButton({ generating, genStage, onGenerate, locked, offline = false, nextLabel = "Next Day", generatedTodayCount }) {
  const [confirming, setConfirming] = useState(false)
  const isExtraToday = generatedTodayCount > 0

  function handleClick() {
    if (locked || generating || offline) return
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
        <div className="flex flex-col gap-2 px-4 py-2.5 rounded-xl bg-white/[0.05] border border-white/[0.08]">
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
          disabled={generating || locked || offline}
          title={offline ? "Generating requires an internet connection" : locked ? "Mark all articles as read to unlock the next package" : undefined}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/[0.05] hover:bg-white/[0.09] border border-white/[0.07] hover:border-white/[0.12] text-sm text-slate-400 hover:text-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          {generating ? (
            <>
              <SpinnerIcon className="w-3.5 h-3.5 animate-spin text-blue-400" />
              Generating {nextLabel} · {stageShortLabel(genStage)}…
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
  genStage,
  onGenerate,
  onRegenerate,
  onOpenInChat,
  isLatestPackage,
  nextPackage,
  onSelectPackage,
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
  isOnline = true,
  offlineIds,
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

  if (failed) {
    return (
      <div>
        <FailedPackageBanner pkg={pkg} nextLabel={nextLabel} generating={generating} onRegenerate={onRegenerate} />
        <div className="mt-4 pt-4 border-t border-slate-800">
          <GenerateButton generating={generating} onGenerate={onGenerate} locked={false} offline={!isOnline} nextLabel={nextLabel} generatedTodayCount={generatedTodayCount} />
        </div>
      </div>
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
        <DayProgressBar readCount={readCount} totalCount={totalCoreCards} />
      )}

      {/* News cards */}
      {newsCards.length > 0 && (
        <>
          <SectionDivider label="Current Events" />
          <div className="space-y-2 md:space-y-3">
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
          <div className="space-y-2 md:space-y-3">
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
          <div className="space-y-2 md:space-y-3">
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

      {/* Generating belongs to the newest day; older days offer the way forward instead. */}
      <div className="mt-3 md:mt-6 pt-3 md:pt-5 border-t border-slate-800">
        {isLatestPackage ? (
          <GenerateButton
            generating={generating}
            genStage={genStage}
            onGenerate={onGenerate}
            locked={generationLocked}
            offline={!isOnline}
            nextLabel={nextLabel}
            generatedTodayCount={generatedTodayCount}
          />
        ) : nextPackage ? (
          <button
            type="button"
            onClick={() => onSelectPackage?.(nextPackage.id)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/[0.05] hover:bg-white/[0.09] border border-white/[0.07] hover:border-white/[0.12] text-sm text-slate-400 hover:text-slate-100 transition-all"
          >
            Read {nextPackage.label}
          </button>
        ) : null}
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

  if (packages.length === 0) {
    // Dismissed with nothing to read yet: the progress strip carries the run,
    // so give the page the planned path to read instead of an empty column.
    if (generating && genDismissed) return <JourneyPreviewPanel projectId={project?.project_id} />
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
      <div className="fixed top-3.5 left-1/2 -translate-x-1/2 z-50">
        <DayDropdown
          packages={packages}
          displayLabels={displayLabels}
          selectedId={selectedId}
          onSelect={selectPackage}
        />
      </div>
      <PackageContent
        pkg={selected}
        project={project}
        generating={generating}
        genStage={genStage}
        onGenerate={onGenerate}
        onRegenerate={onRegenerate}
        onOpenInChat={onOpenInChat}
        isLatestPackage={isLatest}
        nextPackage={nextPkg ? { id: nextPkg.id, label: displayLabels.get(nextPkg.id) ?? `Day ${nextPkg.day_number}` } : null}
        onSelectPackage={selectPackage}
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
        isOnline={isOnline}
        offlineIds={offlineIds}
      />
      <JourneyPreviewPanel projectId={project.project_id} />
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
    <div data-no-unpack className="max-w-xl mx-auto py-10 md:py-16">
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
                  className="absolute -left-[9px] top-[1px] h-[19px] w-[19px] rounded-full animate-ping motion-reduce:hidden"
                  style={{ background: "var(--u-accent)", opacity: 0.18, animationDuration: "2.4s" }}
                />
              )}
              <span
                aria-hidden
                className="absolute -left-[5px] top-[6px] h-[9px] w-[9px] rounded-full transition-colors duration-500"
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

function JourneyPreviewPanel({ projectId }) {
  const [preview, setPreview] = useState(null)

  useEffect(() => {
    if (!projectId) return
    getJourneyPreview(projectId).then(setPreview).catch(() => {})
  }, [projectId])

  if (!preview) return null

  if (!preview.planned) {
    return (
      <div className="mt-4 md:mt-6 px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-600 mb-1">Your path</p>
        <p className="text-[12px] text-slate-600">Not yet planned — your path will appear here once your first package is generated.</p>
      </div>
    )
  }

  if (preview.shape === "rotating_theme") {
    return (
      <div className="mt-4 md:mt-6 px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-600 mb-1.5">Your path</p>
        <p className="text-[12px] text-slate-400 leading-relaxed">{preview.display_summary}</p>
      </div>
    )
  }

  // fixed_sequence
  return (
    <div className="mt-4 md:mt-6 px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-600 mb-2">Your path</p>
      <div className="space-y-1.5">
        <div className="flex items-baseline gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-blue-400/70 w-10 flex-shrink-0">Today</span>
          <span className="text-[12px] text-slate-300 leading-snug">{preview.today.display_title}</span>
        </div>
        {preview.upcoming.map(day => (
          <div key={day.day_number} className="flex items-baseline gap-2">
            <span className="text-[10px] font-medium text-slate-600 w-10 flex-shrink-0">Day {day.day_number}</span>
            <span className="text-[12px] text-slate-500 leading-snug">{day.display_title}</span>
          </div>
        ))}
      </div>
      {preview.remaining_count > 0 && (
        <p className="mt-2 text-[11px] text-slate-600">+{preview.remaining_count} more planned</p>
      )}
    </div>
  )
}

function EmptyPackageState({ project, onGenerate, isOnline = true }) {
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
        disabled={!isOnline}
        title={!isOnline ? "Generating requires an internet connection" : undefined}
        className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Generate Day 1
      </button>
      <JourneyPreviewPanel projectId={project.project_id} />
    </div>
  )
}

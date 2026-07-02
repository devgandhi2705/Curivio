/**
 * InsightCard — single insight card from a daily package.
 *
 * content_type: "news" (blue) | "educational" (emerald)
 *
 * Props:
 *   card                 — insight data object
 *   isRead               — boolean, whether this card has been read
 *   onMarkRead()         — called to mark read (no args)
 *   onMarkUnread()       — called to mark unread (no args)
 *   onAskAbout(card)     — open in chat: ask about this
 *   onDeepResearch(card) — open in chat: deep research
 *   relatedChats         — list of linked chat sessions (null = not loaded)
 *   onLoadRelatedChats() — trigger lazy load of related chats
 *   onOpenChat(sessionId)— navigate to a specific chat session
 */
import { useState, useEffect, useRef } from "react"
import BookmarkButton from "../bookmarks/BookmarkButton.jsx"

const DIFF_BADGE = {
  beginner:     "text-emerald-400/60 bg-emerald-900/15 border-emerald-800/25",
  intermediate: "text-blue-400/60 bg-blue-900/15 border-blue-800/25",
  advanced:     "text-violet-400/60 bg-violet-900/15 border-violet-800/25",
}

// ─── Icon components ──────────────────────────────────────────────────────────

function GlobeIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM4.332 8.027a6.012 6.012 0 0 1 1.912-2.706C6.512 5.73 6.974 6 7.5 6A1.5 1.5 0 0 1 9 7.5V8a2 2 0 0 0 4 0 2 2 0 0 1 1.523-1.943A5.977 5.977 0 0 1 16 10c0 .34-.028.675-.083 1H15a2 2 0 0 0-2 2v2.197A5.973 5.973 0 0 1 10 16v-2a2 2 0 0 0-2-2 2 2 0 0 1-2-2 2 2 0 0 0-1.668-1.973Z" clipRule="evenodd" />
    </svg>
  )
}

function BookIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path d="M10.75 16.82A7.462 7.462 0 0 1 15 15.5c.71 0 1.396.098 2.046.282A.75.75 0 0 0 18 15.06V4.442a.75.75 0 0 0-.546-.721A9.006 9.006 0 0 0 15 3.5a8.994 8.994 0 0 0-4.25 1.051V16.82ZM9.25 4.551A8.994 8.994 0 0 0 5 3.5c-.85 0-1.673.118-2.454.322A.75.75 0 0 0 2 4.544V15.06a.75.75 0 0 0 .954.721A7.462 7.462 0 0 1 5 15.5c1.738 0 2.763.653 3.745 1.682A.75.75 0 0 0 9.25 17V4.551Z" />
    </svg>
  )
}

function ExternalLinkIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6.5 3.5H3a1 1 0 0 0-1 1V13a1 1 0 0 0 1 1h8.5a1 1 0 0 0 1-1V9.5M9 2.5h4.5m0 0v4.5m0-4.5L7.5 10" />
    </svg>
  )
}

function ChevronIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
    </svg>
  )
}

function LightbulbIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path d="M10 1a6 6 0 0 1 3.479 10.907A1 1 0 0 1 13 13H7a1 1 0 0 1-.479-1.093A6 6 0 0 1 10 1ZM8.5 15.5a.5.5 0 0 0 0 1h3a.5.5 0 0 0 0-1h-3Zm.25 2a.25.25 0 0 0 0 .5h2.5a.25.25 0 0 0 0-.5h-2.5Z" />
    </svg>
  )
}

function ChatIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M1 2.75C1 1.784 1.784 1 2.75 1h10.5c.966 0 1.75.784 1.75 1.75v7.5A1.75 1.75 0 0 1 13.25 12H9.06l-2.573 2.573A1.458 1.458 0 0 1 4 13.543V12H2.75A1.75 1.75 0 0 1 1 10.25Z" />
    </svg>
  )
}


function MicroscopeIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M9.5 0a.75.75 0 0 1 .75.75v1h1.5a.75.75 0 0 1 0 1.5h-1.5v.75a.75.75 0 0 1-1.5 0V.75A.75.75 0 0 1 9.5 0ZM7.25 4.5a.75.75 0 0 0-1.5 0v1h-.25C3.783 5.5 2.5 6.783 2.5 8.25V10h-.75a.75.75 0 0 0 0 1.5h9.5a.75.75 0 0 0 0-1.5H10.5V8.25C10.5 6.783 9.217 5.5 7.75 5.5H7.5V4.5Zm-3 6H9V8.25A1.25 1.25 0 0 0 7.75 7h-2A1.25 1.25 0 0 0 4.5 8.25V10.5ZM2.5 12h11a.75.75 0 0 1 0 1.5h-11a.75.75 0 0 1 0-1.5Z" />
    </svg>
  )
}

function CheckCircleIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 16A8 8 0 1 1 8 0a8 8 0 0 1 0 16Zm3.78-9.72a.75.75 0 0 0-1.06-1.06L6.75 9.19 5.28 7.72a.75.75 0 0 0-1.06 1.06l2 2a.75.75 0 0 0 1.06 0l4.5-4.5Z" />
    </svg>
  )
}

function CircleIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="8" r="6.5" />
    </svg>
  )
}

function CloudCheckIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M4.406 3.342A5.53 5.53 0 0 1 8 2c2.69 0 4.923 2 5.166 4.579C14.758 6.804 16 8.137 16 9.75 16 11.545 14.545 13 12.75 13H4a4 4 0 0 1-.821-7.911 5.53 5.53 0 0 1 1.227-1.747Zm5.03 3.596a.75.75 0 0 0-1.06-1.06L6.25 8l-.876-.876a.75.75 0 0 0-1.06 1.06l1.406 1.406a.75.75 0 0 0 1.06 0l2.656-2.652Z" />
    </svg>
  )
}

function PencilIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61Zm.176 4.823L9.75 4.81l-6.286 6.287a.253.253 0 0 0-.064.108l-.558 1.953 1.953-.558a.253.253 0 0 0 .108-.064Zm1.238-3.763a.25.25 0 0 0-.354 0L10.811 3.75l1.439 1.44 1.263-1.263a.25.25 0 0 0 0-.354Z" />
    </svg>
  )
}

function ClockIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0ZM7.25 4.75a.75.75 0 0 1 1.5 0V8.5h2a.75.75 0 0 1 0 1.5H8a.75.75 0 0 1-.75-.75V4.75Z" />
    </svg>
  )
}

function DotsIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3ZM1.5 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Zm13 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" />
    </svg>
  )
}

// ─── Card type config ─────────────────────────────────────────────────────────

const TYPE_CONFIG = {
  news: {
    label:      "News",
    borderTop:  "border-t-2 border-t-blue-500/60",
    iconBg:     "bg-blue-500/15 border-blue-500/30",
    iconColor:  "text-blue-400",
    labelColor: "text-blue-400/65 bg-blue-500/[0.08] border-blue-500/15",
    Icon: GlobeIcon,
  },
  educational: {
    label:      "Educational",
    borderTop:  "border-t-2 border-t-emerald-500/60",
    iconBg:     "bg-emerald-500/15 border-emerald-500/30",
    iconColor:  "text-emerald-400",
    labelColor: "text-emerald-400/65 bg-emerald-500/[0.08] border-emerald-500/15",
    Icon: BookIcon,
  },
  curiosity: {
    label:      "Curiosity Pick",
    borderTop:  "border-t border-t-amber-500/40",
    iconBg:     "bg-amber-500/10 border-amber-500/20",
    iconColor:  "text-amber-400/80",
    labelColor: "text-amber-400/60 bg-amber-500/[0.07] border-amber-500/15",
    Icon: LightbulbIcon,
  },
}

// ─── Block renderer ───────────────────────────────────────────────────────────
// Public API: renderBlock(type, content)
// Third param `key` is an implementation detail for list rendering.

function renderBlock(type, content, key) {
  const text = content || ""

  // ── 8 visually distinct types ──────────────────────────────────────────────

  // headline → section sub-heading
  if (type === "headline") {
    return (
      <div key={key} className="px-3 md:px-4 pt-3 pb-1">
        <p className="text-[13px] font-semibold text-slate-200 leading-snug">{text}</p>
      </div>
    )
  }

  // key_takeaway → highlighted callout box
  if (type === "key_takeaway") {
    return (
      <div key={key} className="mx-3 md:mx-4 mb-2.5">
        <div className="bg-blue-500/[0.07] border border-blue-500/20 rounded-lg px-3 py-2.5">
          <p className="text-[12px] text-blue-200/75 leading-relaxed">{text}</p>
        </div>
      </div>
    )
  }

  // example → bordered card
  if (type === "example") {
    return (
      <div key={key} className="mx-3 md:mx-4 mb-2.5">
        <p className="text-[9px] font-semibold uppercase tracking-widest text-slate-600 mb-1.5 px-0.5">For Example</p>
        <div className="border border-slate-700/40 rounded-lg bg-slate-800/20 px-3 py-2.5">
          <p className="text-[11px] text-slate-400 leading-relaxed">{text}</p>
        </div>
      </div>
    )
  }

  // timeline → dotted chronological list
  if (type === "timeline") {
    const items = text.split("\n").map(s => s.trim()).filter(Boolean)
    return (
      <div key={key} className="border-t border-slate-800/50">
        <div className="flex items-center gap-2 px-3 md:px-4 py-1.5 md:py-2">
          <ClockIcon className="w-3 h-3 text-slate-600" />
          <span className="text-[10px] font-medium text-slate-600 uppercase tracking-wide">Timeline</span>
        </div>
        <div className="px-3 md:px-4 pb-2.5 space-y-1.5">
          {items.length > 0 ? items.map((item, j) => (
            <div key={j} className="flex gap-2.5 items-start">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-600 flex-shrink-0 mt-[5px]" />
              <p className="text-[11px] text-slate-500 leading-relaxed">{item}</p>
            </div>
          )) : <p className="text-[11px] text-slate-500 leading-relaxed">{text}</p>}
        </div>
      </div>
    )
  }

  // comparison → row-per-item layout
  if (type === "comparison") {
    const items = text.split("\n").map(s => s.trim()).filter(Boolean)
    return (
      <div key={key} className="border-t border-slate-800/50">
        <div className="flex items-center gap-2 px-3 md:px-4 py-1.5 md:py-2">
          <BookIcon className="w-3 h-3 text-slate-600" />
          <span className="text-[10px] font-medium text-slate-600 uppercase tracking-wide">Comparison</span>
        </div>
        <div className="px-3 md:px-4 pb-2.5 space-y-1">
          {items.length > 1 ? items.map((item, j) => (
            <div key={j} className="bg-slate-800/25 rounded px-2.5 py-1.5">
              <p className="text-[11px] text-slate-500 leading-relaxed">{item}</p>
            </div>
          )) : <p className="text-[11px] text-slate-500 leading-relaxed">{text}</p>}
        </div>
      </div>
    )
  }

  // warning → amber caution block
  if (type === "warning") {
    return (
      <div key={key} className="mx-3 md:mx-4 mb-2.5">
        <div className="bg-amber-500/[0.07] border border-amber-500/25 rounded-lg px-3 py-2.5">
          <p className="text-[9px] font-semibold uppercase tracking-widest text-amber-500/60 mb-1.5">Caution</p>
          <p className="text-[11px] text-amber-200/60 leading-relaxed">{text}</p>
        </div>
      </div>
    )
  }

  // evidence → citation block with left rule
  if (type === "evidence") {
    return (
      <div key={key} className="border-t border-slate-800/50">
        <div className="flex items-center gap-2 px-3 md:px-4 py-1.5 md:py-2">
          <GlobeIcon className="w-3 h-3 text-slate-600" />
          <span className="text-[10px] font-medium text-slate-600 uppercase tracking-wide">Source</span>
        </div>
        <div className="mx-3 md:mx-4 mb-2.5 border-l-2 border-slate-700/50 pl-2.5">
          <p className="text-[11px] text-slate-500 leading-relaxed italic">{text}</p>
        </div>
      </div>
    )
  }

  // reflection → closing italic block with top rule
  if (type === "reflection") {
    return (
      <div key={key} className="mx-3 md:mx-4 mb-3 mt-0.5 border-t border-slate-800/40 pt-2.5">
        <p className="text-[11px] text-slate-500/80 leading-relaxed italic">{text}</p>
      </div>
    )
  }

  // ── Other named types ──────────────────────────────────────────────────────

  if (type === "mechanism") {
    return (
      <div key={key} className="mx-3 mb-2.5 md:mx-4 md:mb-3 flex gap-2.5">
        <div className="w-px flex-shrink-0 self-stretch rounded-full bg-indigo-500/35" />
        <div className="min-w-0 py-0.5">
          <p className="text-[9px] font-semibold uppercase tracking-widest text-indigo-400/55 mb-1.5">Hidden Mechanism</p>
          <p className="text-[11px] text-slate-500 leading-relaxed">{text}</p>
        </div>
      </div>
    )
  }

  if (type === "insight") {
    return (
      <div key={key} className="mx-3 mb-2.5 md:mx-4 md:mb-3 flex gap-2.5">
        <div className="w-px flex-shrink-0 self-stretch rounded-full bg-blue-500/35" />
        <div className="min-w-0 py-0.5">
          <p className="text-[9px] font-semibold uppercase tracking-widest text-blue-400/55 mb-1.5">Insight</p>
          <p className="text-[11px] text-slate-500 leading-relaxed">{text}</p>
        </div>
      </div>
    )
  }

  if (type === "step_list") {
    const steps = text.split("\n").map(s => s.replace(/^\d+\.\s*/, "").trim()).filter(Boolean)
    return (
      <div key={key} className="border-t border-slate-800/50">
        <div className="flex items-center gap-2 px-3 md:px-4 py-1.5 md:py-2">
          <BookIcon className="w-3 h-3 text-slate-600" />
          <span className="text-[10px] font-medium text-slate-600 uppercase tracking-wide">Steps</span>
        </div>
        <div className="px-3 md:px-4 pb-2.5 space-y-1.5">
          {steps.length > 0 ? steps.map((step, j) => (
            <div key={j} className="flex gap-2.5 items-start">
              <span className="text-[9px] font-bold text-slate-600 flex-shrink-0 mt-[3px] w-3.5 text-right">{j + 1}.</span>
              <p className="text-[11px] text-slate-500 leading-relaxed">{step}</p>
            </div>
          )) : <p className="text-[11px] text-slate-500 leading-relaxed">{text}</p>}
        </div>
      </div>
    )
  }

  // labeled fallback for: explanation, counterpoint, implication, and any unknown type
  const LABELED = {
    explanation:  { label: "Why This Works", Icon: LightbulbIcon },
    counterpoint: { label: "Counterpoint",   Icon: BookIcon },
    implication:  { label: "Implication",    Icon: BookIcon },
  }
  const cfg = LABELED[type] || { label: type || "Note", Icon: BookIcon }
  return (
    <div key={key} className="border-t border-slate-800/50">
      <div className="flex items-center gap-2 px-3 md:px-4 py-1.5 md:py-2">
        <cfg.Icon className="w-3 h-3 text-slate-600" />
        <span className="text-[10px] font-medium text-slate-600 uppercase tracking-wide">{cfg.label}</span>
      </div>
      <div className="px-3 md:px-4 pb-2.5 md:pb-3.5">
        <p className="text-[12px] md:text-xs text-slate-500 md:text-slate-400 leading-relaxed">{text}</p>
      </div>
    </div>
  )
}

// ─── Source validation helpers ────────────────────────────────────────────────

const _BLOCKED_HOSTS = new Set(["example.com", "placeholder.com", "test.com", "localhost"])

function _isValidSourceUrl(url) {
  if (!url || typeof url !== "string") return false
  try {
    const { protocol, hostname } = new URL(url)
    if (protocol !== "http:" && protocol !== "https:") return false
    const bare = hostname.replace(/^www\./, "")
    if (_BLOCKED_HOSTS.has(bare)) return false
    if (!hostname.includes(".")) return false
    return true
  } catch {
    return false
  }
}

function _extractPublisher(url, title) {
  try {
    const bare = new URL(url).hostname.replace(/^www\./, "")
    const label = bare.split(".").at(-2) ?? bare.split(".")[0]
    return label.charAt(0).toUpperCase() + label.slice(1)
  } catch {
    return (title ?? "").split(" ").slice(0, 2).join(" ") || "Source"
  }
}

// ─── Source section ───────────────────────────────────────────────────────────

function SourceSection({ sourceLinks, cardTitle }) {
  const [expanded, setExpanded] = useState(false)

  const valid = (sourceLinks ?? []).filter(s => _isValidSourceUrl(s?.url))

  if (!valid.length) {
    if ((sourceLinks ?? []).length > 0) {
      console.error("[InsightCard] source_links present but no valid URLs for card:", cardTitle, sourceLinks)
    }
    return null
  }

  const enriched = valid.map(s => ({ ...s, publisher: _extractPublisher(s.url, s.title) }))

  return (
    <div className="border-t border-slate-800/40">
      {/* Compact row — publisher pills + toggle */}
      <div className="px-3 md:px-4 pt-2 pb-1.5 flex items-center gap-2 flex-wrap">
        <span className="text-[9px] font-semibold uppercase tracking-widest text-slate-600 flex-shrink-0">
          Sources
        </span>
        {enriched.map((s, i) => (
          <span
            key={i}
            className="px-1.5 py-0.5 rounded text-[9px] font-medium text-slate-500 bg-slate-800/60 border border-slate-700/30"
          >
            {s.publisher}
          </span>
        ))}
        <button
          onClick={() => setExpanded(o => !o)}
          className="ml-auto inline-flex items-center gap-1 text-[10px] text-slate-600 hover:text-slate-400 transition-colors"
          aria-label={expanded ? "Collapse sources" : "Open sources"}
        >
          Sources
          <ChevronIcon className={`w-3 h-3 transition-transform ${expanded ? "rotate-180" : ""}`} />
        </button>
      </div>

      {/* Expanded: full links */}
      {expanded && (
        <div className="px-3 md:px-4 pb-2.5 space-y-0.5">
          {enriched.map((s, i) => (
            <a
              key={i}
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 py-1 text-[11px] text-slate-500 hover:text-slate-200 transition-colors group min-w-0"
            >
              <ExternalLinkIcon className="w-2.5 h-2.5 flex-shrink-0 group-hover:text-blue-400" />
              <span className="truncate flex-1">{s.title || s.publisher}</span>
              <span className="text-[9px] text-slate-700 flex-shrink-0 ml-1">{s.publisher}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Inline note textarea (rendered below action bar when open) ───────────────

function NoteArea({ draft, onChange }) {
  return (
    <div className="px-3 py-2 md:px-4 md:py-3 border-t border-slate-800/80 bg-slate-800/20">
      <textarea
        className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-amber-500/40 focus:bg-slate-800/70 resize-none transition-colors"
        rows={3}
        placeholder="Your thoughts on this card…"
        value={draft}
        onChange={onChange}
        autoFocus
      />
      <p className="text-[10px] text-slate-600 mt-1">
        {draft.trim() ? "Auto-saved" : "Start typing to save a note"}
      </p>
    </div>
  )
}

// ─── Related chats section ────────────────────────────────────────────────────

const INTERACTION_LABELS = {
  ask_about:      "Asked about",
  continue_research: "Researched",
  deep_research:  "Deep research",
  explain_simply: "Explained simply",
}

function RelatedChats({ relatedChats, onLoadRelatedChats, onOpenChat }) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (relatedChats === null && onLoadRelatedChats) {
      onLoadRelatedChats()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function handleToggle() {
    if (!open) onLoadRelatedChats?.()
    setOpen(o => !o)
  }

  if (!onLoadRelatedChats && !relatedChats?.length) return null

  const count = relatedChats?.length ?? 0

  return (
    <div className="border-t border-slate-800/50">
      <button
        onClick={handleToggle}
        className="w-full flex items-center justify-between px-3 py-1.5 md:px-4 hover:bg-slate-800/20 transition-colors text-left"
      >
        <div className="flex items-center gap-1.5">
          <ChatIcon className="w-3 h-3 text-slate-600" />
          <span className="text-[11px] font-medium text-slate-500">
            {relatedChats === null
              ? "Related discussions"
              : count === 0
                ? "No related discussions yet"
                : `${count} related discussion${count !== 1 ? "s" : ""}`}
          </span>
        </div>
        <ChevronIcon className={`w-3 h-3 text-slate-600 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="px-3 pb-2 md:px-4 md:pb-3 space-y-1.5">
          {relatedChats === null ? (
            <p className="text-[11px] text-slate-600 animate-pulse">Loading…</p>
          ) : relatedChats.length === 0 ? (
            <p className="text-[11px] text-slate-600">Start a chat from this card to see it here.</p>
          ) : (
            relatedChats.map((link) => (
              <button
                key={link.id}
                onClick={() => onOpenChat?.(link.session_id, link.session_title)}
                className="w-full text-left flex items-start gap-2 p-2 rounded-lg hover:bg-slate-800/60 transition-colors group"
              >
                <span className="mt-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600 w-16 flex-shrink-0">
                  {INTERACTION_LABELS[link.interaction_type] ?? "Chat"}
                </span>
                <span className="text-[11px] text-slate-400 group-hover:text-slate-200 transition-colors leading-snug">
                  {link.session_title || "Untitled session"}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function InsightCard({
  card,
  isRead = false,
  onMarkRead,
  onMarkUnread,
  onAskAbout,
  onDeepResearch,
  onExplainSimply,
  isQueued = false,
  onToggleQueue,
  relatedChats = null,
  onLoadRelatedChats,
  onOpenChat,
  projectId   = '',
  projectName = '',
  note        = null,
  onSaveNote,
  onDeleteNote,
  isOfflineAvailable = false,
  offlineDisabled    = false,
}) {

  const type   = TYPE_CONFIG[card.content_type] || TYPE_CONFIG.news

  const hasChatActions = onAskAbout || onDeepResearch || onExplainSimply || onToggleQueue

  const [noteOpen, setNoteOpen] = useState(false)
  const [noteDraft, setNoteDraft] = useState(note ?? "")
  const [moreOpen, setMoreOpen] = useState(false)
  const noteTimerRef = useRef(null)

  useEffect(() => { setNoteDraft(note ?? "") }, [note])

  function handleNoteChange(e) {
    const val = e.target.value
    setNoteDraft(val)
    clearTimeout(noteTimerRef.current)
    noteTimerRef.current = setTimeout(() => {
      if (val.trim()) onSaveNote?.(val)
      else onDeleteNote?.()
    }, 600)
  }

  const hasNote = (note ?? "").trim().length > 0

  function handleReadToggle(e) {
    e.stopPropagation()
    if (isRead) onMarkUnread?.()
    else onMarkRead?.()
  }

  return (
    <div className={`rounded-2xl border overflow-hidden flex flex-col transition-colors ${
      type.borderTop
    } ${card.content_type === "curiosity"
        ? "bg-amber-950/[0.10] border-amber-900/20"
        : `bg-slate-900/50 ${isRead ? "border-slate-800/50 opacity-75" : "border-slate-800"}`
    }`}>

      {/* Card header */}
      <div className="px-3 pt-3 pb-1.5 md:px-4 md:pt-4 md:pb-3 flex items-start justify-between gap-2.5">
        <div className="flex items-start gap-2 md:gap-3 min-w-0">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap mb-1.5">
              <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide border ${type.labelColor}`}>
                {type.label}
              </span>
              {isOfflineAvailable && (
                <CloudCheckIcon className="w-3.5 h-3.5 text-slate-600" />
              )}
              {card.category && (
                <span className="inline-flex items-center text-[10px] text-slate-500/60 leading-none">
                  {card.category}
                </span>
              )}
            </div>
            <h3 className="text-[15px] md:text-sm font-semibold text-slate-100 leading-snug">{card.title}</h3>
          </div>
        </div>
      </div>

      {/* Summary */}
      <div className="px-3 pb-2 md:px-4 md:pb-3">
        <p className="text-[13px] md:text-sm text-slate-400 leading-relaxed">{card.summary}</p>
      </div>

      {/* Content blocks — new schema; fallback to legacy flat fields */}
      {card.blocks?.length > 0 ? (
        card.blocks.map((b, i) => renderBlock(b.type || "", b.content || "", i))
      ) : (
        <>
          {card.educational_explanation && (
            <div className="border-t border-slate-800/50">
              <div className="flex items-center gap-2 px-3 md:px-4 py-1.5 md:py-2">
                <LightbulbIcon className="w-3 h-3 text-slate-600" />
                <span className="text-[10px] font-medium text-slate-600 uppercase tracking-wide">
                  {card.content_type === "educational" ? "Deep Dive" : "Why This Works"}
                </span>
              </div>
              <div className="px-3 md:px-4 pb-2.5 md:pb-3.5">
                <p className="text-[12px] md:text-xs text-slate-500 md:text-slate-400 leading-relaxed">{card.educational_explanation}</p>
              </div>
            </div>
          )}
          {card.why_it_matters && (
            <div className="mx-3 mb-2.5 md:mx-4 md:mb-3 flex gap-2.5">
              <div className="w-px flex-shrink-0 self-stretch rounded-full bg-indigo-500/35" />
              <div className="min-w-0 py-0.5">
                <p className="text-[9px] font-semibold uppercase tracking-widest text-indigo-400/55 mb-1.5">
                  Hidden Mechanism
                </p>
                <p className="text-[11px] text-slate-500 leading-relaxed">{card.why_it_matters}</p>
              </div>
            </div>
          )}
        </>
      )}

      {/* Source section — validated, two-tier: publisher pills + expandable URLs */}
      <SourceSection sourceLinks={card.source_links} cardTitle={card.title} />

      {/* Bottom action bar */}
      {(hasChatActions || onMarkRead || onMarkUnread) && (
        <div className="border-t border-slate-800/50 px-2.5 md:px-4 py-1.5 md:py-2.5">
          {/* Primary + secondary row — always visible */}
          <div className="flex items-center gap-1 md:gap-1.5 flex-wrap">
            {/* PRIMARY: Ask About */}
            {onAskAbout && (
              <button
                onClick={() => onAskAbout(card)}
                disabled={offlineDisabled}
                title={offlineDisabled ? "Requires an internet connection" : undefined}
                className="inline-flex items-center gap-1 md:gap-1.5 px-2 py-0.5 md:px-2.5 md:py-1 rounded-lg text-[11px] font-medium text-slate-400 hover:text-blue-300 bg-slate-800/20 hover:bg-blue-500/10 border border-slate-700/20 hover:border-blue-500/30 md:bg-slate-800/40 md:border-slate-700/40 transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-slate-400 disabled:hover:bg-slate-800/20 disabled:hover:border-slate-700/20"
              >
                <ChatIcon className="w-3 h-3" />
                Ask About
              </button>
            )}
            {/* PRIMARY: Explain Simply */}
            {onExplainSimply && (
              <button
                onClick={() => onExplainSimply(card)}
                disabled={offlineDisabled}
                title={offlineDisabled ? "Requires an internet connection" : undefined}
                className="inline-flex items-center gap-1 md:gap-1.5 px-2 py-0.5 md:px-2.5 md:py-1 rounded-lg text-[11px] font-medium text-slate-400 hover:text-amber-300 bg-slate-800/20 hover:bg-amber-500/10 border border-slate-700/20 hover:border-amber-500/30 md:bg-slate-800/40 md:border-slate-700/40 transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-slate-400 disabled:hover:bg-slate-800/20 disabled:hover:border-slate-700/20"
              >
                <LightbulbIcon className="w-3 h-3" />
                Explain Simply
              </button>
            )}
            {/* SECONDARY: Deep Research — icon only on mobile */}
            {onDeepResearch && (
              <button
                onClick={() => onDeepResearch(card)}
                disabled={offlineDisabled}
                title={offlineDisabled ? "Requires an internet connection" : undefined}
                className="inline-flex items-center gap-1 md:gap-1.5 px-2 py-0.5 md:px-2.5 md:py-1 rounded-lg text-[11px] font-medium text-slate-400 hover:text-violet-300 bg-slate-800/20 hover:bg-violet-500/10 border border-slate-700/20 hover:border-violet-500/30 md:bg-slate-800/40 md:border-slate-700/40 transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-slate-400 disabled:hover:bg-slate-800/20 disabled:hover:border-slate-700/20"
              >
                <MicroscopeIcon className="w-3 h-3" />
                <span className="hidden md:inline">Deep Research</span>
              </button>
            )}
            {/* SECONDARY: Read Later — desktop main row only */}
            {onToggleQueue && (
              <button
                onClick={(e) => { e.stopPropagation(); onToggleQueue(card) }}
                className={`hidden md:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all ${
                  isQueued
                    ? "text-amber-400 bg-amber-500/10 border-amber-500/30 hover:bg-slate-800/40 hover:text-slate-400 hover:border-slate-700/40"
                    : "text-slate-500 bg-slate-800/40 border-slate-700/40 hover:text-amber-300 hover:bg-amber-500/10 hover:border-amber-500/30"
                }`}
              >
                <ClockIcon className="w-3 h-3" />
                {isQueued ? "Queued" : "Read Later"}
              </button>
            )}
            {/* Add note — desktop main row only (ml-auto) */}
            {(onSaveNote || onDeleteNote || note) && (
              <button
                onClick={() => setNoteOpen(o => !o)}
                className={`hidden md:inline-flex ml-auto items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all ${
                  noteOpen || hasNote
                    ? "text-amber-400 bg-amber-500/10 border-amber-500/30"
                    : "text-slate-500 bg-slate-800/40 border-slate-700/40 hover:text-amber-300 hover:bg-amber-500/10 hover:border-amber-500/30"
                }`}
              >
                <PencilIcon className="w-3 h-3" />
                {hasNote ? "My note" : "Add note"}
                {hasNote && !noteOpen && (
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400/70 flex-shrink-0" />
                )}
              </button>
            )}
            {/* Bookmark — always visible */}
            <BookmarkButton
              className={(onSaveNote || onDeleteNote || note) ? "" : "md:ml-auto"}
              label
              bookmarkData={{
                title:              card.title,
                summary:            card.summary || '',
                content_type:       card.content_type === 'curiosity' ? 'curiosity' : 'feed_article',
                source_url:         card.source_links?.[0]?.url || '',
                project_id:         projectId,
                project_name:       projectName,
                ai_generated_notes: note?.trim() || card.why_it_matters || '',
                related_topics:     card.related_topics || [],
                source_type:        'feed',
                tags:               [card.category, card.content_type].filter(Boolean),
              }}
            />
            {/* Read / Unread — desktop main row only */}
            {(onMarkRead || onMarkUnread) && (
              <button
                onClick={handleReadToggle}
                className={`hidden md:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all ${
                  isRead
                    ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30 hover:bg-slate-800/40 hover:text-slate-400 hover:border-slate-700/40"
                    : "text-slate-500 bg-slate-800/40 border-slate-700/40 hover:text-emerald-400 hover:bg-emerald-500/10 hover:border-emerald-500/30"
                }`}
              >
                {isRead
                  ? <><CheckCircleIcon className="w-3 h-3" /> Read</>
                  : <><CircleIcon className="w-3 h-3" /> Mark as Read</>
                }
              </button>
            )}
            {/* More toggle — mobile only, reveals tertiary actions */}
            {(onToggleQueue || onSaveNote || onDeleteNote || note || onMarkRead || onMarkUnread) && (
              <button
                onClick={() => setMoreOpen(o => !o)}
                className={`md:hidden ml-auto inline-flex items-center gap-1 px-1.5 py-0.5 rounded-lg text-[11px] font-medium border transition-all ${
                  moreOpen
                    ? "text-slate-300 bg-slate-800/60 border-slate-700/50"
                    : "text-slate-500/70 bg-transparent border-slate-700/20 hover:text-slate-300"
                }`}
              >
                <DotsIcon className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          {/* Tertiary row — mobile only, shown when More is open */}
          {moreOpen && (
            <div className="md:hidden flex items-center gap-1 flex-wrap mt-1.5 pt-1.5 border-t border-slate-800/40">
              {onToggleQueue && (
                <button
                  onClick={(e) => { e.stopPropagation(); onToggleQueue(card) }}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] font-medium border transition-all ${
                    isQueued
                      ? "text-amber-400 bg-amber-500/10 border-amber-500/30"
                      : "text-slate-500 bg-slate-800/20 border-slate-700/20 hover:text-amber-300 hover:bg-amber-500/10 hover:border-amber-500/30"
                  }`}
                >
                  <ClockIcon className="w-3 h-3" />
                  {isQueued ? "Queued" : "Read Later"}
                </button>
              )}
              {(onSaveNote || onDeleteNote || note) && (
                <button
                  onClick={() => setNoteOpen(o => !o)}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] font-medium border transition-all ${
                    noteOpen || hasNote
                      ? "text-amber-400 bg-amber-500/10 border-amber-500/30"
                      : "text-slate-500 bg-slate-800/20 border-slate-700/20 hover:text-amber-300 hover:bg-amber-500/10 hover:border-amber-500/30"
                  }`}
                >
                  <PencilIcon className="w-3 h-3" />
                  {hasNote ? "My note" : "Add note"}
                  {hasNote && !noteOpen && (
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400/70 flex-shrink-0" />
                  )}
                </button>
              )}
              {(onMarkRead || onMarkUnread) && (
                <button
                  onClick={handleReadToggle}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] font-medium border transition-all ${
                    isRead
                      ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
                      : "text-slate-500 bg-slate-800/20 border-slate-700/20 hover:text-emerald-400 hover:bg-emerald-500/10 hover:border-emerald-500/30"
                  }`}
                >
                  {isRead
                    ? <><CheckCircleIcon className="w-3 h-3" /> Read</>
                    : <><CircleIcon className="w-3 h-3" /> Mark as Read</>
                  }
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Note textarea — shown when Add note is toggled */}
      {noteOpen && (onSaveNote || onDeleteNote || note) && (
        <NoteArea draft={noteDraft} onChange={handleNoteChange} />
      )}

      {/* Related discussions */}
      <RelatedChats
        relatedChats={relatedChats}
        onLoadRelatedChats={onLoadRelatedChats}
        onOpenChat={onOpenChat}
      />
    </div>
  )
}

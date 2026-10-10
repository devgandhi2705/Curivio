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
 *   relatedChats         — list of linked chat sessions (null = not loaded)
 *   onLoadRelatedChats() — trigger lazy load of related chats
 *   onOpenChat(sessionId)— navigate to a specific chat session
 */
import { useState, useEffect, useRef } from "react"
import BookmarkButton from "../bookmarks/BookmarkButton.jsx"
import ShareButton from "../ShareButton.jsx"
import { m, AnimatePresence, presets } from "../../lib/motion.jsx"
import { useChangeCount } from "../../hooks/useChangeCount.js"

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

// ─── Image block ──────────────────────────────────────────────────────────────
// Hides itself entirely on load failure — these are arbitrary fetched URLs,
// no broken-image icon.

function ImageBlock({ url, sourceId }) {
  const [failed, setFailed] = useState(false)
  if (!url || failed) return null
  return (
    <div className="mx-3 md:mx-5 mb-2.5">
      <img
        src={url}
        alt="Illustrative image for this insight"
        loading="lazy"
        onError={() => setFailed(true)}
        className="w-full max-h-64 object-cover rounded-lg border border-slate-800/50"
      />
      {sourceId && <SourceTag sourceId={sourceId} className="mt-1 block" />}
    </div>
  )
}

// ─── Source-id tag ────────────────────────────────────────────────────────────
// Non-interactive label — source_id has no reliable mapping to a source_links[]
// entry in the data the frontend receives, so this never links anywhere.

function SourceTag({ sourceId, className = "" }) {
  if (!sourceId) return null
  return (
    <span className={`text-[10.5px] text-slate-500 ${className}`}>
      Source: {sourceId}
    </span>
  )
}

// ─── Block renderer ───────────────────────────────────────────────────────────
// Public API: renderBlock(type, content)
// Third param `key` is an implementation detail for list rendering.
// Fourth param `sourceId` renders a plain "Source: X" tag on every block type
// that carries one — inline in the header row for types that have one,
// trailing bottom-right otherwise. No reliable mapping to source_links[]
// exists (see SourceTag), so it's a label, never a link.

function renderBlock(type, content, key, sourceId) {
  const text = content || ""

  // image → fetched article image, hidden entirely on load failure
  if (type === "image") {
    return (
      <ImageBlock key={key} url={content || ""} sourceId={sourceId} />
    )
  }

  // ── 8 visually distinct types ──────────────────────────────────────────────

  // headline → section sub-heading
  if (type === "headline") {
    return (
      <div key={key} className="px-3 md:px-5 pt-3 pb-1">
        <p className="u-read-heading text-slate-100">{text}</p>
        <SourceTag sourceId={sourceId} className="mt-1 block text-right" />
      </div>
    )
  }

  // key_takeaway → highlighted callout box
  if (type === "key_takeaway") {
    return (
      <div key={key} className="mx-3 md:mx-5 mb-2.5">
        <div className="bg-blue-500/[0.07] border border-blue-500/20 rounded-lg px-3 py-2.5">
          <p className="u-read-body text-blue-200/90">{text}</p>
          <SourceTag sourceId={sourceId} className="mt-1 block text-right" />
        </div>
      </div>
    )
  }

  // example → bordered card
  if (type === "example") {
    return (
      <div key={key} className="mx-3 md:mx-5 mb-2.5">
        <p className="u-read-label text-slate-500 mb-1.5 px-0.5">For Example</p>
        <div className="border border-slate-700/40 rounded-lg bg-slate-800/20 px-3 py-2.5">
          <p className="u-read-body text-slate-300">{text}</p>
          <SourceTag sourceId={sourceId} className="mt-1 block text-right" />
        </div>
      </div>
    )
  }

  // timeline → dotted chronological list
  if (type === "timeline") {
    const items = text.split("\n").map(s => s.trim()).filter(Boolean)
    return (
      <div key={key} className="border-t border-slate-800/50">
        <div className="flex items-center gap-2 px-3 md:px-5 py-1.5 md:py-2">
          <ClockIcon className="w-3 h-3 text-slate-600" />
          <span className="u-read-label text-slate-500">Timeline</span>
          <SourceTag sourceId={sourceId} className="ml-auto" />
        </div>
        <div className="px-3 md:px-5 pb-2.5 space-y-1.5">
          {items.length > 0 ? items.map((item, j) => (
            <div key={j} className="flex gap-2.5 items-start">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-500 flex-shrink-0 mt-[10px]" />
              <p className="u-read-body text-slate-300">{item}</p>
            </div>
          )) : <p className="u-read-body text-slate-300">{text}</p>}
        </div>
      </div>
    )
  }

  // comparison → row-per-item layout
  if (type === "comparison") {
    const items = text.split("\n").map(s => s.trim()).filter(Boolean)
    return (
      <div key={key} className="border-t border-slate-800/50">
        <div className="flex items-center gap-2 px-3 md:px-5 py-1.5 md:py-2">
          <BookIcon className="w-3 h-3 text-slate-600" />
          <span className="u-read-label text-slate-500">Comparison</span>
          <SourceTag sourceId={sourceId} className="ml-auto" />
        </div>
        <div className="px-3 md:px-5 pb-2.5 space-y-1">
          {items.length > 1 ? items.map((item, j) => (
            <div key={j} className="bg-slate-800/25 rounded px-2.5 py-1.5">
              <p className="u-read-body text-slate-300">{item}</p>
            </div>
          )) : <p className="u-read-body text-slate-300">{text}</p>}
        </div>
      </div>
    )
  }

  // warning → amber caution block
  if (type === "warning") {
    return (
      <div key={key} className="mx-3 md:mx-5 mb-2.5">
        <div className="bg-amber-500/[0.07] border border-amber-500/25 rounded-lg px-3 py-2.5">
          <p className="u-read-label text-amber-500/80 mb-1.5">Caution</p>
          <p className="u-read-body text-amber-200/85">{text}</p>
          <SourceTag sourceId={sourceId} className="mt-1 block text-right" />
        </div>
      </div>
    )
  }

  // evidence → citation block with left rule
  if (type === "evidence") {
    return (
      <div key={key} className="border-t border-slate-800/50">
        <div className="flex items-center gap-2 px-3 md:px-5 py-1.5 md:py-2">
          <GlobeIcon className="w-3 h-3 text-slate-600" />
          <span className="u-read-label text-slate-500">Source</span>
          <SourceTag sourceId={sourceId} className="ml-auto" />
        </div>
        <div className="mx-3 md:mx-5 mb-2.5 border-l-2 border-slate-700/50 pl-2.5">
          <p className="u-read-quote text-slate-400">{text}</p>
        </div>
      </div>
    )
  }

  // reflection → closing italic block with top rule
  if (type === "reflection") {
    return (
      <div key={key} className="mx-3 md:mx-5 mb-3 mt-0.5 border-t border-slate-800/40 pt-2.5">
        <p className="u-read-quote text-slate-400">{text}</p>
        <SourceTag sourceId={sourceId} className="mt-1 block text-right" />
      </div>
    )
  }

  // ── Other named types ──────────────────────────────────────────────────────

  if (type === "mechanism") {
    return (
      <div key={key} className="mx-3 mb-2.5 md:mx-5 md:mb-3 flex gap-2.5">
        <div className="w-px flex-shrink-0 self-stretch rounded-full bg-indigo-500/35" />
        <div className="min-w-0 py-0.5">
          <p className="u-read-label text-indigo-400/75 mb-1.5">Hidden Mechanism</p>
          <p className="u-read-body text-slate-300">{text}</p>
          <SourceTag sourceId={sourceId} className="mt-1 block text-right" />
        </div>
      </div>
    )
  }

  if (type === "insight") {
    return (
      <div key={key} className="mx-3 mb-2.5 md:mx-5 md:mb-3 flex gap-2.5">
        <div className="w-px flex-shrink-0 self-stretch rounded-full bg-blue-500/35" />
        <div className="min-w-0 py-0.5">
          <p className="u-read-label text-blue-400/75 mb-1.5">Insight</p>
          <p className="u-read-body text-slate-300">{text}</p>
          <SourceTag sourceId={sourceId} className="mt-1 block text-right" />
        </div>
      </div>
    )
  }

  if (type === "step_list") {
    const steps = text.split("\n").map(s => s.replace(/^\d+\.\s*/, "").trim()).filter(Boolean)
    return (
      <div key={key} className="border-t border-slate-800/50">
        <div className="flex items-center gap-2 px-3 md:px-5 py-1.5 md:py-2">
          <BookIcon className="w-3 h-3 text-slate-600" />
          <span className="u-read-label text-slate-500">Steps</span>
          <SourceTag sourceId={sourceId} className="ml-auto" />
        </div>
        <div className="px-3 md:px-5 pb-2.5 space-y-1.5">
          {steps.length > 0 ? steps.map((step, j) => (
            <div key={j} className="flex gap-2.5 items-start">
              <span className="u-read-body font-semibold text-slate-500 flex-shrink-0 w-4 text-right tabular-nums">{j + 1}.</span>
              <p className="u-read-body text-slate-300">{step}</p>
            </div>
          )) : <p className="u-read-body text-slate-300">{text}</p>}
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
      <div className="flex items-center gap-2 px-3 md:px-5 py-1.5 md:py-2">
        <cfg.Icon className="w-3 h-3 text-slate-600" />
        <span className="u-read-label text-slate-500">{cfg.label}</span>
        <SourceTag sourceId={sourceId} className="ml-auto" />
      </div>
      <div className="px-3 md:px-5 pb-2.5 md:pb-3.5">
        <p className="u-read-body text-slate-300">{text}</p>
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

// Reading mode's reference sections start open where the spread has room
// (≥1024px, same breakpoint as index.css) and closed on phones.
const readerWide = () => window.matchMedia?.("(min-width: 1024px)").matches ?? true

// Phones: the row heading a Reading-mode reference section, inside the
// grouped card (.u-rc-ref in index.css). Its parts hide at ≥1024px, where
// `children` — the desktop heading — shows instead.
function RefRow({ icon, title, sub, count, open, onClick, className = "", children }) {
  return (
    <button type="button" onClick={onClick} aria-expanded={open} className={`u-rc-row ${className}`}>
      <span className="u-rc-tile lg:hidden" aria-hidden="true">{icon}</span>
      <span className="flex-1 min-w-0 lg:hidden">
        <span className="block text-[14px] font-medium leading-tight text-slate-200">{title}</span>
        {sub && <span className="block mt-1 truncate text-[12px] leading-tight text-slate-500">{sub}</span>}
      </span>
      {count > 0 && <span className="u-rc-count lg:hidden">{count}</span>}
      <span className={`u-rc-chev lg:hidden ${open ? "rotate-180" : ""}`} aria-hidden="true">
        <ChevronIcon className="w-3.5 h-3.5" />
      </span>
      {children}
    </button>
  )
}

// ─── Source section ───────────────────────────────────────────────────────────

// `aside`: Reading mode's side column — the full link list under a heading.
function SourceSection({ sourceLinks, cardTitle, aside = false }) {
  const [expanded, setExpanded] = useState(false)

  const valid = (sourceLinks ?? []).filter(s => _isValidSourceUrl(s?.url))

  if (!valid.length) {
    if ((sourceLinks ?? []).length > 0) {
      console.error("[InsightCard] source_links present but no valid URLs for card:", cardTitle, sourceLinks)
    }
    return null
  }

  const enriched = valid.map(s => ({ ...s, publisher: _extractPublisher(s.url, s.title) }))

  // Phones: a closed row (publishers, count) that folds open to the list.
  // ≥1024px: a plain heading and the list, always shown (index.css).
  if (aside) {
    const names = [...new Set(enriched.map(s => s.publisher))]
    return (
      <div>
        <p className="hidden lg:block u-read-label text-slate-500 mb-2">Sources</p>
        <RefRow icon={<ExternalLinkIcon className="w-3.5 h-3.5" />} title="Sources"
          sub={names.slice(0, 3).join(" · ") + (names.length > 3 ? ` +${names.length - 3}` : "")}
          count={enriched.length} open={expanded} onClick={() => setExpanded(o => !o)} className="lg:hidden" />
        <div className="u-rc-fold" data-open={expanded}>
          <div>
            <div className="space-y-0.5 px-2 pb-2 lg:p-0">
              {enriched.map((s, i) => (
                <a
                  key={i}
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-start gap-3 rounded-lg px-2.5 py-2 text-[13px] text-slate-300 hover:bg-white/[0.04] lg:gap-2 lg:rounded-none lg:px-0 lg:py-1.5 lg:text-[12.5px] lg:text-slate-400 lg:hover:bg-transparent leading-snug hover:text-slate-100 transition-colors"
                >
                  <ExternalLinkIcon className="order-last lg:order-first w-3 h-3 mt-0.5 flex-shrink-0 text-slate-600 group-hover:text-blue-400" />
                  <span className="min-w-0 flex-1">
                    <span className="block line-clamp-2">{s.title || s.publisher}</span>
                    <span className="block text-[11px] text-slate-600">{s.publisher}</span>
                  </span>
                </a>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="border-t border-slate-800/40">
      {/* Compact row — publisher pills + toggle */}
      <div className="px-3 md:px-5 pt-2 pb-1.5 flex items-center gap-2 flex-wrap">
        <span className="u-read-label text-slate-500 flex-shrink-0">
          Sources
        </span>
        {enriched.map((s, i) => (
          <span
            key={i}
            className="px-1.5 py-0.5 rounded text-[10.5px] font-medium text-slate-500 bg-slate-800/60 border border-slate-700/30"
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
        <div className="px-3 md:px-5 pb-2.5 space-y-0.5">
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
              <span className="text-[10px] text-slate-600 flex-shrink-0 ml-1">{s.publisher}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Inline note textarea (rendered below action bar when open) ───────────────

// No autoFocus: focusing on open pops the phone keyboard over the card.
function NoteArea({ draft, onChange, aside = false }) {
  return (
    <div className={aside ? "" : "px-3 py-2 md:px-5 md:py-3 border-t border-slate-800/80 bg-slate-800/20"}>
      {aside && <p className="u-read-label text-slate-500 mb-2">Your note</p>}
      <textarea
        className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-amber-500/40 focus:bg-slate-800/70 resize-none transition-colors"
        rows={aside ? 5 : 3}
        placeholder="Your thoughts on this card…"
        value={draft}
        onChange={onChange}
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

function RelatedChats({ relatedChats, onLoadRelatedChats, onOpenChat, aside = false }) {
  const [open, setOpen] = useState(() => aside && readerWide())

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
  const heading = (
    <span className="flex items-center gap-1.5">
      <ChatIcon className="w-3 h-3 text-slate-600" />
      <span className="text-[11px] font-medium text-slate-500">
        {relatedChats === null
          ? "Related discussions"
          : count === 0
            ? "No related discussions yet"
            : `${count} related discussion${count !== 1 ? "s" : ""}`}
      </span>
    </span>
  )
  const chevron = <ChevronIcon className={`w-3 h-3 text-slate-600 transition-transform ${open ? "rotate-180" : ""}`} />
  const body = (
    <div className={aside ? "px-2 pb-2 space-y-0.5 lg:p-0 lg:pt-1.5 lg:space-y-1" : "px-3 pb-2 md:px-5 md:pb-3 space-y-1.5"}>
      {relatedChats === null ? (
        <p className={`text-[11px] text-slate-600 animate-pulse ${aside ? "px-2.5 py-1 lg:p-0" : ""}`}>Loading…</p>
      ) : relatedChats.length === 0 ? (
        <p className={`text-[11px] text-slate-600 ${aside ? "px-2.5 py-1 lg:p-0" : ""}`}>Start a chat from this card to see it here.</p>
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
  )

  // Reading mode: the phone row folds the list open; ≥1024px keeps the plain heading.
  if (aside) {
    return (
      <div>
        <RefRow icon={<ChatIcon className="w-3.5 h-3.5" />} title="Discussions" count={count} open={open} onClick={handleToggle}
          sub={relatedChats === null ? "Loading…"
            : count === 0 ? "None yet · tap Ask to start one"
            : relatedChats[0].session_title || "Untitled session"}
          className="w-full flex items-center justify-between py-1 transition-colors text-left">
          <span className="hidden lg:flex w-full items-center justify-between">{heading}{chevron}</span>
        </RefRow>
        <div className="u-rc-fold" data-open={open}><div>{body}</div></div>
      </div>
    )
  }

  return (
    <div className="border-t border-slate-800/50">
      <button
        onClick={handleToggle}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-3 py-1.5 md:px-5 hover:bg-slate-800/20 transition-colors text-left"
      >
        {heading}
        {chevron}
      </button>
      {open && body}
    </div>
  )
}

// ─── Reading-mode rail action ─────────────────────────────────────────────────

const RAIL_TONE = {
  emerald: "text-emerald-400",
  amber:   "text-amber-400",
}

// `short`: the label under the icon in the phone action row (index.css).
function RailAction({ icon, label, short, onClick, active = false, tone, disabled = false, className = "" }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={tone ? active : undefined}
      aria-label={short ? label : undefined}
      title={disabled ? "Requires an internet connection" : undefined}
      className={`u-rc-act ${active && tone ? RAIL_TONE[tone] : "text-slate-400 hover:text-slate-100"} disabled:opacity-40 disabled:cursor-not-allowed ${className}`}
    >
      {icon}
      {short
        ? <><span className="lg:hidden">{short}</span><span className="hidden lg:inline">{label}</span></>
        : <span>{label}</span>}
    </button>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function InsightCard({
  card,
  isRead = false,
  onMarkRead,
  onMarkUnread,
  onAskAbout,
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
  day         = null,
  articleKey  = null,
  readOnly    = false,
  // Notes-only feed opens the note inline: the whole point of that view is
  // reading notes, so making the user click the pencil on every card is noise.
  defaultNoteOpen = false,
  // Reading mode: the slide is the page, so no card chrome — and no Share there.
  bare        = false,
  hideShare   = false,
  eyebrow     = null,   // Reading mode: "Article 1 of 4", shown in the left column
}) {

  const type   = TYPE_CONFIG[card.content_type] || TYPE_CONFIG.news

  const hasChatActions = !readOnly && (onAskAbout || onExplainSimply || onToggleQueue)
  // The note pencil lives in the bottom action bar, so the bar has to render
  // whenever the card can hold a note — otherwise a card given only note
  // handlers (NotesOnlyFeed) draws no bar and the note is unreachable.
  const hasNoteActions = !readOnly && Boolean(onSaveNote || onDeleteNote || note)
  const shareResourceId = projectId && day != null
    ? `${projectId}/${day}${articleKey ? `/${articleKey}` : ''}`
    : null

  const [noteOpen, setNoteOpen] = useState(defaultNoteOpen)
  const [noteDraft, setNoteDraft] = useState(note ?? "")
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

  // One-shot reactions keyed on real changes — never on first render.
  const readChanges  = useChangeCount(isRead)
  const queueChanges = useChangeCount(isQueued)

  function handleReadToggle(e) {
    e.stopPropagation()
    if (isRead) onMarkUnread?.()
    else onMarkRead?.()
  }

  const bookmarkData = {
    title:              card.title,
    summary:            card.summary || '',
    content_type:       card.content_type === 'curiosity' ? 'curiosity' : 'feed_article',
    source_url:         card.source_links?.[0]?.url || '',
    project_id:          projectId,
    project_name:        projectName,
    ai_generated_notes:  note?.trim() || card.why_it_matters || '',
    related_topics:     card.related_topics || [],
    source_type:        'feed',
    tags:                [card.category, card.content_type].filter(Boolean),
    retrieval_metadata:  { insight_id: day ?? null, article_key: articleKey || '' },
  }

  // Content blocks — new schema; fallback to legacy flat fields
  const blocksEl = (
    card.blocks?.length > 0 ? (
      card.blocks.map((b, i) => renderBlock(b.type || "", b.content || "", i, b.source_id))
    ) : (
      <>
        {card.educational_explanation && (
          <div className="border-t border-slate-800/50">
            <div className="flex items-center gap-2 px-3 md:px-5 py-1.5 md:py-2">
              <LightbulbIcon className="w-3 h-3 text-slate-600" />
              <span className="u-read-label text-slate-500">
                {card.content_type === "educational" ? "Deep Dive" : "Why This Works"}
              </span>
            </div>
            <div className="px-3 md:px-5 pb-2.5 md:pb-3.5">
              <p className="u-read-body text-slate-300">{card.educational_explanation}</p>
            </div>
          </div>
        )}
        {card.why_it_matters && (
          <div className="mx-3 mb-2.5 md:mx-5 md:mb-3 flex gap-2.5">
            <div className="w-px flex-shrink-0 self-stretch rounded-full bg-indigo-500/35" />
            <div className="min-w-0 py-0.5">
              <p className="u-read-label text-indigo-400/75 mb-1.5">
                Hidden Mechanism
              </p>
              <p className="u-read-body text-slate-300">{card.why_it_matters}</p>
            </div>
          </div>
        )}
      </>
    )
  )

  // Reading mode on a wide screen is a spread, not a card: the left column
  // holds what the article is and what you can do with it, the centre holds
  // only what you read, the right holds reference (sources, note, discussions).
  // index.css (.u-reader-card) stacks the same pieces into one column on
  // narrow screens, in the card's usual order.
  if (bare) {
    const canRead = !readOnly && (onMarkRead || onMarkUnread)
    const showNote = !readOnly && (noteOpen || hasNote) && (onSaveNote || onDeleteNote || note)
    return (
      <article className="u-reader-card">
        <aside className="u-rc-rail">
          {eyebrow && (
            <p className="u-rc-eyebrow u-read-label text-slate-500 flex items-center gap-2">
              {eyebrow}
              {/* Phones; the rail says "Saved for offline" under its actions */}
              {!readOnly && isOfflineAvailable && (
                <span className="lg:hidden inline-flex items-center gap-1.5 text-slate-600">
                  <span aria-hidden="true">·</span><CloudCheckIcon className="w-3 h-3" />Offline
                </span>
              )}
            </p>
          )}
          <div className="u-rc-meta flex gap-1.5">
            <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wide border ${type.labelColor}`}>
              {type.label}
            </span>
            {card.category && <span className="text-[12px] leading-snug text-slate-500">{card.category}</span>}
          </div>
          {!readOnly && (
            <div className="u-rc-actions">
              {canRead && (
                <RailAction onClick={handleReadToggle} active={isRead} tone="emerald"
                  icon={isRead ? <CheckCircleIcon className={`w-3.5 h-3.5 ${readChanges ? "u-stamp" : ""}`} /> : <CircleIcon className="w-3.5 h-3.5" />}
                  label={isRead ? "Read" : "Mark as read"} short={isRead ? "Read" : "Mark read"} />
              )}
              <div className="u-rc-bm"><BookmarkButton label bookmarkData={bookmarkData} /></div>
              {onToggleQueue && (
                <RailAction onClick={(e) => { e.stopPropagation(); onToggleQueue(card) }} active={isQueued} tone="amber"
                  icon={<ClockIcon key={queueChanges} className={`w-3.5 h-3.5 ${queueChanges ? "u-spin-once" : ""}`} />}
                  label={isQueued ? "In Read later" : "Read later"} short="Later" />
              )}
              {(onSaveNote || onDeleteNote || note) && (
                <RailAction onClick={() => setNoteOpen(o => !o)} active={noteOpen || hasNote} tone="amber"
                  icon={<PencilIcon className="w-3.5 h-3.5" />} label={hasNote ? "Your note" : "Add note"} short="Note" />
              )}
              {/* Phones get Ask / Explain from Reading mode's bottom dock instead (.u-rc-ai) */}
              {(onAskAbout || onExplainSimply) && <span className="u-rc-sep u-rc-ai" aria-hidden="true" />}
              {onAskAbout && (
                <RailAction onClick={() => onAskAbout(card)} disabled={offlineDisabled} className="u-rc-ai"
                  icon={<ChatIcon className="w-3.5 h-3.5" />} label="Ask about this" />
              )}
              {onExplainSimply && (
                <RailAction onClick={() => onExplainSimply(card)} disabled={offlineDisabled} className="u-rc-ai"
                  icon={<LightbulbIcon className="w-3.5 h-3.5" />} label="Explain simply" />
              )}
              {isOfflineAvailable && (
                <p className="u-rc-offline flex items-center gap-2 px-2.5 pt-1 text-[11.5px] text-slate-600">
                  <CloudCheckIcon className="w-3.5 h-3.5" /> Saved for offline
                </p>
              )}
            </div>
          )}
        </aside>

        <div className="u-rc-main">
          <h3 className="u-read-title text-slate-100 px-3 md:px-5">{card.title}</h3>
          <div className="px-3 md:px-5 pt-3 pb-2 md:pb-3">
            <p className="u-read-lead text-slate-300">{card.summary}</p>
          </div>
          {blocksEl}
        </div>

        <aside className="u-rc-aside">
          {/* One grouped card on phones; ≥1024px it dissolves (display: contents) */}
          <div className="u-rc-ref">
            <div className="u-rc-sources"><SourceSection aside sourceLinks={card.source_links} cardTitle={card.title} /></div>
            <div className="u-rc-related">
              <RelatedChats aside relatedChats={relatedChats} onLoadRelatedChats={onLoadRelatedChats} onOpenChat={onOpenChat} />
            </div>
          </div>
          {showNote && (
            <div className="u-rc-note"><NoteArea aside draft={noteDraft} onChange={handleNoteChange} /></div>
          )}
        </aside>
      </article>
    )
  }

  return (
    <div className={`u-read-card u-reveal relative rounded-2xl border overflow-hidden flex flex-col ${
      type.borderTop
    } ${card.content_type === "curiosity"
        ? "bg-amber-950/[0.10] border-amber-900/20"
        : `bg-slate-900/50 ${isRead ? "border-slate-800/50 opacity-75" : "border-slate-800"}`
    }`}>

      {/* Card header */}
      <div className="px-3 pt-3 pb-1.5 md:px-5 md:pt-4 md:pb-3 flex items-start justify-between gap-2.5">
        <div className="flex items-start gap-2 md:gap-3 min-w-0">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap mb-1.5">
              <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wide border ${type.labelColor}`}>
                {type.label}
              </span>
              {card.category && (
                <span className="inline-flex items-center text-[11px] text-slate-500 leading-none">
                  {card.category}
                </span>
              )}
            </div>
            <h3 className="u-read-title text-slate-100">{card.title}</h3>
          </div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {isOfflineAvailable && (
            <CloudCheckIcon className="w-3 h-3 text-slate-600" />
          )}
          {!readOnly && (
            <BookmarkButton
              className="w-7 h-7 justify-center p-0 [&>svg]:w-3 [&>svg]:h-3"
              bookmarkData={bookmarkData}
            />
          )}
          {shareResourceId && !hideShare && (
            <ShareButton
              type="feed"
              resourceId={shareResourceId}
              shareTitle={card.title || ""}
              shareText={card.summary || ""}
              buttonClassName="w-7 h-7 justify-center p-0 [&_svg]:w-3 [&_svg]:h-3"
            />
          )}
        </div>
      </div>

      {/* Summary */}
      <div className="px-3 pb-2 md:px-5 md:pb-3">
        <p className="u-read-lead text-slate-300">{card.summary}</p>
      </div>

      {/* Content blocks — new schema; fallback to legacy flat fields */}
      {blocksEl}

      {/* Source section — validated, two-tier: publisher pills + expandable URLs */}
      <SourceSection sourceLinks={card.source_links} cardTitle={card.title} />

      {/* Bottom action bar */}
      {(hasChatActions || hasNoteActions || (!readOnly && (onMarkRead || onMarkUnread))) && (
        <div className="border-t border-slate-800/50 px-2.5 md:px-5 py-1.5 md:py-2.5">
          {/* Primary + secondary row — always visible */}
          <div className="flex items-center gap-1 md:gap-1.5 flex-wrap">
            {/* PRIMARY: Ask About */}
            {!readOnly && onAskAbout && (
              <button
                onClick={() => onAskAbout(card)}
                disabled={offlineDisabled}
                title={offlineDisabled ? "Requires an internet connection" : undefined}
                className="u-btn-2 inline-flex items-center gap-1 md:gap-1.5 px-2 py-0.5 md:px-2.5 md:py-1 rounded-lg text-[11px] font-medium text-slate-400 hover:text-blue-300 bg-slate-800/20 hover:bg-blue-500/10 border border-slate-700/20 hover:border-blue-500/30 md:bg-slate-800/40 md:border-slate-700/40 transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-slate-400 disabled:hover:bg-slate-800/20 disabled:hover:border-slate-700/20"
              >
                <ChatIcon className="w-3 h-3" />
                Ask About
              </button>
            )}
            {/* PRIMARY: Explain Simply */}
            {!readOnly && onExplainSimply && (
              <button
                onClick={() => onExplainSimply(card)}
                disabled={offlineDisabled}
                title={offlineDisabled ? "Requires an internet connection" : undefined}
                className="u-btn-2 inline-flex items-center gap-1 md:gap-1.5 px-2 py-0.5 md:px-2.5 md:py-1 rounded-lg text-[11px] font-medium text-slate-400 hover:text-amber-300 bg-slate-800/20 hover:bg-amber-500/10 border border-slate-700/20 hover:border-amber-500/30 md:bg-slate-800/40 md:border-slate-700/40 transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-slate-400 disabled:hover:bg-slate-800/20 disabled:hover:border-slate-700/20"
              >
                <LightbulbIcon className="w-3 h-3" />
                Explain Simply
              </button>
            )}
            <div className="ml-auto flex items-center gap-1 md:gap-1.5">
            {/* Read Later — always visible, icon-only */}
            {!readOnly && onToggleQueue && (
              <div className="relative group">
                <button
                  onClick={(e) => { e.stopPropagation(); onToggleQueue(card) }}
                  aria-label={isQueued ? "Queued" : "Read Later"}
                  title={isQueued ? "Queued" : "Read Later"}
                  className={`inline-flex w-7 h-7 items-center justify-center p-0 rounded-lg border transition-all ${
                    isQueued
                      ? "text-amber-400 bg-amber-500/10 border-amber-500/30 hover:bg-slate-800/40 hover:text-slate-400 hover:border-slate-700/40"
                      : "text-slate-500 bg-slate-800/40 border-slate-700/40 hover:text-amber-300 hover:bg-amber-500/10 hover:border-amber-500/30"
                  }`}
                >
                  <ClockIcon key={queueChanges} className={`w-3 h-3 ${queueChanges ? "u-spin-once" : ""}`} />
                </button>
                <span className="pointer-events-none absolute right-0 bottom-full z-20 mb-1 whitespace-nowrap rounded bg-slate-800 px-2 py-1 text-[10px] text-slate-200 opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  {isQueued ? "Queued" : "Read Later"}
                </span>
              </div>
            )}
            {/* Add note — always visible, icon-only */}
            {!readOnly && (onSaveNote || onDeleteNote || note) && (
              <div className="relative group">
                <button
                  onClick={() => setNoteOpen(o => !o)}
                  aria-label={hasNote ? "My note" : "Add note"}
                  title={hasNote ? "My note" : "Add note"}
                  className={`inline-flex w-7 h-7 items-center justify-center p-0 rounded-lg text-[11px] font-medium border transition-all ${
                    noteOpen || hasNote
                      ? "text-amber-400 bg-amber-500/10 border-amber-500/30"
                      : "text-slate-500 bg-slate-800/40 border-slate-700/40 hover:text-amber-300 hover:bg-amber-500/10 hover:border-amber-500/30"
                  }`}
                >
                  <PencilIcon className="w-3 h-3" />
                  {hasNote && !noteOpen && (
                    <span className="absolute right-1 top-1 w-1.5 h-1.5 rounded-full bg-amber-400/70" />
                  )}
                </button>
                <span className="pointer-events-none absolute right-0 bottom-full z-20 mb-1 whitespace-nowrap rounded bg-slate-800 px-2 py-1 text-[10px] text-slate-200 opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  {hasNote ? "My note" : "Add note"}
                </span>
              </div>
            )}
            {/* Read / Unread — desktop main row only */}
            {!readOnly && (onMarkRead || onMarkUnread) && (
              <div className="relative group">
                <button
                  onClick={handleReadToggle}
                  aria-label={isRead ? "Read" : "Mark as Read"}
                  title={isRead ? "Read" : "Mark as Read"}
                  className={`inline-flex w-7 h-7 items-center justify-center p-0 rounded-lg border transition-all ${
                    isRead
                      ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30 hover:bg-slate-800/40 hover:text-slate-400 hover:border-slate-700/40"
                      : "text-slate-500 bg-slate-800/40 border-slate-700/40 hover:text-emerald-400 hover:bg-emerald-500/10 hover:border-emerald-500/30"
                  }`}
                >
                  {isRead
                    ? <CheckCircleIcon className={`w-3 h-3 ${readChanges ? "u-stamp" : ""}`} />
                    : <CircleIcon className="w-3 h-3" />
                  }
                </button>
                <span className="pointer-events-none absolute right-0 bottom-full z-20 mb-1 whitespace-nowrap rounded bg-slate-800 px-2 py-1 text-[10px] text-slate-200 opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  {isRead ? "Read" : "Mark as Read"}
                </span>
              </div>
            )}
            </div>
          </div>
        </div>
      )}

      {/* Note textarea — shown when Add note is toggled */}
      <AnimatePresence initial={false}>
        {noteOpen && (onSaveNote || onDeleteNote || note) && (
          <m.div key="note" {...presets.collapse}>
            <NoteArea draft={noteDraft} onChange={handleNoteChange} />
          </m.div>
        )}
      </AnimatePresence>

      {/* Related discussions */}
      <RelatedChats
        relatedChats={relatedChats}
        onLoadRelatedChats={onLoadRelatedChats}
        onOpenChat={onOpenChat}
      />
    </div>
  )
}

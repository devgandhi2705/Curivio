import { useState, useRef, useEffect, useMemo } from "react"
import BookmarkButton from "../bookmarks/BookmarkButton.jsx"
import MessageText from "../shared/MarkdownText.jsx"
import { normalizeResponse, cleanContent } from "../shared/responseAdapter.js"
import { fetchDocumentText, fetchAttachmentBlob } from "../../api/chat.js"

// ─── Human-paced text reveal ─────────────────────────────────────────────────
// `text` already only grows (it's the accumulated stream buffer from
// ChatWorkspace) — this just decouples how fast it's REVEALED on screen from
// how fast/chunky it ARRIVES over SSE, so a big chunk still types out instead
// of popping in whole. `active` false (history reload, stream done, non-
// streaming message) shows the full string immediately, no animation.
function useDrip(text, active, { charsPerTick = 2, intervalMs = 22 } = {}) {
  const [revealed, setRevealed] = useState(active ? "" : text)
  const textRef = useRef(text)
  textRef.current = text

  useEffect(() => {
    if (!active) {
      setRevealed(textRef.current)
      return
    }
    const id = setInterval(() => {
      setRevealed(prev => {
        const full = textRef.current
        if (!full.startsWith(prev)) return full // text reset/edited underneath — snap instead of garbling
        if (prev.length >= full.length) return prev
        const backlog = full.length - prev.length
        const step = Math.max(charsPerTick, Math.ceil(backlog / 20)) // catch up fast if a big chunk landed at once
        return full.slice(0, prev.length + step)
      })
    }, intervalMs)
    return () => clearInterval(id)
  }, [active, charsPerTick, intervalMs])

  return active ? revealed : text
}

// Thinking panel reads noticeably slower than the answer text/tool query/code.
const THINKING_DRIP = { charsPerTick: 1, intervalMs: 40 }

function DrippedMessageText({ text, streaming, variant, className, dripOptions, sources }) {
  return <MessageText text={useDrip(text, streaming, dripOptions)} variant={variant} className={className} sources={sources} />
}

// ─── Structured response metadata ───────────────────────────────────────────

const TYPE_META = {
  chat_explanation:  { label: "Explanation",       accent: "blue"    },
  comparison:        { label: "Comparison",        accent: "violet"  },
  roadmap:           { label: "Learning Roadmap",  accent: "emerald" },
  deep_research:     { label: "Deep Research",     accent: "violet"  },
  industry_analysis: { label: "Industry Analysis", accent: "amber"   },
  feed_insight:      { label: "Feed Insight",      accent: "cyan"    },
}

const ACCENT = {
  blue:    { border: "border-blue-500",    text: "text-blue-400",    bg: "bg-blue-500/10"    },
  violet:  { border: "border-violet-500",  text: "text-violet-400",  bg: "bg-violet-500/10"  },
  emerald: { border: "border-emerald-500", text: "text-emerald-400", bg: "bg-emerald-500/10" },
  amber:   { border: "border-amber-500",   text: "text-amber-400",   bg: "bg-amber-500/10"   },
  cyan:    { border: "border-cyan-500",    text: "text-cyan-400",    bg: "bg-cyan-500/10"    },
}

const RESOURCE_TYPE_CONFIG = {
  article:  { label: "Article",  color: "bg-blue-900/50 text-blue-300 border-blue-800/50"            },
  github:   { label: "GitHub",   color: "bg-slate-800 text-slate-300 border-slate-700"               },
  arxiv:    { label: "arXiv",    color: "bg-red-900/50 text-red-300 border-red-800/50"               },
  official: { label: "Official", color: "bg-emerald-900/50 text-emerald-300 border-emerald-800/50"   },
  report:   { label: "Report",   color: "bg-amber-900/50 text-amber-300 border-amber-800/50"         },
}

const ACTION_LABELS = {
  show_repos:         { label: "Repos found",     color: "bg-emerald-900/60 text-emerald-300 border-emerald-800/60" },
  learning_roadmap:   { label: "Roadmap",          color: "bg-blue-900/60 text-blue-300 border-blue-800/60"         },
  compare:            { label: "Comparison",       color: "bg-violet-900/60 text-violet-300 border-violet-800/60"   },
  explain_simply:     { label: "Simplified",       color: "bg-amber-900/60 text-amber-300 border-amber-800/60"      },
  find_tutorials:     { label: "Tutorials found",  color: "bg-cyan-900/60 text-cyan-300 border-cyan-800/60"         },
  beginner_resources: { label: "Beginner guide",   color: "bg-teal-900/60 text-teal-300 border-teal-800/60"         },
}

// ─── Structured response components ─────────────────────────────────────────

function StreamingCursor() {
  return <span className="chat-stream-cursor ml-0.5 inline-block h-4 w-[2px] align-text-bottom" />
}

// Chat-R17 / Phase P: fillers shown ONLY before any real status/tool/thinking/
// content signal has arrived (see `active` below) — deliberately don't claim a
// specific action (no "Searching…", no "Analyzing…") since no tool decision has
// been made yet at this point in the turn. Phase P replaced the six sentence-
// length phrases with this single-word list, rendered as "{Word}…"; the cycling
// mechanism, its random 800-2200ms interval, and the hard rule that real
// content pre-empts instantly are all unchanged from Chat-R17.
const _FILLER_WORDS = [
  "Accomplishing", "Actioning", "Actualizing", "Architecting", "Baking",
  "Beaming", "Beboppin'", "Befuddling", "Billowing", "Blanching",
  "Bloviating", "Boogieing", "Boondoggling", "Booping", "Bootstrapping",
  "Brewing", "Bunning", "Burrowing", "Calculating", "Canoodling",
  "Caramelizing", "Cascading", "Catapulting", "Cerebrating", "Channeling",
  "Channelling", "Choreographing", "Churning", "Clauding", "Coalescing",
  "Cogitating", "Combobulating", "Composing", "Computing", "Concocting",
  "Considering", "Contemplating", "Cooking", "Crafting", "Creating",
  "Crunching", "Crystallizing", "Cultivating", "Deciphering", "Deliberating",
  "Determining", "Dilly-dallying", "Discombobulating", "Doing", "Doodling",
  "Drizzling", "Ebbing", "Effecting", "Elucidating", "Embellishing",
  "Enchanting", "Envisioning", "Evaporating", "Fermenting", "Fiddle-faddling",
  "Finagling", "Flambéing", "Flibbertigibbeting", "Flowing", "Flummoxing",
  "Fluttering", "Forging", "Forming", "Frolicking", "Frosting",
  "Gallivanting", "Galloping", "Garnishing", "Generating", "Gesticulating",
  "Germinating", "Gitifying", "Grooving", "Gusting", "Harmonizing",
  "Hashing", "Hatching", "Herding", "Honking", "Hullaballooing",
  "Hyperspacing", "Ideating", "Imagining", "Improvising", "Incubating",
  "Inferring", "Infusing", "Ionizing", "Jitterbugging", "Julienning",
  "Kneading", "Leavening", "Levitating", "Lollygagging", "Manifesting",
  "Marinating", "Meandering", "Metamorphosing", "Misting", "Moonwalking",
  "Moseying", "Mulling", "Mustering", "Musing", "Nebulizing",
  "Nesting", "Newspapering", "Noodling", "Nucleating", "Orbiting",
  "Orchestrating", "Osmosing", "Perambulating", "Percolating", "Perusing",
  "Philosophising", "Photosynthesizing", "Pollinating", "Pondering", "Pontificating",
  "Pouncing", "Precipitating", "Prestidigitating", "Processing", "Proofing",
  "Propagating", "Puttering", "Puzzling", "Quantumizing", "Razzle-dazzling",
  "Razzmatazzing", "Recombobulating", "Reticulating", "Roosting", "Ruminating",
  "Sautéing", "Scampering", "Schlepping", "Scurrying", "Seasoning",
  "Shenaniganing", "Shimmying", "Simmering", "Skedaddling", "Sketching",
  "Slithering", "Smooshing", "Sock-hopping", "Spelunking", "Spinning",
  "Sprouting", "Stewing", "Sublimating", "Swirling", "Swooping",
  "Symbioting", "Synthesizing", "Tempering", "Thinking", "Thundering",
  "Tinkering", "Tomfoolering", "Topsy-turvying", "Transfiguring", "Transmuting",
  "Twisting", "Undulating", "Unfurling", "Unravelling", "Vibing",
  "Waddling", "Wandering", "Warping", "Whatchamacalliting", "Whirlpooling",
  "Whirring", "Whisking", "Wibbling", "Working", "Wrangling",
  "Zesting", "Zigzagging",
]

function _shuffled(arr) {
  const a = [...arr]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

// Chat-R17: self-cycling filler text for the genuinely-silent pre-content
// window. `active` is false the instant any real signal exists (statusMsg) —
// StreamingDots itself also unmounts the instant the parent's blocks[]/
// hasVisibleContent gate flips (any real chunk/thinking/tool_start event
// updates blocks[] in the same tick, per ChatWorkspace.jsx's onChunk/
// onThinking/onStatus handlers), so React's own unmount cleanup clears the
// pending timer — no manual coordination with those handlers needed, and no
// stray timer can ever fire after real content starts. Never delays real
// content: `label` below reads `statusMsg` directly on every render,
// independent of whatever the timer last set — there's no minimum display
// duration and no queued transition.
function _useCyclingFiller(active) {
  const queueRef = useRef(null)
  if (queueRef.current === null) queueRef.current = _shuffled(_FILLER_WORDS)
  const idxRef = useRef(0)
  const [phrase, setPhrase] = useState(() => queueRef.current[0])

  useEffect(() => {
    if (!active) return
    // 1600-4400ms, randomized per step so each filler word has time to land.
    const delay = 1600 + Math.random() * 2800
    const timer = setTimeout(() => {
      idxRef.current += 1
      if (idxRef.current >= queueRef.current.length) {
        queueRef.current = _shuffled(_FILLER_WORDS)
        idxRef.current = 0
      }
      setPhrase(queueRef.current[idxRef.current])
    }, delay)
    return () => clearTimeout(timer)
  }, [active, phrase])

  return phrase
}

function StreamingDots({ statusMsg }) {
  const active = !statusMsg
  const filler = _useCyclingFiller(active)

  // Phase P: the outgoing word is kept for one cycle so it can fade OUT while
  // the incoming word fades IN — a real crossfade, not a swap. Both sit in the
  // same CSS grid cell (gridArea "1/1"), so they overlap instead of stacking
  // and the box sizes itself to the wider of the two. The outgoing layer is
  // replaced on the next change rather than cleared on a timer: it has already
  // animated to opacity 0 and holds there (`forwards`), so no extra timer is
  // needed to hide it.
  const prevRef = useRef(null)
  const shownRef = useRef(filler)
  if (shownRef.current !== filler) {
    prevRef.current = shownRef.current
    shownRef.current = filler
  }

  // Real status text pre-empts the filler immediately and is rendered with no
  // animation at all — the Chat-R17 constraint that real content is never
  // delayed by the placeholder is a hard rule, and a crossfade here would
  // delay it by exactly the fade duration.
  if (statusMsg) {
    return (
      <p className="text-[14px] px-1 w-fit" style={{ color: "var(--dk-accent)" }}>{statusMsg}</p>
    )
  }
  if (!filler) return null

  return (
    <p className="text-[14px] px-1 w-fit grid" style={{ color: "var(--dk-accent)" }}>
      {prevRef.current ? (
        <span
          key={`out-${prevRef.current}`}
          className="chat-filler-out"
          style={{ gridArea: "1 / 1" }}
        >{prevRef.current}…</span>
      ) : null}
      <span
        key={`in-${filler}`}
        className="chat-filler-in"
        style={{ gridArea: "1 / 1" }}
      >{filler}…</span>
    </p>
  )
}

function SummaryCard({ title, summary, accentKey }) {
  const acc = ACCENT[accentKey] ?? ACCENT.blue
  return (
    <div className={`border-l-4 ${acc.border} pl-4 py-3 mb-4 sm:mb-6 rounded-r-lg ${acc.bg}`}>
      <h3 className={`font-semibold text-[14.5px] sm:text-[15.5px] leading-snug mb-2 ${acc.text}`}>{title}</h3>
      {summary && <p className="text-slate-300 text-[13.5px] sm:text-[14px] leading-[1.68] sm:leading-[1.72]">{summary}</p>}
    </div>
  )
}

function SectionBlock({ section }) {
  const [collapsed, setCollapsed] = useState(false)
  const isHigh = section.importance === "high"

  return (
    <div className="mb-4 sm:mb-6">
      <button
        className="w-full flex items-center justify-between text-left group mb-2"
        onClick={() => section.collapsible && setCollapsed(c => !c)}
        style={{ cursor: section.collapsible ? "pointer" : "default" }}
      >
        <h4 className={`font-semibold text-[13px] sm:text-[13.5px] leading-snug ${isHigh ? "text-slate-100" : "text-slate-300"}`}>
          {section.title}
        </h4>
        {section.collapsible && (
          <svg
            className={`w-3.5 h-3.5 text-slate-500 transition-transform ${collapsed ? "" : "rotate-180"}`}
            viewBox="0 0 20 20" fill="currentColor"
          >
            <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
          </svg>
        )}
      </button>
      {!collapsed && (
        <div className="text-[13.5px] sm:text-[14.5px] leading-[1.68] sm:leading-[1.72]">
          <MessageText text={section.content} />
        </div>
      )}
    </div>
  )
}

function KeyTakeawaysList({ items }) {
  if (!items?.length) return null
  return (
    <div className="mt-6 pt-5 border-t border-slate-700/50">
      <h4 className="text-[10.5px] font-semibold uppercase tracking-widest text-slate-500 mb-3">Key Takeaways</h4>
      <ul className="space-y-2.5">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2.5 text-[13.5px] sm:text-[14px] text-slate-300 leading-[1.68] sm:leading-[1.7]">
            <span className="text-blue-400/60 flex-shrink-0 mt-[3px] text-[13px] select-none">•</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ResourceLinksPanel({ resources }) {
  if (!resources?.length) return null
  return (
    <div className="mt-6 pt-5 border-t border-slate-700/50">
      <h4 className="text-[10.5px] font-semibold uppercase tracking-widest text-slate-500 mb-3">Resources</h4>
      <div className="flex flex-col gap-2">
        {resources.map((r, i) => {
          const conf = RESOURCE_TYPE_CONFIG[r.type] ?? RESOURCE_TYPE_CONFIG.article
          return (
            <a
              key={i}
              href={r.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2.5 p-2.5 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 hover:bg-slate-800/70 transition-all group"
            >
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium border flex-shrink-0 ${conf.color}`}>
                {conf.label}
              </span>
              <span className="text-[13.5px] text-slate-400 group-hover:text-slate-200 transition-colors truncate flex-1 leading-snug">
                {r.title}
              </span>
              <LinkIcon />
            </a>
          )
        })}
      </div>
    </div>
  )
}

function NextTopicsChips({ topics }) {
  if (!topics?.length) return null
  return (
    <div className="mt-6 pt-5 border-t border-slate-700/50">
      <h4 className="text-[10.5px] font-semibold uppercase tracking-widest text-slate-500 mb-3">Explore Next</h4>
      <div className="flex flex-wrap gap-2">
        {topics.map((t, i) => (
          <span
            key={i}
            className="px-3 py-1 rounded-full text-xs font-medium bg-slate-800 border border-slate-700 text-slate-300 hover:border-blue-500/50 hover:text-blue-300 transition-colors cursor-default"
          >
            {t}
          </span>
        ))}
      </div>
    </div>
  )
}

function StructuredResponseRenderer({ sr }) {
  const meta = TYPE_META[sr.response_type] ?? TYPE_META.chat_explanation
  return (
    <div>
      <SummaryCard title={sr.title} summary={sr.summary} accentKey={meta.accent} />
      <div>
        {(sr.sections || []).map((s, i) => (
          <SectionBlock key={i} section={s} />
        ))}
      </div>
      <KeyTakeawaysList items={sr.key_takeaways} />
      <ResourceLinksPanel resources={sr.resources} />
      <NextTopicsChips topics={sr.next_topics} />
    </div>
  )
}

// ─── Export helper ────────────────────────────────────────────────────────────

function exportAsMarkdown(sr) {
  const lines = [`# ${sr.title || "Response"}`, "", sr.summary || "", ""]
  for (const s of (sr.sections || [])) {
    lines.push(`## ${s.title}`, "", s.content, "")
  }
  if (sr.key_takeaways?.length) {
    lines.push("## Key Takeaways", "")
    sr.key_takeaways.forEach(t => lines.push(`- ${t}`))
    lines.push("")
  }
  if (sr.resources?.length) {
    lines.push("## Resources", "")
    sr.resources.forEach(r => lines.push(`- [${r.title}](${r.url})`))
    lines.push("")
  }
  if (sr.next_topics?.length) {
    lines.push("## Explore Next", "")
    sr.next_topics.forEach(t => lines.push(`- ${t}`))
  }
  return lines.join("\n")
}

function ExportButton({ structuredResponse }) {
  function handleExport() {
    const md = exportAsMarkdown(structuredResponse)
    const blob = new Blob([md], { type: "text/markdown" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${(structuredResponse.title || "response").slice(0, 40).replace(/[^a-z0-9]/gi, "-").toLowerCase()}.md`
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <button
      onClick={handleExport}
      title="Export as Markdown"
      className="flex items-center gap-1 px-2 py-1 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors text-xs"
    >
      <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
        <path d="M2.75 14A1.75 1.75 0 0 1 1 12.25v-2.5a.75.75 0 0 1 1.5 0v2.5c0 .138.112.25.25.25h10.5a.25.25 0 0 0 .25-.25v-2.5a.75.75 0 0 1 1.5 0v2.5A1.75 1.75 0 0 1 13.25 14Z" />
        <path d="M7.25 7.689V2a.75.75 0 0 1 1.5 0v5.689l1.97-1.97a.749.749 0 1 1 1.06 1.06l-3.25 3.25a.749.749 0 0 1-1.06 0L4.22 6.779a.749.749 0 1 1 1.06-1.06l1.97 1.97Z" />
      </svg>
      <span>.md</span>
    </button>
  )
}

// ─── Shared sub-components ────────────────────────────────────────────────────

function ActionBadge({ action }) {
  const config = ACTION_LABELS[action]
  if (!config) return null
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${config.color}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-80" />
      {config.label}
    </span>
  )
}

function ContextBadges({ contextUsed }) {
  if (!contextUsed) return null
  const badges = []
  if (contextUsed.has_deep_research)   badges.push({ key: "dr", label: "Deep research" })
  if (contextUsed.has_learning_path)   badges.push({ key: "lp", label: "Learning path" })
  if (contextUsed.has_topic_expansion) badges.push({ key: "te", label: "Topic map" })
  if (contextUsed.has_github_repos)    badges.push({ key: "gh", label: "GitHub repos" })
  if (!badges.length) return null
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {badges.map(b => (
        <span key={b.key} className="px-2 py-0.5 rounded-md text-xs bg-slate-800 text-slate-400 border border-slate-700/50">
          {b.label}
        </span>
      ))}
    </div>
  )
}

function RecommendationPanel({ recommendations }) {
  const [open, setOpen] = useState(false)
  if (!recommendations || recommendations.source === "empty") return null

  const { next_topics = [], prerequisites = [], advanced_topics = [] } = recommendations
  const total = next_topics.length + prerequisites.length + advanced_topics.length
  if (total === 0) return null

  return (
    <div className="mt-3 border border-slate-700/60 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-slate-800/60 hover:bg-slate-800 transition-colors text-left"
      >
        <span className="text-xs font-medium text-slate-300">
          {total} follow-up suggestion{total !== 1 ? "s" : ""}
          {recommendations.based_on_topic && (
            <span className="text-slate-500 font-normal"> · {recommendations.based_on_topic}</span>
          )}
        </span>
        <svg
          className={`w-3.5 h-3.5 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        <div className="px-4 py-3 space-y-3 bg-slate-900/40">
          {prerequisites.length > 0 && (
            <RecommendationSection title="Prerequisites" items={prerequisites} color="amber" />
          )}
          {next_topics.length > 0 && (
            <RecommendationSection title="Explore next" items={next_topics} color="blue" />
          )}
          {advanced_topics.length > 0 && (
            <RecommendationSection title="Advanced" items={advanced_topics} color="violet" />
          )}
        </div>
      )}
    </div>
  )
}

function RecommendationSection({ title, items, color }) {
  const colorMap = {
    amber:  "text-amber-400",
    blue:   "text-blue-400",
    violet: "text-violet-400",
  }
  return (
    <div>
      <div className={`text-xs font-semibold uppercase tracking-wide mb-1.5 ${colorMap[color] || "text-slate-400"}`}>
        {title}
      </div>
      <div className="space-y-1.5">
        {items.map((item, i) => (
          <div key={i} className="flex gap-2">
            <span className="text-slate-100 text-sm font-medium min-w-0 truncate">{item.topic}</span>
            {item.reason && (
              <span className="text-slate-500 text-sm truncate">— {item.reason}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function LinkIcon() {
  return (
    <svg className="w-3 h-3 flex-shrink-0 text-slate-500 group-hover:text-slate-400" viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6.5 9.5l4-4M9.5 5.5h3v3M10 10.5v3.5H2V6h3.5" />
    </svg>
  )
}

function CopyIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z" />
      <path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z" />
    </svg>
  )
}

function RetryIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M1.705 8.005a.75.75 0 0 1 .834.656 5.5 5.5 0 0 0 9.592 2.97l-1.204-1.204a.25.25 0 0 1 .177-.427h3.646a.25.25 0 0 1 .25.25v3.646a.25.25 0 0 1-.427.177l-1.38-1.38A7.002 7.002 0 0 1 1.05 8.84a.75.75 0 0 1 .656-.834ZM8 2.5a5.487 5.487 0 0 0-4.131 1.869l1.204 1.204A.25.25 0 0 1 4.896 6H1.25A.25.25 0 0 1 1 5.75V2.104a.25.25 0 0 1 .427-.177l1.38 1.38A7.002 7.002 0 0 1 14.95 7.16a.75.75 0 0 1-1.49.178A5.5 5.5 0 0 0 8 2.5Z" />
    </svg>
  )
}

function EditIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61Zm.176 4.823L9.75 4.81l-6.286 6.287a.253.253 0 0 0-.064.108l-.558 1.953 1.953-.558a.253.253 0 0 0 .108-.064Zm1.238-3.763a.25.25 0 0 0-.354 0L10.811 3.75l1.439 1.44 1.263-1.263a.25.25 0 0 0 0-.354Z" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M2.75 14A1.75 1.75 0 0 1 1 12.25v-2.5a.75.75 0 0 1 1.5 0v2.5c0 .138.112.25.25.25h10.5a.25.25 0 0 0 .25-.25v-2.5a.75.75 0 0 1 1.5 0v2.5A1.75 1.75 0 0 1 13.25 14Z" />
      <path d="M7.25 7.689V2a.75.75 0 0 1 1.5 0v5.689l1.97-1.97a.749.749 0 1 1 1.06 1.06l-3.25 3.25a.749.749 0 0 1-1.06 0L4.22 6.779a.749.749 0 1 1 1.06-1.06l1.97 1.97Z" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
    </svg>
  )
}

function FileChipIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </svg>
  )
}

// Chat-R14b: R2's own original-bytes retention clock — r2_expires_at for
// images (Chat-R14a's dual-write), expires_at for documents/"other" files
// (R13 scoped that field to R2-only for those two, never a second clock).
// Deliberately NOT images' own expires_at (Gemini's real 48h window) — that
// now only governs whether the model can still see the file in a later chat
// turn, a backend/model concern separate from preview/download availability.
export function isAttachmentPastRetention(attachment) {
  const isImage = attachment.mime_type?.startsWith("image/")
  const field = isImage ? attachment.r2_expires_at : attachment.expires_at
  if (!field) return false
  return new Date(field).getTime() < Date.now()
}

// Chat-R14b: whether the chip is a clickable button opening the preview
// modal at all. Documents and "other" files always are — the modal itself
// now handles every expiry/no-preview state honestly (see below). Images are
// clickable only when some viewable source could exist: an R2-backed copy
// (r2_attachment_id — even past its own retention, so the modal can still
// show the honest "no longer available" state) or, pre-R14a rows / a failed
// R2 dual-write, the session-only previewUrl blob. Neither -> exactly
// today's non-clickable chip; no pretending a copy exists that never did.
function isAttachmentPreviewable(attachment) {
  const isImage = attachment.mime_type?.startsWith("image/")
  if (!isImage) return true
  return !!attachment.r2_attachment_id || !!attachment.previewUrl
}

function downloadUrl(url, filename) {
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
}

// Reuses RenameModal's shell (backdrop + centered card) — no new modal shape.
// Chat-R15b: shareToken, when present (share view, no JWT), routes both
// fetch calls below to R15a/R15b's share-scoped endpoints instead of the
// authenticated ones — see fetchAttachmentBlob/fetchDocumentText in api/chat.js.
export function AttachmentPreviewModal({ attachment, onClose, shareToken }) {
  const isImage    = attachment.mime_type?.startsWith("image/")
  const isPdf      = attachment.mime_type === "application/pdf"
  const isOther    = attachment.uri?.startsWith("file://")
  const isDocText  = !isImage && !isOther // doc:// scheme — extracted-text preview, incl. PDF's text fallback
  const isDocScheme = attachment.uri?.startsWith("doc://")

  const pastRetention = isAttachmentPastRetention(attachment)

  // Blob-backed preview: image beyond the same-tab previewUrl, or a PDF's
  // native embed. Both go through fetchAttachmentBlob (Chat-R14b) since the
  // endpoint needs an Authorization header a bare src= can't send.
  const needsBlobFetch = (isImage && !attachment.previewUrl && !!attachment.r2_attachment_id) || isPdf
  const [previewUrl, setPreviewUrl]         = useState(isImage ? attachment.previewUrl ?? null : null)
  const [previewError, setPreviewError]     = useState(null)
  const [previewLoading, setPreviewLoading] = useState(needsBlobFetch && !pastRetention)

  useEffect(() => {
    if (!needsBlobFetch || pastRetention) return
    let cancelled = false
    setPreviewLoading(true)
    setPreviewError(null)
    fetchAttachmentBlob(attachment, shareToken)
      .then(url => { if (!cancelled) setPreviewUrl(url) })
      .catch(err => { if (!cancelled) setPreviewError(err.message || "Could not load preview.") })
      .finally(() => { if (!cancelled) setPreviewLoading(false) })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attachment.uri, attachment.r2_attachment_id])

  // Extracted-text preview — permanent, unaffected by expires_at. Skipped
  // entirely for "other" files (Chat-R14a: no document_chunks_vec entry, no
  // text to fetch — asking would just 404 confusingly).
  const [docText, setDocText]       = useState(null)
  const [docError, setDocError]     = useState(null)
  const [docLoading, setDocLoading] = useState(isDocText)

  useEffect(() => {
    if (!isDocText) return
    let cancelled = false
    setDocLoading(true)
    setDocError(null)
    const attachmentId = attachment.uri.replace(/^doc:\/\//, "")
    fetchDocumentText(attachmentId, shareToken)
      .then(({ text }) => { if (!cancelled) setDocText(text) })
      .catch(err => { if (!cancelled) setDocError(err.message || "Could not load document text.") })
      .finally(() => { if (!cancelled) setDocLoading(false) })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attachment.uri])

  const [downloading, setDownloading] = useState(false)

  // Real original bytes, real filename — every type now goes through the
  // same fetch (Chat-R14b fixes the old bug where a document "download"
  // silently renamed report.pdf -> report.txt and served extracted text
  // instead of the file). The one exception: a pre-R14a image with only a
  // session previewUrl and no r2_attachment_id reuses that blob directly —
  // there's nothing else to fetch.
  async function handleDownload() {
    if (pastRetention || downloading) return
    if (isImage && attachment.previewUrl && !attachment.r2_attachment_id) {
      downloadUrl(attachment.previewUrl, attachment.filename)
      return
    }
    setDownloading(true)
    try {
      const url = await fetchAttachmentBlob(attachment, shareToken)
      downloadUrl(url, attachment.filename)
    } catch {
      // No dedicated error slot for the download button itself — the preview
      // pane above already surfaces the same fetch failure for image/PDF,
      // and a stale-clock 404 here (object swept moments after expires_at
      // was checked) is rare enough not to need its own UI.
    } finally {
      setDownloading(false)
    }
  }

  const downloadDisabled = pastRetention || downloading || previewLoading

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div className="relative w-full max-w-lg bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl p-5 space-y-3" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-200 truncate">{attachment.filename}</h2>
          <div className="flex items-center gap-0.5 flex-shrink-0">
            <button
              onClick={handleDownload}
              disabled={downloadDisabled}
              title={pastRetention ? "Original file no longer available" : "Download"}
              className="flex items-center justify-center p-1.5 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <DownloadIcon />
            </button>
            <button
              onClick={onClose}
              title="Close"
              className="flex items-center justify-center p-1.5 rounded-md text-slate-600 hover:text-slate-400 hover:bg-slate-800/60 transition-colors"
            >
              <CloseIcon />
            </button>
          </div>
        </div>

        {pastRetention && (
          <div className="px-4 py-3 bg-slate-900/30 border border-slate-800 rounded-lg text-xs text-slate-500 leading-relaxed">
            {isDocScheme
              ? "The original file is no longer available — the extracted text below is still shown."
              : "This file is no longer available."}
          </div>
        )}

        {!pastRetention && isImage && (
          previewLoading ? (
            <div className="px-4 py-3 text-xs text-slate-500">Loading…</div>
          ) : previewError ? (
            <div className="px-4 py-3 text-xs text-red-400">{previewError}</div>
          ) : previewUrl ? (
            <img src={previewUrl} alt={attachment.filename} className="max-h-[70vh] w-full object-contain rounded-lg" />
          ) : (
            <div className="px-4 py-3 text-xs text-slate-500">Preview unavailable — only available in the tab that sent it.</div>
          )
        )}

        {!pastRetention && isPdf && (
          previewLoading ? (
            <div className="px-4 py-3 text-xs text-slate-500">Loading…</div>
          ) : previewError ? (
            <div className="px-4 py-3 text-xs text-red-400">{previewError}</div>
          ) : previewUrl ? (
            <iframe src={previewUrl} title={attachment.filename} className="w-full h-[70vh] rounded-lg border border-slate-800 bg-white" />
          ) : null
        )}

        {!pastRetention && isOther && (
          <div className="px-4 py-3 bg-slate-900/30 border border-slate-800 rounded-lg text-xs text-slate-500 leading-relaxed">
            No preview available for this file type.
          </div>
        )}

        {isDocText && (
          <div className="px-4 py-3 bg-slate-900/30 border border-slate-800 rounded-lg text-xs text-slate-400 leading-relaxed whitespace-pre-wrap max-h-[60vh] overflow-y-auto">
            {docLoading ? "Loading…" : docError || docText}
          </div>
        )}
      </div>
    </div>
  )
}

// A sent message's attachments render as chips. Chat-R14b: past-retention
// wording differs by type — documents/PDF still have their permanent
// extracted text ("text only"), images/"other" files have nothing left
// ("expired") — matching the modal's own distinction below.
function MessageAttachments({ attachments, shareToken }) {
  const [previewAttachment, setPreviewAttachment] = useState(null)
  if (!attachments?.length) return null
  return (
    <>
      <div className="flex flex-wrap gap-1.5 justify-end mb-1.5">
        {attachments.map((a, i) => {
          const isImage        = a.mime_type?.startsWith("image/")
          const isDocScheme    = a.uri?.startsWith("doc://")
          const pastRetention  = isAttachmentPastRetention(a)
          const previewable    = isAttachmentPreviewable(a)
          const noLocalCopy    = isImage && !previewable
          const Tag            = previewable ? "button" : "div"
          const badgeLabel     = pastRetention
            ? (isDocScheme ? "text only" : "expired")
            : (noLocalCopy ? "no preview" : null)
          return (
            <Tag
              key={i}
              type={previewable ? "button" : undefined}
              onClick={previewable ? () => setPreviewAttachment(a) : undefined}
              className={`flex items-center gap-1.5 pl-1.5 pr-2 py-1 rounded-lg border text-[11px] ${
                pastRetention
                  ? "bg-slate-900/40 border-slate-800 opacity-60"
                  : "bg-white/[0.04] border-white/[0.08]"
              } ${previewable ? "hover:border-white/[0.16] hover:bg-white/[0.07] transition-colors cursor-pointer" : ""}`}
              title={
                pastRetention
                  ? `${a.filename} — no longer available (past its retention window)`
                  : previewable
                    ? `${a.filename} — click to preview`
                    : `${a.filename} — preview unavailable (only available in the tab that sent it)`
              }
            >
              {isImage && a.previewUrl ? (
                <img src={a.previewUrl} alt="" className="w-6 h-6 rounded-md object-cover flex-shrink-0" />
              ) : (
                <span className="text-slate-500 flex-shrink-0"><FileChipIcon /></span>
              )}
              <span className="max-w-[100px] truncate text-slate-400">{a.filename}</span>
              {(badgeLabel === "expired" || badgeLabel === "text only") && (
                <span className="text-amber-500/80 text-[10px] flex-shrink-0">{badgeLabel}</span>
              )}
              {badgeLabel === "no preview" && <span className="text-slate-600 text-[10px] flex-shrink-0">no preview</span>}
            </Tag>
          )
        })}
      </div>
      {previewAttachment && (
        <AttachmentPreviewModal attachment={previewAttachment} onClose={() => setPreviewAttachment(null)} shareToken={shareToken} />
      )}
    </>
  )
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button
      onClick={handleCopy}
      title="Copy"
      className="flex items-center gap-1 px-2 py-1 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors text-xs"
    >
      <CopyIcon />
      {copied && <span className="text-[10px]">Copied!</span>}
    </button>
  )
}

function SourcesPanel({ sources }) {
  const [open, setOpen] = useState(false)
  if (!sources || sources.length === 0) return null

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 text-xs font-medium text-slate-300 hover:text-slate-100 transition-colors"
      >
        <svg className="w-3.5 h-3.5 text-slate-400" viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 0C3.58 0 0 3.58 0 8s3.58 8 8 8 8-3.58 8-8-3.58-8-8-8zM6.5 11.5l-3-3 1.06-1.06L6.5 9.38l5.44-5.44L13 5l-6.5 6.5z" />
        </svg>
        {sources.length} source{sources.length !== 1 ? "s" : ""}
        <svg
          className={`w-3.5 h-3.5 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        <div className="mt-2 space-y-1">
          {sources.map((src, i) => (
            <a
              key={i}
              href={src.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-2 px-2 py-1.5 rounded-lg hover:bg-slate-800/60 transition-colors group"
            >
              <span className="mt-0.5 text-slate-500 group-hover:text-blue-400 transition-colors">
                <LinkIcon />
              </span>
              <span className="text-[11px] text-slate-400 group-hover:text-slate-200 transition-colors leading-snug min-w-0 truncate">
                {src.title ? `${src.title} - ${src.url}` : src.url}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function ThinkingIcon({ streaming = false }) {
  return streaming ? (
    <svg className="w-3.5 h-3.5 text-slate-200 animate-spin [animation-duration:1.8s]" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2.75A9.25 9.25 0 1 0 21.25 12" />
      <path d="M12 2.75V6.5" />
      <path d="M12 17.5v-3.25" />
      <path d="M2.75 12h3.75" />
      <path d="M17.5 12h3.75" />
    </svg>
  ) : (
    <svg className="w-3.5 h-3.5 text-slate-400" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 20V14M12 20V8M18 20V4" />
    </svg>
  )
}

function StatusCheckIcon() {
  return (
    <svg className="w-3.5 h-3.5 text-slate-500" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 12.5 2.5 2.5 4.5-5" />
    </svg>
  )
}

// Chat-R10g: last complete title-like line in the accumulated thinking text.
// We detect either a standalone **bold** line or a # heading line and return
// the extracted phrase plus the original matched line so the renderer can strip
// the duplicate title from the body without touching the rest of the content.
function extractLastBoldPhrase(text) {
  if (!text) return null
  const lines = text.split(/\r?\n/)
  let match = null

  for (const line of lines) {
    const trimmed = line.trim()
    if (/^\*\*(.+?)\*\*$/.test(trimmed)) {
      match = { phrase: trimmed.slice(2, -2).trim(), matchedLine: line }
      continue
    }
    const headingMatch = trimmed.match(/^#{1,6}\s+(.+)$/)
    if (headingMatch) {
      match = { phrase: headingMatch[1].trim(), matchedLine: line }
    }
  }

  return match?.phrase ? match : null
}

// Reasoning panel above the answer (Chat-6). It keeps a truncated preview
// visible at all times, toggles between preview and full content, and swaps
// its status icon from in-progress to done using the same streaming signal
// already used by the message renderer.
// Chat-R10g: below this many chars the preview already shows the whole
// thing, so line-clamp + "Show more" would just be a dead button.
const THINKING_PREVIEW_CHAR_LIMIT = 260

function ThinkingPanel({ thinking, streaming }) {
  const [expanded, setExpanded] = useState(false)
  const [open, setOpen] = useState(streaming) // auto-open while the model is actively thinking
  const summary = useMemo(() => extractLastBoldPhrase(thinking), [thinking])
  if (!thinking) return null

  const label = summary?.phrase || "Thinking"
  const bodyThinking = summary?.matchedLine
    ? thinking.replace(summary.matchedLine, "")
    : thinking
  const statusText = streaming ? "Thinking…" : "Done"
  const isLong = bodyThinking.trim().length > THINKING_PREVIEW_CHAR_LIMIT

  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setOpen(value => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 text-left text-[13px] sm:text-[13.5px] font-medium leading-[1.25] text-slate-200 transition-colors hover:text-slate-100"
      >
        <span className="min-w-0 truncate">{label}</span>
        <svg className="w-3.5 h-3.5 text-slate-400 -rotate-90" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M7.22 5.22a.75.75 0 0 1 1.06 0L12 8.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L7.22 6.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        <div className="mt-1 pl-3 border-l border-slate-700/50">
          <div className="relative overflow-hidden">
            <div className={`text-[10px] sm:text-[11px] leading-[1.45] text-slate-300 ${isLong && !expanded ? "line-clamp-4" : ""}`}>
              <DrippedMessageText text={bodyThinking} streaming={streaming} variant="thinking" className="space-y-0.5" dripOptions={THINKING_DRIP} />
            </div>
            {isLong && !expanded && (
              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-slate-950/95 via-slate-950/55 to-transparent" />
            )}
          </div>

          {isLong && (
            <button
              type="button"
              onClick={() => setExpanded(value => !value)}
              aria-expanded={expanded}
              className="mt-1 text-[11px] font-medium text-slate-500 transition-colors hover:text-slate-300"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          )}

          <div className="mt-1 flex items-center gap-1.5 text-[11.5px] text-slate-500">
            <StatusCheckIcon />
            <span>{statusText}</span>
          </div>
        </div>
      )}
    </div>
  )
}

function GlobeIcon() {
  return (
    <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5 flex-shrink-0 text-blue-400" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </svg>
  )
}

const _TOOL_CALL_LABELS = {
  web_search:    "Searched the web",
  deep_research: "Ran deep research",
}

// Chat-R10g: Google's s2/favicons service, derived from the source URL alone
// — no new backend field (sources are strictly {title, url}, confirmed).
// onError hides the <img> entirely so a dead favicon never shows a broken-
// image icon; the pill's text label (computed independently below) is
// unaffected either way.
function SourceFavicon({ url }) {
  const [failed, setFailed] = useState(false)
  let hostname
  try { hostname = new URL(url).hostname } catch { return null }
  if (failed) return null
  return (
    <img
      src={`https://www.google.com/s2/favicons?domain=${hostname}&sz=32`}
      alt=""
      className="w-3.5 h-3.5 rounded-sm flex-shrink-0"
      onError={() => setFailed(true)}
    />
  )
}

// Chat-R10e: compact inline tool-call block — a block.blocks[] entry
// ({type:"tool_call", tool, query, sources}), rendered in its true
// chronological position instead of SourcesPanel's old always-last dump.
// Query is always visible; sources collapse behind a small toggle so a
// 6-source call doesn't turn into a wall of links mid-answer.
function ToolCallBlock({ block, streaming }) {
  const [open, setOpen] = useState(false)
  const { tool, query, sources } = block
  const label = _TOOL_CALL_LABELS[tool] || `Ran ${tool}`
  const hasSources = sources && sources.length > 0
  const drippedQuery = useDrip(query || "", streaming)

  return (
    <div className="mb-3 text-sm">
      <button
        onClick={() => hasSources && setOpen(o => !o)}
        className="flex items-center gap-2 min-w-0 w-full text-left hover:opacity-80 transition-opacity"
        style={{ cursor: hasSources ? "pointer" : "default" }}
      >
        <GlobeIcon />
        <span className="text-slate-300 flex-shrink-0">{label}</span>
        {query && <span className="italic text-slate-500 truncate min-w-0">"{drippedQuery}"</span>}
        {hasSources && (
          <span className="flex items-center gap-1 text-slate-500 flex-shrink-0">
            {sources.length} source{sources.length !== 1 ? "s" : ""}
            <svg className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`} viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
            </svg>
          </span>
        )}
      </button>
      {open && hasSources && (
        <div
          className="mt-2 ml-0 sm:ml-5 p-3 border border-slate-700/50 rounded-lg bg-slate-900/30 flex flex-col gap-1.5 overflow-y-auto"
          style={{ maxHeight: "136px" }}
        >
          {sources.map((src, i) => (
            <a
              key={i} href={src.url} target="_blank" rel="noopener noreferrer"
              className="flex items-center justify-start gap-1.5 px-2 py-1 rounded-md bg-slate-900/60 hover:bg-slate-900 text-slate-400 hover:text-slate-200 transition-colors w-full"
            >
              <SourceFavicon url={src.url} />
              <span className="truncate">
                {src.title ? `${src.title} - ${src.url}` : src.url}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

// Chat-R10e: walks message.blocks in true chronological order — replaces the
// old fixed-zone layout (thinking always first, sources always last) for any
// message that has a real blocks[] (post-R10d turns). Multiple thinking
// blocks render as separate ThinkingPanel instances at their real position,
// not merged. The final "text" block swaps in StructuredResponseRenderer
// when the whole message parses as one (srObject is computed off the full
// message.content, same as the legacy path) — earlier text blocks, if any,
// are plain MessageText.
function BlocksRenderer({ blocks, streaming, srObject }) {
  const lastTextIdx = blocks.reduce((acc, b, i) => (b.type === "text" ? i : acc), -1)
  // Phase E: real, ordered {title,url} list for this turn's [N] citation
  // markers — flattened from every tool_call block's own `sources` (Chat-R10e
  // already carries these per-block; real evidence, 0/118 real turns ever
  // produced more than one tool_call block, but flattening rather than
  // assuming exactly one keeps this correct either way). Derived from
  // `blocks` itself (not a separate message.sources field) because blocks is
  // what actually gets persisted — this must resolve identically live and on
  // reload from history.
  const citationSources = blocks
    .filter(b => b.type === "tool_call")
    .flatMap(b => b.sources || [])
  return (
    <>
      {blocks.map((block, i) => {
        if (block.type === "thinking") {
          return <ThinkingPanel key={i} thinking={block.text} streaming={streaming} />
        }
        if (block.type === "tool_call") {
          return <ToolCallBlock key={i} block={block} streaming={streaming} />
        }
        if (block.type === "text") {
          // Defense-in-depth (backstop, not the real fix — see
          // chat_title_service.advance_stream_state for that): the backend
          // strips [TITLE: ...] before this ever reaches the wire, but this
          // block.text is rendered raw with no other cleaning step, live
          // AND on reload — cleanContent() is a second, independent layer
          // in case a future provider's chunking ever defeats the backend
          // fix in some new way.
          return i === lastTextIdx && srObject
            ? <StructuredResponseRenderer key={i} sr={srObject} />
            : <DrippedMessageText key={i} text={cleanContent(block.text)} streaming={streaming} sources={citationSources} />
        }
        return null
      })}
    </>
  )
}

function CodeIcon() {
  return (
    <svg className="w-3.5 h-3.5 text-emerald-400" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 18l6-6-6-6M8 6l-6 6 6 6" />
    </svg>
  )
}

// Real executed code + its real output — distinct from ThinkingPanel (Gemini's
// reasoning, never actually run) and from a ```fenced code block in the prose
// (the model's own restatement). One block per code_execution call this turn;
// `output` is null until the matching code_execution_result chunk arrives.
function CodeExecutionBlock({ b, streaming }) {
  const drippedCode = useDrip(b.code, streaming)
  const drippedOutput = useDrip(b.output ?? "", streaming && b.output !== null)
  return (
    <div className="border border-emerald-800/40 rounded-xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 bg-emerald-950/30 border-b border-emerald-800/30">
        <CodeIcon />
        <span className="text-xs font-medium text-emerald-300/90">Executed {b.language || "python"}</span>
      </div>
      <div className="bg-slate-900">
        <div className="flex items-center justify-between pl-4 pr-1.5 pt-2.5">
          <span className="text-[10.5px] font-semibold uppercase tracking-widest text-slate-500">Code</span>
          <CopyButton text={b.code} />
        </div>
        <pre className="px-4 pb-3 pt-1 overflow-x-scroll-touch">
          <code className="text-[13px] font-mono text-slate-200 leading-[1.68] whitespace-pre">{drippedCode}</code>
        </pre>
      </div>
      {/* Chat-R10g: code has streamed but the matching code_execution_result
          chunk hasn't arrived yet — b.output stays null until then (see
          chat_agent._split_content_chunks). Was previously blank space. */}
      {b.output === null ? (
        <div className="px-4 py-3 border-t bg-slate-950/60 border-slate-800/60 text-[11px] text-slate-500 italic animate-pulse">
          Running…
        </div>
      ) : (
        <div className={`border-t ${b.success === false ? "bg-red-950/20 border-red-900/30" : "bg-slate-950/60 border-slate-800/60"}`}>
          <div className="flex items-center justify-between pl-4 pr-1.5 pt-2.5">
            <span className={`text-[10.5px] font-semibold uppercase tracking-widest ${b.success === false ? "text-red-400/80" : "text-slate-500"}`}>
              {b.success === false ? "Error" : "Output"}
            </span>
            <CopyButton text={b.output} />
          </div>
          <code className="block px-4 pb-3 pt-1 text-[13px] font-mono text-slate-300 leading-[1.68] whitespace-pre-wrap">{drippedOutput}</code>
        </div>
      )}
    </div>
  )
}

function CodeExecutionPanel({ blocks, streaming }) {
  if (!blocks?.length) return null
  return (
    <div className="mb-3 space-y-2.5">
      {blocks.map((b, i) => <CodeExecutionBlock key={i} b={b} streaming={streaming} />)}
    </div>
  )
}

// Honest one-line note for turns where reasoning ran but Gemini's streaming
// API never surfaces it (a confirmed upstream limitation on some model
// tiers, not a bug here — see chat_agent._THINKING_GAP_TEXT). Shown in place
// of ThinkingPanel instead of leaving a silent gap that looks broken —
// static, not collapsible, nothing to expand into.
function ThinkingGapNote({ text }) {
  if (!text) return null
  return (
    <div className="mb-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/40 text-xs text-slate-500 italic">
      <ThinkingIcon />
      <span>{text}</span>
    </div>
  )
}

// Chat-R5b: task_type=="coding" but the leg that answered can't run
// code_execution (every Gemini 3+ leg exhausted, or landed on 2.5's
// write-only tier) — shown alongside CodeExecutionPanel, not in place of it,
// since there's no executed block to show, just an unexecuted answer.
function CodeExecutionGapNote({ text }) {
  if (!text) return null
  return (
    <div className="mb-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/40 text-xs text-slate-500 italic">
      <CodeIcon />
      <span>{text}</span>
    </div>
  )
}

// Chat-R10: live tool-use signal that survives past the first content chunk.
// The backend's "Searching the web…" status (chat_service.py's tool_start
// handler) used to only live in the ephemeral TypingIndicator, which
// disappears the instant text starts streaming — blink-and-miss-it. This
// persists the same text onto the message itself so it stays visible for the
// rest of the turn and after, without duplicating SourcesPanel's citation
// list (which shows post-hoc and only if the tool actually returned sources).
function SearchStatusNote({ text }) {
  if (!text) return null
  return (
    <div className="mb-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/40 text-xs text-slate-500 italic">
      <GlobeIcon />
      <span>{text.replace(/…$/, "")}</span>
    </div>
  )
}

function MessageTimestamp({ value }) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return (
    <span className="px-2 py-1 text-[11px] text-slate-600 tabular-nums">
      {date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
    </span>
  )
}

// ─── Main export ──────────────────────────────────────────────────────────────

export default function ChatMessage({ message, msgIndex, sessionId, isLastAssistant, onRetry, onEdit, shareToken }) {
  const isUser = message.role === "user"
  const [editing, setEditing] = useState(false)
  const [draft, setDraft]     = useState("")
  const textareaRef           = useRef(null)

  function startEdit() {
    setDraft(message.content)
    setEditing(true)
    setTimeout(() => {
      textareaRef.current?.focus()
      textareaRef.current?.select()
    }, 0)
  }

  function commitEdit() {
    const trimmed = draft.trim()
    if (trimmed) onEdit?.(msgIndex, trimmed)
    setEditing(false)
  }

  function handleEditKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commitEdit() }
    if (e.key === "Escape") setEditing(false)
  }

  if (isUser) {
    return (
      <div className="flex justify-end group/msg">
        <div className="flex flex-col items-end gap-1 max-w-[85%] sm:max-w-[70%]">
          <MessageAttachments attachments={message.attachments} shareToken={shareToken} />
          {editing ? (
            <div className="w-full">
              <textarea
                ref={textareaRef}
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={handleEditKeyDown}
                rows={Math.min(8, draft.split("\n").length + 1)}
                className="w-full px-4 py-3 bg-violet-600/20 border border-violet-400/50 rounded-2xl rounded-tr-sm text-slate-100 text-sm leading-relaxed resize-none focus:outline-none focus:ring-1 focus:ring-violet-400/60"
              />
              <div className="flex gap-1.5 mt-1.5 justify-end">
                <button
                  onClick={() => setEditing(false)}
                  className="px-3 py-1 text-xs rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={commitEdit}
                  className="px-3 py-1 text-xs rounded-lg bg-violet-600/50 text-violet-200 hover:bg-violet-600/70 transition-colors"
                >
                  Send
                </button>
              </div>
            </div>
          ) : message.content ? (
            <div className="bg-violet-600/20 border border-violet-500/30 rounded-2xl rounded-tr-sm px-4 py-3 text-[14px] text-slate-100 leading-[1.68] prose-wrap">
              {message.content}
            </div>
          ) : null}
          {!editing && (
            <div className="flex items-center gap-0.5">
              <CopyButton text={message.content} />
              {onEdit && (
                <button
                  onClick={startEdit}
                  title="Edit"
                  className="flex items-center gap-1 px-2 py-1 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
                >
                  <EditIcon />
                </button>
              )}
              <MessageTimestamp value={message.created_at} />
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── Assistant message ────────────────────────────────────────────────────

  const { srObject, displayContent } = normalizeResponse(message)
  const hasVisibleContent = typeof message.content === "string" && message.content.trim().length > 0
  const showStreamingCursor = message.streaming && hasVisibleContent

  return (
    <div className={`flex gap-2.5 sm:gap-3 max-w-4xl group/msg ${message.streaming && !hasVisibleContent ? "items-center" : ""}`}>
      <div className={`hidden sm:flex sm:flex-shrink-0 rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 items-center justify-center shadow-md shadow-violet-950/50 ${message.streaming && !hasVisibleContent ? "sm:w-9 sm:h-9" : "sm:w-7 sm:h-7 mt-0.5"}`}>
        <svg className={`w-3 h-3 text-white ${message.streaming && !hasVisibleContent ? "sm:w-[18px] sm:h-[18px]" : "sm:w-3.5 sm:h-3.5"}`} viewBox="0 0 16 16" fill="currentColor">
          <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
        </svg>
      </div>

      <div className="flex-1 min-w-0">
        {!message.streaming && message.action && <ActionBadge action={message.action} />}

        <div className={!message.streaming && message.action ? "mt-2" : ""}>
          {/* R5 gap note keys off the flat `thinking` field (chat_service.py
              still fills this alongside blocks[] — see _stream_agent's gap
              yields, which bypass block tagging entirely), so it applies the
              same regardless of which branch below renders — a Gemini-3+ turn
              with a real blocks[] (e.g. just a text block) still needs
              thinking_gap to show, not just the null-blocks path. */}
          {!message.thinking && <ThinkingGapNote text={message.thinkingGap} />}
          {message.blocks?.length ? (
            // Chat-R10e: real chronological order (thinking/tool_call/text
            // interleaved as they actually happened) — one renderer for both
            // live-streaming and reloaded-from-history messages, since both
            // feed BlocksRenderer the same blocks[] shape (live: built in
            // ChatWorkspace.jsx as events stream; historical: get_history's
            // persisted `blocks` column via apiMessageToLocal).
            <>
              <BlocksRenderer blocks={message.blocks} streaming={message.streaming} srObject={srObject} />
              <CodeExecutionPanel blocks={message.codeBlocks} streaming={message.streaming} />
              <CodeExecutionGapNote text={message.codeExecutionGap} />
            </>
          ) : (
            // Fallback for any message with no blocks[] (pre-R10d history,
            // or a turn that produced neither thinking nor a tool call) —
            // untouched fixed-zone layout, same as before R10d/R10e.
            <>
              <ThinkingPanel thinking={message.thinking} streaming={message.streaming} />
              <CodeExecutionPanel blocks={message.codeBlocks} streaming={message.streaming} />
              <CodeExecutionGapNote text={message.codeExecutionGap} />
              <SearchStatusNote text={message.searchStatus} />
              {message.streaming && !hasVisibleContent ? (
                <StreamingDots statusMsg={message.statusMsg} />
              ) : srObject ? (
                <StructuredResponseRenderer sr={srObject} />
              ) : (
                // Defense-in-depth, same as BlocksRenderer's text-block case above —
                // displayContent already runs message.content through cleanContent()
                // post-stream (normalizeResponse), so only the live-streaming branch
                // needs the explicit wrap here.
                <DrippedMessageText text={message.streaming ? cleanContent(message.content) : displayContent} streaming={message.streaming} />
              )}
            </>
          )}
          {showStreamingCursor && <StreamingCursor />}
        </div>

        {!message.streaming && !srObject && !message.blocks?.length && <SourcesPanel sources={message.sources} />}
        {!message.streaming && !srObject && <ContextBadges contextUsed={message.contextUsed} />}
        {!message.streaming && <RecommendationPanel recommendations={message.recommendations} />}

        {!message.streaming && (
          <div className="flex items-center gap-0.5 mt-2">
            <CopyButton text={message.content} />
            {srObject && <ExportButton structuredResponse={srObject} />}
            <BookmarkButton
              bookmarkData={{
                title:                   srObject?.title || message.content.slice(0, 80) || 'Chat insight',
                summary:                 srObject?.summary || message.content.slice(0, 300) || '',
                content_type:            srObject ? 'deep_research' : 'chat_insight',
                source_type:             'chat',
                ai_generated_notes:      srObject?.key_takeaways?.slice(0,2).join(' · ') || '',
                related_topics:          srObject?.next_topics || [],
                content_snapshot:        message.content.slice(0, 2000),
                deep_research_reference: srObject?.title || '',
                conversation_reference:  sessionId || '',
              }}
            />
            {isLastAssistant && onRetry && (
              <button
                onClick={() => onRetry(msgIndex)}
                title="Regenerate"
                className="flex items-center gap-1 px-2 py-1 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors text-xs"
              >
                <RetryIcon />
                <span>Regenerate</span>
              </button>
            )}
            <MessageTimestamp value={message.created_at} />
          </div>
        )}
      </div>
    </div>
  )
}

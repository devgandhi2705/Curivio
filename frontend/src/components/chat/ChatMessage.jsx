import { useState, useRef } from "react"
import BookmarkButton from "../bookmarks/BookmarkButton.jsx"
import MessageText from "../shared/MarkdownText.jsx"
import { normalizeResponse } from "../shared/responseAdapter.js"

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

function StreamingSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="h-5 bg-slate-800 rounded-lg w-2/3" />
      <div className="h-3 bg-slate-800/70 rounded w-full" />
      <div className="h-3 bg-slate-800/70 rounded w-5/6" />
      <div className="h-3 bg-slate-800/70 rounded w-4/5" />
      <div className="mt-5 space-y-2">
        <div className="h-4 bg-slate-800/60 rounded w-1/3" />
        <div className="h-3 bg-slate-800/50 rounded w-full" />
        <div className="h-3 bg-slate-800/50 rounded w-11/12" />
        <div className="h-3 bg-slate-800/50 rounded w-4/5" />
      </div>
      <div className="mt-4 space-y-2">
        <div className="h-4 bg-slate-800/60 rounded w-1/4" />
        <div className="h-3 bg-slate-800/50 rounded w-full" />
        <div className="h-3 bg-slate-800/50 rounded w-3/4" />
      </div>
      <div className="mt-4 flex gap-2">
        <div className="h-6 bg-slate-800/50 rounded-full w-20" />
        <div className="h-6 bg-slate-800/50 rounded-full w-28" />
        <div className="h-6 bg-slate-800/50 rounded-full w-24" />
      </div>
    </div>
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
    <div className="mt-3 border border-slate-700/50 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-slate-800/50 hover:bg-slate-800/80 transition-colors text-left"
      >
        <span className="flex items-center gap-2 text-xs font-medium text-slate-300">
          <svg className="w-3.5 h-3.5 text-slate-400" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 0C3.58 0 0 3.58 0 8s3.58 8 8 8 8-3.58 8-8-3.58-8-8-8zM6.5 11.5l-3-3 1.06-1.06L6.5 9.38l5.44-5.44L13 5l-6.5 6.5z" />
          </svg>
          {sources.length} source{sources.length !== 1 ? "s" : ""}
        </span>
        <svg
          className={`w-3.5 h-3.5 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        <div className="px-3 py-2 space-y-1 bg-slate-900/30">
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
              <span className="text-xs text-slate-400 group-hover:text-slate-200 transition-colors leading-snug min-w-0">
                {src.title || (() => { try { return new URL(src.url).hostname } catch { return src.url } })()}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Main export ──────────────────────────────────────────────────────────────

export default function ChatMessage({ message, msgIndex, sessionId, isLastAssistant, onRetry, onEdit }) {
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
    if (trimmed && trimmed !== message.content) onEdit?.(msgIndex, trimmed)
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
          ) : (
            <div className="bg-violet-600/20 border border-violet-500/30 rounded-2xl rounded-tr-sm px-4 py-3 text-[14px] text-slate-100 leading-[1.68] prose-wrap">
              {message.content}
            </div>
          )}
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
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── Assistant message ────────────────────────────────────────────────────

  const { srObject, displayContent } = normalizeResponse(message)

  return (
    <div className="flex gap-2.5 sm:gap-3 max-w-4xl group/msg">
      <div className="hidden sm:flex sm:flex-shrink-0 sm:w-7 sm:h-7 rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 items-center justify-center shadow-md shadow-violet-950/50 mt-0.5">
        <svg className="w-3 h-3 sm:w-3.5 sm:h-3.5 text-white" viewBox="0 0 16 16" fill="currentColor">
          <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
        </svg>
      </div>

      <div className="flex-1 min-w-0">
        {!message.streaming && message.action && <ActionBadge action={message.action} />}

        <div className={!message.streaming && message.action ? "mt-2" : ""}>
          {message.streaming ? (
            <StreamingSkeleton />
          ) : srObject ? (
            <StructuredResponseRenderer sr={srObject} />
          ) : (
            <MessageText text={displayContent} />
          )}
        </div>

        {!message.streaming && !srObject && <SourcesPanel sources={message.sources} />}
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
          </div>
        )}
      </div>
    </div>
  )
}

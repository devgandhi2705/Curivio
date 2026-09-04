/**
 * GlobalSearch — Cmd/Ctrl+K command-palette search across the entire app.
 *
 * Searches feed cards, bookmarks, and chat messages simultaneously.
 * Results are keyboard-navigable (↑↓ + Enter) and grouped by section.
 *
 * Props:
 *   onClose      () => void
 *   onNavigate   ({ type: 'feed'|'bookmarks'|'chat', ...data }) => void
 */
import { useState, useEffect, useRef, useCallback } from "react"
import { globalSearch } from "../api/search.js"

// ── Color map (mirrors ProjectCard) ──────────────────────────────────────────

const COLOR_DOT = {
  blue:    "bg-blue-500",
  emerald: "bg-emerald-500",
  violet:  "bg-violet-500",
  amber:   "bg-amber-500",
  rose:    "bg-rose-500",
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function SearchIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z" clipRule="evenodd" />
    </svg>
  )
}

function CardIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
    </svg>
  )
}

function BookmarkIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M3 2.75C3 1.784 3.784 1 4.75 1h6.5c.966 0 1.75.784 1.75 1.75v11.5a.75.75 0 0 1-1.227.579L8 11.722l-3.773 3.107A.75.75 0 0 1 3 14.25Z" />
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

function SpinnerIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

// ── Highlight matching text ───────────────────────────────────────────────────

function Highlight({ text, query }) {
  if (!query || !text) return <span>{text}</span>
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return <span>{text}</span>
  return (
    <span>
      {text.slice(0, idx)}
      <mark className="bg-blue-500/25 text-blue-300 rounded-[2px] px-0.5">
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </span>
  )
}

// ── Result row ────────────────────────────────────────────────────────────────

function ResultRow({ result, query, isSelected, onSelect, onHover, flatIdx }) {
  const ref = useRef(null)

  useEffect(() => {
    if (isSelected) ref.current?.scrollIntoView({ block: "nearest" })
  }, [isSelected])

  const icon = result.type === "card"
    ? <CardIcon className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" />
    : result.type === "bookmark"
    ? <BookmarkIcon className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
    : <ChatIcon className="w-3.5 h-3.5 text-violet-400 flex-shrink-0" />

  const title = result.type === "chat"
    ? result.session_title
    : result.card_title || result.title

  const snippet = result.type === "chat"
    ? result.message_snippet
    : result.card_summary

  const meta = result.type === "card"
    ? (
      <span className="flex items-center gap-1.5">
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${COLOR_DOT[result.project_color] || "bg-blue-500"}`} />
        <span>{result.project_name}</span>
        <span className="text-slate-700">·</span>
        <span>Day {result.day_number}</span>
        {result.content_type && (
          <>
            <span className="text-slate-700">·</span>
            <span className="capitalize">{result.content_type}</span>
          </>
        )}
      </span>
    )
    : result.type === "bookmark"
    ? (
      <span>
        {result.project_name ? `${result.project_name} · ` : ""}Bookmark
      </span>
    )
    : (
      <span className="flex items-center gap-1">
        <span className="capitalize">{result.role}</span>
        <span className="text-slate-700">·</span>
        <span>Chat session</span>
      </span>
    )

  return (
    <button
      ref={ref}
      onMouseEnter={() => onHover(flatIdx)}
      onClick={() => onSelect(result)}
      className={`w-full text-left px-4 py-3 flex items-start gap-3 transition-colors ${
        isSelected ? "bg-slate-800/80" : "hover:bg-slate-800/40"
      }`}
    >
      <div className="mt-0.5 flex-shrink-0">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-slate-200 truncate leading-snug">
          <Highlight text={title} query={query} />
        </p>
        {snippet && (
          <p className="text-[11px] text-slate-500 mt-0.5 line-clamp-1 leading-snug">
            <Highlight text={snippet} query={query} />
          </p>
        )}
        <p className="text-[10px] text-slate-600 mt-1">{meta}</p>
      </div>
      {isSelected && (
        <div className="flex-shrink-0 mt-0.5">
          <kbd className="px-1.5 py-0.5 text-[9px] rounded bg-slate-700 text-slate-400 border border-slate-600/60">
            ↵
          </kbd>
        </div>
      )}
    </button>
  )
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ label, count }) {
  return (
    <div className="px-4 py-1.5 flex items-center gap-2 border-t border-slate-800/60 first:border-t-0">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-600">
        {label}
      </span>
      <span className="text-[10px] text-slate-700 bg-slate-800/60 rounded-full px-1.5 py-px">
        {count}
      </span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function GlobalSearch({ onClose, onNavigate }) {
  const [query,       setQuery]       = useState("")
  const [results,     setResults]     = useState(null)  // null = no search yet
  const [loading,     setLoading]     = useState(false)
  const [selectedIdx, setSelectedIdx] = useState(0)

  const inputRef    = useRef(null)
  const debounceRef = useRef(null)

  // Auto-focus input
  useEffect(() => { inputRef.current?.focus() }, [])

  // Debounced search
  const runSearch = useCallback((q) => {
    clearTimeout(debounceRef.current)
    if (!q || q.trim().length < 2) {
      setResults(null)
      setLoading(false)
      return
    }
    setLoading(true)
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await globalSearch(q.trim())
        setResults(data.results)
        setSelectedIdx(0)
      } catch {
        setResults(null)
      } finally {
        setLoading(false)
      }
    }, 300)
  }, [])

  const handleChange = (e) => {
    const q = e.target.value
    setQuery(q)
    runSearch(q)
  }

  // Flatten all sections into one list for keyboard nav
  const flatResults = results
    ? [
        ...( results.cards     || []).map(r => ({ ...r })),
        ...( results.bookmarks || []).map(r => ({ ...r })),
        ...( results.chats     || []).map(r => ({ ...r })),
      ]
    : []

  const total = flatResults.length

  const handleSelect = useCallback((result) => {
    if (result.type === "card") {
      onNavigate({ type: "feed", projectId: result.project_id })
    } else if (result.type === "bookmark") {
      onNavigate({ type: "bookmarks" })
    } else if (result.type === "chat") {
      onNavigate({ type: "chat", sessionId: result.session_id, sessionTitle: result.session_title })
    }
    onClose()
  }, [onNavigate, onClose])

  const handleKeyDown = (e) => {
    if (e.key === "Escape") { onClose(); return }
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setSelectedIdx(i => Math.min(i + 1, total - 1))
    }
    if (e.key === "ArrowUp") {
      e.preventDefault()
      setSelectedIdx(i => Math.max(i - 1, 0))
    }
    if (e.key === "Enter" && flatResults[selectedIdx]) {
      handleSelect(flatResults[selectedIdx])
    }
  }

  // Compute per-section flat indices for mapping
  const cardCount     = results?.cards?.length     || 0
  const bookmarkCount = results?.bookmarks?.length  || 0
  const chatCount     = results?.chats?.length      || 0
  const hasResults    = total > 0

  const isEmpty = query.trim().length >= 2 && !loading && !hasResults

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4"
      style={{ background: "var(--u-scrim)", backdropFilter: "blur(4px)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-[640px] bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl overflow-hidden"
        onKeyDown={handleKeyDown}
      >
        {/* Input row */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-slate-800/70">
          {loading
            ? <SpinnerIcon className="w-4 h-4 text-slate-500 animate-spin flex-shrink-0" />
            : <SearchIcon className="w-4 h-4 text-slate-500 flex-shrink-0" />
          }
          <input
            ref={inputRef}
            value={query}
            onChange={handleChange}
            placeholder="Search cards, bookmarks, chats…"
            className="flex-1 bg-transparent text-sm text-slate-100 placeholder-slate-600 outline-none"
          />
          {query && (
            <button
              onClick={() => { setQuery(""); setResults(null); inputRef.current?.focus() }}
              className="text-slate-600 hover:text-slate-400 transition-colors text-xs"
            >
              Clear
            </button>
          )}
          <kbd className="hidden sm:flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] rounded bg-slate-800 text-slate-500 border border-slate-700/60">
            Esc
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-[55vh] sm:max-h-[420px] overflow-y-auto">

          {/* Empty prompt */}
          {!query && (
            <div className="px-4 py-10 text-center">
              <SearchIcon className="w-6 h-6 text-slate-700 mx-auto mb-3" />
              <p className="text-sm text-slate-600">
                Type to search across your feed cards, bookmarks, and chat history.
              </p>
              <p className="text-xs text-slate-700 mt-1">
                Tip: use{" "}
                <kbd className="px-1 py-px rounded bg-slate-800 text-slate-500 border border-slate-700/60 text-[10px]">
                  ↑↓
                </kbd>{" "}
                to navigate,{" "}
                <kbd className="px-1 py-px rounded bg-slate-800 text-slate-500 border border-slate-700/60 text-[10px]">
                  ↵
                </kbd>{" "}
                to open.
              </p>
            </div>
          )}

          {/* No results */}
          {isEmpty && (
            <div className="px-4 py-10 text-center">
              <p className="text-sm text-slate-500">
                No results for <span className="text-slate-300">"{query}"</span>
              </p>
              <p className="text-xs text-slate-700 mt-1">Try a different keyword or shorter phrase.</p>
            </div>
          )}

          {/* Cards section */}
          {cardCount > 0 && (
            <>
              <SectionHeader label="Feed Cards" count={cardCount} />
              {results.cards.map((r, i) => (
                <ResultRow
                  key={`card-${r.insight_id}-${r.card_id}`}
                  result={r}
                  query={query}
                  isSelected={selectedIdx === i}
                  flatIdx={i}
                  onSelect={handleSelect}
                  onHover={setSelectedIdx}
                />
              ))}
            </>
          )}

          {/* Bookmarks section */}
          {bookmarkCount > 0 && (
            <>
              <SectionHeader label="Bookmarks" count={bookmarkCount} />
              {results.bookmarks.map((r, i) => (
                <ResultRow
                  key={`bm-${r.bookmark_id}`}
                  result={r}
                  query={query}
                  isSelected={selectedIdx === cardCount + i}
                  flatIdx={cardCount + i}
                  onSelect={handleSelect}
                  onHover={setSelectedIdx}
                />
              ))}
            </>
          )}

          {/* Chats section */}
          {chatCount > 0 && (
            <>
              <SectionHeader label="Chat Messages" count={chatCount} />
              {results.chats.map((r, i) => (
                <ResultRow
                  key={`chat-${r.session_id}-${i}`}
                  result={r}
                  query={query}
                  isSelected={selectedIdx === cardCount + bookmarkCount + i}
                  flatIdx={cardCount + bookmarkCount + i}
                  onSelect={handleSelect}
                  onHover={setSelectedIdx}
                />
              ))}
            </>
          )}

        </div>

        {/* Footer */}
        {hasResults && (
          <div className="px-4 py-2 border-t border-slate-800/60 flex items-center gap-4 text-[10px] text-slate-700">
            <span>{total} result{total !== 1 ? "s" : ""}</span>
            <span className="ml-auto hidden sm:flex items-center gap-2">
              <span><kbd className="px-1 rounded bg-slate-800 text-slate-500 border border-slate-700/50">↑↓</kbd> navigate</span>
              <span><kbd className="px-1 rounded bg-slate-800 text-slate-500 border border-slate-700/50">↵</kbd> open</span>
              <span><kbd className="px-1 rounded bg-slate-800 text-slate-500 border border-slate-700/50">esc</kbd> close</span>
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

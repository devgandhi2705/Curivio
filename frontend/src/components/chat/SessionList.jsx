import { useState, useRef, useEffect } from "react"
import { searchSessions } from "../../api/chat.js"
import { m, AnimatePresence, presets } from "../../lib/motion.jsx"
import PopMenu from "../shared/PopMenu.jsx"

// ─── Icons ────────────────────────────────────────────────────────────────────

function DotsIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <circle cx="3" cy="8" r="1.5" />
      <circle cx="8" cy="8" r="1.5" />
      <circle cx="13" cy="8" r="1.5" />
    </svg>
  )
}

// ─── Highlight matching text ──────────────────────────────────────────────────

function Highlight({ text, query }) {
  if (!query || !text) return <>{text}</>
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return <>{text}</>
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-blue-500/30 text-blue-200 not-italic rounded-sm px-0.5">
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  )
}

// ─── Session row ──────────────────────────────────────────────────────────────

function SessionRow({ session, isActive, onSelect, onRename, onDelete, query }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!menuOpen) return
    function onMouseDown(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [menuOpen])

  const displayTitle = session.title || session.first_topic_hint || "Conversation"
  const showSnippet  = query && session.match_snippet

  return (
    <div className={`u-nudge group relative rounded-lg transition-colors ${menuOpen ? "z-10" : ""} ${isActive ? "bg-white/[0.07]" : "hover:bg-white/[0.04]"}`}>
      <button onClick={() => onSelect(session)} className="w-full text-left px-3 py-2.5 pr-8 text-xs">
        <div className={`font-medium truncate ${isActive ? "text-slate-100" : "text-slate-300 hover:text-slate-100"}`}>
          <Highlight text={displayTitle} query={query} />
        </div>
        {showSnippet ? (
          <div className="text-slate-600 mt-0.5 text-[10px] leading-snug line-clamp-2">
            <Highlight text={session.match_snippet} query={query} />
          </div>
        ) : (
          <div className="text-slate-600 mt-0.5 text-[10px]">
            {session.message_count} msg{session.message_count !== 1 ? "s" : ""}
            {" · "}
            {formatRelativeTime(session.last_active_at)}
          </div>
        )}
      </button>
      {/* Desktop per-item action menu */}
      <div ref={menuRef} className="hidden md:block absolute right-1 top-1/2 -translate-y-1/2">
        <button
          onClick={(e) => { e.stopPropagation(); setMenuOpen(v => !v) }}
          className={`p-1 rounded text-slate-500 hover:text-slate-200 hover:bg-white/[0.08] transition-opacity ${menuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
          title="Actions"
        >
          <DotsIcon />
        </button>
        <AnimatePresence>
        {menuOpen && (
          <PopMenu key="menu" className="origin-top-right absolute right-0 top-full mt-1 z-50 min-w-[110px] bg-slate-800 border border-slate-700/50 rounded-lg shadow-xl py-1 overflow-hidden">
            <button
              onClick={() => { setMenuOpen(false); onRename?.(session) }}
              className="w-full text-left px-3 py-1.5 text-[11px] text-slate-300 hover:text-white hover:bg-white/[0.06] transition-colors"
            >
              Rename
            </button>
            <button
              onClick={() => { setMenuOpen(false); onDelete?.(session) }}
              className="w-full text-left px-3 py-1.5 text-[11px] text-red-400 hover:text-red-300 hover:bg-red-500/[0.08] transition-colors"
            >
              Delete
            </button>
          </PopMenu>
        )}
        </AnimatePresence>
      </div>
    </div>
  )
}

// ─── Inline content for unified sidebar Zone 3 ───────────────────────────────
// No <aside>, no own search input — query comes from the sidebar's Zone 3 field.

export function SessionListContent({ query = "", sessions, currentSessionId, onSelect, onNew, onRename, onDelete }) {
  const [results,   setResults]   = useState(null)
  const [searching, setSearching] = useState(false)
  const timerRef = useRef(null)

  useEffect(() => {
    clearTimeout(timerRef.current)
    if (!query.trim()) {
      setResults(null)
      setSearching(false)
      return
    }
    setSearching(true)
    timerRef.current = setTimeout(async () => {
      try {
        const data = await searchSessions(query.trim())
        setResults(data)
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, 250)
    return () => clearTimeout(timerRef.current)
  }, [query])

  const isSearchMode    = query.trim().length > 0
  const displaySessions = isSearchMode ? (results ?? []) : sessions
  const showEmpty       = !isSearchMode && sessions.length === 0
  const showNoResults   = isSearchMode && !searching && results !== null && results.length === 0

  return (
    <div className="relative flex flex-col gap-0.5">

      {/* New Chat button */}
      <button
        onClick={onNew}
        className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 mb-1.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.08] text-slate-400 hover:text-slate-100 text-[12px] font-medium transition-colors"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
          <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
        </svg>
        New chat
      </button>

      {/* Section label */}
      {!isSearchMode && sessions.length > 0 && (
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 px-1 pb-0.5 pt-0.5">
          Conversations
        </p>
      )}

      {/* Search: loading */}
      {isSearchMode && searching && (
        <p className="text-[11px] text-slate-600 px-2 py-2 text-center animate-pulse">Searching…</p>
      )}

      {/* Search: no results */}
      {showNoResults && (
        <div className="px-2 py-3 text-center">
          <p className="text-[11px] text-slate-500">No conversations found</p>
          <p className="text-[10px] text-slate-700 mt-0.5">for &ldquo;{query}&rdquo;</p>
        </div>
      )}

      {/* Empty state */}
      {showEmpty && (
        <p className="text-xs text-slate-600 px-2 py-2 text-center">No conversations yet</p>
      )}

      {/* Search result count */}
      {isSearchMode && !searching && results && results.length > 0 && (
        <p className="text-[9px] font-semibold uppercase tracking-widest text-slate-700 px-1 pb-0.5">
          {results.length} result{results.length !== 1 ? "s" : ""}
        </p>
      )}

      {/* Session rows */}
      <AnimatePresence mode="popLayout" initial={false}>
      {(!isSearchMode || !searching) && displaySessions.map(session => (
        <m.div key={session.session_id} {...presets.listItem}>
        <SessionRow
          session={session}
          isActive={session.session_id === currentSessionId}
          onSelect={onSelect}
          onRename={onRename}
          onDelete={onDelete}
          query={isSearchMode ? query : ""}
        />
        </m.div>
      ))}
      </AnimatePresence>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatRelativeTime(ts) {
  if (!ts) return ""
  try {
    const date = new Date(ts)
    const diffMs = Date.now() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    if (diffMins < 1)  return "just now"
    if (diffMins < 60) return `${diffMins}m ago`
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    return `${diffDays}d ago`
  } catch {
    return ""
  }
}

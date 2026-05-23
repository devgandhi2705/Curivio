import { useState, useRef, useEffect, useCallback } from "react"
import { searchSessions } from "../../api/chat.js"

// ─── Icons ────────────────────────────────────────────────────────────────────

function PencilIcon() {
  return (
    <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
      <path d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61Zm.176 4.823L9.75 4.81l-6.286 6.287a.253.253 0 0 0-.064.108l-.558 1.953 1.953-.558a.253.253 0 0 0 .108-.064l6.286-6.286Zm1.238-3.763a.25.25 0 0 0-.354 0L10.811 3.75l1.439 1.44 1.263-1.263a.25.25 0 0 0 0-.354l-1.086-1.086Z" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
      <path d="M11 1.75V3h2.25a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75ZM4.496 6.675l.66 6.6a.25.25 0 0 0 .249.225h5.19a.25.25 0 0 0 .249-.225l.66-6.6a.75.75 0 0 1 1.492.149l-.66 6.6A1.748 1.748 0 0 1 10.595 15h-5.19a1.75 1.75 0 0 1-1.741-1.575l-.66-6.6a.75.75 0 1 1 1.492-.15ZM6.5 1.75V3h3V1.75a.25.25 0 0 0-.25-.25h-2.5a.25.25 0 0 0-.25.25Z" />
    </svg>
  )
}

function SearchIcon() {
  return (
    <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
      <path d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z" />
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
  const [editing,    setEditing]    = useState(false)
  const [draft,      setDraft]      = useState("")
  const [confirmDel, setConfirmDel] = useState(false)
  const inputRef = useRef(null)

  const displayTitle = session.title || session.first_topic_hint || "Conversation"
  const showSnippet  = query && session.match_snippet

  const startEdit = useCallback((e) => {
    e.stopPropagation()
    setDraft(session.title || session.first_topic_hint || "")
    setEditing(true)
    setConfirmDel(false)
  }, [session.title, session.first_topic_hint])

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [editing])

  function commitEdit() {
    const trimmed = draft.trim()
    if (trimmed && trimmed !== displayTitle) onRename(session.session_id, trimmed)
    setEditing(false)
  }

  function handleKeyDown(e) {
    if (e.key === "Enter")  { e.preventDefault(); commitEdit() }
    if (e.key === "Escape") { setEditing(false) }
    e.stopPropagation()
  }

  function handleDeleteClick(e) {
    e.stopPropagation()
    setConfirmDel(true)
    setEditing(false)
  }

  function handleConfirmDelete(e) {
    e.stopPropagation()
    onDelete(session.session_id)
  }

  function handleCancelDelete(e) {
    e.stopPropagation()
    setConfirmDel(false)
  }

  return (
    <div
      className={`group relative rounded-lg transition-colors ${
        isActive ? "bg-white/[0.07]" : "hover:bg-white/[0.04]"
      }`}
    >
      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={handleKeyDown}
          maxLength={100}
          className="w-full px-3 py-2.5 bg-transparent text-xs text-slate-100 focus:outline-none rounded-lg ring-1 ring-blue-500/50"
          onClick={e => e.stopPropagation()}
        />
      ) : confirmDel ? (
        <div className="px-3 py-2.5 flex items-center justify-between gap-2">
          <span className="text-xs text-slate-400 truncate">Delete?</span>
          <div className="flex gap-1 flex-shrink-0">
            <button
              onClick={handleConfirmDelete}
              className="px-2 py-0.5 text-[10px] rounded bg-red-900/60 text-red-300 hover:bg-red-800/70 transition-colors"
            >
              Delete
            </button>
            <button
              onClick={handleCancelDelete}
              className="px-2 py-0.5 text-[10px] rounded bg-slate-700/60 text-slate-400 hover:bg-slate-700 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => onSelect(session)}
          className="w-full text-left px-3 py-2.5 text-xs"
        >
          <div className={`font-medium truncate pr-12 ${isActive ? "text-slate-100" : "text-slate-300 group-hover:text-slate-100"}`}>
            <Highlight text={displayTitle} query={query} />
          </div>
          {showSnippet ? (
            <div className="text-slate-600 mt-0.5 text-[10px] leading-snug line-clamp-2 pr-12">
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
      )}

      {!editing && !confirmDel && (
        <div className="absolute right-1.5 top-1/2 -translate-y-1/2 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={startEdit}
            title="Rename"
            className="p-1 rounded text-slate-600 hover:text-slate-300 hover:bg-slate-700/60 transition-colors"
          >
            <PencilIcon />
          </button>
          <button
            onClick={handleDeleteClick}
            title="Delete"
            className="p-1 rounded text-slate-600 hover:text-red-400 hover:bg-red-950/40 transition-colors"
          >
            <TrashIcon />
          </button>
        </div>
      )}
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
    <div className="flex flex-col gap-0.5">

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
      {(!isSearchMode || !searching) && displaySessions.map(session => (
        <SessionRow
          key={session.session_id}
          session={session}
          isActive={session.session_id === currentSessionId}
          onSelect={onSelect}
          onRename={onRename}
          onDelete={onDelete}
          query={isSearchMode ? query : ""}
        />
      ))}
    </div>
  )
}

// ─── Main export (standalone drawer, kept for potential future use) ────────────

export default function SessionList({ sessions, currentSessionId, onSelect, onNew, onRename, onDelete, onMobileClose }) {
  const [query,     setQuery]     = useState("")
  const [results,   setResults]   = useState(null)  // null = not in search mode
  const [searching, setSearching] = useState(false)
  const timerRef = useRef(null)

  function handleQueryChange(e) {
    const q = e.target.value
    setQuery(q)
    clearTimeout(timerRef.current)

    if (!q.trim()) {
      setResults(null)
      setSearching(false)
      return
    }

    setSearching(true)
    timerRef.current = setTimeout(async () => {
      try {
        const data = await searchSessions(q.trim())
        setResults(data)
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, 250)
  }

  function clearSearch() {
    clearTimeout(timerRef.current)
    setQuery("")
    setResults(null)
    setSearching(false)
  }

  const isSearchMode    = query.trim().length > 0
  const displaySessions = isSearchMode ? (results ?? []) : sessions
  const showEmpty       = !isSearchMode && sessions.length === 0
  const showNoResults   = isSearchMode && !searching && results !== null && results.length === 0

  return (
    <aside className="fixed left-0 top-0 bottom-0 z-30 md:static md:inset-auto w-64 flex-shrink-0 flex flex-col border-r border-slate-800 bg-slate-950">

      {/* Header: New chat + search input */}
      <div className="p-3 border-b border-slate-800 flex flex-col gap-2">
        <button
          onClick={onNew}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium transition-colors"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
            <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
          </svg>
          New chat
        </button>

        {/* Search input */}
        <div className="relative">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none">
            <SearchIcon />
          </span>
          <input
            type="text"
            value={query}
            onChange={handleQueryChange}
            placeholder="Search conversations…"
            className="w-full bg-slate-900/80 border border-slate-800 hover:border-slate-700 focus:border-slate-600 rounded-lg pl-7 pr-7 py-1.5 text-[11px] text-slate-300 placeholder-slate-600 focus:outline-none transition-colors"
          />
          {query && (
            <button
              onClick={clearSearch}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400 transition-colors leading-none"
              title="Clear search"
            >
              <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
                <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Session list / search results */}
      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">

        {/* Search mode: loading */}
        {isSearchMode && searching && (
          <p className="text-[11px] text-slate-600 px-2 py-3 text-center animate-pulse">
            Searching…
          </p>
        )}

        {/* Search mode: no results */}
        {showNoResults && (
          <div className="px-2 py-4 text-center">
            <p className="text-[11px] text-slate-500">No conversations found</p>
            <p className="text-[10px] text-slate-700 mt-0.5">for "{query}"</p>
          </div>
        )}

        {/* Normal empty state */}
        {showEmpty && (
          <p className="text-xs text-slate-600 px-2 py-3 text-center">No previous sessions</p>
        )}

        {/* Count label when in search mode with results */}
        {isSearchMode && !searching && results && results.length > 0 && (
          <p className="text-[9px] font-semibold uppercase tracking-widest text-slate-700 px-2 pt-1 pb-1">
            {results.length} result{results.length !== 1 ? "s" : ""}
          </p>
        )}

        {/* Results (search or normal) */}
        {(!isSearchMode || !searching) && displaySessions.map(session => (
          <SessionRow
            key={session.session_id}
            session={session}
            isActive={session.session_id === currentSessionId}
            onSelect={onSelect}
            onRename={onRename}
            onDelete={onDelete}
            query={isSearchMode ? query : ""}
          />
        ))}
      </div>
    </aside>
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

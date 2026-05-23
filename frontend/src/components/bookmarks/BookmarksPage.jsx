import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  fetchCollections, fetchBookmarks,
  deleteBookmark, deleteCollection,
  createCollection, updateCollection,
} from '../../api/bookmarks.js'
import CollectionPickerModal from './CollectionPickerModal.jsx'
import { useSidebarSubsection } from '../../contexts/SidebarSubsection.jsx'
import { useContextMenu } from '../../contexts/ContextMenu.jsx'

// ── Color palette ──────────────────────────────────────────────────────────────

const COLOR_DOT = {
  blue:    'bg-blue-500',
  violet:  'bg-violet-500',
  emerald: 'bg-emerald-500',
  amber:   'bg-amber-500',
  rose:    'bg-rose-500',
  cyan:    'bg-cyan-500',
}

const COLOR_BORDER = {
  blue:    'border-blue-500/40',
  violet:  'border-violet-500/40',
  emerald: 'border-emerald-500/40',
  amber:   'border-amber-500/40',
  rose:    'border-rose-500/40',
  cyan:    'border-cyan-500/40',
}

const COLOR_TEXT = {
  blue:    'text-blue-400',
  violet:  'text-violet-400',
  emerald: 'text-emerald-400',
  amber:   'text-amber-400',
  rose:    'text-rose-400',
  cyan:    'text-cyan-400',
}

const COLOR_BG = {
  blue:    'bg-blue-500/10',
  violet:  'bg-violet-500/10',
  emerald: 'bg-emerald-500/10',
  amber:   'bg-amber-500/10',
  rose:    'bg-rose-500/10',
  cyan:    'bg-cyan-500/10',
}

// ── Content type labels ────────────────────────────────────────────────────────

const TYPE_LABEL = {
  feed_article:    { label: 'Article',       color: 'text-blue-400   bg-blue-500/10   border-blue-500/20'   },
  curiosity:       { label: 'Curiosity',     color: 'text-amber-400  bg-amber-500/10  border-amber-500/20'  },
  deep_research:   { label: 'Research',      color: 'text-violet-400 bg-violet-500/10 border-violet-500/20' },
  chat_insight:    { label: 'Chat Insight',  color: 'text-cyan-400   bg-cyan-500/10   border-cyan-500/20'   },
  resource_link:   { label: 'Resource',      color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' },
  external:        { label: 'External',      color: 'text-slate-400  bg-slate-500/10  border-slate-500/20'  },
}

function typeBadge(ct) {
  const t = TYPE_LABEL[ct] ?? { label: ct, color: 'text-slate-400 bg-slate-800 border-slate-700' }
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${t.color}`}>
      {t.label}
    </span>
  )
}

function formatDate(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch { return '' }
}

// ── Bookmark card ─────────────────────────────────────────────────────────────

function BookmarkCard({ bookmark, onDelete, onOpenChat }) {
  const [deleting, setDeleting] = useState(false)

  async function handleDelete(e) {
    e.stopPropagation()
    setDeleting(true)
    try { await deleteBookmark(bookmark.bookmark_id); onDelete(bookmark.bookmark_id) } catch { setDeleting(false) }
  }

  return (
    <div className="group relative flex flex-col gap-2 p-4 bg-slate-900/60 border border-slate-800 rounded-xl hover:border-slate-700 transition-all">
      {/* Top row */}
      <div className="flex items-start gap-2 justify-between">
        <div className="flex items-center gap-1.5 flex-wrap">
          {typeBadge(bookmark.content_type)}
          {bookmark.project_name && (
            <span className="px-1.5 py-0.5 rounded text-[10px] border border-slate-700 text-slate-500 bg-slate-800/60">
              {bookmark.project_name}
            </span>
          )}
        </div>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="opacity-0 group-hover:opacity-100 p-1 rounded text-slate-600 hover:text-red-400 hover:bg-red-950/40 transition-all flex-shrink-0"
        >
          <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
            <path d="M11 1.75V3h2.25a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75ZM4.496 6.675l.66 6.6a.25.25 0 0 0 .249.225h5.19a.25.25 0 0 0 .249-.225l.66-6.6a.75.75 0 0 1 1.492.149l-.66 6.6A1.748 1.748 0 0 1 10.595 15h-5.19a1.75 1.75 0 0 1-1.741-1.575l-.66-6.6a.75.75 0 1 1 1.492-.15Z" />
          </svg>
        </button>
      </div>

      {/* Title */}
      <h3 className="text-sm font-semibold text-slate-100 leading-snug">
        {bookmark.source_url ? (
          <a href={bookmark.source_url} target="_blank" rel="noopener noreferrer" className="hover:text-blue-300 transition-colors">
            {bookmark.title}
          </a>
        ) : bookmark.title}
      </h3>

      {/* Summary */}
      {bookmark.summary && (
        <p className="text-xs text-slate-400 leading-relaxed line-clamp-2">{bookmark.summary}</p>
      )}

      {/* AI notes */}
      {bookmark.ai_generated_notes && (
        <div className="flex gap-2 mt-1">
          <div className="flex-shrink-0 w-0.5 rounded-full bg-violet-500/40 self-stretch" />
          <p className="text-[11px] text-slate-500 leading-relaxed italic">{bookmark.ai_generated_notes}</p>
        </div>
      )}

      {/* Tags */}
      {bookmark.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {bookmark.tags.map((tag, i) => (
            <span key={i} className="px-1.5 py-0.5 rounded-md text-[10px] bg-slate-800 text-slate-500 border border-slate-700/50">
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* Related topics */}
      {bookmark.related_topics?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {bookmark.related_topics.map((t, i) => (
            <span key={i} className="px-1.5 py-0.5 rounded-full text-[10px] text-slate-500 border border-slate-700/30">
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between pt-1 mt-auto">
        <span className="text-[10px] text-slate-600">{formatDate(bookmark.saved_at)}</span>
        <div className="flex items-center gap-2">
          {bookmark.source_type === 'chat' && bookmark.conversation_reference && (
            <button
              onClick={() => onOpenChat?.(bookmark.conversation_reference)}
              className="text-[10px] text-violet-500 hover:text-violet-300 transition-colors flex items-center gap-0.5"
            >
              <svg className="w-2.5 h-2.5" viewBox="0 0 16 16" fill="currentColor">
                <path d="M14 1a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H4.414A2 2 0 0 0 3 11.586l-2 2V2a1 1 0 0 1 1-1h12Z" />
              </svg>
              View Chat
            </button>
          )}
          {bookmark.source_url && (
            <a
              href={bookmark.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[10px] text-slate-600 hover:text-blue-400 transition-colors flex items-center gap-0.5"
            >
              <svg className="w-2.5 h-2.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <path d="M6.5 9.5l4-4M9.5 5.5h3v3M10 10.5v3.5H2V6h3.5" />
              </svg>
              Open
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Collection sidebar item ───────────────────────────────────────────────────

function CollectionItem({ col, isActive, onClick }) {
  return (
    <button
      onClick={() => onClick(col.collection_id)}
      className={`w-full flex items-start gap-2.5 px-3 py-2 rounded-lg transition-colors text-left ${
        isActive ? 'bg-white/[0.07] text-white' : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]'
      }`}
    >
      <div className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${COLOR_DOT[col.color] ?? 'bg-blue-500'}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-1">
          <span className="text-sm font-medium truncate">{col.name}</span>
          <span className="text-[10px] text-slate-500 flex-shrink-0">{col.bookmark_count}</span>
        </div>
        {col.description && (
          <p className={`text-[11px] leading-snug mt-0.5 truncate ${isActive ? 'text-slate-400' : 'text-slate-500'}`}>
            {col.description}
          </p>
        )}
      </div>
    </button>
  )
}

// ── Filter bar ────────────────────────────────────────────────────────────────

const CONTENT_TYPES = [
  { value: '', label: 'All types' },
  { value: 'feed_article',  label: 'Articles'  },
  { value: 'deep_research', label: 'Research'  },
  { value: 'chat_insight',  label: 'Insights'  },
  { value: 'resource_link', label: 'Resources' },
]

// ── New collection modal ──────────────────────────────────────────────────────

const COLOR_OPTIONS = [
  { key: 'blue',    cls: 'bg-blue-500'    },
  { key: 'violet',  cls: 'bg-violet-500'  },
  { key: 'emerald', cls: 'bg-emerald-500' },
  { key: 'amber',   cls: 'bg-amber-500'   },
  { key: 'rose',    cls: 'bg-rose-500'    },
  { key: 'cyan',    cls: 'bg-cyan-500'    },
]

function NewCollectionModal({ onClose, onCreate }) {
  const [name,  setName]  = useState('')
  const [desc,  setDesc]  = useState('')
  const [color, setColor] = useState('blue')
  const [busy,  setBusy]  = useState(false)

  async function handleCreate() {
    if (!name.trim()) return
    setBusy(true)
    try {
      const col = await createCollection({ name: name.trim(), description: desc.trim(), color })
      onCreate(col)
      onClose()
    } finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div className="relative w-full max-w-sm bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl p-6 space-y-4" onClick={e => e.stopPropagation()}>
        <h2 className="text-sm font-semibold text-slate-100">New collection</h2>
        <input
          autoFocus value={name} onChange={e => setName(e.target.value)}
          placeholder="Collection name"
          className="w-full bg-slate-800 text-sm text-slate-100 placeholder-slate-500 px-3 py-2.5 rounded-xl border border-slate-700 focus:outline-none focus:border-blue-500/60"
          onKeyDown={e => { if (e.key === 'Enter') handleCreate() }}
        />
        <input
          value={desc} onChange={e => setDesc(e.target.value)}
          placeholder="Description (optional)"
          className="w-full bg-slate-800 text-sm text-slate-100 placeholder-slate-500 px-3 py-2.5 rounded-xl border border-slate-700 focus:outline-none focus:border-blue-500/60"
        />
        <div className="flex gap-2">
          {COLOR_OPTIONS.map(c => (
            <button key={c.key} onClick={() => setColor(c.key)}
              className={`w-6 h-6 rounded-full ${c.cls} transition-transform ${color === c.key ? 'ring-2 ring-white/60 scale-110' : 'opacity-50 hover:opacity-80'}`} />
          ))}
        </div>
        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 py-2 text-sm rounded-xl text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">Cancel</button>
          <button onClick={handleCreate} disabled={!name.trim() || busy}
            className="flex-1 py-2 text-sm rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-medium transition-colors">
            Create
          </button>
        </div>
      </div>
    </div>
  )
}

function EditCollectionModal({ col, onClose, onSave }) {
  const [name,  setName]  = useState(col.name || '')
  const [desc,  setDesc]  = useState(col.description || '')
  const [color, setColor] = useState(col.color || 'blue')
  const [busy,  setBusy]  = useState(false)

  async function handleSave() {
    if (!name.trim()) return
    setBusy(true)
    try { await onSave({ name: name.trim(), description: desc.trim(), color }) } finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div className="relative w-full max-w-sm bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl p-6 space-y-4" onClick={e => e.stopPropagation()}>
        <h2 className="text-sm font-semibold text-slate-100">Edit collection</h2>
        <input
          autoFocus value={name} onChange={e => setName(e.target.value)}
          placeholder="Collection name"
          className="w-full bg-slate-800 text-sm text-slate-100 placeholder-slate-500 px-3 py-2.5 rounded-xl border border-slate-700 focus:outline-none focus:border-blue-500/60"
          onKeyDown={e => { if (e.key === 'Enter') handleSave() }}
        />
        <input
          value={desc} onChange={e => setDesc(e.target.value)}
          placeholder="Description (optional)"
          className="w-full bg-slate-800 text-sm text-slate-100 placeholder-slate-500 px-3 py-2.5 rounded-xl border border-slate-700 focus:outline-none focus:border-blue-500/60"
        />
        <div className="flex gap-2">
          {COLOR_OPTIONS.map(c => (
            <button key={c.key} onClick={() => setColor(c.key)}
              className={`w-6 h-6 rounded-full ${c.cls} transition-transform ${color === c.key ? 'ring-2 ring-white/60 scale-110' : 'opacity-50 hover:opacity-80'}`} />
          ))}
        </div>
        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 py-2 text-sm rounded-xl text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">Cancel</button>
          <button onClick={handleSave} disabled={!name.trim() || busy}
            className="flex-1 py-2 text-sm rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-medium transition-colors">
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Rename modal ──────────────────────────────────────────────────────────────

function RenameModal({ heading, initialValue, onConfirm, onClose }) {
  const [value, setValue] = useState(initialValue)
  const inputRef = useRef(null)
  useEffect(() => { inputRef.current?.focus(); inputRef.current?.select() }, [])
  function handleKeyDown(e) {
    if (e.key === 'Enter' && value.trim()) { e.preventDefault(); onConfirm(value.trim()) }
    if (e.key === 'Escape') onClose()
    e.stopPropagation()
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div className="relative w-full max-w-xs bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl p-5 space-y-3" onClick={e => e.stopPropagation()}>
        <h2 className="text-sm font-semibold text-slate-200">{heading}</h2>
        <input
          ref={inputRef}
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          maxLength={120}
          className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500/60"
        />
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 py-2 text-sm rounded-xl text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">Cancel</button>
          <button onClick={() => value.trim() && onConfirm(value.trim())} disabled={!value.trim()} className="flex-1 py-2 text-sm rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-medium transition-colors">Rename</button>
        </div>
      </div>
    </div>
  )
}

// ── Delete confirmation modal ─────────────────────────────────────────────────

function DeleteConfirmModal({ name, message, onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onCancel}>
      <div className="relative w-full max-w-sm bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-3 mb-3">
          <div className="w-9 h-9 rounded-xl bg-red-950/60 border border-red-900/50 flex items-center justify-center flex-shrink-0">
            <svg className="w-4 h-4 text-red-400" viewBox="0 0 16 16" fill="currentColor">
              <path d="M11 1.75V3h2.25a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75ZM4.496 6.675l.66 6.6a.25.25 0 0 0 .249.225h5.19a.25.25 0 0 0 .249-.225l.66-6.6a.75.75 0 0 1 1.492.149l-.66 6.6A1.748 1.748 0 0 1 10.595 15h-5.19a1.75 1.75 0 0 1-1.741-1.575l-.66-6.6a.75.75 0 1 1 1.492-.15Z" />
            </svg>
          </div>
          <div>
            <h3 className="font-semibold text-slate-100 text-sm">Delete "{name}"?</h3>
            <p className="text-xs text-slate-500 mt-0.5">This cannot be undone.</p>
          </div>
        </div>
        {message && <p className="text-sm text-slate-400 mb-5 leading-relaxed">{message}</p>}
        <div className="flex gap-3">
          <button onClick={onCancel} className="flex-1 px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-700/50 transition-colors">Cancel</button>
          <button onClick={onConfirm} className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-red-600 hover:bg-red-500 text-white transition-colors">Delete</button>
        </div>
      </div>
    </div>
  )
}

// ── Collections subsection — rendered inside App sidebar's Zone 3 ─────────────

function BookmarksSubsection({ collections, activeId, colLoading, onSelect, onNew }) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-1 mb-2 flex-shrink-0">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">Collections</span>
        <button
          onClick={onNew}
          className="p-1 rounded text-slate-500 hover:text-slate-200 hover:bg-white/[0.06] transition-colors"
          title="New collection"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
            <path d="M7.75 2a.75.75 0 0 1 .75.75V7h4.25a.75.75 0 0 1 0 1.5H8.5v4.25a.75.75 0 0 1-1.5 0V8.5H2.75a.75.75 0 0 1 0-1.5H7V2.75A.75.75 0 0 1 7.75 2Z" />
          </svg>
        </button>
      </div>
      <div className="flex-1 space-y-0.5 overflow-y-auto min-h-0">
        {colLoading ? (
          <div className="space-y-1">
            {[1,2,3].map(i => <div key={i} className="h-8 bg-slate-800/40 rounded-lg animate-pulse" />)}
          </div>
        ) : collections.length === 0 ? (
          <p className="text-xs text-slate-600 px-1 py-2">No collections yet.</p>
        ) : (
          collections.map(col => (
            <CollectionItem
              key={col.collection_id}
              col={col}
              isActive={activeId === col.collection_id}
              onClick={onSelect}
            />
          ))
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BookmarksPage({ onOpenChat, onSidebarClose }) {
  const [collections,    setCollections]    = useState([])
  const [bookmarks,      setBookmarks]      = useState([])
  const [activeId,       setActiveId]       = useState(null)
  const [colLoading,     setColLoading]     = useState(true)
  const [bmLoading,      setBmLoading]      = useState(false)
  const [search,         setSearch]         = useState('')
  const [typeFilter,     setTypeFilter]     = useState('')
  const [showNewCol,        setShowNewCol]        = useState(false)
  const [editingCol,        setEditingCol]        = useState(null)
  const [pendingDeleteCol,  setPendingDeleteCol]  = useState(null)
  const [showRenameCol,     setShowRenameCol]     = useState(false)
  const [renameColDraft,    setRenameColDraft]    = useState('')

  const { register, unregister } = useSidebarSubsection()
  const { setViewActions, clearViewActions } = useContextMenu()
  const subsectionHandlers = useRef({})

  // Update handler refs every render so the registered render fn always calls current handlers
  useEffect(() => {
    subsectionHandlers.current = {
      onSelect: (id) => { setActiveId(id); onSidebarClose?.() },
      onNew:    () => setShowNewCol(true),
    }
  })

  // Register subsection — cleanup on unmount since BookmarksPage is conditionally mounted
  useEffect(() => {
    register('bookmarks', (query) => {
      const q = query?.trim().toLowerCase() ?? ''
      const filtered = q
        ? collections.filter(c => c.name.toLowerCase().includes(q))
        : collections
      return (
        <BookmarksSubsection
          collections={filtered}
          activeId={activeId}
          colLoading={colLoading}
          onSelect={(id) => subsectionHandlers.current.onSelect(id)}
          onNew={() => subsectionHandlers.current.onNew()}
        />
      )
    })
    return () => unregister('bookmarks')
  }, [register, unregister, collections, activeId, colLoading])

  // Register contextual ⋮ actions for the bookmarks view
  useEffect(() => {
    if (!activeCol) { clearViewActions('bookmarks'); return }
    setViewActions('bookmarks', [
      {
        label: 'Rename collection',
        onClick: () => { setRenameColDraft(activeCol.name || ''); setShowRenameCol(true) },
      },
      { label: 'Edit collection', onClick: () => setEditingCol(activeCol) },
      { label: 'Delete collection', variant: 'danger', onClick: () => setPendingDeleteCol(activeCol) },
    ])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCol])

  // Load collections on mount
  useEffect(() => {
    fetchCollections()
      .then(cols => { setCollections(cols); if (cols.length > 0) setActiveId(cols[0].collection_id) })
      .finally(() => setColLoading(false))
  }, [])

  // Silently refresh sidebar counts without resetting active selection
  const refreshCounts = useCallback(() => {
    fetchCollections().then(cols => {
      setCollections(prev => cols.map(fresh => {
        const current = prev.find(c => c.collection_id === fresh.collection_id)
        return current ? { ...current, bookmark_count: fresh.bookmark_count } : fresh
      }))
    })
  }, [])

  // Load bookmarks only after collections have resolved (so activeId is the first collection, not null)
  useEffect(() => {
    if (colLoading) return
    setBmLoading(true)
    fetchBookmarks({
      collection_id: activeId ?? undefined,
      content_type:  typeFilter || undefined,
      search:        search     || undefined,
    })
      .then(setBookmarks)
      .finally(() => setBmLoading(false))
  }, [activeId, typeFilter, search, colLoading])

  const activeCol = useMemo(
    () => collections.find(c => c.collection_id === activeId),
    [collections, activeId]
  )

  function handleDeleteBookmark(bmId) {
    setBookmarks(prev => prev.filter(b => b.bookmark_id !== bmId))
    refreshCounts()
  }

  function handleCollectionCreated(col) {
    setCollections(prev => [col, ...prev])
    setActiveId(col.collection_id)
  }

  async function handleDeleteCollection(colId) {
    try {
      await deleteCollection(colId)
      setCollections(prev => {
        const next = prev.filter(c => c.collection_id !== colId)
        setActiveId(next.length > 0 ? next[0].collection_id : null)
        return next
      })
      setBookmarks([])
    } catch {}
  }

  async function handleEditCollection(col, fields) {
    try {
      const updated = await updateCollection(col.collection_id, fields)
      setCollections(prev => prev.map(c => c.collection_id === col.collection_id ? { ...c, ...updated } : c))
    } catch {}
    setEditingCol(null)
  }

  async function handleRenameCollection(newName) {
    if (!activeCol || !newName.trim()) return
    try {
      const updated = await updateCollection(activeCol.collection_id, { ...activeCol, name: newName.trim() })
      setCollections(prev => prev.map(c => c.collection_id === activeCol.collection_id ? { ...c, ...updated } : c))
    } catch {}
    setShowRenameCol(false)
  }

  return (
    <div className="py-6 px-4 sm:px-8">

      {/* Search bar */}
      <div className="flex items-center gap-3 mb-6">
        <div className="relative flex-1 max-w-sm">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" viewBox="0 0 16 16" fill="currentColor">
            <path d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z" />
          </svg>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search bookmarks…"
            className="w-full pl-9 pr-3 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-600 transition-colors"
          />
        </div>
      </div>

      {/* Bookmark grid */}
      {bmLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1,2,3,4,5,6].map(i => (
            <div key={i} className="h-48 bg-slate-800/30 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : bookmarks.length === 0 ? (
        <EmptyState activeCol={activeCol} hasFilters={!!search || !!typeFilter} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {bookmarks.map(bm => (
            <BookmarkCard key={bm.bookmark_id} bookmark={bm} onDelete={handleDeleteBookmark} onOpenChat={onOpenChat} />
          ))}
        </div>
      )}

      {showNewCol && (
        <NewCollectionModal
          onClose={() => setShowNewCol(false)}
          onCreate={handleCollectionCreated}
        />
      )}

      {editingCol && (
        <EditCollectionModal
          col={editingCol}
          onClose={() => setEditingCol(null)}
          onSave={(fields) => handleEditCollection(editingCol, fields)}
        />
      )}

      {showRenameCol && (
        <RenameModal
          heading="Rename collection"
          initialValue={renameColDraft}
          onConfirm={handleRenameCollection}
          onClose={() => setShowRenameCol(false)}
        />
      )}

      {pendingDeleteCol && (
        <DeleteConfirmModal
          name={pendingDeleteCol.name}
          message="All bookmarks inside will be unassigned."
          onConfirm={async () => { await handleDeleteCollection(pendingDeleteCol.collection_id); setPendingDeleteCol(null) }}
          onCancel={() => setPendingDeleteCol(null)}
        />
      )}
    </div>
  )
}

function EmptyState({ activeCol, hasFilters }) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 min-h-[40vh] text-center">
      <div className="w-12 h-12 rounded-2xl bg-slate-800 flex items-center justify-center mb-4">
        <svg className="w-5 h-5 text-slate-500" viewBox="0 0 16 16" fill="currentColor">
          <path d="M3 2.75C3 1.784 3.784 1 4.75 1h6.5C12.216 1 13 1.784 13 2.75v10.5a.75.75 0 0 1-1.2.6l-3.8-2.85-3.8 2.85A.75.75 0 0 1 3 13.25Zm1.75-.25a.25.25 0 0 0-.25.25v9.386l3.05-2.287a.75.75 0 0 1 .9 0l3.05 2.287V2.75a.25.25 0 0 0-.25-.25Z" />
        </svg>
      </div>
      <h3 className="text-sm font-semibold text-slate-300 mb-1">
        {hasFilters ? 'No bookmarks match your filters' : activeCol ? `${activeCol.name} is empty` : 'No bookmarks yet'}
      </h3>
      <p className="text-xs text-slate-600 max-w-xs leading-relaxed">
        {hasFilters
          ? 'Try removing filters or search for something else.'
          : 'Save articles, research reports, and chat insights from anywhere in the app using the bookmark button.'}
      </p>
    </div>
  )
}

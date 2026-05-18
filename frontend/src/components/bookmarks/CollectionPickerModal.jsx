import { useState, useEffect, useCallback } from 'react'
import { fetchCollections, fetchBookmarks, createCollection, saveBookmark, deleteBookmark } from '../../api/bookmarks.js'

const COLOR_OPTIONS = [
  { key: 'blue',    cls: 'bg-blue-500'    },
  { key: 'violet',  cls: 'bg-violet-500'  },
  { key: 'emerald', cls: 'bg-emerald-500' },
  { key: 'amber',   cls: 'bg-amber-500'   },
  { key: 'rose',    cls: 'bg-rose-500'    },
  { key: 'cyan',    cls: 'bg-cyan-500'    },
]

const COLOR_DOT = {
  blue:    'bg-blue-500',
  violet:  'bg-violet-500',
  emerald: 'bg-emerald-500',
  amber:   'bg-amber-500',
  rose:    'bg-rose-500',
  cyan:    'bg-cyan-500',
}

export default function CollectionPickerModal({ bookmarkData, onClose, onSaved }) {
  const [collections, setCollections] = useState([])
  // collection_id → bookmark_id for bookmarks that already exist
  const [existingMap, setExistingMap] = useState({})
  // current checked state (includes pre-existing + newly toggled)
  const [checked,     setChecked]     = useState(new Set())
  const [loading,     setLoading]     = useState(true)
  const [saving,      setSaving]      = useState(false)
  const [creating,    setCreating]    = useState(false)
  const [newName,     setNewName]     = useState('')
  const [newDesc,     setNewDesc]     = useState('')
  const [newColor,    setNewColor]    = useState('blue')
  const [error,       setError]       = useState(null)

  useEffect(() => {
    Promise.all([
      fetchCollections(),
      fetchBookmarks({ search: bookmarkData.title }),
    ])
      .then(([cols, existing]) => {
        setCollections(cols)
        const map = {}
        const initialChecked = new Set()
        existing
          .filter(b => b.title === bookmarkData.title)
          .forEach(b => {
            map[b.collection_id] = b.bookmark_id
            initialChecked.add(b.collection_id)
          })
        setExistingMap(map)
        setChecked(initialChecked)
      })
      .catch(() => setError('Could not load collections'))
      .finally(() => setLoading(false))
  }, [bookmarkData.title])

  function toggleCollection(id) {
    setChecked(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const handleCreateCollection = useCallback(async () => {
    if (!newName.trim()) return
    try {
      const col = await createCollection({ name: newName.trim(), description: newDesc.trim(), color: newColor })
      setCollections(prev => [col, ...prev])
      setChecked(prev => new Set([...prev, col.collection_id]))
      setCreating(false)
      setNewName(''); setNewDesc(''); setNewColor('blue')
    } catch {
      setError('Could not create collection')
    }
  }, [newName, newDesc, newColor])

  const handleSave = useCallback(async () => {
    setSaving(true)
    setError(null)
    try {
      const ops = []
      // Add to newly checked collections
      for (const cid of checked) {
        if (!existingMap[cid]) {
          ops.push(saveBookmark({ ...bookmarkData, collection_id: cid }))
        }
      }
      // Remove from unchecked collections that previously had this bookmark
      for (const [cid, bmId] of Object.entries(existingMap)) {
        if (!checked.has(cid)) {
          ops.push(deleteBookmark(bmId))
        }
      }
      await Promise.all(ops)
      onSaved?.()
    } catch {
      setError('Could not save changes')
      setSaving(false)
    }
  }, [checked, existingMap, bookmarkData, onSaved])

  const addCount    = [...checked].filter(cid => !existingMap[cid]).length
  const removeCount = Object.keys(existingMap).filter(cid => !checked.has(cid)).length
  const hasChanges  = addCount > 0 || removeCount > 0

  function buttonLabel() {
    if (saving) return 'Saving…'
    if (!hasChanges) return 'No changes'
    const parts = []
    if (addCount > 0)    parts.push(`Add to ${addCount}`)
    if (removeCount > 0) parts.push(`Remove from ${removeCount}`)
    return parts.join(' · ')
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={e => { e.stopPropagation(); onClose() }}
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-sm bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl shadow-black/60 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-4 border-b border-slate-800">
          <div>
            <h2 className="text-sm font-semibold text-slate-100">Save to collections</h2>
            <p className="text-xs text-slate-500 mt-0.5 truncate max-w-[240px]">{bookmarkData.title}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-2 max-h-72 overflow-y-auto">
          {loading ? (
            <div className="space-y-2">
              {[1,2,3].map(i => <div key={i} className="h-12 bg-slate-800/60 rounded-xl animate-pulse" />)}
            </div>
          ) : (
            <>
              {collections.map(col => {
                const isChecked   = checked.has(col.collection_id)
                const wasExisting = !!existingMap[col.collection_id]

                let rowClass = 'border-slate-800 bg-slate-800/40 hover:border-slate-700 hover:bg-slate-800/60'
                if (isChecked && wasExisting) rowClass = 'border-emerald-700/40 bg-emerald-500/[0.06]'
                else if (isChecked)           rowClass = 'border-blue-500/50 bg-blue-500/10'
                else if (wasExisting)         rowClass = 'border-rose-700/30 bg-rose-500/[0.04]'

                return (
                  <button
                    key={col.collection_id}
                    onClick={() => toggleCollection(col.collection_id)}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border transition-all text-left ${rowClass}`}
                  >
                    {/* Checkbox */}
                    <div className={`w-4 h-4 rounded flex-shrink-0 flex items-center justify-center border transition-colors ${
                      isChecked
                        ? 'bg-blue-500 border-blue-500'
                        : wasExisting
                          ? 'border-rose-500/40 bg-transparent'
                          : 'border-slate-600 bg-transparent'
                    }`}>
                      {isChecked && (
                        <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M2 6l3 3 5-5" />
                        </svg>
                      )}
                    </div>

                    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${COLOR_DOT[col.color] ?? 'bg-blue-500'}`} />

                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate text-slate-200">{col.name}</p>
                      {col.description && (
                        <p className="text-xs text-slate-500 truncate">{col.description}</p>
                      )}
                    </div>

                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      {wasExisting && isChecked && (
                        <span className="text-[10px] text-emerald-500/70 font-medium">Saved</span>
                      )}
                      {wasExisting && !isChecked && (
                        <span className="text-[10px] text-rose-400/70 font-medium">Remove</span>
                      )}
                      <span className="text-xs text-slate-600">{col.bookmark_count}</span>
                    </div>
                  </button>
                )
              })}

              {/* New collection */}
              {creating ? (
                <div className="border border-slate-700 rounded-xl p-3 space-y-2 mt-1">
                  <input
                    autoFocus
                    value={newName}
                    onChange={e => setNewName(e.target.value)}
                    placeholder="Collection name"
                    className="w-full bg-slate-800 text-sm text-slate-100 placeholder-slate-500 px-3 py-2 rounded-lg border border-slate-700 focus:outline-none focus:border-blue-500/60"
                    onKeyDown={e => { if (e.key === 'Enter') handleCreateCollection(); if (e.key === 'Escape') setCreating(false) }}
                  />
                  <input
                    value={newDesc}
                    onChange={e => setNewDesc(e.target.value)}
                    placeholder="Description (optional)"
                    className="w-full bg-slate-800 text-sm text-slate-100 placeholder-slate-500 px-3 py-2 rounded-lg border border-slate-700 focus:outline-none focus:border-blue-500/60"
                  />
                  <div className="flex gap-1.5">
                    {COLOR_OPTIONS.map(c => (
                      <button key={c.key} onClick={() => setNewColor(c.key)}
                        className={`w-5 h-5 rounded-full ${c.cls} transition-transform ${newColor === c.key ? 'ring-2 ring-white/60 scale-110' : 'opacity-60 hover:opacity-100'}`}
                      />
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => setCreating(false)} className="flex-1 py-1.5 text-xs rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">Cancel</button>
                    <button onClick={handleCreateCollection} disabled={!newName.trim()} className="flex-1 py-1.5 text-xs rounded-lg bg-blue-600/70 hover:bg-blue-600 text-white disabled:opacity-40 transition-colors">Create</button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setCreating(true)}
                  className="w-full flex items-center gap-2 px-3 py-2.5 rounded-xl border border-dashed border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600 transition-all text-sm mt-1"
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M7.75 2a.75.75 0 0 1 .75.75V7h4.25a.75.75 0 0 1 0 1.5H8.5v4.25a.75.75 0 0 1-1.5 0V8.5H2.75a.75.75 0 0 1 0-1.5H7V2.75A.75.75 0 0 1 7.75 2Z" />
                  </svg>
                  New collection
                </button>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 pb-5 pt-3 border-t border-slate-800">
          {error && <p className="text-xs text-red-400 mb-2">{error}</p>}
          <button
            onClick={handleSave}
            disabled={!hasChanges || saving}
            className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm font-semibold transition-colors"
          >
            {buttonLabel()}
          </button>
        </div>
      </div>
    </div>
  )
}

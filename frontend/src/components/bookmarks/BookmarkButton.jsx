import { useState } from 'react'
import CollectionPickerModal from './CollectionPickerModal.jsx'

function BookmarkIcon({ filled }) {
  return filled ? (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M3 2.75C3 1.784 3.784 1 4.75 1h6.5C12.216 1 13 1.784 13 2.75v10.5a.75.75 0 0 1-1.2.6l-3.8-2.85-3.8 2.85A.75.75 0 0 1 3 13.25Z" />
    </svg>
  ) : (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M3 2.75C3 1.784 3.784 1 4.75 1h6.5C12.216 1 13 1.784 13 2.75v10.5a.75.75 0 0 1-1.2.6l-3.8-2.85-3.8 2.85A.75.75 0 0 1 3 13.25Zm1.75-.25a.25.25 0 0 0-.25.25v9.386l3.05-2.287a.75.75 0 0 1 .9 0l3.05 2.287V2.75a.25.25 0 0 0-.25-.25Z" />
    </svg>
  )
}

export default function BookmarkButton({ bookmarkData, className = '', label = false }) {
  const [open,  setOpen]  = useState(false)
  const [saved, setSaved] = useState(false)

  // Both setOpen+setSaved happen in this handler so React batches them in one render
  function handleSaved() {
    setOpen(false)
    setSaved(true)
  }

  return (
    <>
      <button
        onClick={e => { e.stopPropagation(); setOpen(true) }}
        title={saved ? 'Bookmarked!' : 'Save to bookmarks'}
        className={`flex items-center gap-1 px-2 py-1 rounded-md transition-colors text-xs ${
          saved
            ? 'text-amber-400 bg-amber-500/10'
            : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'
        } ${className}`}
      >
        <BookmarkIcon filled={saved} />
        {label && <span>{saved ? 'Saved!' : 'Save'}</span>}
      </button>

      {open && (
        <CollectionPickerModal
          bookmarkData={bookmarkData}
          onClose={() => setOpen(false)}
          onSaved={handleSaved}
        />
      )}
    </>
  )
}

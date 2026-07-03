import { useState, useMemo } from "react"

function relativeTime(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function SortIcon({ asc }) {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {asc ? <path d="M8 13V3M8 3 4 7M8 3l4 4" /> : <path d="M8 3v10M8 13l-4-4M8 13l4-4" />}
    </svg>
  )
}

function NoteRow({ note, showProject, onOpenArticle }) {
  return (
    <button
      onClick={() => onOpenArticle(note.project_id, note.insight_id, note.card_id)}
      className="w-full text-left px-3 py-2.5 rounded-xl hover:bg-slate-800/40 transition-colors"
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-1.5 min-w-0">
          {showProject && (
            <span className="inline-flex items-center text-[10px] text-slate-500 font-medium leading-none flex-shrink-0">
              {note.project_name}
            </span>
          )}
          {note.category && (
            <span className="inline-flex items-center text-[10px] text-slate-500/60 leading-none flex-shrink-0">
              {note.category}
            </span>
          )}
          <span className="text-xs text-slate-200 font-medium truncate">{note.article_title}</span>
        </div>
        <span className="text-[10px] text-slate-600 tabular-nums flex-shrink-0">Day {note.day_number}</span>
      </div>
      <p
        className="text-xs text-[--color-text-secondary,theme(colors.slate.500)] leading-relaxed"
        style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
      >
        {note.content}
      </p>
      <p className="text-[10px] text-slate-600 mt-1 text-right">Last edited: {relativeTime(note.updated_at)}</p>
    </button>
  )
}

function EmptyState({ text, subtext }) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-center">
      <div className="w-12 h-12 rounded-2xl bg-slate-800 flex items-center justify-center mb-4">
        <svg className="w-5 h-5 text-slate-500" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M14.5 3.5a1.5 1.5 0 0 1 2 2L7 15l-3 1 1-3Z" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <h3 className="text-sm font-semibold text-slate-300 mb-1">{text}</h3>
      <p className="text-xs text-slate-600 max-w-xs leading-relaxed">{subtext}</p>
    </div>
  )
}

export default function NotesModule({ notes, noteCount, onOpenArticle }) {
  const [selectedProject, setSelectedProject] = useState("all")
  const [sortAsc, setSortAsc] = useState(false)
  const [search, setSearch] = useState("")

  const projects = useMemo(() => {
    const seen = new Map()
    for (const n of notes || []) seen.set(n.project_id, n.project_name)
    return [...seen.entries()].map(([project_id, project_name]) => ({ project_id, project_name }))
  }, [notes])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (notes || [])
      .filter(n => selectedProject === "all" || n.project_id === selectedProject)
      .filter(n => !q || n.article_title.toLowerCase().includes(q) || n.content.toLowerCase().includes(q))
      .sort((a, b) => sortAsc ? a.day_number - b.day_number : b.day_number - a.day_number)
  }, [notes, selectedProject, search, sortAsc])

  if (!notes || notes.length === 0) {
    return (
      <div className="bg-slate-900/60 border border-slate-800/50 rounded-2xl p-5">
        <EmptyState text="No notes yet" subtext="Add a note from any article in your Feed" />
      </div>
    )
  }

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-2xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <select
          value={selectedProject}
          onChange={e => setSelectedProject(e.target.value)}
          className="text-xs bg-slate-800 border border-slate-700/60 text-slate-300 rounded-lg px-2.5 py-1 outline-none focus:border-slate-600 cursor-pointer flex-shrink-0"
        >
          <option value="all">All Projects</option>
          {projects.map(p => (
            <option key={p.project_id} value={p.project_id}>{p.project_name}</option>
          ))}
        </select>

        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search notes…"
          className="flex-1 min-w-0 text-xs bg-slate-800/60 border border-slate-700/60 text-slate-300 placeholder-slate-600 rounded-lg px-3 py-1 outline-none focus:border-slate-600"
        />

        <button
          onClick={() => setSortAsc(v => !v)}
          className="p-1.5 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-white/[0.06] transition-colors flex-shrink-0"
          title={sortAsc ? "Sorted oldest first" : "Sorted newest first"}
        >
          <SortIcon asc={sortAsc} />
        </button>
      </div>

      <p className="text-xs text-slate-600 mb-3">
        {noteCount} note{noteCount !== 1 ? "s" : ""} across {projects.length} project{projects.length !== 1 ? "s" : ""}
      </p>

      {visible.length === 0 ? (
        <EmptyState text="No matches" subtext="Try a different project or search term." />
      ) : (
        <div className="space-y-0.5">
          {visible.map(note => (
            <NoteRow key={note.id} note={note} showProject={selectedProject === "all" && projects.length > 1} onOpenArticle={onOpenArticle} />
          ))}
        </div>
      )}
    </div>
  )
}

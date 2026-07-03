import { useState, useEffect } from "react"
import { getReadingStats, articleKeyFromTitle } from "../../api/feed.js"
import { listProjectInsights } from "../../api/projects.js"
import { saveCardNote, deleteCardNote } from "../../api/notes.js"
import InsightCard from "./InsightCard.jsx"

function GroupDivider({ label }) {
  return (
    <div className="flex items-center gap-3 my-3 md:my-5">
      <div className="flex-1 h-px bg-white/[0.06]" />
      <span className="text-[10px] font-medium uppercase tracking-widest text-slate-600">{label}</span>
      <div className="flex-1 h-px bg-white/[0.06]" />
    </div>
  )
}

function Skeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-24 rounded-2xl bg-slate-800/40" />
      <div className="h-24 rounded-2xl bg-slate-800/30" />
    </div>
  )
}

/**
 * Cross-project "Notes only" feed view — active while the sidebar's Notes
 * toggle is on. Loads every noted article's full card via the same package
 * endpoint the normal Feed uses, grouped project -> day (backend pre-sorts
 * the notes list project_id ASC, day_number DESC).
 */
export default function NotesOnlyFeed() {
  const [entries, setEntries] = useState(null) // [{ card, note, projectName }]
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getReadingStats().then(async stats => {
      const noteList = (stats?.notes || []).filter(n => n.content && n.content.trim())
      const projectIds = [...new Set(noteList.map(n => n.project_id))]
      const pkgsByProject = {}
      await Promise.all(projectIds.map(async pid => {
        pkgsByProject[pid] = await listProjectInsights(pid, 500).catch(() => [])
      }))
      if (cancelled) return

      const built = []
      for (const n of noteList) {
        const pkg = (pkgsByProject[n.project_id] || []).find(p => p.id === n.insight_id)
        if (!pkg) continue
        const cards = [...(pkg.insights || []), ...(pkg.curiosity_insights || [])]
        const card = cards.find(c => articleKeyFromTitle(c.title || "") === n.card_id)
        if (!card) continue
        built.push({ card, note: n })
      }
      setEntries(built)
      setLoading(false)
    }).catch(() => { if (!cancelled) { setEntries([]); setLoading(false) } })
    return () => { cancelled = true }
  }, [])

  function handleSaveNote(note, content) {
    saveCardNote(note.project_id, note.insight_id, note.card_id, content).catch(() => {})
    setEntries(prev => prev.map(e => e.note === note ? { ...e, note: { ...note, content } } : e))
  }

  function handleDeleteNote(note) {
    deleteCardNote(note.project_id, note.insight_id, note.card_id).catch(() => {})
    setEntries(prev => prev.filter(e => e.note !== note))
  }

  if (loading || entries === null) return <Skeleton />

  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[40vh] text-center px-8">
        <p className="text-sm text-slate-500">No noted articles yet.</p>
        <p className="text-xs text-slate-600 mt-1">Add a note from any article to see it here.</p>
      </div>
    )
  }

  const groups = []
  const groupIndex = new Map()
  for (const entry of entries) {
    const pid = entry.note.project_id
    if (!groupIndex.has(pid)) {
      groupIndex.set(pid, groups.length)
      groups.push({ projectId: pid, projectName: entry.note.project_name, entries: [] })
    }
    groups[groupIndex.get(pid)].entries.push(entry)
  }

  return (
    <div>
      {groups.map(group => (
        <div key={group.projectId}>
          <GroupDivider label={group.projectName} />
          <div className="space-y-2 md:space-y-3">
            {group.entries.map(({ card, note }) => (
              <InsightCard
                key={note.id}
                card={card}
                note={note.content}
                onSaveNote={(content) => handleSaveNote(note, content)}
                onDeleteNote={() => handleDeleteNote(note)}
                projectId={note.project_id}
                projectName={note.project_name}
                day={note.insight_id}
                articleKey={note.card_id}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

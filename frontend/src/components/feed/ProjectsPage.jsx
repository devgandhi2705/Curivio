/**
 * ProjectsPage — the intelligence workspace hub.
 *
 * Layout (sidebar-first architecture):
 *   The project list lives in the App-level sidebar (FeedSubsection, registered via
 *   SidebarSubsectionContext). This component owns only the workspace on the right.
 *
 * Data loading:
 *   On mount:   listProjects() + listAllProgressions() in parallel
 *   On select:  listProjectInsights(id) + getProgression(id) in parallel
 *   On generate: refresh insights list + progression
 */
import { useState, useEffect, useCallback, useRef } from "react"
import {
  listProjects,
  listProjectInsights,
  createProject,
  updateProject,
  deleteProject,
  generateProjectInsight,
  deleteProjectInsight,
  getProgression,
  updateProgression,
  listAllProgressions,
} from "../../api/projects.js"
import {
  getInsightReadKeys,
  markCardRead,
  markCardUnread,
  getArticleChatLinks,
} from "../../api/feed.js"
import ProjectCard from "./ProjectCard.jsx"
import CreateProjectModal from "./CreateProjectModal.jsx"
import EditProjectModal from "./EditProjectModal.jsx"
import ProjectInsightView from "./ProjectInsightView.jsx"
import OnboardingModal, { hasCompletedOnboarding, markOnboardingDone } from "./OnboardingModal.jsx"
import { useSidebarSubsection } from "../../contexts/SidebarSubsection.jsx"
import { useContextMenu } from "../../contexts/ContextMenu.jsx"

// ── Shared style maps ─────────────────────────────────────────────────────────

const COLOR_GRADIENT = {
  blue:    "from-blue-500 to-blue-600",
  emerald: "from-emerald-500 to-emerald-600",
  violet:  "from-violet-500 to-violet-600",
  amber:   "from-amber-500 to-amber-600",
  rose:    "from-rose-500 to-rose-600",
}

// ── Icon helpers ──────────────────────────────────────────────────────────────

function SpinnerIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

function PlusIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
    </svg>
  )
}

// ── Skeleton loaders ──────────────────────────────────────────────────────────

function SidebarSkeleton() {
  return (
    <div className="space-y-1 px-1">
      {[1, 2, 3].map(i => (
        <div key={i} className="h-8 rounded-lg bg-slate-800/40 animate-pulse" />
      ))}
    </div>
  )
}

function WorkspaceSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-24 rounded-2xl bg-slate-800/40" />
      <div className="h-12 rounded-xl bg-slate-800/30" />
      <div className="h-8 w-48 rounded-lg bg-slate-800/40" />
      <div className="h-40 rounded-2xl bg-slate-800/30" />
    </div>
  )
}

// ── Generation state persists across tab switches ─────────────────────────────
const _generatingNow = new Set()

// ── Greeting ──────────────────────────────────────────────────────────────────

function getGreeting(name) {
  const h = new Date().getHours()
  const time = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : h < 21 ? "Good evening" : "Burning the midnight oil"
  const firstName = (name || "").split(" ")[0]
  return firstName ? `${time}, ${firstName}` : time
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

// ── FeedSubsection — rendered inside App sidebar's Zone 3 ─────────────────────

function FeedSubsection({
  projects,
  activeId,
  loadingList,
  listError,
  progressions,
  onSelect,
  onNew,
  onRename,
  onEdit,
  onDelete,
}) {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-2 px-1">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
          Projects
        </span>
        <button
          onClick={onNew}
          className="p-1 rounded-md text-slate-500 hover:text-slate-200 hover:bg-white/[0.06] transition-colors"
          title="New project"
        >
          <PlusIcon className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Project list */}
      {loadingList ? (
        <SidebarSkeleton />
      ) : listError ? (
        <p className="text-xs text-red-400 px-1">{listError}</p>
      ) : projects.length === 0 ? (
        <EmptySidebar onNew={onNew} />
      ) : (
        <div className="space-y-0.5 overflow-y-auto flex-1">
          {projects.map(project => (
            <ProjectCard
              key={project.project_id}
              project={project}
              progression={progressions[project.project_id]}
              isActive={project.project_id === activeId}
              onSelect={onSelect}
              onRename={onRename}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function ProjectsPage({
  onOpenInChat, onOpenChat,
  targetProjectId, targetInsightId, targetArticleKey, onClearQueueTarget,
  userId, userName,
  onSidebarClose,
  onBeforeModal,
}) {
  // Project list
  const [projects,       setProjects]       = useState([])
  const [loadingList,    setLoadingList]    = useState(true)
  const [listError,      setListError]      = useState(null)

  // Progressions map: { project_id -> progression }
  const [progressions,   setProgressions]   = useState({})

  // Active project state
  const [activeId,       setActiveId]       = useState(null)
  const [insights,       setInsights]       = useState([])
  const [loadingContent, setLoadingContent] = useState(false)

  // Generation
  const [generating,     setGenerating]     = useState(false)
  const [genError,       setGenError]       = useState(null)

  // Read state for the latest insight of the active project: Set<articleKey>
  const [readKeys,       setReadKeys]       = useState(new Set())

  // Related chats lazy cache: Map<articleKey, list|null>
  const [relatedChatsMap, setRelatedChatsMap] = useState(new Map())
  const loadingRelated = useRef(new Set())

  // Sidebar content registration
  const [visitedOrder, setVisitedOrder] = useState([])

  // Onboarding
  const [showOnboarding, setShowOnboarding] = useState(false)

  // Modals
  const [showCreate,        setShowCreate]        = useState(false)
  const [creating,          setCreating]          = useState(false)
  const [showEdit,          setShowEdit]          = useState(false)
  const [pendingDelete,     setPendingDelete]     = useState(null)
  const [showRenameProject, setShowRenameProject] = useState(false)
  const [renameProjectDraft, setRenameProjectDraft] = useState('')

  // Export callbacks exposed by DailyPackageView for the current selection
  const [exportCallbacks, setExportCallbacks] = useState({ pdf: null, md: null })

  // ── Sort projects by most-recently-visited ────────────────────────────────────
  const sortedProjects = visitedOrder.length === 0 ? projects : [...projects].sort((a, b) => {
    const ia = visitedOrder.indexOf(a.project_id)
    const ib = visitedOrder.indexOf(b.project_id)
    if (ia === -1 && ib === -1) return 0
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })

  // ── Context menu registration ─────────────────────────────────────────────────
  const { setViewActions, clearViewActions } = useContextMenu()

  // ── Sidebar subsection registration ──────────────────────────────────────────
  const { register } = useSidebarSubsection()

  // Stable ref for handlers so the subsection render fn always calls current handlers
  const subsectionHandlers = useRef({})
  useEffect(() => {
    const run = (fn) => onBeforeModal ? onBeforeModal(fn) : fn()
    subsectionHandlers.current = {
      handleSelect: (project) => {
        handleSelect(project)
        onSidebarClose?.()
      },
      onNew:    () => run(() => setShowCreate(true)),
      onRename: (project) => run(() => { setActiveId(project.project_id); setRenameProjectDraft(project.name || ''); setShowRenameProject(true) }),
      onEdit:   (project) => run(() => { setActiveId(project.project_id); setShowEdit(true) }),
      onDelete: (project) => run(() => setPendingDelete(project)),
    }
  })

  useEffect(() => {
    register('feed', (query) => {
      const q = query?.trim().toLowerCase() ?? ''
      const filtered = q
        ? sortedProjects.filter(p => p.name.toLowerCase().includes(q))
        : sortedProjects
      return (
        <FeedSubsection
          projects={filtered}
          activeId={activeId}
          loadingList={loadingList}
          listError={listError}
          progressions={progressions}
          onSelect={(p) => subsectionHandlers.current.handleSelect(p)}
          onNew={() => subsectionHandlers.current.onNew()}
          onRename={(p) => subsectionHandlers.current.onRename(p)}
          onEdit={(p) => subsectionHandlers.current.onEdit(p)}
          onDelete={(p) => subsectionHandlers.current.onDelete(p)}
        />
      )
    })
    // No cleanup — ProjectsPage is always-mounted.
  }, [register, sortedProjects, activeId, loadingList, listError, progressions])

  // Register contextual ⋮ actions for the feed view
  useEffect(() => {
    const activeProject = projects.find(p => p.project_id === activeId) ?? null
    if (!activeProject) { clearViewActions('feed'); return }
    setViewActions('feed', [
      {
        label: 'Rename project',
        onClick: () => { setRenameProjectDraft(activeProject.name || ''); setShowRenameProject(true) },
      },
      { label: 'Edit project', onClick: () => setShowEdit(true) },
      ...(exportCallbacks.pdf ? [
        { label: 'Export as PDF',      onClick: exportCallbacks.pdf, export: true },
        { label: 'Export as Markdown', onClick: exportCallbacks.md,  export: true },
      ] : []),
      { label: 'Delete project', variant: 'danger', onClick: () => setPendingDelete(activeProject) },
    ])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, projects, exportCallbacks])

  // ── Auto-select project when navigated from global search ─────────────────
  useEffect(() => {
    if (targetProjectId && projects.some(p => p.project_id === targetProjectId)) {
      setActiveId(targetProjectId)
    }
  }, [targetProjectId, projects])

  // ── Mount: load projects + all progressions in parallel ─────────────────────

  useEffect(() => {
    setLoadingList(true)
    listProjects()
      .then(async (data) => {
        setProjects(data)
        if (data.length > 0) {
          setActiveId(data[0].project_id)
          const ids = data.map(p => p.project_id)
          try {
            const map = await listAllProgressions(ids)
            setProgressions(map)
          } catch (_) {}
        } else if (!hasCompletedOnboarding(userId)) {
          setShowOnboarding(true)
        }
      })
      .catch(e => setListError(e.message))
      .finally(() => setLoadingList(false))
  }, [])

  // ── Load insights + read state when active project changes ─────────────────

  useEffect(() => {
    if (!activeId) return
    setLoadingContent(true)
    setInsights([])
    setGenError(null)
    setReadKeys(new Set())
    setRelatedChatsMap(new Map())

    listProjectInsights(activeId, 20)
      .then(async (data) => {
        setInsights(data)
        if (data.length > 0) {
          const latestId = data[0].id
          const keys = await getInsightReadKeys(activeId, latestId).catch(() => new Set())
          setReadKeys(keys)
        }
      })
      .catch(() => {})
      .finally(() => setLoadingContent(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId])

  // Restore generating UI if user switched tabs mid-generation
  useEffect(() => {
    if (!activeId) return
    if (_generatingNow.has(activeId)) setGenerating(true)
  }, [activeId])

  // When generation finishes in background, refresh insights
  useEffect(() => {
    if (!activeId) return
    function onDone(e) {
      if (e.detail.projectId !== activeId) return
      setGenerating(false)
      listProjectInsights(activeId)
        .then(data => setInsights(data))
        .catch(() => {})
    }
    window.addEventListener('feed-generation-done', onDone)
    return () => window.removeEventListener('feed-generation-done', onDone)
  }, [activeId])

  // ── Handlers ────────────────────────────────────────────────────────────────

  const handleSelect = useCallback((project) => {
    if (project.project_id === activeId) return
    setActiveId(project.project_id)
    setVisitedOrder(prev => [project.project_id, ...prev.filter(id => id !== project.project_id)])
  }, [activeId])

  const handleGenerate = useCallback(async () => {
    if (!activeId || generating) return
    _generatingNow.add(activeId)
    setGenerating(true)
    setGenError(null)
    const pid = activeId
    try {
      const pkg = await generateProjectInsight(pid)
      setInsights(prev => {
        if (prev.some(p => p.id === pkg.id)) return prev
        return [pkg, ...prev]
      })
      setProjects(prev =>
        prev.map(p =>
          p.project_id === pid
            ? {
                ...p,
                insight_count:         pkg.day_number,
                last_insight_at:       pkg.generated_at,
                last_package_headline: pkg.package_headline ?? p.last_package_headline,
              }
            : p
        )
      )
      setReadKeys(new Set())
      setRelatedChatsMap(new Map())
      getProgression(pid)
        .then(prog => setProgressions(prev => ({ ...prev, [pid]: prog })))
        .catch(() => {})
    } catch (e) {
      setGenError(e.message || "Generation failed. Please try again.")
    } finally {
      _generatingNow.delete(pid)
      setGenerating(false)
      window.dispatchEvent(new CustomEvent('feed-generation-done', { detail: { projectId: pid } }))
    }
  }, [activeId, generating])

  const handleRegenerate = useCallback(async (insightId) => {
    if (!activeId || generating) return
    _generatingNow.add(activeId)
    setGenerating(true)
    setGenError(null)
    const pid = activeId
    try {
      await deleteProjectInsight(pid, insightId)
      setInsights(prev => prev.filter(p => p.id !== insightId))
      const pkg = await generateProjectInsight(pid)
      setInsights(prev => [pkg, ...prev])
      setProjects(prev =>
        prev.map(p =>
          p.project_id === pid
            ? { ...p, last_package_headline: pkg.package_headline ?? p.last_package_headline }
            : p
        )
      )
      setReadKeys(new Set())
      setRelatedChatsMap(new Map())
      getProgression(pid)
        .then(prog => setProgressions(prev => ({ ...prev, [pid]: prog })))
        .catch(() => {})
    } catch (e) {
      setGenError(e.message || "Regeneration failed. Please try again.")
    } finally {
      _generatingNow.delete(pid)
      setGenerating(false)
      window.dispatchEvent(new CustomEvent('feed-generation-done', { detail: { projectId: pid } }))
    }
  }, [activeId, generating])

  const handleCreate = useCallback(async (fields) => {
    setCreating(true)
    try {
      const project = await createProject(fields)
      setProjects(prev => [project, ...prev])
      setActiveId(project.project_id)
      setShowCreate(false)
    } catch (_) {}
    finally { setCreating(false) }
  }, [])

  const handleOnboardingComplete = useCallback(async (fields) => {
    setCreating(true)
    try {
      const project = await createProject(fields)
      setProjects(prev => [project, ...prev])
      setActiveId(project.project_id)
      setShowOnboarding(false)
      _generatingNow.add(project.project_id)
      setGenerating(true)
      const pid = project.project_id
      try {
        const pkg = await generateProjectInsight(pid)
        setInsights([pkg])
        setProjects(prev =>
          prev.map(p =>
            p.project_id === pid
              ? { ...p, insight_count: pkg.day_number, last_insight_at: pkg.generated_at, last_package_headline: pkg.package_headline ?? p.last_package_headline }
              : p
          )
        )
        setReadKeys(new Set())
      } catch (e) {
        setGenError(e.message || "Generation failed. Please try again.")
      } finally {
        _generatingNow.delete(pid)
        setGenerating(false)
        window.dispatchEvent(new CustomEvent('feed-generation-done', { detail: { projectId: pid } }))
      }
    } catch (_) {}
    finally { setCreating(false) }
  }, [])

  const handleDeleteRequest = useCallback((projectId) => {
    const project = projects.find(p => p.project_id === projectId)
    if (project) setPendingDelete(project)
  }, [projects])

  const handleDeleteConfirm = useCallback(async () => {
    if (!pendingDelete) return
    const projectId = pendingDelete.project_id
    setPendingDelete(null)
    try { await deleteProject(projectId) } catch (_) {}
    setProjects(prev => {
      const next = prev.filter(p => p.project_id !== projectId)
      if (activeId === projectId) setActiveId(next[0]?.project_id ?? null)
      return next
    })
    setProgressions(prev => {
      const next = { ...prev }
      delete next[projectId]
      return next
    })
  }, [pendingDelete, activeId])

  const handleProgressionUpdate = useCallback(async (fields) => {
    if (!activeId) return
    try {
      const updated = await updateProgression(activeId, fields)
      setProgressions(prev => ({ ...prev, [activeId]: updated }))
    } catch (_) {}
  }, [activeId])

  const handleEditProject = useCallback(async (fields) => {
    const updated = await updateProject(activeId, fields)
    setProjects(prev => prev.map(p => p.project_id === activeId ? { ...p, ...updated } : p))
    setShowEdit(false)
  }, [activeId])

  const handleRenameProject = useCallback(async (newName) => {
    if (!activeId) return
    try {
      await updateProject(activeId, { name: newName })
      setProjects(prev => prev.map(p => p.project_id === activeId ? { ...p, name: newName } : p))
    } catch (_) {}
    setShowRenameProject(false)
  }, [activeId])

  const handleExportReady = useCallback((pdfFn, mdFn) => {
    setExportCallbacks({ pdf: pdfFn, md: mdFn })
  }, [])

  // ── Read tracking ──────────────────────────────────────────────────────────

  const handleMarkRead = useCallback(async (insightId, articleKey, articleTitle) => {
    if (!activeId) return
    setReadKeys(prev => { const s = new Set(prev); s.add(articleKey); return s })
    await markCardRead(activeId, insightId, articleKey, articleTitle).catch(() => {})
  }, [activeId])

  const handleMarkUnread = useCallback(async (insightId, articleKey) => {
    if (!activeId) return
    setReadKeys(prev => { const s = new Set(prev); s.delete(articleKey); return s })
    await markCardUnread(activeId, insightId, articleKey).catch(() => {})
  }, [activeId])

  // ── Related chats ──────────────────────────────────────────────────────────

  const handleLoadRelatedChats = useCallback(async (insightId, articleKey) => {
    if (!activeId) return
    if (loadingRelated.current.has(articleKey)) return
    loadingRelated.current.add(articleKey)
    try {
      const links = await getArticleChatLinks(activeId, articleKey)
      setRelatedChatsMap(prev => {
        const next = new Map(prev)
        next.set(articleKey, links)
        return next
      })
    } catch {
      setRelatedChatsMap(prev => {
        const next = new Map(prev)
        next.set(articleKey, [])
        return next
      })
    } finally {
      loadingRelated.current.delete(articleKey)
    }
  }, [activeId])

  const handleOpenChat = useCallback((sessionId, title) => {
    onOpenChat?.(sessionId, title)
  }, [onOpenChat])

  // ── Derived ─────────────────────────────────────────────────────────────────

  const activeProject = projects.find(p => p.project_id === activeId) ?? null

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <>
      {/* Greeting */}
      <div className="mb-2.5 md:mb-4 px-1">
        <h1 className="text-xl md:text-2xl font-bold text-slate-100 tracking-tight">{getGreeting(userName)}</h1>
      </div>

      {/* Workspace */}
      {!activeProject ? (
        <EmptyWorkspace onNew={() => setShowCreate(true)} />
      ) : (
        <>
          {genError && (
            <div className="mb-5 px-4 py-3 bg-red-950/30 border border-red-900/40 rounded-xl text-xs text-red-400">
              {genError}
            </div>
          )}

          {loadingContent && !generating ? (
            <WorkspaceSkeleton />
          ) : (
            <ProjectInsightView
              project={activeProject}
              insights={insights}
              onGenerate={handleGenerate}
              onRegenerate={handleRegenerate}
              generating={generating}
              targetInsightId={targetInsightId}
              targetArticleKey={targetArticleKey}
              onClearQueueTarget={onClearQueueTarget}
              onOpenInChat={
                onOpenInChat
                  ? (card, action) => onOpenInChat(card, action, {
                      name:       activeProject.name,
                      keywords:   activeProject.keywords,
                      domain:     activeProject.domain || "default",
                      project_id: activeProject.project_id,
                      insight_id: insights[0]?.id ?? null,
                    })
                  : undefined
              }
              readKeys={readKeys}
              onMarkRead={handleMarkRead}
              onMarkUnread={handleMarkUnread}
              relatedChatsMap={relatedChatsMap}
              onLoadRelatedChats={handleLoadRelatedChats}
              onOpenChat={handleOpenChat}
              onExportReady={handleExportReady}
            />
          )}
        </>
      )}

      {showOnboarding && (
        <OnboardingModal
          onCreate={handleOnboardingComplete}
          creating={creating}
          userId={userId}
        />
      )}

      {showCreate && (
        <CreateProjectModal
          onClose={() => setShowCreate(false)}
          onCreate={handleCreate}
          loading={creating}
        />
      )}

      {showRenameProject && (
        <RenameModal
          heading="Rename project"
          initialValue={renameProjectDraft}
          onConfirm={handleRenameProject}
          onClose={() => setShowRenameProject(false)}
        />
      )}

      {showEdit && activeProject && (
        <EditProjectModal
          project={activeProject}
          onClose={() => setShowEdit(false)}
          onSave={handleEditProject}
        />
      )}

      {pendingDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
          onClick={e => { if (e.target === e.currentTarget) setPendingDelete(null) }}
        >
          <div className="w-full max-w-sm bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-xl bg-red-950/60 border border-red-900/50 flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-red-400" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M11 1.75V3h2.25a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75ZM4.496 6.675l.66 6.6a.25.25 0 0 0 .249.225h5.19a.25.25 0 0 0 .249-.225l.66-6.6a.75.75 0 0 1 1.492.149l-.66 6.6A1.748 1.748 0 0 1 10.595 15h-5.19a1.75 1.75 0 0 1-1.741-1.575l-.66-6.6a.75.75 0 1 1 1.492-.15Z" />
                </svg>
              </div>
              <div>
                <h3 className="font-semibold text-slate-100 text-sm">Delete project?</h3>
                <p className="text-xs text-slate-500 mt-0.5">This cannot be undone.</p>
              </div>
            </div>

            <p className="text-sm text-slate-400 mb-5 leading-relaxed">
              <span className="text-slate-200 font-medium">{pendingDelete.name}</span>
              {" "}and all its daily packages, read history, and chat links will be permanently deleted.
            </p>

            <div className="flex gap-3">
              <button
                onClick={() => setPendingDelete(null)}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-700/50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteConfirm}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium bg-red-600 hover:bg-red-500 text-white transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ── Empty states ──────────────────────────────────────────────────────────────

function EmptySidebar({ onNew }) {
  return (
    <div className="flex flex-col items-center justify-center py-10 px-3 text-center">
      <div className="w-10 h-10 rounded-xl bg-slate-800/80 border border-slate-700/60 flex items-center justify-center mb-3">
        <svg className="w-4 h-4 text-slate-500" viewBox="0 0 16 16" fill="currentColor">
          <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
        </svg>
      </div>
      <p className="text-xs text-slate-500 leading-relaxed mb-4">
        No projects yet. Create one to start your structured learning stream.
      </p>
      <button
        onClick={onNew}
        className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors"
      >
        Create Project
      </button>
    </div>
  )
}

function EmptyWorkspace({ onNew }) {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center px-8">
      <div className="relative w-16 h-16 mb-6">
        <div className="absolute inset-0 rounded-2xl bg-slate-800/80 border border-slate-700/60" />
        <div className="absolute inset-0 flex items-center justify-center">
          <svg className="w-7 h-7 text-slate-500" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M4.25 2A2.25 2.25 0 0 0 2 4.25v2.5A2.25 2.25 0 0 0 4.25 9h2.5A2.25 2.25 0 0 0 9 6.75v-2.5A2.25 2.25 0 0 0 6.75 2h-2.5Zm0 9A2.25 2.25 0 0 0 2 13.25v2.5A2.25 2.25 0 0 0 4.25 18h2.5A2.25 2.25 0 0 0 9 15.75v-2.5A2.25 2.25 0 0 0 6.75 11h-2.5Zm9-9A2.25 2.25 0 0 0 11 4.25v2.5A2.25 2.25 0 0 0 13.25 9h2.5A2.25 2.25 0 0 0 18 6.75v-2.5A2.25 2.25 0 0 0 15.75 2h-2.5Zm0 9A2.25 2.25 0 0 0 11 13.25v2.5A2.25 2.25 0 0 0 13.25 18h2.5A2.25 2.25 0 0 0 18 15.75v-2.5A2.25 2.25 0 0 0 15.75 11h-2.5Z" clipRule="evenodd" />
          </svg>
        </div>
      </div>

      <h2 className="text-lg font-bold text-slate-200 mb-2">Your Intelligence Workspace</h2>
      <p className="text-sm text-slate-500 max-w-sm mb-6 leading-relaxed">
        Create focused learning projects — each one generates a structured daily brief with current events and deep-dive concepts tailored to your level.
      </p>

      <div className="flex flex-col gap-2.5 items-center">
        <button
          onClick={onNew}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors shadow-md"
        >
          <PlusIcon className="w-4 h-4" />
          Create Your First Project
        </button>
        <p className="text-[11px] text-slate-600">AI in Manufacturing · Quant Finance · Supply Chain · and more</p>
      </div>
    </div>
  )
}

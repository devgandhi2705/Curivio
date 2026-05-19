/**
 * ProjectsPage — the intelligence workspace hub.
 *
 * Layout:
 *   Left sidebar (w-72)  — project list with rich cards + "New Project" button
 *   Right workspace      — project header → stat strip → progression → daily feed
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

function ChevronLeftIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M9.78 12.78a.75.75 0 0 1-1.06 0L4.47 8.53a.75.75 0 0 1 0-1.06l4.25-4.25a.75.75 0 0 1 1.06 1.06L6.06 8l3.72 3.72a.75.75 0 0 1 0 1.06Z" />
    </svg>
  )
}

function ChevronRightIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06Z" />
    </svg>
  )
}

// ── Skeleton loaders ──────────────────────────────────────────────────────────

function SidebarSkeleton() {
  return (
    <div className="space-y-1">
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

// ── Main export ───────────────────────────────────────────────────────────────

function getGreeting(name) {
  const h = new Date().getHours()
  const time = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : h < 21 ? "Good evening" : "Burning the midnight oil"
  const firstName = (name || "").split(" ")[0]
  return firstName ? `${time}, ${firstName}` : time
}

export default function ProjectsPage({ onOpenInChat, onOpenChat, targetProjectId, targetInsightId, targetArticleKey, onClearQueueTarget, userId, userName }) {
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
  // null = not loaded yet, list = loaded (may be empty)
  const [relatedChatsMap, setRelatedChatsMap] = useState(new Map())
  // Track which article_keys are currently loading to avoid duplicate fetches
  const loadingRelated = useRef(new Set())

  // Sidebar
  const [sidebarCollapsed,    setSidebarCollapsed]    = useState(false)
  const [mobileSidebarOpen,   setMobileSidebarOpen]   = useState(false)
  const [visitedOrder,        setVisitedOrder]        = useState([])

  // Onboarding
  const [showOnboarding, setShowOnboarding] = useState(false)

  // Modals
  const [showCreate,     setShowCreate]     = useState(false)
  const [creating,       setCreating]       = useState(false)
  const [showEdit,       setShowEdit]       = useState(false)
  const [pendingDelete,  setPendingDelete]  = useState(null) // project object awaiting confirmation

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
          // Batch-load progressions for all projects
          const ids = data.map(p => p.project_id)
          try {
            const map = await listAllProgressions(ids)
            setProgressions(map)
          } catch (_) {}
        } else if (!hasCompletedOnboarding(userId)) {
          // New user — show guided onboarding instead of empty state
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
        // Load read state for the latest package
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

  // ── Handlers ────────────────────────────────────────────────────────────────

  const handleSelect = useCallback((project) => {
    if (project.project_id === activeId) return
    setActiveId(project.project_id)
    setVisitedOrder(prev => [project.project_id, ...prev.filter(id => id !== project.project_id)])
  }, [activeId])

  const handleGenerate = useCallback(async () => {
    if (!activeId || generating) return
    setGenerating(true)
    setGenError(null)
    try {
      const pkg = await generateProjectInsight(activeId)
      setInsights(prev => {
        if (prev.some(p => p.id === pkg.id)) return prev
        return [pkg, ...prev]
      })
      setProjects(prev =>
        prev.map(p =>
          p.project_id === activeId
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
      getProgression(activeId)
        .then(prog => setProgressions(prev => ({ ...prev, [activeId]: prog })))
        .catch(() => {})
    } catch (e) {
      setGenError(e.message || "Generation failed. Please try again.")
    } finally {
      setGenerating(false)
    }
  }, [activeId, generating])

  const handleRegenerate = useCallback(async (insightId) => {
    if (!activeId || generating) return
    setGenerating(true)
    setGenError(null)
    try {
      await deleteProjectInsight(activeId, insightId)
      setInsights(prev => prev.filter(p => p.id !== insightId))
      const pkg = await generateProjectInsight(activeId)
      setInsights(prev => [pkg, ...prev])
      setProjects(prev =>
        prev.map(p =>
          p.project_id === activeId
            ? { ...p, last_package_headline: pkg.package_headline ?? p.last_package_headline }
            : p
        )
      )
      setReadKeys(new Set())
      setRelatedChatsMap(new Map())
      getProgression(activeId)
        .then(prog => setProgressions(prev => ({ ...prev, [activeId]: prog })))
        .catch(() => {})
    } catch (e) {
      setGenError(e.message || "Regeneration failed. Please try again.")
    } finally {
      setGenerating(false)
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

  // Onboarding path: create project then immediately generate Day 1
  const handleOnboardingComplete = useCallback(async (fields) => {
    setCreating(true)
    try {
      const project = await createProject(fields)
      setProjects(prev => [project, ...prev])
      setActiveId(project.project_id)
      setShowOnboarding(false)
      // Auto-generate Day 1 so the user lands on content, not an empty state
      setGenerating(true)
      try {
        const pkg = await generateProjectInsight(project.project_id)
        setInsights([pkg])
        setProjects(prev =>
          prev.map(p =>
            p.project_id === project.project_id
              ? { ...p, insight_count: pkg.day_number, last_insight_at: pkg.generated_at, last_package_headline: pkg.package_headline ?? p.last_package_headline }
              : p
          )
        )
        setReadKeys(new Set())
      } catch (e) {
        setGenError(e.message || "Generation failed. Please try again.")
      } finally {
        setGenerating(false)
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

  // ── Related chats (lazy load per article) ─────────────────────────────────

  const handleLoadRelatedChats = useCallback(async (insightId, articleKey) => {
    if (!activeId) return
    if (loadingRelated.current.has(articleKey)) return  // deduplicate concurrent calls
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

  // Sort sidebar by most-recently-visited first
  const sortedProjects = visitedOrder.length === 0 ? projects : [...projects].sort((a, b) => {
    const ia = visitedOrder.indexOf(a.project_id)
    const ib = visitedOrder.indexOf(b.project_id)
    if (ia === -1 && ib === -1) return 0
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col md:flex-row gap-0 min-h-[calc(100vh-8rem)]">

      {/* ── Left sidebar — desktop only ── */}
      <aside className={`hidden md:flex flex-shrink-0 flex-col border-r border-slate-800/40 transition-[width] duration-200 ease-in-out ${sidebarCollapsed ? "w-16" : "w-56"}`}
        style={{ paddingRight: sidebarCollapsed ? '0' : '12px', marginRight: '20px' }}>

        {/* Sidebar header */}
        <div className={`flex items-center mb-4 ${sidebarCollapsed ? "justify-center flex-col gap-2" : "justify-between"}`}>
          {!sidebarCollapsed && (
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-600">
              Projects
            </span>
          )}
          <div className={`flex ${sidebarCollapsed ? "flex-col" : "flex-row"} items-center gap-1`}>
            {!sidebarCollapsed && (
              <button
                onClick={() => setShowCreate(true)}
                className="p-1.5 rounded-md text-slate-600 hover:text-slate-300 hover:bg-slate-800/60 transition-colors"
                title="New project"
              >
                <PlusIcon className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              onClick={() => setSidebarCollapsed(c => !c)}
              className="p-1.5 rounded-md text-slate-700 hover:text-slate-400 hover:bg-slate-800/50 transition-colors"
              title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {sidebarCollapsed
                ? <ChevronRightIcon className="w-3.5 h-3.5" />
                : <ChevronLeftIcon className="w-3.5 h-3.5" />
              }
            </button>
          </div>
        </div>

        {/* Project list */}
        {loadingList ? (
          sidebarCollapsed ? null : <SidebarSkeleton />
        ) : listError ? (
          sidebarCollapsed ? null : <p className="text-xs text-red-400 px-1">{listError}</p>
        ) : projects.length === 0 ? (
          sidebarCollapsed ? (
            <button
              onClick={() => setShowCreate(true)}
              className="w-10 h-10 mx-auto rounded-xl flex items-center justify-center bg-slate-800/50 text-slate-600 hover:text-slate-400 hover:bg-slate-800 transition-all"
              title="New project"
            >
              <PlusIcon className="w-4 h-4" />
            </button>
          ) : (
            <EmptySidebar onNew={() => setShowCreate(true)} />
          )
        ) : sidebarCollapsed ? (
          /* Collapsed: stacked gradient icon squares */
          <div className="flex flex-col items-center gap-2">
            {sortedProjects.map(project => {
              const grad = COLOR_GRADIENT[project.color] || COLOR_GRADIENT.blue
              const isActive = project.project_id === activeId
              return (
                <button
                  key={project.project_id}
                  onClick={() => handleSelect(project)}
                  title={project.name}
                  className={`w-10 h-10 rounded-xl flex items-center justify-center text-[13px] font-bold transition-all flex-shrink-0 shadow-sm ${
                    isActive
                      ? `bg-gradient-to-br ${grad} text-white shadow-md ring-1 ring-white/10`
                      : "bg-slate-800/60 text-slate-400 hover:bg-slate-700/70 hover:text-slate-200"
                  }`}
                >
                  {project.name.charAt(0).toUpperCase()}
                </button>
              )
            })}
            <button
              onClick={() => setShowCreate(true)}
              className="w-10 h-10 mt-1 rounded-xl flex items-center justify-center border border-dashed border-slate-700/60 text-slate-700 hover:border-slate-600 hover:text-slate-500 transition-all"
              title="New project"
            >
              <PlusIcon className="w-4 h-4" />
            </button>
          </div>
        ) : (
          /* Expanded: project rows, sorted by recently visited */
          <div className="space-y-1 overflow-y-auto">
            {sortedProjects.map(project => (
              <ProjectCard
                key={project.project_id}
                project={project}
                progression={progressions[project.project_id]}
                isActive={project.project_id === activeId}
                onSelect={handleSelect}
                onDelete={handleDeleteRequest}
                onEdit={(id) => { setActiveId(id); setShowEdit(true) }}
              />
            ))}
          </div>
        )}
      </aside>

      {/* ── Right workspace ── */}
      <main className="flex-1 min-w-0">

        {/* Greeting banner — always visible at the top */}
        <div className="mb-4 px-1">
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">{getGreeting(userName)}</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {activeProject ? `Day ${activeProject.insight_count ?? 1} · ${activeProject.name}` : "Here's your intelligence workspace"}
          </p>
        </div>

        {/* Mobile project selector strip — mobile only */}
        <div className="flex md:hidden items-center gap-2 mb-3 -mx-3 px-3">
          {/* Sidebar trigger */}
          <button
            onClick={() => setMobileSidebarOpen(true)}
            className="flex-shrink-0 p-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
            title="All projects"
          >
            <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M2 4.75A.75.75 0 0 1 2.75 4h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 4.75ZM2 10a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 10Zm0 5.25a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1-.75-.75Z" clipRule="evenodd" />
            </svg>
          </button>

          {/* Project chips */}
          {projects.length > 0 && (
            <div className="flex overflow-x-auto gap-2 pb-1 scrollbar-none flex-1">
              {sortedProjects.map(project => {
                const isActive = project.project_id === activeId
                const grad = COLOR_GRADIENT[project.color] || COLOR_GRADIENT.blue
                return (
                  <button
                    key={project.project_id}
                    onClick={() => handleSelect(project)}
                    className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
                      isActive
                        ? `bg-gradient-to-r ${grad} text-white shadow-sm`
                        : 'bg-slate-800/60 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {project.name}
                  </button>
                )
              })}
              <button
                onClick={() => setShowCreate(true)}
                className="flex-shrink-0 flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium border border-dashed border-slate-700/60 text-slate-600 hover:text-slate-400 transition-all"
              >
                <PlusIcon className="w-3 h-3" />
                New
              </button>
            </div>
          )}
        </div>

        {/* Mobile slide-out project sidebar */}
        {mobileSidebarOpen && (
          <>
            <div
              className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 md:hidden"
              onClick={() => setMobileSidebarOpen(false)}
            />
            <div className="fixed left-0 top-0 bottom-0 w-72 bg-slate-950 border-r border-slate-800/60 z-50 flex flex-col md:hidden">
              {/* Drawer header */}
              <div className="flex items-center justify-between px-4 py-4 border-b border-slate-800/60">
                <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">Projects</span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => { setShowCreate(true); setMobileSidebarOpen(false) }}
                    className="p-1.5 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
                    title="New project"
                  >
                    <PlusIcon className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setMobileSidebarOpen(false)}
                    className="p-1.5 rounded-md text-slate-600 hover:text-slate-300 hover:bg-slate-800 transition-colors"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.06 1.06L9.06 8l3.22 3.22a.749.749 0 0 1-1.06 1.06L8 9.06l-3.22 3.22a.751.751 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                    </svg>
                  </button>
                </div>
              </div>

              {/* Project list */}
              <div className="flex-1 overflow-y-auto px-3 py-3 space-y-1">
                {sortedProjects.map(project => {
                  const isActive = project.project_id === activeId
                  const grad = COLOR_GRADIENT[project.color] || COLOR_GRADIENT.blue
                  return (
                    <div
                      key={project.project_id}
                      className={`group flex items-center gap-2 px-3 py-2.5 rounded-xl transition-all ${
                        isActive ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
                      }`}
                    >
                      <button
                        onClick={() => { handleSelect(project); setMobileSidebarOpen(false) }}
                        className="flex items-center gap-2.5 flex-1 min-w-0 text-left"
                      >
                        <div className={`w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-bold flex-shrink-0 bg-gradient-to-br ${grad} text-white`}>
                          {project.name.charAt(0).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate leading-snug">{project.name}</p>
                          <p className="text-[10px] text-slate-600 mt-0.5">Day {project.insight_count ?? 1}</p>
                        </div>
                      </button>
                      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                        <button
                          onClick={() => { setActiveId(project.project_id); setShowEdit(true); setMobileSidebarOpen(false) }}
                          className="p-1.5 rounded-lg text-slate-600 hover:text-slate-300 hover:bg-slate-700 transition-colors"
                          title="Edit"
                        >
                          <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                            <path d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61Z" />
                          </svg>
                        </button>
                        <button
                          onClick={() => { handleDeleteRequest(project.project_id); setMobileSidebarOpen(false) }}
                          className="p-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-950/40 transition-colors"
                          title="Delete"
                        >
                          <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                            <path d="M11 1.75V3h2.25a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75ZM4.496 6.675l.66 6.6a.25.25 0 0 0 .249.225h5.19a.25.25 0 0 0 .249-.225l.66-6.6a.75.75 0 0 1 1.492.149l-.66 6.6A1.748 1.748 0 0 1 10.595 15h-5.19a1.75 1.75 0 0 1-1.741-1.575l-.66-6.6a.75.75 0 1 1 1.492-.15Z" />
                          </svg>
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </>
        )}

        {!activeProject ? (
          <EmptyWorkspace onNew={() => setShowCreate(true)} />
        ) : (
          <>
            {genError && (
              <div className="mb-5 px-4 py-3 bg-red-950/30 border border-red-900/40 rounded-xl text-xs text-red-400">
                {genError}
              </div>
            )}

            {loadingContent ? (
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
              />
            )}
          </>
        )}
      </main>

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
                  <path d="M11 1.75V3h2.25a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75ZM4.496 6.675l.66 6.6a.25.25 0 0 0 .249.225h5.19a.25.25 0 0 0 .249-.225l.66-6.6a.75.75 0 0 1 1.492.149l-.66 6.6A1.748 1.748 0 0 1 10.595 15h-5.19a1.75 1.75 0 0 1-1.741-1.575l-.66-6.6a.75.75 0 1 1 1.492-.15ZM6.5 1.75V3h3V1.75a.25.25 0 0 0-.25-.25h-2.5a.25.25 0 0 0-.25.25Z" />
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
    </div>
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
      {/* Decorative grid */}
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

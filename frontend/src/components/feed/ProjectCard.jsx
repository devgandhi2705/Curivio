import { useState, useRef, useEffect } from "react"
import { useAuth } from "../../contexts/AuthContext.jsx"

const COLOR_GRAD = {
  blue:    "from-blue-500 to-blue-600",
  emerald: "from-emerald-500 to-emerald-600",
  violet:  "from-violet-500 to-violet-600",
  amber:   "from-amber-500 to-amber-600",
  rose:    "from-rose-500 to-rose-600",
}

const LEVEL_LABEL = {
  beginner:     { label: "Beginner",     color: "text-emerald-500" },
  intermediate: { label: "Intermediate", color: "text-blue-400"    },
  advanced:     { label: "Advanced",     color: "text-violet-400"  },
}

function intensityLabel(count) {
  if (!count || count <= 3) return "Light"
  if (count <= 5)           return "Standard"
  return "Intensive"
}

function DotsIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <circle cx="3" cy="8" r="1.5" />
      <circle cx="8" cy="8" r="1.5" />
      <circle cx="13" cy="8" r="1.5" />
    </svg>
  )
}

export default function ProjectCard({ project, progression, isActive, onSelect, onRename, onEdit, onDelete }) {
  const { user } = useAuth()
  const isLegacyFeed = (user?.feed_version || "legacy") === "legacy"
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

  const grad      = COLOR_GRAD[project.color] || COLOR_GRAD.blue
  const level     = progression?.current_level || project.difficulty || "beginner"
  const lvl       = LEVEL_LABEL[level] || LEVEL_LABEL.beginner
  const intensity = intensityLabel(project.daily_core_article_count)

  return (
    <div
      onClick={() => onSelect(project)}
      className={`
        group relative flex items-center gap-2.5 px-3 py-2 rounded-xl cursor-pointer transition-colors select-none
        ${menuOpen ? "z-50" : ""}
        ${isActive ? "bg-white/[0.07]" : menuOpen ? "bg-white/[0.04]" : "hover:bg-white/[0.04]"}
      `}
    >
      <div className={`flex-shrink-0 w-[3px] h-7 rounded-full bg-gradient-to-b ${grad} opacity-90`} />
      <div className="flex-1 min-w-0 pr-5">
        <p className={`text-[13px] font-medium leading-snug truncate ${isActive ? "text-white" : "text-slate-300 group-hover:text-white"}`}>
          {project.name}
        </p>
        <p className="text-[10px] flex items-center gap-1.5">
          <span className={lvl.color}>{lvl.label}</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-500">{intensity}</span>
          {isLegacyFeed && (
            <>
              <span className="text-slate-600">·</span>
              <span className="text-slate-500 uppercase tracking-wide text-[9px]">Legacy feed</span>
            </>
          )}
        </p>
      </div>
      {/* Desktop per-item action menu */}
      <div ref={menuRef} className="hidden md:block absolute right-1 top-1/2 -translate-y-1/2">
        <button
          onClick={(e) => { e.stopPropagation(); setMenuOpen(v => !v) }}
          className={`p-1 rounded text-slate-500 hover:text-slate-200 hover:bg-white/[0.08] transition-opacity ${menuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
          title="Actions"
        >
          <DotsIcon />
        </button>
        {menuOpen && (
          <div className="absolute right-0 top-full mt-1 z-50 min-w-[110px] bg-[#1e2330] border border-slate-700/60 rounded-lg shadow-2xl py-1 overflow-hidden isolate" style={{ backdropFilter: "none" }}>
            <button
              onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onRename?.(project) }}
              className="w-full text-left px-3 py-1.5 text-[11px] text-slate-300 hover:text-white hover:bg-white/[0.06] transition-colors"
            >
              Rename
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onEdit?.(project) }}
              className="w-full text-left px-3 py-1.5 text-[11px] text-slate-300 hover:text-white hover:bg-white/[0.06] transition-colors"
            >
              Edit
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onDelete?.(project) }}
              className="w-full text-left px-3 py-1.5 text-[11px] text-red-400 hover:text-red-300 hover:bg-red-500/[0.08] transition-colors"
            >
              Delete
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
